use crosshair_ui::{Rgb565, Surface};
use std::fs::File;
use std::io::{BufWriter, Write};

/// A rendering fixture, not a desktop, launcher, phone, or hardware driver.
pub fn render(surface: &mut Surface<'_>) {
    let background = Rgb565::from_rgb(226, 234, 234);
    let ink = Rgb565::from_rgb(24, 40, 48);
    let accent = Rgb565::from_rgb(40, 72, 88);
    let edge = Rgb565::from_rgb(112, 136, 144);
    surface.fill(background);
    surface.fill_rect(0, 0, 240, 27, accent);
    surface.text(8, 7, "Crosshair UI 0.1", Rgb565(0xffff));
    surface.text(8, 33, "240x320  RGB565", ink);
    surface.line(8, 48, 231, 48, edge);

    surface.stroke_rect(8, 56, 224, 69, edge);
    surface.text(14, 62, "Примитивы", ink);
    surface.fill_rect(14, 83, 28, 12, Rgb565(0xf800));
    surface.fill_rect(46, 83, 28, 12, Rgb565(0x07e0));
    surface.fill_rect(78, 83, 28, 12, Rgb565(0x001f));
    surface.stroke_rect(126, 82, 97, 25, accent);
    surface.line(14, 113, 106, 104, ink);

    surface.stroke_rect(8, 135, 224, 92, edge);
    surface.text(14, 141, "Кириллица", ink);
    surface.text(14, 160, "Съешь ещё этих мягких", ink);
    surface.text(14, 174, "французских булок, да", ink);
    surface.text(14, 188, "выпей чаю.", ink);
    surface.text(14, 208, "Ёё Йй Ъъ Ьь —", ink);

    surface.stroke_rect(8, 237, 224, 43, edge);
    surface.text(14, 243, "Обрезка / границы", ink);
    surface.line(-100, 265, 339, 265, accent);
    surface.fill_rect(-6, 261, 24, 9, accent);
    surface.fill_rect(222, 261, 24, 9, accent);
    surface.text(8, 295, "Без MMIO, heap и ОС хоста", ink);
}

fn main() -> std::io::Result<()> {
    let output = std::env::args()
        .nth(1)
        .expect("output raw565 path required");
    // Host fixture owns one 153600-byte framebuffer on the heap, never a large
    // automatic array. Bare-metal callers must provide BSS/RAM or a small strip.
    let mut pixels = vec![0u16; 240 * 320];
    let mut surface = Surface::new(&mut pixels, 240, 320, 240).unwrap();
    render(&mut surface);
    let dirty = surface.dirty_rects().len();
    let mut writer = BufWriter::new(File::create(output)?);
    for pixel in surface.pixels() {
        writer.write_all(&pixel.to_le_bytes())?;
    }
    writer.flush()?;
    println!(
        "RGB565 240x320: {} bytes, {dirty} dirty region(s), one framebuffer",
        240 * 320 * 2
    );
    Ok(())
}
