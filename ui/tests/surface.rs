use crosshair_ui::{DIRTY_CAPACITY, MAX_FRAMEBUFFER_BYTES, Rgb565, Surface, SurfaceError, font};

#[allow(dead_code)]
#[path = "../examples/primitives.rs"]
mod primitives;

fn acknowledge(surface: &mut Surface<'_>) {
    surface.present(|_, _, _| Ok::<(), ()>(())).unwrap();
}

#[test]
fn rgb565_primary_colors_and_quantization() {
    assert_eq!(Rgb565::from_rgb(255, 0, 0).0, 0xf800);
    assert_eq!(Rgb565::from_rgb(0, 255, 0).0, 0x07e0);
    assert_eq!(Rgb565::from_rgb(0, 0, 255).0, 0x001f);
    assert_eq!(Rgb565::from_rgb(255, 255, 255).0, 0xffff);
    assert_eq!(Rgb565::from_rgb(7, 3, 7).0, 0);
}

#[test]
fn invalid_surfaces_never_access_the_buffer() {
    let mut data = [0xaaaa; 4];
    let cases = [
        (0, 1, 1, SurfaceError::Dimensions),
        (241, 1, 241, SurfaceError::Dimensions),
        (1, 321, 1, SurfaceError::Dimensions),
        (2, 1, 1, SurfaceError::Stride),
        (1, 2, usize::MAX, SurfaceError::Overflow),
        (1, 1, 76801, SurfaceError::MemoryBudget),
        (2, 3, 2, SurfaceError::BufferTooShort),
    ];
    for (width, height, stride, error) in cases {
        assert!(matches!(Surface::new(&mut data, width, height, stride), Err(e) if e == error));
    }
    assert_eq!(data, [0xaaaa; 4]);
    assert_eq!(MAX_FRAMEBUFFER_BYTES, 153600);
}

#[test]
fn clipped_rectangles_preserve_stride_padding_and_outer_guards() {
    let mut data = [0xabcd; 20];
    {
        let mut surface = Surface::new(&mut data[2..18], 3, 4, 4).unwrap();
        surface.fill(Rgb565(0));
        surface.fill_rect(-1, -1, 3, 3, Rgb565(7));
        surface.fill_rect(2, 3, u32::MAX, u32::MAX, Rgb565(9));
    }
    assert_eq!(
        data,
        [
            0xabcd, 0xabcd, 7, 7, 0, 0xabcd, 7, 7, 0, 0xabcd, 0, 0, 0, 0xabcd, 0, 0, 9, 0xabcd,
            0xabcd, 0xabcd
        ]
    );
}

#[test]
fn far_rectangles_and_empty_strokes_do_not_dirty_or_wrap() {
    let mut data = [0; 16];
    let mut surface = Surface::new(&mut data, 4, 4, 4).unwrap();
    acknowledge(&mut surface);
    surface.fill_rect(i32::MAX, i32::MAX, u32::MAX, u32::MAX, Rgb565(1));
    surface.stroke_rect(i32::MAX, 0, u32::MAX, 4, Rgb565(1));
    surface.fill_rect(i32::MIN, i32::MIN, 4, 4, Rgb565(1));
    surface.stroke_rect(0, 0, 0, 4, Rgb565(1));
    assert!(surface.dirty_rects().is_empty());
    assert!(surface.pixels().iter().all(|x| *x == 0));
}

#[test]
fn line_golden_and_extreme_clipping_are_bounded() {
    let mut data = [0; 25];
    let mut surface = Surface::new(&mut data, 5, 5, 5).unwrap();
    surface.line(i32::MIN, 2, i32::MAX, 2, Rgb565(1));
    surface.line(0, 0, 4, 4, Rgb565(2));
    surface.line(i32::MIN, i32::MIN, i32::MAX, i32::MAX, Rgb565(2));
    surface.line(i32::MIN, -1, i32::MAX, -1, Rgb565(9));
    assert_eq!(
        surface.pixels(),
        &[
            2, 0, 0, 0, 0, 0, 2, 0, 0, 0, 1, 1, 2, 1, 1, 0, 0, 0, 2, 0, 0, 0, 0, 0, 2
        ]
    );
}

#[test]
fn strokes_keep_the_interior_and_clip_without_filling_it() {
    let mut data = [0; 25];
    let mut surface = Surface::new(&mut data, 5, 5, 5).unwrap();
    surface.stroke_rect(-1, -1, 5, 5, Rgb565(3));
    assert_eq!(
        surface.pixels(),
        &[
            0, 0, 0, 3, 0, 0, 0, 0, 3, 0, 0, 0, 0, 3, 0, 3, 3, 3, 3, 0, 0, 0, 0, 0, 0
        ]
    );
}

