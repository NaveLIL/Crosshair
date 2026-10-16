use crosshair_ui::{
    Surface,
    components::{AppsScreen, Event, InputQueue},
    fixtures::{BOUNDARY_CAPTURE_STEPS, BOUNDARY_SCENARIO, CAPTURE_STEPS, SCENARIO},
    theme::layout,
};
use std::{
    fs::File,
    io::{BufWriter, Write},
};

pub fn scenario() -> AppsScreen {
    let mut screen = AppsScreen::new();
    let mut queue = InputQueue::new();
    for event in SCENARIO {
        queue.push(event).unwrap();
        screen.handle(queue.pop().unwrap());
    }
    screen
}

fn event_json(event: Event) -> String {
    match event {
        Event::TextInput(ch) => {
            let text = match ch {
                '"' => "\\\"".to_owned(),
                '\\' => "\\\\".to_owned(),
                c if c.is_control() => format!("\\u{:04x}", c as u32),
                c => c.to_string(),
            };
            format!("{{\"kind\":\"TextInput\",\"text\":\"{text}\"}}")
        }
        key => format!("{{\"kind\":\"{key:?}\"}}"),
    }
}

fn main() -> std::io::Result<()> {
    let mut args = std::env::args().skip(1);
    let raw = args.next().expect("output raw565 path required");
    let trace = args.next().expect("output JSON trace path required");
    let directory = args
        .next()
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| {
            std::path::Path::new(&trace)
                .parent()
                .unwrap()
                .join("design-system")
        });
    std::fs::create_dir_all(&directory)?;
    let mut screen = AppsScreen::new();
    let mut queue = InputQueue::new();
    let mut records = Vec::new();
    let mut frames = Vec::new();
    // One host-owned framebuffer is reused for every captured state.
    let mut pixels = vec![0u16; layout::WIDTH as usize * layout::HEIGHT as usize];
    let mut surface = Surface::new(
        &mut pixels,
        layout::WIDTH as usize,
        layout::HEIGHT as usize,
        layout::WIDTH as usize,
    )
    .unwrap();
    frames.push(capture(&screen, &mut surface, &directory, "step", 0)?);
    for (step, event) in SCENARIO.into_iter().enumerate() {
        queue.push(event).unwrap();
        let changed = screen.handle(queue.pop().unwrap());
        if CAPTURE_STEPS.contains(&(step + 1)) {
            frames.push(capture(
                &screen,
                &mut surface,
                &directory,
                "step",
                step + 1,
            )?);
        }
        records.push(record(step, event, changed, &screen));
    }
    screen.render(&mut surface);
    write_raw(surface.pixels(), std::path::Path::new(&raw))?;
    std::fs::write(
        directory.join("frames.json"),
        format!(
            "{{\n  \"schema\":\"crosshair-ui-frames-v1\",\n  \"theme\":\"0.1\",\n  \"pixel_format\":\"RGB565_LE\",\n  \"frames\":[\n{}\n  ]\n}}\n",
            frames.join(",\n")
        ),
    )?;
    std::fs::write(
        trace,
        format!(
            "{{\n  \"schema\":\"crosshair-ui-input-trace-v1\",\n  \"physical_input\":false,\n  \"events\":[\n{}\n  ]\n}}\n",
            records.join(",\n")
        ),
    )?;
    boundary(&mut surface, &directory)?;
    println!(
        "UI Design System0.1 scenario: {} events, item {:?}, scroll {}, opened {}; one 153600-byte framebuffer",
        SCENARIO.len(),
        screen.selected_item(),
        screen.scroll(),
        screen.opened_count()
    );
    Ok(())
}

fn write_raw(pixels: &[u16], path: &std::path::Path) -> std::io::Result<()> {
    let mut writer = BufWriter::new(File::create(path)?);
    for pixel in pixels {
        writer.write_all(&pixel.to_le_bytes())?;
    }
    writer.flush()
}

fn capture(
    screen: &AppsScreen,
    surface: &mut Surface<'_>,
    directory: &std::path::Path,
    prefix: &str,
    state: usize,
) -> std::io::Result<String> {
    screen.render(surface);
    let file = format!("{prefix}-{state:02}.raw565");
    write_raw(surface.pixels(), &directory.join(&file))?;
    let mut hash = 0xcbf29ce484222325u64;
    for pixel in surface.pixels() {
        for byte in pixel.to_le_bytes() {
            hash = (hash ^ byte as u64).wrapping_mul(0x100000001b3);
        }
    }
    Ok(format!(
        concat!(
            "    {{\"state\":{},\"file\":\"{}\",\"width\":{},\"height\":{},\"stride\":{},\"bytes\":153600,",
            "\"fnv1a64\":\"0x{:016x}\",\"view\":\"{:?}\",\"focus\":\"{:?}\",\"selected_item\":{},",
            "\"scroll\":{},\"matches\":{},\"filter_len\":{},\"opened\":{}}}"
        ),
        state,
        file,
        surface.width(),
        surface.height(),
        surface.stride(),
        hash,
        screen.view(),
        screen.focus(),
        screen
            .selected_item()
            .map_or("null".to_owned(), |i| i.to_string()),
        screen.scroll(),
        screen.match_count(),
        screen.filter().len(),
        screen.opened_count()
    ))
}

fn record(step: usize, event: Event, changed: bool, screen: &AppsScreen) -> String {
    format!(
        concat!(
            "    {{\"step\":{},\"event\":{},\"changed\":{},",
            "\"view\":\"{:?}\",\"focus\":\"{:?}\",\"selected_item\":{},",
            "\"scroll\":{},\"matches\":{},\"filter_len\":{},\"opened\":{}}}"
        ),
        step,
        event_json(event),
        changed,
        screen.view(),
        screen.focus(),
        screen
            .selected_item()
            .map_or("null".to_owned(), |i| i.to_string()),
        screen.scroll(),
        screen.match_count(),
        screen.filter().len(),
        screen.opened_count()
    )
}

fn boundary(surface: &mut Surface<'_>, directory: &std::path::Path) -> std::io::Result<()> {
    let mut screen = AppsScreen::new();
    let mut queue = InputQueue::new();
    let mut records = Vec::new();
    let mut frames = vec![capture(&screen, surface, directory, "boundary-step", 0)?];
    for (step, event) in BOUNDARY_SCENARIO.into_iter().enumerate() {
        queue.push(event).unwrap();
        let changed = screen.handle(queue.pop().unwrap());
        records.push(record(step, event, changed, &screen));
        if BOUNDARY_CAPTURE_STEPS.contains(&(step + 1)) {
            frames.push(capture(
                &screen,
                surface,
                directory,
                "boundary-step",
                step + 1,
            )?);
        }
    }
    std::fs::write(
        directory.join("boundary-trace.json"),
        format!(
            "{{\n  \"schema\":\"crosshair-ui-input-trace-v1\",\n  \"physical_input\":false,\n  \"events\":[\n{}\n  ]\n}}\n",
            records.join(",\n")
        ),
    )?;
    std::fs::write(
        directory.join("boundary-frames.json"),
        format!(
            "{{\n  \"schema\":\"crosshair-ui-frames-v1\",\n  \"theme\":\"0.1\",\n  \"pixel_format\":\"RGB565_LE\",\n  \"frames\":[\n{}\n  ]\n}}\n",
            frames.join(",\n")
        ),
    )?;
    Ok(())
}
