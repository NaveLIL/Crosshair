//! Keyboard-driven components and a bounded, explicitly test-only applications screen.
//! Physical key mapping, repeat timing, stylus calibration and display transport stay outside.

use crate::{Rgb565, Surface};

pub const FILTER_CAPACITY: usize = 16;
pub const INPUT_CAPACITY: usize = 8;
pub const VISIBLE_ROWS: usize = 8;
pub const ITEMS: [&str; 16] = [
    "Текст",
    "Цвета",
    "Рамки",
    "Линии",
    "Кириллица",
    "Обрезка",
    "Фокус",
    "События",
    "Список",
    "Прокрутка",
    "Клавиши",
    "Возврат",
    "Кнопки",
    "Выделение",
    "Символы",
    "Прямоугольники",
];

const PAPER: Rgb565 = Rgb565::from_rgb(232, 238, 238);
const INK: Rgb565 = Rgb565::from_rgb(24, 40, 48);
const ACCENT: Rgb565 = Rgb565::from_rgb(40, 72, 88);
const SELECTED: Rgb565 = Rgb565::from_rgb(184, 210, 218);
const EDGE: Rgb565 = Rgb565::from_rgb(112, 136, 144);
const WHITE: Rgb565 = Rgb565(0xffff);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Area {
    pub x: i32,
    pub y: i32,
    pub width: u16,
    pub height: u16,
}

fn label(surface: &mut Surface<'_>, area: Area, text: &str, color: Rgb565) {
    if area.width < 8 || area.height < 13 {
        return;
    }
    // The last glyph may extend two pixels past its six-pixel advance.
    // Restrict ink to the component, independently of Surface's screen clipping.
    let limit = (area.width as usize - 8) / 6 + 1;
    let y = area.y.saturating_add((area.height as i32 - 13) / 2);
    for (index, ch) in text
        .chars()
        .take(limit)
        .take_while(|c| *c != '\n')
        .enumerate()
    {
        let mut bytes = [0; 4];
        surface.text(
            area.x.saturating_add(index as i32 * 6),
            y,
            ch.encode_utf8(&mut bytes),
            color,
        );
    }
}

fn inset(area: Area, amount: u16) -> Area {
    Area {
        x: area.x.saturating_add(amount as i32),
        y: area.y.saturating_add(amount as i32),
        width: area.width.saturating_sub(amount.saturating_mul(2)),
        height: area.height.saturating_sub(amount.saturating_mul(2)),
    }
}

/// Shared selection background and visible two-pixel keyboard focus border.
pub fn selection(surface: &mut Surface<'_>, area: Area, focused: bool) {
    surface.fill_rect(
        area.x,
        area.y,
        area.width as u32,
        area.height as u32,
        SELECTED,
    );
    if focused {
        surface.stroke_rect(
            area.x,
            area.y,
            area.width as u32,
            area.height as u32,
            ACCENT,
        );
        let inner = inset(area, 1);
        surface.stroke_rect(
            inner.x,
            inner.y,
            inner.width as u32,
            inner.height as u32,
            ACCENT,
        );
    }
}

pub fn list_row(surface: &mut Surface<'_>, area: Area, text: &str, selected: bool, focused: bool) {
    if selected {
        selection(surface, area, focused);
    } else {
        surface.fill_rect(area.x, area.y, area.width as u32, area.height as u32, PAPER);
    }
    label(surface, inset(area, 4), text, INK);
}

pub fn button(surface: &mut Surface<'_>, area: Area, text: &str, focused: bool) {
    surface.fill_rect(area.x, area.y, area.width as u32, area.height as u32, PAPER);
    if focused {
        selection(surface, area, true);
    } else {
        surface.stroke_rect(area.x, area.y, area.width as u32, area.height as u32, EDGE);
    }
    label(surface, inset(area, 4), text, INK);
}

