//! Static build-time RGB565 wallpaper. No PNG/SVG decoder, allocation, second
//! framebuffer or expanded row buffer. Only bounded run spans reach Surface.
use crosshair_ui::{Rgb565, Surface};
#[rustfmt::skip]
#[path = "wallpaper_assets.rs"]
pub mod assets;

/// Software composition work, never hardware cycles or display transfer size.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct DrawStats {
    pub packets_decoded: u32,
    pub pixels_decoded: u32,
    pub pixels_written: u32,
    pub runs_written: u32,
}

/// Restore a clipped rectangle in the sole existing RGB565 surface. The row
/// table jumps directly to requested rows; decoding stops at the right edge.
/// Generated arrays are validated and source-bound before the guest is built.
/// Defensive get/range bounds remain in the safe runtime; it accepts no files
/// or untrusted encoded assets. Scalar state is the only decode scratch.
pub fn draw_region(s: &mut Surface<'_>, x: u16, y: u16, width: u16, height: u16, night: bool) -> DrawStats {
    let mut stats = DrawStats::default();
    let left = x as u32;
    let top = y as u32;
    let right = (left + width as u32).min(assets::WIDTH as u32).min(s.width() as u32);
    let bottom = (top + height as u32).min(assets::HEIGHT as u32).min(s.height() as u32);
    if left >= right || top >= bottom { return stats; }
    for row in top..bottom {
        let Some(&start) = assets::ROW_OFFSETS.get(row as usize) else { continue; };
        let Some(&end) = assets::ROW_OFFSETS.get(row as usize + 1) else { continue; };
        let Some(packets) = assets::DATA.get(start as usize..end as usize) else { continue; };
        let mut column = 0u32;
        for &packet in packets {
            if column >= right { break; }
            let length = (packet >> 4) as u32 + 1;
            let span_end = (column + length).min(assets::WIDTH as u32);
            stats.packets_decoded += 1;
            stats.pixels_decoded += length;
            let span_left = column.max(left);
            let span_right = span_end.min(right);
            if span_left < span_right {
                let index = (packet & 15) as usize + if night { 16 } else { 0 };
                s.fill_rect(span_left as i32, row as i32, span_right - span_left, 1, Rgb565(assets::PALETTE[index]));
                stats.pixels_written += span_right - span_left;
                stats.runs_written += 1;
            }
            column = span_end;
        }
    }
    stats
}

#[cfg(test)]
mod tests {
    extern crate std;
    use super::*;
    use std::vec;

    #[test]
    fn generated_rows_have_exact_extent_and_full_palette_bounds() {
        assert_eq!(assets::ROW_OFFSETS[0], 0);
        assert_eq!(*assets::ROW_OFFSETS.last().unwrap() as usize, assets::DATA.len());
        assert_eq!(assets::PAYLOAD_BYTES, assets::DATA.len() + 642 + 64);
        for row in 0..320 {
            let start = assets::ROW_OFFSETS[row] as usize;
            let end = assets::ROW_OFFSETS[row + 1] as usize;
            assert!(start < end && end <= assets::DATA.len());
            assert_eq!(assets::DATA[start..end].iter().map(|b| ((b >> 4) + 1) as usize).sum::<usize>(), 240);
        }
    }

    #[test]
    fn regional_restore_preserves_every_other_pixel_padding_and_canaries() {
        let mut pixels = vec![0x55aau16; 16 + 240 * 320];
        {
            let mut s = Surface::new(&mut pixels[8..8 + 240 * 320], 240, 320, 240).unwrap();
            s.present(|_,_,_|Ok::<(),()>(())).unwrap();
            let stats = draw_region(&mut s, 8, 42, 72, 58, false);
            assert_eq!(stats.pixels_written, 72 * 58);
            assert!(stats.pixels_decoded < 240 * 58);
            assert!(stats.runs_written > 0 && stats.packets_decoded >= stats.runs_written);
            assert_eq!(s.dirty_rects().len(), 1);
            let rect = s.dirty_rects()[0];
            assert_eq!((rect.x(),rect.y(),rect.width(),rect.height()), (8,42,72,58));
            assert_eq!(draw_region(&mut s,u16::MAX,u16::MAX,u16::MAX,u16::MAX,true),DrawStats::default());
        }
        for row in 0..320 {
            for col in 0..240 {
                let value = pixels[8 + row * 240 + col];
                if (42..100).contains(&row) && (8..80).contains(&col) {
                    assert!(assets::PALETTE[..16].contains(&value));
                } else { assert_eq!(value,0x55aa); }
            }
        }
        assert!(pixels[..8].iter().chain(pixels[8 + 240 * 320..].iter()).all(|&v|v==0x55aa));
    }
}
