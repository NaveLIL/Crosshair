//! Keyboard-driven components and a bounded, explicitly test-only applications screen.
//! Physical key mapping, repeat timing, stylus calibration and display transport stay outside.

use crate::{
    Rgb565, Surface,
    theme::{colors::*, layout},
};

pub use crate::fixtures::SCENARIO;

pub const FILTER_CAPACITY: usize = 16;
pub const INPUT_CAPACITY: usize = 8;
pub const VISIBLE_ROWS: usize = layout::VISIBLE_ROWS;
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Area {
    pub x: i32,
    pub y: i32,
    pub width: u16,
    pub height: u16,
}

fn label(surface: &mut Surface<'_>, area: Area, text: &str, color: Rgb565) {
    if area.width < layout::FONT_INK_WIDTH || area.height < layout::FONT_HEIGHT {
        return;
    }
    // The last glyph may extend two pixels past its six-pixel advance.
    // Restrict ink to the component, independently of Surface's screen clipping.
    let limit = (area.width - layout::FONT_INK_WIDTH) as usize / layout::FONT_ADVANCE as usize + 1;
    let y = area
        .y
        .saturating_add((area.height - layout::FONT_HEIGHT) as i32 / 2);
    for (index, ch) in text
        .chars()
        .take(limit)
        .take_while(|c| *c != '\n')
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
        for amount in 0..layout::FOCUS_WIDTH {
            let inner = inset(area, amount);
            surface.stroke_rect(
                inner.x,
                inner.y,
                inner.width as u32,
                inner.height as u32,
                FOCUS,
            );
        }
    }
}

pub fn list_row(surface: &mut Surface<'_>, area: Area, text: &str, selected: bool, focused: bool) {
    if selected {
        selection(surface, area, focused);
    } else {
        surface.fill_rect(
            area.x,
            area.y,
            area.width as u32,
            area.height as u32,
            SURFACE,
        );
    }
    label(surface, inset(area, layout::LABEL_PADDING), text, INK);
}

pub fn button(surface: &mut Surface<'_>, area: Area, text: &str, focused: bool) {
    surface.fill_rect(
        area.x,
        area.y,
        area.width as u32,
        area.height as u32,
        SOFTKEY,
    );
    if focused {
        selection(surface, area, true);
    } else {
        surface.stroke_rect(area.x, area.y, area.width as u32, area.height as u32, EDGE);
    }
    label(surface, inset(area, layout::LABEL_PADDING), text, INK);
}

pub fn title_bar(surface: &mut Surface<'_>, area: Area, text: &str) {
    surface.fill_rect(
        area.x,
        area.y,
        area.width as u32,
        area.height as u32,
        HEADER,
    );
    let text_area = Area {
        x: area.x.saturating_add(layout::HEADER_PADDING as i32),
        width: area.width.saturating_sub(layout::HEADER_PADDING * 2),
        ..area
    };
    label(surface, text_area, text, WHITE);
}