pub fn title_bar(surface: &mut Surface<'_>, area: Area, text: &str) {
    surface.fill_rect(
        area.x,
        area.y,
        area.width as u32,
        area.height as u32,
        ACCENT,
    );
    label(surface, inset(area, 4), text, WHITE);
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Focus {
    List,
    LeftSoftkey,
    RightSoftkey,
}

pub fn bottom_softkeys(surface: &mut Surface<'_>, left: &str, right: &str, focus: Focus) {
    button(
        surface,
        Area {
            x: 0,
            y: 296,
            width: 120,
            height: 24,
        },
        left,
        focus == Focus::LeftSoftkey,
    );
    button(
        surface,
        Area {
            x: 120,
            y: 296,
            width: 120,
            height: 24,
        },
        right,
        focus == Focus::RightSoftkey,
    );
}

/// One logical press/repeat or one Unicode scalar. U+0008 erases one filter
/// character. Unsupported text/control characters are ignored, never split UTF-8.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Event {
    Up,
    Down,
    Left,
    Right,
    Select,
    Back,
    Menu,
    TextInput(char),
}

/// FIFO with explicit backpressure: a full queue returns the unconsumed event.
/// The caller can retry; silently overwriting a key press is never permitted.
pub struct InputQueue {
    events: [Option<Event>; INPUT_CAPACITY],
    head: u8,
    len: u8,
}

impl Default for InputQueue {
    fn default() -> Self {
        Self::new()
    }
}
impl InputQueue {
    pub const fn new() -> Self {
        Self {
            events: [None; INPUT_CAPACITY],
            head: 0,
            len: 0,
        }
    }
    pub const fn len(&self) -> usize {
        self.len as usize
    }
    pub const fn is_empty(&self) -> bool {
        self.len == 0
    }
    pub fn push(&mut self, event: Event) -> Result<(), Event> {
        if self.len() == INPUT_CAPACITY {
            return Err(event);
        }
        self.events[(self.head as usize + self.len()) % INPUT_CAPACITY] = Some(event);
        self.len += 1;
        Ok(())
    }
    pub fn pop(&mut self) -> Option<Event> {
        if self.is_empty() {
            return None;
        }
        let event = self.events[self.head as usize].take();
        self.head = (self.head + 1) % INPUT_CAPACITY as u8;
        self.len -= 1;
        event
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum View {
    List,
    Action(u8),
    Menu,
}

/// Owns only bounded UI state. It holds neither pixels nor hardware handles.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AppsScreen {
    filter: [char; FILTER_CAPACITY],
    filter_len: u8,
    selected: u8,
    scroll: u8,
    menu_selected: u8,
    focus: Focus,
    view: View,
    return_to: View,
    opened: u16,
}

impl Default for AppsScreen {
    fn default() -> Self {
        Self::new()
    }
}
impl AppsScreen {
    pub const fn new() -> Self {
        Self {
            filter: ['\0'; FILTER_CAPACITY],
            filter_len: 0,
            selected: 0,
            scroll: 0,
            menu_selected: 0,
            focus: Focus::List,
            view: View::List,
            return_to: View::List,
            opened: 0,
        }
    }
    pub const fn view(&self) -> View {
        self.view
    }
    pub const fn focus(&self) -> Focus {
        self.focus
    }
    pub const fn scroll(&self) -> usize {
        self.scroll as usize
    }
    pub const fn selected_position(&self) -> usize {
        self.selected as usize
    }
    pub const fn menu_selection(&self) -> usize {
        self.menu_selected as usize
    }
    pub const fn opened_count(&self) -> u16 {
        self.opened
    }
    pub fn filter(&self) -> &[char] {
        &self.filter[..self.filter_len as usize]
    }
    pub fn match_count(&self) -> usize {
        (0..ITEMS.len()).filter(|i| self.matches(*i)).count()
    }
    pub fn selected_item(&self) -> Option<u8> {
        self.item_at(self.selected_position())
    }

