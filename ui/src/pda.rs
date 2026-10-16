//! Dense content components for PDA screens. These borrow the existing Surface;
//! no allocation, framebuffer, input ownership or system policy lives here.

use crate::{Rgb565, Surface, components::Area, theme::layout};

#[derive(Clone, Copy)]
pub struct Palette {
    pub ink: Rgb565,
    pub muted: Rgb565,
    pub surface: Rgb565,
    pub edge: Rgb565,
    pub focus: Rgb565,
    pub selected: Rgb565,
}

/// Single line, vertically centered. Limit ink, including Cozette's two-pixel
/// overhang, to the supplied area before Surface applies screen clipping.
pub fn text(surface: &mut Surface<'_>, area: Area, value: &str, color: Rgb565) {
    if area.width < layout::FONT_INK_WIDTH || area.height < layout::FONT_HEIGHT {
        return;
    }
    let limit = (area.width - layout::FONT_INK_WIDTH) as usize / layout::FONT_ADVANCE as usize + 1;
    let y = area
        .y
        .saturating_add((area.height - layout::FONT_HEIGHT) as i32 / 2);
    for (index, ch) in value
        .chars()
        .take(limit)
        .take_while(|ch| *ch != '\n')
        .enumerate()
    {
        let mut bytes = [0; 4];
        surface.text(
            area.x
                .saturating_add(index as i32 * layout::FONT_ADVANCE as i32),
            y,
            ch.encode_utf8(&mut bytes),
            color,
        );
    }
}

fn inset(area: Area, x: u16, y: u16) -> Area {
    Area {
        x: area.x.saturating_add(x as i32),
        y: area.y.saturating_add(y as i32),
        width: area.width.saturating_sub(x.saturating_mul(2)),
        height: area.height.saturating_sub(y.saturating_mul(2)),
    }
}

pub fn section_heading(surface: &mut Surface<'_>, area: Area, label: &str, palette: Palette) {
    text(surface, inset(area, 2, 0), label, palette.muted);
    if area.height != 0 {
        surface.fill_rect(
            area.x,
            area.y.saturating_add(area.height as i32 - 1),
            area.width as u32,
            1,
            palette.edge,
        );
    }
}

/// A shared 2:3 label/value split; either cell clips independently. Background
/// belongs to the parent, so a short fact never requires a filled card.
pub fn key_value(
    surface: &mut Surface<'_>,
    area: Area,
    label: &str,
    value: &str,
    palette: Palette,
) {
    let area = inset(area, 2, 0);
    let split = area.width as u32 * 2 / 5;
    text(
        surface,
        Area {
            width: split.saturating_sub(3) as u16,
            ..area
        },
        label,
        palette.muted,
    );
    text(
        surface,
        Area {
            x: area.x.saturating_add(split as i32),
            width: area.width.saturating_sub(split as u16),
            ..area
        },
        value,
        palette.ink,
    );
}

/// Lists and context menus use the same selection geometry. The parent clears
/// the row when focus changes; an unselected row does not paint a card.
pub fn compact_row(
    surface: &mut Surface<'_>,
    area: Area,
    label: &str,
    selected: bool,
    palette: Palette,
) {
    if selected {
        surface.fill_rect(
            area.x,
            area.y,
            area.width as u32,
            area.height as u32,
            palette.selected,
        );
        surface.stroke_rect(
            area.x,
            area.y,
            area.width as u32,
            area.height as u32,
            palette.focus,
        );
    }
    text(surface, inset(area, 3, 0), label, palette.ink);
}

pub fn inline_action(
    surface: &mut Surface<'_>,
    area: Area,
    label: &str,
    focused: bool,
    palette: Palette,
) {
    if focused {
        compact_row(surface, area, label, true, palette);
    } else {
        text(surface, inset(area, 3, 0), label, palette.focus);
    }
}

/// Row-index scrolling, bounded even for zero visible rows or stale selection.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct Scroll {
    pub offset: u16,
}

impl Scroll {
    pub fn clamp(&mut self, total: u16, visible: u16) {
        self.offset = self.offset.min(total.saturating_sub(visible.max(1)));
    }

    pub fn reveal(&mut self, selected: u16, total: u16, visible: u16) {
        let visible = visible.max(1);
        let selected = selected.min(total.saturating_sub(1));
        if selected < self.offset {
            self.offset = selected;
        } else if selected as u32 >= self.offset as u32 + visible as u32 {
            self.offset = selected.saturating_sub(visible - 1);
        }
        self.clamp(total, visible);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const PALETTE: Palette = Palette {
        ink: Rgb565(1),
        muted: Rgb565(2),
        surface: Rgb565(3),
        edge: Rgb565(4),
        focus: Rgb565(5),
        selected: Rgb565(6),
    };

    #[test]
    fn content_ink_and_selections_stay_inside_component_and_screen() {
        // A padded stride exposes accidental writes beyond the visible screen;
        // outer canaries detect escaping the exact Surface borrow.
        let mut guarded = [0xace5; 2 + 44 * 32];
        let mut surface = Surface::new(&mut guarded[1..1 + 44 * 32], 40, 32, 44).unwrap();
        let area = Area {
            x: 5,
            y: 4,
            width: 25,
            height: 20,
        };
        compact_row(&mut surface, area, "WWWКириллица\nNext", true, PALETTE);
        for y in 0..32 {
            for x in 0..44 {
                if !(5..30).contains(&x) || !(4..24).contains(&y) {
                    assert_eq!(surface.pixels()[y * 44 + x], 0xace5);
                }
            }
        }
        assert_eq!(guarded[0], 0xace5);
        assert_eq!(guarded[1 + 44 * 32], 0xace5);
    }

    #[test]
    fn tiny_and_extreme_text_areas_are_bounded() {
        let mut pixels = [0xace5; 40 * 32];
        let mut surface = Surface::new(&mut pixels, 40, 32, 40).unwrap();
        for area in [
            Area {
                x: 0,
                y: 0,
                width: 7,
                height: 32,
            },
            Area {
                x: 0,
                y: 0,
                width: 40,
                height: 12,
            },
            Area {
                x: i32::MAX,
                y: i32::MAX,
                width: 40,
                height: 32,
            },
            Area {
                x: i32::MIN,
                y: i32::MIN,
                width: 40,
                height: 32,
            },
        ] {
            text(&mut surface, area, "Кириллица", PALETTE.ink);
        }
        assert!(surface.pixels().iter().all(|pixel| *pixel == 0xace5));
    }

    #[test]
    fn scrolling_reveals_selection_at_bounds_without_overflow() {
        for total in [0, 1, 12, u16::MAX] {
            for visible in [0, 1, 7, u16::MAX] {
                let mut scroll = Scroll { offset: u16::MAX };
                for selected in [u16::MAX, 1, 0, 8, u16::MAX - 1] {
                    scroll.reveal(selected, total, visible);
                    assert!(scroll.offset <= total.saturating_sub(visible.max(1)));
                    if total > 0 {
                        let selected = selected.min(total - 1);
                        assert!(selected >= scroll.offset);
                        assert!((selected as u32) < scroll.offset as u32 + visible.max(1) as u32);
                    }
                }
            }
        }
    }
}