/// Static mode labels only. Time, battery and radio require proven data sources.
pub fn system_strip(surface: &mut Surface<'_>) {
    surface.fill_rect(
        0,
        layout::SYSTEM_TOP as i32,
        layout::WIDTH as u32,
        layout::SYSTEM_HEIGHT as u32,
        SYSTEM,
    );
    surface.text(
        layout::LABEL_PADDING as i32,
        layout::SYSTEM_TEXT_Y as i32,
        "Система",
        WHITE,
    );
    surface.text(
        layout::SYSTEM_RIGHT_X as i32,
        layout::SYSTEM_TEXT_Y as i32,
        "Тест",
        WHITE,
    );
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
            y: layout::SOFTKEY_TOP as i32,
            width: layout::SOFTKEY_WIDTH,
            height: layout::SOFTKEY_HEIGHT,
        },
        left,
        focus == Focus::LeftSoftkey,
    );
    button(
        surface,
        Area {
            x: layout::SOFTKEY_WIDTH as i32,
            y: layout::SOFTKEY_TOP as i32,
            width: layout::SOFTKEY_WIDTH,
            height: layout::SOFTKEY_HEIGHT,
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
        surface.fill(BACKGROUND);
        system_strip(surface);
        let title = match self.view {
            View::List => "Приложения",
            View::Action(_) => "Проверка",
            View::Menu => "Меню",
        };
        title_bar(
            surface,
            Area {
                x: 0,
                y: layout::HEADER_TOP as i32,
                width: layout::WIDTH,
                height: layout::HEADER_HEIGHT,
            },
            title,
        );
        match self.view {
            View::List => {
                surface.fill_rect(
                    0,
                    layout::SEARCH_TOP as i32,
                    layout::WIDTH as u32,
                    layout::SEARCH_HEIGHT as u32,
                    SURFACE,
                );
                surface.text(
                    layout::PAGE_LEFT as i32,
                    layout::SEARCH_TEXT_Y as i32,
                    "Поиск:",
                    MUTED,
                );
                for (i, ch) in self.filter().iter().enumerate() {
                    let mut bytes = [0; 4];
                    surface.text(
                        layout::FILTER_X as i32 + i as i32 * layout::FONT_ADVANCE as i32,
                        layout::SEARCH_TEXT_Y as i32,
                        ch.encode_utf8(&mut bytes),
                        INK,
                    );
                }
                if self.match_count() == 0 {
                    if self.focus == Focus::List {
                        selection(surface, row_area(0), true);
                    }
                    label(
                        surface,
                        inset(row_area(0), layout::LABEL_PADDING),
                        "Нет совпадений",
                        INK,
                    );
                }
                for row in 0..VISIBLE_ROWS {
                    let position = self.scroll() + row;
                    if let Some(item) = self.item_at(position) {
                        list_row(
                            surface,
                            row_area(row),
                            ITEMS[item as usize],
                            position == self.selected_position(),
                            self.focus == Focus::List,
                        );
                    }
                }
                scrollbar(surface, self.scroll(), self.match_count());
                surface.fill_rect(
                    0,
                    layout::STATUS_TOP as i32,
                    layout::WIDTH as u32,
                    layout::STATUS_HEIGHT as u32,
                    SURFACE,
                );
                number(
                    surface,
                    layout::PAGE_LEFT as i32,
                    layout::STATUS_TEXT_Y as i32,
                    if self.match_count() == 0 {
                        0
                    } else {
                        self.selected + 1
                    },
                );
                surface.text(
                    layout::STATUS_SLASH_X as i32,
                    layout::STATUS_TEXT_Y as i32,
                    "/",
                    MUTED,
                );
                number(
                    surface,
                    layout::STATUS_TOTAL_X as i32,
                    layout::STATUS_TEXT_Y as i32,
                    self.match_count() as u8,
                );
                surface.text(
                    layout::STATUS_HINT_X as i32,
                    layout::STATUS_TEXT_Y as i32,
                    "Тестовый список",
                    MUTED,
                );
                bottom_softkeys(surface, "Открыть", "Меню", self.focus);
            }
            View::Action(item) => {
                surface.text(
                    layout::PAGE_LEFT as i32,
                    layout::ACTION_NAME_Y as i32,
                    ITEMS[item as usize],
                    INK,
                );
                surface.text(
                    layout::PAGE_LEFT as i32,
                    layout::ACTION_CAPTION_Y as i32,
                    "Тестовый просмотр",
                    MUTED,
                );
                // Real selected diagnostic previews, not phone/contact applications.
                match item % 3 {
                    0 => surface.text(
                        layout::PREVIEW_X as i32,
                        layout::PREVIEW_Y as i32,
                        "Съешь ещё мягких булок.\nЁё Йй Ъъ Ьь",
                        INK,
                    ),
                    1 => {
                        for (i, color) in [TEST_RED, TEST_GREEN, TEST_BLUE].iter().enumerate() {
                            surface.fill_rect(
                                layout::PREVIEW_X as i32 + i as i32 * layout::COLOR_PITCH as i32,
                                layout::PREVIEW_Y as i32,
                                layout::COLOR_WIDTH as u32,
                                layout::COLOR_HEIGHT as u32,
                                *color,
                            );
                        }
                    }
                    _ => {
                        surface.stroke_rect(
                            layout::PREVIEW_X as i32,
                            layout::PREVIEW_Y as i32,
                            layout::PREVIEW_WIDTH as u32,
                            layout::PREVIEW_HEIGHT as u32,
                            HEADER,
                        );
                        surface.line(
                            layout::PREVIEW_X as i32,
                            layout::PREVIEW_Y as i32,
                            (layout::PREVIEW_X + layout::PREVIEW_WIDTH - 1) as i32,
                            (layout::PREVIEW_Y + layout::PREVIEW_HEIGHT - 1) as i32,
                            INK,
                        );
                    }
                }
                surface.text(
                    layout::PAGE_LEFT as i32,
                    layout::BACK_HINT_Y as i32,
                    "Назад — к списку",
                    MUTED,
                );
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
                            x: layout::PAGE_LEFT as i32,
                            y: layout::MENU_TOP as i32 + i as i32 * layout::MENU_PITCH as i32,
                            width: layout::ROW_WIDTH,
                            height: layout::MENU_ROW_HEIGHT,
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

fn row_area(row: usize) -> Area {
    Area {
        x: layout::PAGE_LEFT as i32,
        y: layout::LIST_TOP as i32 + row as i32 * layout::ROW_PITCH as i32,
        width: layout::ROW_WIDTH,
        height: layout::ROW_HEIGHT,
    }
}

fn scrollbar(surface: &mut Surface<'_>, first: usize, total: usize) {
    if total <= VISIBLE_ROWS {
        return;
    }
    let track = layout::SCROLL_HEIGHT as usize;
    let thumb = (track * VISIBLE_ROWS / total)
        .max(layout::SCROLL_MIN_THUMB as usize)
        .min(track);
    let top = (track - thumb) * first / (total - VISIBLE_ROWS);
    surface.fill_rect(
        layout::SCROLL_X as i32,
        layout::LIST_TOP as i32,
        layout::SCROLL_WIDTH as u32,
        track as u32,
        SCROLL_TRACK,
    );
    surface.fill_rect(
        layout::SCROLL_X as i32,
        layout::LIST_TOP as i32 + top as i32,
        layout::SCROLL_WIDTH as u32,
        thumb as u32,
        SCROLL_THUMB,
    );
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