    fn matches(&self, index: usize) -> bool {
        if self.filter_len == 0 {
            return true;
        }
        let text = ITEMS[index];
        text.char_indices().any(|(start, _)| {
            let mut suffix = text[start..].chars();
            self.filter()
                .iter()
                .all(|wanted| suffix.next().is_some_and(|ch| lower(ch) == lower(*wanted)))
        })
    }
    fn item_at(&self, position: usize) -> Option<u8> {
        (0..ITEMS.len())
            .filter(|i| self.matches(*i))
            .nth(position)
            .map(|i| i as u8)
    }
    fn reset_list(&mut self) {
        self.selected = 0;
        self.scroll = 0;
        self.focus = Focus::List;
    }
    fn keep_visible(&mut self) {
        if self.selected < self.scroll {
            self.scroll = self.selected;
        }
        if self.selected as usize >= self.scroll() + VISIBLE_ROWS {
            self.scroll = self.selected + 1 - VISIBLE_ROWS as u8;
        }
    }
    fn open_menu(&mut self) {
        self.return_to = self.view;
        self.view = View::Menu;
        self.menu_selected = 0;
        self.focus = Focus::List;
    }
    fn close_menu(&mut self) {
        self.view = self.return_to;
        self.focus = if matches!(self.view, View::Action(_)) {
            Focus::LeftSoftkey
        } else {
            Focus::List
        };
    }
    fn primary(&mut self) {
        match self.view {
            View::List => {
                if let Some(item) = self.selected_item() {
                    self.view = View::Action(item);
                    self.opened = self.opened.saturating_add(1);
                    self.focus = Focus::LeftSoftkey;
                }
            }
            View::Action(_) => {
                self.view = View::List;
                self.focus = Focus::List;
            }
            View::Menu => match self.menu_selected {
                0 => {
                    self.filter_len = 0;
                    self.view = View::List;
                    self.reset_list();
                }
                1 => {
                    self.view = View::List;
                    self.focus = Focus::List;
                }
                _ => self.close_menu(),
            },
        }
    }
    fn secondary(&mut self) {
        if self.view == View::Menu {
            self.close_menu();
        } else {
            self.open_menu();
        }
    }
    /// Returns true exactly when state changes. Rendering and presentation are
    /// explicit caller decisions; no hidden timer or input source is consulted.
    pub fn handle(&mut self, event: Event) -> bool {
        let before = *self;
        match event {
            Event::Left => self.focus = Focus::LeftSoftkey,
            Event::Right => self.focus = Focus::RightSoftkey,
            Event::Menu => self.secondary(),
            Event::Back => match self.view {
                View::Menu => self.close_menu(),
                View::Action(_) => {
                    self.view = View::List;
                    self.focus = Focus::List;
                }
                View::List => {
                    self.filter_len = 0;
                    self.reset_list();
                }
            },
            Event::Select => match self.focus {
                Focus::RightSoftkey => self.secondary(),
                _ => self.primary(),
            },
            Event::Up | Event::Down => {
                if matches!(self.view, View::Action(_)) {
                    self.focus = Focus::LeftSoftkey;
                } else if self.focus != Focus::List {
                    self.focus = Focus::List;
                } else if self.view == View::Menu {
                    if event == Event::Up {
                        self.menu_selected = self.menu_selected.saturating_sub(1);
                    } else {
                        self.menu_selected = (self.menu_selected + 1).min(2);
                    }
                } else if self.view == View::List {
                    if event == Event::Up {
                        self.selected = self.selected.saturating_sub(1);
                    } else if self.selected as usize + 1 < self.match_count() {
                        self.selected += 1;
                    }
                    self.keep_visible();
                }
            }
            Event::TextInput(ch) if self.view == View::List => {
                if ch == '\u{8}' && self.filter_len > 0 {
                    self.filter_len -= 1;
                    self.filter[self.filter_len as usize] = '\0';
                    self.reset_list();
                } else if accepted_text(ch) && (self.filter_len as usize) < FILTER_CAPACITY {
                    self.filter[self.filter_len as usize] = ch;
                    self.filter_len += 1;
                    self.reset_list();
                }
            }
            Event::TextInput(_) => {}
        }
        *self != before
    }

