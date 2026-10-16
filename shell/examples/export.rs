//! Host replay of the exact no_std shell, with externally captured kernel
//! observations per step. Host allocations/PNG encoder are not linked to guest.
use crosshair_shell::{Action, BuildInfo, RuntimeInfo, Shell, Snapshot, fixtures};
use crosshair_ui::{Surface, components::Event};
use std::{
    fs,
    io::{self, Write},
    path::{Path, PathBuf},
};

fn fail(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message)
}
fn integer(value: &str) -> io::Result<u32> {
    if let Some(hex) = value.strip_prefix("0x") {
        u32::from_str_radix(hex, 16)
    } else {
        value.parse()
    }
    .map_err(|_| fail("invalid u32 in replay"))
}
fn action(value: &str) -> io::Result<Option<Action>> {
    if value == "-1" {
        return Ok(None);
    }
    if let Some(point) = value.strip_prefix("pointer:") {
        let (x, y) = point
            .split_once(',')
            .ok_or_else(|| fail("pointer requires x,y"))?;
        return Ok(Some(Action::Pointer {
            x: u16::try_from(integer(x)?).map_err(|_| fail("pointer x exceeds u16"))?,
            y: u16::try_from(integer(y)?).map_err(|_| fail("pointer y exceeds u16"))?,
        }));
    }
    if let Some(hex) = value.strip_prefix("text:") {
        let scalar = u32::from_str_radix(hex.trim_start_matches("0x"), 16)
            .map_err(|_| fail("invalid text scalar"))?;
        if scalar >= 0x90000 || (0xe000..=0xf0ff).contains(&scalar) {
            return Err(fail("scalar reserved for synthetic system input"));
        }
        return char::from_u32(scalar)
            .map(|ch| Some(Action::Key(Event::TextInput(ch))))
            .ok_or_else(|| fail("invalid Unicode scalar"));
    }
    if let Some(hex) = value.strip_prefix("wire:") {
        let wire = u32::from_str_radix(hex.trim_start_matches("0x"), 16)
            .map_err(|_| fail("invalid logical wire"))?;
        return Ok(Some(Action::from_wire(wire)));
    }
    Action::from_code(integer(value)?)
        .map(Some)
        .ok_or_else(|| fail("unsupported shell action"))
}
fn json(value: &str) -> String {
    let mut out = String::from("\"");
    for ch in value.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            c if c.is_control() => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}
fn snapshot(value: Snapshot) -> String {
    const NAMES: [&str; 16] = [
        "screen",
        "desktop_selected",
        "launcher_selected",
        "settings_selected",
        "today_selected",
        "overlay",
        "overlay_selected",
        "theme",
        "opened_mask",
        "history_depth",
        "events_processed",
        "revision",
        "renders",
        "runtime_valid",
        "runtime_ticks",
        "runtime_switches",
    ];
    let fields: Vec<String> = NAMES
        .into_iter()
        .zip(value.words())
        .map(|(name, v)| format!("\"{name}\":{v}"))
        .collect();
    format!("{{{}}}", fields.join(","))
}
fn capture(
    shell: &mut Shell,
    surface: &mut Surface<'_>,
    out: &Path,
    name: &str,
    changed: bool,
) -> io::Result<String> {
    if name.is_empty()
        || name.len() > 80
        || !name
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_')
    {
        return Err(fail("unsafe frame name"));
    }
    let rendered = shell.render(surface);
    let file = format!("{name}.raw565");
    let mut raw = fs::File::create(out.join(&file))?;
    let mut hash = 0xcbf2_9ce4_8422_2325u64;
    for pixel in surface.pixels() {
        let bytes = pixel.to_le_bytes();
        raw.write_all(&bytes)?;
        for byte in bytes {
            hash = (hash ^ byte as u64).wrapping_mul(0x100_0000_01b3);
        }
    }
    png(surface.pixels(), &out.join(format!("{name}.png")))?;
    surface.present(|_, _, _| Ok::<_, io::Error>(()))?;
    let query: String = shell.query().iter().collect();
    Ok(format!(
        concat!(
            "{{\"name\":{},\"snapshot\":{},\"snapshot_words\":{:?},\"query\":{},",
            "\"runtime_words\":{:?},\"ux_words\":{:?},\"render_stats\":{:?},\"changed\":{},\"rendered\":{},\"file\":{},",
            "\"width\":240,\"height\":320,\"stride\":240,\"bytes\":153600,\"fnv1a64\":\"0x{:016x}\"}}"
        ),
        json(name),
        snapshot(shell.snapshot()),
        shell.snapshot().words(),
        json(&query),
        shell.runtime().words(),
        shell.ux_snapshot().words(),
        shell.render_stats().words(),
        changed,
        rendered,
        json(&file),
        hash
    ))
}
fn main() -> io::Result<()> {
    let mut args = std::env::args().skip(1);
    let out = PathBuf::from(args.next().ok_or_else(|| fail("OUT required"))?);
    let mut replay = None;
    let mut build = BuildInfo::WAVE007_2;
    while let Some(flag) = args.next() {
        let value = args.next().ok_or_else(|| fail("flag requires a value"))?;
        match flag.as_str() {
            "--replay" => replay = Some(PathBuf::from(value)),
            "--version" => build.version = Box::leak(value.into_boxed_str()),
            "--arch" => build.architecture = Box::leak(value.into_boxed_str()),
            "--environment" => build.environment = Box::leak(value.into_boxed_str()),
            _ => return Err(fail("unknown flag")),
        }
    }
    fs::create_dir_all(&out)?;
    let mut shell = Shell::new(build);
    let mut pixels = vec![0u16; 240 * 320];
    let mut surface = Surface::new(&mut pixels, 240, 320, 240).unwrap();
    let mut frames = Vec::new();
    if let Some(path) = replay {
        for line in fs::read_to_string(path)?.lines() {
            if line.trim().is_empty() || line.trim_start().starts_with('#') {
                continue;
            }
            let fields: Vec<_> = line.split_whitespace().collect();
            if fields.len() != 14 {
                return Err(fail(
                    "replay line: name action plus exactly 12 RuntimeInfo words",
                ));
            }
            let mut words = [0u32; 12];
            for (index, word) in fields[2..].iter().enumerate() {
                words[index] = integer(word)?;
            }
            shell.update_runtime(RuntimeInfo::from_words(words));
            let changed = action(fields[1])?.is_some_and(|a| shell.handle(a));
            frames.push(capture(&mut shell, &mut surface, &out, fields[0], changed)?);
        }
    } else {
        frames.push(capture(&mut shell, &mut surface, &out, "step-00", false)?);
        for (step, event) in fixtures::SCENARIO.into_iter().enumerate() {
            let changed = shell.handle(event);
            frames.push(capture(
                &mut shell,
                &mut surface,
                &out,
                &format!("step-{:02}", step + 1),
                changed,
            )?);
        }
    }
    fs::write(
        out.join("frames.json"),
        format!(
            concat!(
                "{{\n\"schema\":\"crosshair-shell-frames-v1\",",
                "\"pixel_format\":\"RGB565_LE\",\"physical_input\":false,\"shell_bytes\":{},",
                "\"runtime_bytes\":48,\"snapshot_bytes\":64,\"ux_bytes\":80,\"frames\":[\n{}\n]}}\n"
            ),
            core::mem::size_of::<Shell>(),
            frames.join(",\n")
        ),
    )?;
    println!(
        "Shell: {} replay frames, one 153600-byte host framebuffer",
        frames.len()
    );
    Ok(())
}

