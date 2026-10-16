//! Theme-tinted Tabler system icons. Only pinned compact 1bpp masks enter guest.
//! Upstream MIT notice and exact SVG/tool provenance: shell/assets/tabler/.
use crosshair_ui::{Rgb565, Surface};
#[rustfmt::skip]
#[path = "icon_assets.rs"]
pub mod catalog;
pub use catalog::{ICON_COUNT, IconId, MASK_BYTES, Mask, mask};

/// Draw a supported catalog mask in one theme color without allocation. Unknown
/// sizes fail without touching pixels. Coordinates saturate before Surface clips.
pub fn draw_icon(s: &mut Surface<'_>, x: i32, y: i32, id: IconId, size: u8, color: Rgb565) -> bool {
    let Some(mask) = mask(id, size) else {
        return false;
    };
    for row in 0..size {
        let mut column = 0;
        while column < size {
            if !mask.is_set(column, row) {
                column += 1;
                continue;
            }
            let start = column;
            while column < size && mask.is_set(column, row) {
                column += 1;
            }
            s.fill_rect(
                x.saturating_add(start as i32),
                y.saturating_add(row as i32),
                (column - start) as u32,
                1,
                color,
            );
        }
    }
    true
}

/// Existing Shell role IDs stay stable: apps, Today, Settings, Diagnostics,
/// About, Switch. Extra catalog IDs are assets, not claims of working services.
/// The monochrome foreground follows the caller's theme; accent is retained in
/// the existing drawing API but no second stored color/bitmap is introduced.
pub fn draw(s: &mut Surface<'_>, x: i32, y: i32, kind: u8, ink: Rgb565, _accent: Rgb565) {
    let id = IconId::from_u16(kind as u16).unwrap_or(IconId::SwitchView);
    draw_icon(s, x, y, id, 24, ink);
}

#[cfg(test)]
mod tests {
    extern crate std;
    use super::*;
    use std::vec;
    #[test]
    fn stable_catalog_all_sizes_and_mask_bounds() {
        assert_eq!(ICON_COUNT, 18);
        assert_eq!(MASK_BYTES, 2196);
        for id in 0..18 {
            let icon = IconId::from_u16(id).unwrap();
            for size in [12, 16, 24] {
                let value = mask(icon, size).unwrap();
                assert_eq!(value.bits.len(), (size as usize * size as usize + 7) / 8);
                assert!(value.bits.iter().any(|&v| v != 0));
                assert!(!value.is_set(size, 0) && !value.is_set(0, size));
            }
        }
        assert!(IconId::from_u16(18).is_none());
        assert!(mask(IconId::Home, 13).is_none());
    }
    #[test]
    fn monochrome_tint_clipping_and_invalid_size_do_not_allocate_or_overdraw() {
        let mut pixels = vec![0x55aa; 32 * 32 + 16];
        {
            let mut surface = Surface::new(&mut pixels[8..8 + 32 * 32], 32, 32, 32).unwrap();
            surface.present(|_, _, _| Ok::<(), ()>(())).unwrap();
            assert!(!draw_icon(
                &mut surface,
                0,
                0,
                IconId::Phone,
                13,
                Rgb565(0x1234)
            ));
            assert!(surface.dirty_rects().is_empty());
            assert!(draw_icon(
                &mut surface,
                -4,
                -4,
                IconId::Settings,
                24,
                Rgb565(0x1234)
            ));
            draw_icon(
                &mut surface,
                i32::MAX,
                i32::MIN,
                IconId::Home,
                12,
                Rgb565(0x1234),
            );
        }
        assert!(
            pixels[..8]
                .iter()
                .chain(&pixels[8 + 32 * 32..])
                .all(|&v| v == 0x55aa)
        );
        assert!(
            pixels[8..8 + 32 * 32]
                .iter()
                .all(|&v| v == 0x55aa || v == 0x1234)
        );
        assert!(pixels.iter().any(|&v| v == 0x1234));
    }
}
