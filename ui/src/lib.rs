#![no_std]
#![forbid(unsafe_code)]
//! Bounded software drawing. This crate allocates no framebuffer and touches no MMIO.

pub mod components;
pub mod fixtures;
pub mod font;
pub mod pda;
pub mod theme;

pub const MAX_WIDTH: usize = 240;
pub const MAX_HEIGHT: usize = 320;
pub const MAX_PIXELS: usize = MAX_WIDTH * MAX_HEIGHT;
pub const MAX_FRAMEBUFFER_BYTES: usize = MAX_PIXELS * 2;
pub const DIRTY_CAPACITY: usize = 8;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Rgb565(pub u16);

impl Rgb565 {
    /// Truncate RGB888 to the device-independent numeric RGB565 value.
    pub const fn from_rgb(red: u8, green: u8, blue: u8) -> Self {
        Self(((red as u16 & 0xf8) << 8) | ((green as u16 & 0xfc) << 3) | (blue as u16 >> 3))
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct Rect {
    x: u16,
    y: u16,
    width: u16,
    height: u16,
}

impl Rect {
    pub const fn x(self) -> usize {
        self.x as usize
    }
    pub const fn y(self) -> usize {
        self.y as usize
    }
    pub const fn width(self) -> usize {
        self.width as usize
    }
    pub const fn height(self) -> usize {
        self.height as usize
    }
    pub const fn right(self) -> usize {
        self.x() + self.width()
    }
    pub const fn bottom(self) -> usize {
        self.y() + self.height()
    }

    fn touches(self, other: Self) -> bool {
        self.x() <= other.right()
            && other.x() <= self.right()
            && self.y() <= other.bottom()
            && other.y() <= self.bottom()
    }

    fn union(self, other: Self) -> Self {
        // Both rectangles are clipped to a validated surface <= 240 x 320.
        let x = self.x.min(other.x);
        let y = self.y.min(other.y);
        Self {
            x,
            y,
            width: (self.right().max(other.right()) - x as usize) as u16,
            height: (self.bottom().max(other.bottom()) - y as usize) as u16,
        }
    }
}

#[derive(Clone, Copy)]
struct DirtyRects {
    rects: [Rect; DIRTY_CAPACITY],
    len: usize,
}

impl DirtyRects {
    fn new(full: Rect) -> Self {
        let mut this = Self {
            rects: [Rect::default(); DIRTY_CAPACITY],
            len: 1,
        };
        this.rects[0] = full;
        this
    }

    fn mark(&mut self, mut rect: Rect) {
        let mut index = 0;
        while index < self.len {
            if rect.touches(self.rects[index]) {
                rect = rect.union(self.rects[index]);
                self.len -= 1;
                self.rects[index] = self.rects[self.len];
                // A union can now touch an earlier rectangle; bounded by capacity.
                index = 0;
            } else {
                index += 1;
            }
        }
        if self.len == DIRTY_CAPACITY {
            for existing in &self.rects[..self.len] {
                rect = rect.union(*existing);
            }
            self.len = 0;
        }
        self.rects[self.len] = rect;
        self.len += 1;
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SurfaceError {
    Dimensions,
    Stride,
    Overflow,
    MemoryBudget,
    BufferTooShort,
}

/// A single exclusive borrow, at most 153600 bytes. Row padding is never drawn.
pub struct Surface<'a> {
    pixels: &'a mut [u16],
    width: usize,
    height: usize,
    stride: usize,
    dirty: DirtyRects,
}

impl<'a> Surface<'a> {
    pub fn new(
        pixels: &'a mut [u16],
        width: usize,
        height: usize,
        stride: usize,
    ) -> Result<Self, SurfaceError> {
        if width == 0 || height == 0 || width > MAX_WIDTH || height > MAX_HEIGHT {
            return Err(SurfaceError::Dimensions);
        }
        if stride < width {
            return Err(SurfaceError::Stride);
        }
        let span = stride.checked_mul(height).ok_or(SurfaceError::Overflow)?;
        if span > MAX_PIXELS {
            return Err(SurfaceError::MemoryBudget);
        }
        if pixels.len() < span {
            return Err(SurfaceError::BufferTooShort);
        }
        let full = Rect {
            x: 0,
            y: 0,
            width: width as u16,
            height: height as u16,
        };
        Ok(Self {
            pixels: &mut pixels[..span],
            width,
            height,
            stride,
            dirty: DirtyRects::new(full),
        })
    }

    pub const fn width(&self) -> usize {
        self.width
    }
    pub const fn height(&self) -> usize {
        self.height
    }
    pub const fn stride(&self) -> usize {
        self.stride
    }
    pub fn pixels(&self) -> &[u16] {
        self.pixels
    }
    pub fn dirty_rects(&self) -> &[Rect] {
        &self.dirty.rects[..self.dirty.len]
    }

    /// Present a snapshot of all dirty rectangles. Clear only after *all* calls
    /// succeed. A failed transfer keeps every region dirty for idempotent retry.
    /// The callback sees the same borrowed framebuffer; no second buffer exists.
    pub fn present<E>(
        &mut self,
        mut send: impl FnMut(Rect, &[u16], usize) -> Result<(), E>,
    ) -> Result<usize, E> {
        let count = self.dirty.len;
        for rect in &self.dirty.rects[..count] {
            send(*rect, self.pixels, self.stride)?;
        }
        self.dirty.len = 0;
        Ok(count)
    }

    fn clip(&self, x: i64, y: i64, width: i64, height: i64) -> Option<Rect> {
        if width <= 0 || height <= 0 {
            return None;
        }
        let left = x.max(0);
        let top = y.max(0);
        let right = x.saturating_add(width).min(self.width as i64);
        let bottom = y.saturating_add(height).min(self.height as i64);
        if left >= right || top >= bottom {
            return None;
        }
        Some(Rect {
            x: left as u16,
            y: top as u16,
            width: (right - left) as u16,
            height: (bottom - top) as u16,
        })
    }

    pub fn fill(&mut self, color: Rgb565) {
        self.fill_rect(0, 0, self.width as u32, self.height as u32, color);
    }

    fn fill_at(&mut self, x: i64, y: i64, width: i64, height: i64, color: Rgb565) {
        let Some(rect) = self.clip(x, y, width, height) else {
            return;
        };
        for row in rect.y()..rect.bottom() {
            let start = row * self.stride + rect.x();
            self.pixels[start..start + rect.width()].fill(color.0);
        }
        self.dirty.mark(rect);
    }

    pub fn fill_rect(&mut self, x: i32, y: i32, width: u32, height: u32, color: Rgb565) {
        self.fill_at(x as i64, y as i64, width as i64, height as i64, color);
    }

    pub fn stroke_rect(&mut self, x: i32, y: i32, width: u32, height: u32, color: Rgb565) {
        if width == 0 || height == 0 {
            return;
        }
        let (x, y, w, h) = (x as i64, y as i64, width as i64, height as i64);
        self.fill_at(x, y, w, 1, color);
        self.fill_at(x, y + h - 1, w, 1, color);
        self.fill_at(x, y, 1, h, color);
        self.fill_at(x + w - 1, y, 1, h, color);
    }

    pub fn pixel(&mut self, x: i32, y: i32, color: Rgb565) {
        self.fill_rect(x, y, 1, 1, color);
    }

    /// Clip first: even i32-extreme endpoints take bounded work, then at most
    /// max(width,height) Bresenham steps. Integer intersections truncate to zero.
    pub fn line(&mut self, x0: i32, y0: i32, x1: i32, y1: i32, color: Rgb565) {
        let Some((mut x, mut y, end_x, end_y)) = clip_line(
            x0,
            y0,
            x1,
            y1,
            self.width as i64 - 1,
            self.height as i64 - 1,
        ) else {
            return;
        };
        let dirty = Rect {
            x: x.min(end_x) as u16,
            y: y.min(end_y) as u16,
            width: (x - end_x).unsigned_abs() as u16 + 1,
            height: (y - end_y).unsigned_abs() as u16 + 1,
        };
        let dx = (end_x - x).abs();
        let dy = -(end_y - y).abs();
        let sx = if x < end_x { 1 } else { -1 };
        let sy = if y < end_y { 1 } else { -1 };
        let mut error = dx + dy;
        loop {
            self.pixels[y as usize * self.stride + x as usize] = color.0;
            if x == end_x && y == end_y {
                break;
            }
            let doubled = error * 2;
            if doubled >= dy {
                error += dy;
                x += sx;
            }
            if doubled <= dx {
                error += dx;
                y += sy;
            }
        }
        self.dirty.mark(dirty);
    }

    /// Top-left text coordinates; 6-pixel advance and 14-pixel line spacing.
    /// Glyph ink can overhang the advance. Unknown Unicode uses U+FFFD.
    pub fn text(&mut self, x: i32, y: i32, text: &str, color: Rgb565) {
        let (mut cursor_x, mut cursor_y) = (x as i64, y as i64);
        for ch in text.chars() {
            if ch == '\n' {
                cursor_x = x as i64;
                cursor_y = cursor_y.saturating_add(font::LINE_HEIGHT as i64);
                continue;
            }
            let rows = font::glyph(ch).unwrap_or_else(|| font::replacement());
            if let Some(rect) = self.clip(cursor_x, cursor_y, 8, font::HEIGHT as i64) {
                for yy in rect.y()..rect.bottom() {
                    let bits = rows[(yy as i64 - cursor_y) as usize];
                    for xx in rect.x()..rect.right() {
                        let column = (xx as i64 - cursor_x) as u32;
                        if bits & (0x80 >> column) != 0 {
                            self.pixels[yy * self.stride + xx] = color.0;
                        }
                    }
                }
                self.dirty.mark(rect);
            }
            cursor_x = cursor_x.saturating_add(font::ADVANCE as i64);
        }
    }
}

fn clip_line(
    x0: i32,
    y0: i32,
    x1: i32,
    y1: i32,
    right: i64,
    bottom: i64,
) -> Option<(i64, i64, i64, i64)> {
    fn code(x: i64, y: i64, right: i64, bottom: i64) -> u8 {
        (if x < 0 {
            1
        } else if x > right {
            2
        } else {
            0
        }) | (if y < 0 {
            4
        } else if y > bottom {
            8
        } else {
            0
        })
    }
    // i128 products prevent overflow for the entire public i32 endpoint range.
    fn intersection(base: i64, delta: i64, numerator: i64, denominator: i64) -> i64 {
        (base as i128 + delta as i128 * numerator as i128 / denominator as i128) as i64
    }
    let (mut ax, mut ay, mut bx, mut by) = (x0 as i64, y0 as i64, x1 as i64, y1 as i64);
    for _ in 0..16 {
        let (a, b) = (code(ax, ay, right, bottom), code(bx, by, right, bottom));
        if a | b == 0 {
            return Some((ax, ay, bx, by));
        }
        if a & b != 0 {
            return None;
        }
        let outside = if a != 0 { a } else { b };
        let (x, y) = if outside & 4 != 0 {
            (intersection(ax, bx - ax, -ay, by - ay), 0)
        } else if outside & 8 != 0 {
            (intersection(ax, bx - ax, bottom - ay, by - ay), bottom)
        } else if outside & 2 != 0 {
            (right, intersection(ay, by - ay, right - ax, bx - ax))
        } else {
            (0, intersection(ay, by - ay, -ax, bx - ax))
        };
        if outside == a {
            ax = x;
            ay = y;
        } else {
            bx = x;
            by = y;
        }
    }
    None
}