fn crc32(bytes: &[u8]) -> u32 {
    let mut crc = !0u32;
    for &byte in bytes {
        crc ^= byte as u32;
        for _ in 0..8 {
            crc = (crc >> 1) ^ ((0u32.wrapping_sub(crc & 1)) & 0xedb8_8320);
        }
    }
    !crc
}
fn chunk(out: &mut Vec<u8>, name: &[u8; 4], data: &[u8]) {
    out.extend_from_slice(&(data.len() as u32).to_be_bytes());
    let start = out.len();
    out.extend_from_slice(name);
    out.extend_from_slice(data);
    let crc = crc32(&out[start..]);
    out.extend_from_slice(&crc.to_be_bytes());
}
/// Minimal original host-only PNG encoder: RGB888 scanlines and stored DEFLATE,
/// preserving exact bit-expanded RGB565 values used by the existing UI tooling.
fn png(pixels: &[u16], path: &Path) -> io::Result<()> {
    let mut scan = Vec::with_capacity((240 * 3 + 1) * 320);
    for row in pixels.chunks_exact(240) {
        scan.push(0);
        for &p in row {
            let r = ((p >> 11) & 31) as u8;
            let g = ((p >> 5) & 63) as u8;
            let b = (p & 31) as u8;
            scan.extend_from_slice(&[
                (r << 3) | (r >> 2),
                (g << 2) | (g >> 4),
                (b << 3) | (b >> 2),
            ]);
        }
    }
    let mut zlib = vec![0x78, 0x01];
    let total = scan.len();
    let mut offset = 0;
    while offset < total {
        let len = (total - offset).min(65535);
        zlib.push(if offset + len == total { 1 } else { 0 });
        zlib.extend_from_slice(&(len as u16).to_le_bytes());
        zlib.extend_from_slice(&(!(len as u16)).to_le_bytes());
        zlib.extend_from_slice(&scan[offset..offset + len]);
        offset += len;
    }
    let (mut a, mut b) = (1u32, 0u32);
    for byte in scan {
        a = (a + byte as u32) % 65521;
        b = (b + a) % 65521;
    }
    zlib.extend_from_slice(&((b << 16) | a).to_be_bytes());
    let mut out = b"\x89PNG\r\n\x1a\n".to_vec();
    let mut ihdr = Vec::new();
    ihdr.extend_from_slice(&240u32.to_be_bytes());
    ihdr.extend_from_slice(&320u32.to_be_bytes());
    ihdr.extend_from_slice(&[8, 2, 0, 0, 0]);
    chunk(&mut out, b"IHDR", &ihdr);
    chunk(&mut out, b"IDAT", &zlib);
    chunk(&mut out, b"IEND", &[]);
    fs::write(path, out)
}