    /// Fixed 240x320 layout; smaller validated surfaces clip it safely. Full
    /// repaint on a state change uses one borrowed framebuffer, no hidden copy.
    pub fn render(&self, surface: &mut Surface<'_>) {
        surface.fill(PAPER);
        let title = match self.view {
            View::List => "Приложения",
            View::Action(_) => "Проверка",
            View::Menu => "Меню",
        };
        title_bar(
            surface,
            Area {
                x: 0,
                y: 0,
                width: 240,
                height: 24,
            },
            title,
        );
        match self.view {
            View::List => {
                surface.text(8, 31, "Поиск:", INK);
                for (i, ch) in self.filter().iter().enumerate() {
                    let mut bytes = [0; 4];
                    surface.text(52 + i as i32 * 6, 31, ch.encode_utf8(&mut bytes), INK);
                }
                surface.text(8, 49, "Тестовый список", INK);
                if self.match_count() == 0 {
                    if self.focus == Focus::List {
                        selection(
                            surface,
                            Area {
                                x: 8,
                                y: 68,
                                width: 224,
                                height: 24,
                            },
                            true,
                        );
                    }
                    surface.text(12, 74, "Нет совпадений", INK);
                }
                for row in 0..VISIBLE_ROWS {
                    let position = self.scroll() + row;
                    if let Some(item) = self.item_at(position) {
                        list_row(
                            surface,
                            Area {
                                x: 8,
                                y: 68 + row as i32 * 26,
                                width: 224,
                                height: 24,
                            },
                            ITEMS[item as usize],
                            position == self.selected_position(),
                            self.focus == Focus::List,
                        );
                    }
                }
                number(
                    surface,
                    8,
                    280,
                    if self.match_count() == 0 {
                        0
                    } else {
                        self.selected + 1
                    },
                );
                surface.text(26, 280, "/", INK);
                number(surface, 38, 280, self.match_count() as u8);
                bottom_softkeys(surface, "Открыть", "Меню", self.focus);
            }
            View::Action(item) => {
                surface.text(8, 38, "Тестовый просмотр", INK);
                surface.text(8, 60, ITEMS[item as usize], INK);
                // This really draws a selected diagnostic preview. It does not
                // pretend to launch an unimplemented phone/contact application.
                match item % 3 {
                    0 => surface.text(12, 100, "Съешь ещё мягких булок.\nЁё Йй Ъъ Ьь", INK),
                    1 => {
                        for (i, color) in [Rgb565(0xf800), Rgb565(0x07e0), Rgb565(0x001f)]
                            .iter()
                            .enumerate()
                        {
                            surface.fill_rect(12 + i as i32 * 72, 100, 64, 48, *color);
                        }
                    }
                    _ => {
                        surface.stroke_rect(12, 100, 216, 70, ACCENT);
                        surface.line(12, 100, 227, 169, INK);
                    }
                }
                surface.text(8, 250, "Назад — к списку", INK);
                bottom_softkeys(surface, "Назад", "Меню", self.focus);
            }
            View::Menu => {
                for (i, text) in ["Очистить фильтр", "К списку", "Закрыть меню"]
                    .iter()
                    .enumerate()
                {
                    list_row(
                        surface,
                        Area {
                            x: 8,
                            y: 48 + i as i32 * 30,
                            width: 224,
                            height: 26,
                        },
                        text,
                        i == self.menu_selection(),
                        self.focus == Focus::List,
                    );
                }
                bottom_softkeys(surface, "Выбрать", "Закрыть", self.focus);
            }
        }
    }
}

fn accepted_text(ch: char) -> bool {
    ch.is_ascii_alphanumeric() || matches!(ch, 'А'..='я' | 'Ё' | 'ё' | ' ' | '-')
}
fn lower(ch: char) -> char {
    match ch {
        'A'..='Z' => ((ch as u8) + 32) as char,
        'А'..='Я' => char::from_u32(ch as u32 + 32).unwrap_or(ch),
        'Ё' => 'ё',
        _ => ch,
    }
}
fn number(surface: &mut Surface<'_>, x: i32, y: i32, value: u8) {
    let bytes = [b'0' + value / 10, b'0' + value % 10];
    let start = if value < 10 { 1 } else { 0 };
    // Both bytes are decimal ASCII by construction; conversion cannot fail.
    if let Ok(text) = core::str::from_utf8(&bytes[start..]) {
        surface.text(x, y, text, INK);
    }
}
