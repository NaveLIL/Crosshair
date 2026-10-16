use crosshair_ui::{
    Surface,
    components::{AppsScreen, Event, InputQueue},
};
use std::{
    fs::File,
    io::{BufWriter, Write},
};

// Every transition is driven through the same bounded FIFO a future input
// adapter can use. No physical driver, wall clock or host window participates.
pub const SCENARIO: [Event; 37] = [
    Event::Down,
    Event::Down,
    Event::Down,
    Event::Down,
    Event::Down,
    Event::Down,
    Event::Down,
    Event::Down,
    Event::Down,
    Event::Down,
    Event::Select,
    Event::Menu,
    Event::Back,
    Event::Back,
    Event::TextInput('Ц'),
    Event::Down,
    Event::Select,
    Event::Back,
    Event::Back,
    Event::Right,
    Event::Select,
    Event::Down,
    Event::Select,
    Event::Left,
    Event::Select,
    Event::Back,
    Event::Down,
    Event::Down,
    Event::Down,
    Event::Down,
    Event::Down,
    Event::Down,
    Event::Down,
    Event::Down,
    Event::Down,
    Event::Down,
    Event::Down,
];

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
    let mut screen = AppsScreen::new();
    let mut queue = InputQueue::new();
    let mut records = Vec::new();
    for (step, event) in SCENARIO.into_iter().enumerate() {
        queue.push(event).unwrap();
        let changed = screen.handle(queue.pop().unwrap());
        records.push(format!(
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
        ));
    }
    let mut pixels = vec![0u16; 240 * 320];
    let mut surface = Surface::new(&mut pixels, 240, 320, 240).unwrap();
    screen.render(&mut surface);
    let mut writer = BufWriter::new(File::create(raw)?);
    for pixel in surface.pixels() {
        writer.write_all(&pixel.to_le_bytes())?;
    }
    writer.flush()?;
    std::fs::write(
        trace,
        format!(
            "{{\n  \"schema\":\"crosshair-ui-input-trace-v1\",\n  \"physical_input\":false,\n  \"events\":[\n{}\n  ]\n}}\n",
            records.join(",\n")
        ),
    )?;
    println!(
        "UI0.2 scenario: {} events, item {:?}, scroll {}, opened {}; one 153600-byte framebuffer",
        SCENARIO.len(),
        screen.selected_item(),
        screen.scroll(),
        screen.opened_count()
    );
    Ok(())
}