#[test]
fn dirty_overflow_retains_every_changed_pixel() {
    let mut data = [0; 240 * 4];
    let mut surface = Surface::new(&mut data, 240, 4, 240).unwrap();
    acknowledge(&mut surface);
    for index in 0..DIRTY_CAPACITY + 1 {
        surface.pixel((index * 4) as i32, 1, Rgb565(5));
    }
    assert_eq!(surface.dirty_rects().len(), 1);
    let rect = surface.dirty_rects()[0];
    for x in (0..=DIRTY_CAPACITY * 4).step_by(4) {
        assert!(rect.x() <= x && x < rect.right() && rect.y() <= 1 && 1 < rect.bottom());
        assert_eq!(surface.pixels()[240 + x], 5);
    }
}

#[test]
fn failed_present_keeps_all_regions_until_complete_success() {
    let mut data = [0; 24];
    let mut surface = Surface::new(&mut data, 12, 2, 12).unwrap();
    // Initial framebuffer requires a full first transfer, even before drawing.
    assert_eq!(surface.dirty_rects()[0].width(), 12);
    acknowledge(&mut surface);
    surface.pixel(0, 0, Rgb565(1));
    surface.pixel(8, 0, Rgb565(2));
    let before = surface.dirty_rects().to_vec();
    let mut calls = 0;
    assert_eq!(
        surface.present(|_, pixels, stride| {
            calls += 1;
            assert_eq!(stride, 12);
            assert_eq!(pixels[8], 2);
            if calls == 2 { Err("transport") } else { Ok(()) }
        }),
        Err("transport")
    );
    assert_eq!(surface.dirty_rects(), before);
    assert_eq!(surface.present(|_, _, _| Ok::<(), ()>(())), Ok(2));
    assert!(surface.dirty_rects().is_empty());
    assert_eq!(
        surface.present(|_, _, _| -> Result<(), ()> { panic!("empty transfer") }),
        Ok(0)
    );
}

#[test]
fn font_contains_complete_russian_and_preserves_ink_overhang() {
    assert_eq!(font::GLYPH_COUNT, 163);
    assert!(font::CODEPOINTS.windows(2).all(|x| x[0] < x[1]));
    for ch in (0x410..0x450)
        .chain([0x401, 0x451])
        .map(|c| char::from_u32(c).unwrap())
    {
        assert!(font::glyph(ch).is_some_and(|rows| rows.iter().any(|row| *row != 0)));
    }
    let mut data = [0; 8 * 13];
    let mut surface = Surface::new(&mut data, 8, 13, 8).unwrap();
    surface.text(0, 0, "Д", Rgb565(1));
    assert!(surface.pixels().chunks_exact(8).any(|row| row[6] == 1));
    assert!(surface.pixels().chunks_exact(8).all(|row| row[7] == 0));
}

#[test]
fn utf8_fallback_newline_and_edge_clipping() {
    let mut a = [0; 16 * 28];
    let mut b = [0; 16 * 28];
    let mut left = Surface::new(&mut a, 16, 28, 16).unwrap();
    let mut right = Surface::new(&mut b, 16, 28, 16).unwrap();
    left.text(-2, -2, "Ё💡\nй", Rgb565(1));
    right.text(-2, -2, "Ё�\nй", Rgb565(1));
    left.text(i32::MAX, i32::MAX, "Ш\nЩ", Rgb565(9));
    assert_eq!(left.pixels(), right.pixels());
    assert!(left.pixels().iter().any(|p| *p != 0));
}

#[test]
fn full_frame_pixel_golden() {
    let mut data = vec![0; 240 * 320];
    let mut surface = Surface::new(&mut data, 240, 320, 240).unwrap();
    primitives::render(&mut surface);
    // FNV-1a over the defined little-endian raw565 fixture, not a PNG encoder.
    let mut hash = 0xcbf29ce484222325u64;
    for pixel in surface.pixels() {
        for byte in pixel.to_le_bytes() {
            hash = (hash ^ byte as u64).wrapping_mul(0x100000001b3);
        }
    }
    assert_eq!(surface.pixels()[84 * 240 + 15], 0xf800);
    assert_eq!(surface.pixels()[84 * 240 + 47], 0x07e0);
    assert_eq!(surface.pixels()[84 * 240 + 79], 0x001f);
    assert_eq!(
        hash, 5431880093368634183,
        "reviewed 240x320 raw565 pixel golden"
    );
}
