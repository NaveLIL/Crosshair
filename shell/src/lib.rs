#![no_std]
#![forbid(unsafe_code)]
//! Original MIT shell state and composition on crosshair-ui. No hardware access,
//! allocator, framebuffer ownership, clock or invented device-status service.
use crosshair_ui::{Surface, components::Event};
mod adaptive;
pub mod fixtures;
use adaptive::PointerState;
pub use adaptive::{ChromeMode, KeyPhase, PointerPhase, UxSnapshot};
pub mod geometry;
pub mod icons;
mod render;
pub mod wallpaper;

pub const VERSION: &str = "0.1.2";
pub const UX_WORDS: usize = 20;
pub const RUNTIME_VERSION: u32 = 1;
pub const VALID_TIMER: u32 = 1;
pub const VALID_TASKS: u32 = 2;
pub const VALID_MEMORY: u32 = 4;
pub const VALID_INPUT: u32 = 8;
pub const HISTORY_CAPACITY: usize = 8;
pub const APP_COUNT: usize = 4;
pub const DESKTOP_COUNT: usize = 3;
pub const QUERY_CAPACITY: usize = 16;
pub const POINTER_SCALAR_BASE: u32 = 0x000f_0000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BuildInfo {
    pub version: &'static str,
    pub architecture: &'static str,
    pub environment: &'static str,
}
impl BuildInfo {
    pub const WAVE007: Self = Self {
        version: "0.1.0 / Wave007",
        architecture: "ARMv5TE",
        environment: "QEMU synthetic",
    };
    pub const WAVE007_1: Self = Self {
        version: "0.1.1 / Wave007.1",
        architecture: "ARMv5TE",
        environment: "QEMU synthetic",
    };
    pub const WAVE007_2: Self = Self {
        version: "0.1.2 / Wave007.2",
        architecture: "ARMv5TE",
        environment: "QEMU synthetic",
    };
}

/// Work performed by the most recent render call. Pixel counts describe
/// software composition and Surface dirty bounds, not full-frame publication
/// bytes, CPU cycles or physical display latency. A no-op clears all fields.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct RenderStats {
    pub wallpaper: wallpaper::DrawStats,
    pub dirty_rects: u32,
    pub dirty_pixels: u32,
    pub full: u32,
    pub rendered: u32,
}
impl RenderStats {
    pub const ZERO: Self = Self {
        wallpaper: wallpaper::DrawStats {
            packets_decoded: 0,
            pixels_decoded: 0,
            pixels_written: 0,
            runs_written: 0,
        },
        dirty_rects: 0,
        dirty_pixels: 0,
        full: 0,
        rendered: 0,
    };
    pub const fn words(self) -> [u32; 8] {
        [
            self.wallpaper.packets_decoded,
            self.wallpaper.pixels_decoded,
            self.wallpaper.pixels_written,
            self.wallpaper.runs_written,
            self.dirty_rects,
            self.dirty_pixels,
            self.full,
            self.rendered,
        ]
    }
}

/// Versioned kernel-supplied observation, not a writable kernel capability.
/// Invalid/version-mismatched groups are displayed as unavailable. Values are
/// diagnostic counters, never pointers, identities used for authorization, or
/// commands to the scheduler. Kernel integration owns the snapshot timing.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct RuntimeInfo {
    pub version: u32,
    pub valid: u32,
    pub ticks: u32,
    pub switches: u32,
    pub task_count: u32,
    pub ready_tasks: u32,
    pub running_tasks: u32,
    pub faulted_tasks: u32,
    pub working_ram_bytes: u32,
    pub events_delivered: u32,
    pub input_overflows: u32,
    pub reserved: u32,
}
impl RuntimeInfo {
    pub const UNKNOWN: Self = Self {
        version: RUNTIME_VERSION,
        valid: 0,
        ticks: 0,
        switches: 0,
        task_count: 0,
        ready_tasks: 0,
        running_tasks: 0,
        faulted_tasks: 0,
        working_ram_bytes: 0,
        events_delivered: 0,
        input_overflows: 0,
        reserved: 0,
    };
    pub const fn words(self) -> [u32; 12] {
        [
            self.version,
            self.valid,
            self.ticks,
            self.switches,
            self.task_count,
            self.ready_tasks,
            self.running_tasks,
            self.faulted_tasks,
            self.working_ram_bytes,
            self.events_delivered,
            self.input_overflows,
            self.reserved,
        ]
    }
    pub const fn from_words(w: [u32; 12]) -> Self {
        Self {
            version: w[0],
            valid: w[1],
            ticks: w[2],
            switches: w[3],
            task_count: w[4],
            ready_tasks: w[5],
            running_tasks: w[6],
            faulted_tasks: w[7],
            working_ram_bytes: w[8],
            events_delivered: w[9],
            input_overflows: w[10],
            reserved: w[11],
        }
    }
    pub const fn has(self, group: u32) -> bool {
        self.version == RUNTIME_VERSION && self.reserved == 0 && self.valid & group == group
    }
}

#[repr(u32)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Screen {
    Desktop = 0,
    Today = 1,
    Launcher = 2,
    About = 3,
    Diagnostics = 4,
    Settings = 5,
}
impl Screen {
    pub const fn title(self) -> &'static str {
        match self {
            Self::Desktop => "Рабочий стол",
            Self::Today => "Сегодня",
            Self::Launcher => "Приложения",
            Self::About => "О системе",
            Self::Diagnostics => "Диагностика",
            Self::Settings => "Настройки",
        }
    }
    fn from_index(index: u32) -> Self {
        match index {
            1 => Self::Today,
            2 => Self::Launcher,
            3 => Self::About,
            4 => Self::Diagnostics,
            5 => Self::Settings,
            _ => Self::Desktop,
        }
    }
}
pub const APPS: [Screen; APP_COUNT] = [
    Screen::About,
    Screen::Diagnostics,
    Screen::Settings,
    Screen::Today,
];
pub const SHORTCUTS: [Screen; DESKTOP_COUNT] =
    [Screen::Today, Screen::Settings, Screen::Diagnostics];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Action {
    Key(Event),
    Home,
    SoftLeft,
    SoftRight,
    SwitchTask,
    Start,
    SystemPanel,
    CancelInput,
    HardwareKey {
        phase: KeyPhase,
        key: u8,
    },
    PointerEvent {
        phase: PointerPhase,
        x: u16,
        y: u16,
    },
    PointerHold {
        millis: u16,
    },
    /// One logical tap in the fixed guest pixel coordinate space. No press,
    /// release, calibration, drag or host-window coordinates are implied.
    Pointer {
        x: u16,
        y: u16,
    },
}
impl Action {
    /// Test/integration action numbers, not physical key scan codes.
    pub fn from_code(code: u32) -> Option<Self> {
        Some(match code {
            0 => Self::Key(Event::Up),
            1 => Self::Key(Event::Down),
            2 => Self::Key(Event::Left),
            3 => Self::Key(Event::Right),
            4 => Self::Key(Event::Select),
            5 => Self::Key(Event::Back),
            6 => Self::Key(Event::Menu),
            7 => Self::Home,
            8 => Self::SoftLeft,
            9 => Self::SoftRight,
            10 => Self::SwitchTask,
            11 => Self::Start,
            12 => Self::SystemPanel,
            _ => return None,
        })
    }
    fn semantic(self) -> Self {
        match self {
            Self::Key(Event::TextInput('\u{e000}')) => Self::Home,
            Self::Key(Event::TextInput('\u{e001}')) => Self::SoftLeft,
            Self::Key(Event::TextInput('\u{e002}')) => Self::SoftRight,
            Self::Key(Event::TextInput('\u{e003}')) => Self::SwitchTask,
            Self::Key(Event::TextInput(ch))
                if ch as u32 >= 0x90000 || (0xe004..=0xf0ff).contains(&(ch as u32)) =>
            {
                Self::from_wire(0x08000000 | ch as u32)
            }
            _ => self,
        }
    }
    /// Synthetic logical transport, not physical PDA key IDs. Invalid reserved
    /// words cancel pending input instead of becoming application text/actions.
    pub fn from_wire(wire: u32) -> Self {
        let scalar = wire & 0xffffff;
        if wire >> 24 == 8 {
            if (0x90000..=0x10ffff).contains(&scalar) {
                let block = (scalar - 0x90000) / 0x20000;
                let point = (scalar - 0x90000) % 0x20000;
                let x = (point & 255) as u16;
                let y = (point >> 8) as u16;
                if x >= 240 || y >= 320 {
                    return Self::CancelInput;
                }
                return match block {
                    0 => Self::PointerEvent {
                        phase: PointerPhase::Release,
                        x,
                        y,
                    },
                    1 => Self::PointerEvent {
                        phase: PointerPhase::Move,
                        x,
                        y,
                    },
                    2 => Self::PointerEvent {
                        phase: PointerPhase::Press,
                        x,
                        y,
                    },
                    _ => Self::Pointer { x, y },
                };
            }
            if (0xe100..=0xf0ff).contains(&scalar) {
                return Self::PointerHold {
                    millis: (scalar - 0xe100) as u16,
                };
            }
            if (0xe010..=0xe03c).contains(&scalar) {
                let code = scalar - 0xe010;
                let key = (code & 15) as u8;
                return if key <= 12 {
                    Self::HardwareKey {
                        phase: match code >> 4 {
                            0 => KeyPhase::Press,
                            1 => KeyPhase::Repeat,
                            _ => KeyPhase::Release,
                        },
                        key,
                    }
                } else {
                    Self::CancelInput
                };
            }
            return match scalar {
                0xe000 => Self::Home,
                0xe001 => Self::SoftLeft,
                0xe002 => Self::SoftRight,
                0xe003 => Self::SwitchTask,
                0xe004 => Self::Start,
                0xe005 => Self::SystemPanel,
                0xe006 => Self::PointerEvent {
                    phase: PointerPhase::Cancel,
                    x: 0,
                    y: 0,
                },
                0xe007 => Self::CancelInput,
                0xe004..=0xf0ff => Self::CancelInput,
                _ => char::from_u32(scalar)
                    .map_or(Self::CancelInput, |ch| Self::Key(Event::TextInput(ch))),
            };
        }
        if scalar != 0 {
            return Self::CancelInput;
        }
        match wire >> 24 {
            1 => Self::Key(Event::Up),
            2 => Self::Key(Event::Down),
            3 => Self::Key(Event::Left),
            4 => Self::Key(Event::Right),
            5 => Self::Key(Event::Select),
            6 => Self::Key(Event::Back),
            7 => Self::Key(Event::Menu),
            _ => Self::CancelInput,
        }
    }
}

/// Observation ABI for host/ARM verification. All offsets are consecutive u32
/// words, no pointers or private history bytes are exported.
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Snapshot {
    pub screen: u32,
    pub desktop_selected: u32,
    pub launcher_selected: u32,
    pub settings_selected: u32,
    pub today_selected: u32,
    pub overlay: u32,
    pub overlay_selected: u32,
    pub theme: u32,
    pub opened_mask: u32,
    pub history_depth: u32,
    pub events_processed: u32,
    pub revision: u32,
    pub renders: u32,
    pub runtime_valid: u32,
    pub runtime_ticks: u32,
    pub runtime_switches: u32,
}
impl Snapshot {
    pub const fn words(self) -> [u32; 16] {
        [
            self.screen,
            self.desktop_selected,
            self.launcher_selected,
            self.settings_selected,
            self.today_selected,
            self.overlay,
            self.overlay_selected,
            self.theme,
            self.opened_mask,
            self.history_depth,
            self.events_processed,
            self.revision,
            self.renders,
            self.runtime_valid,
            self.runtime_ticks,
            self.runtime_switches,
        ]
    }
}
const _: () = {
    assert!(core::mem::size_of::<RuntimeInfo>() == 48);
    assert!(core::mem::size_of::<Snapshot>() == 64);
    assert!(core::mem::size_of::<RenderStats>() == 32);
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Shell {
    build: BuildInfo,
    runtime: RuntimeInfo,
    screen: Screen,
    history: [Screen; HISTORY_CAPACITY],
    history_len: u8,
    desktop_selected: u8,
    launcher_selected: u8,
    query: [char; QUERY_CAPACITY],
    query_len: u8,
    settings_selected: u8,
    today_selected: u8,
    overlay: u8,
    overlay_selected: u8,
    theme: u8,
    opened_mask: u8,
    dirty: bool,
    desktop_dirty: u8,
    render_stats: RenderStats,
    events_processed: u32,
    revision: u32,
    renders: u32,
    modes: [u8; 6],
    scroll: [u16; 6],
    pointer: PointerState,
    gesture_serial: u32,
    actions_invoked: u32,
    input_cancels: u32,
    last_phase: u32,
    panel_invocations: u32,
    mode_changes: u32,
    held_keys: u16,
    last_key_phase: u32,
    last_key: u32,
    key_actions: u32,
}
impl Shell {
    pub const fn new(build: BuildInfo) -> Self {
        Self {
            build,
            runtime: RuntimeInfo::UNKNOWN,
            screen: Screen::Desktop,
            history: [Screen::Desktop; HISTORY_CAPACITY],
            history_len: 0,
            desktop_selected: 0,
            launcher_selected: 0,
            query: ['\0'; QUERY_CAPACITY],
            query_len: 0,
            settings_selected: 0,
            today_selected: 0,
            overlay: 0,
            overlay_selected: 0,
            theme: 0,
            opened_mask: 1,
            dirty: true,
            desktop_dirty: 0x80,
            render_stats: RenderStats::ZERO,
            events_processed: 0,
            revision: 0,
            renders: 0,
            modes: [0; 6],
            scroll: [0; 6],
            pointer: PointerState::EMPTY,
            gesture_serial: 0,
            actions_invoked: 0,
            input_cancels: 0,
            last_phase: 0,
            panel_invocations: 0,
            mode_changes: 0,
            held_keys: 0,
            last_key_phase: 0,
            last_key: 0,
            key_actions: 0,
        }
    }
    pub const fn snapshot(&self) -> Snapshot {
        Snapshot {
            screen: self.screen as u32,
            desktop_selected: self.desktop_selected as u32,
            launcher_selected: self.launcher_selected as u32,
            settings_selected: self.settings_selected as u32,
            today_selected: self.today_selected as u32,
            overlay: self.overlay as u32,
            overlay_selected: self.overlay_selected as u32,
            theme: self.theme as u32,
            opened_mask: self.opened_mask as u32,
            history_depth: self.history_len as u32,
            events_processed: self.events_processed,
            revision: self.revision,
            renders: self.renders,
            runtime_valid: if self.runtime.version == RUNTIME_VERSION && self.runtime.reserved == 0
            {
                self.runtime.valid
            } else {
                0
            },
            runtime_ticks: self.runtime.ticks,
            runtime_switches: self.runtime.switches,
        }
    }
    pub const fn runtime(&self) -> RuntimeInfo {
        self.runtime
    }
    pub const fn render_stats(&self) -> RenderStats {
        self.render_stats
    }
    pub fn query(&self) -> &[char] {
        &self.query[..self.query_len as usize]
    }
    pub fn launcher_matches(&self) -> usize {
        APPS.iter().filter(|app| self.matches(**app)).count()
    }
    fn matches(&self, app: Screen) -> bool {
        let mut title = app.title().chars();
        self.query()
            .iter()
            .all(|&query| title.next().is_some_and(|ch| fold(ch) == fold(query)))
    }
    fn query_changed(&mut self) {
        if !self.matches(APPS[self.launcher_selected as usize]) {
            if let Some(index) = APPS.iter().position(|app| self.matches(*app)) {
                self.launcher_selected = index as u8;
            }
        }
    }
    fn clear_query(&mut self) {
        self.query = ['\0'; QUERY_CAPACITY];
        self.query_len = 0;
    }
    pub const fn needs_render(&self) -> bool {
        self.dirty
    }
    pub fn update_runtime(&mut self, runtime: RuntimeInfo) {
        if self.runtime != runtime {
            if (self.runtime.has(VALID_INPUT) && !runtime.has(VALID_INPUT))
                || (runtime.has(VALID_INPUT)
                    && runtime.input_overflows != self.runtime.input_overflows)
            {
                self.handle(Action::CancelInput);
            }
            self.runtime = runtime;
            if matches!(self.screen, Screen::Today | Screen::Diagnostics) && self.overlay == 0 {
                self.invalidate();
            }
        }
    }
    fn invalidate(&mut self) {
        self.dirty = true;
        self.desktop_dirty = 0x80;
        self.revision = self.revision.wrapping_add(1);
    }
    fn open(&mut self, screen: Screen) {
        self.overlay = 0;
        if self.screen == screen {
            return;
        }
        if self.history_len as usize == HISTORY_CAPACITY {
            self.history.copy_within(1..HISTORY_CAPACITY, 0);
            self.history_len -= 1;
        }
        self.history[self.history_len as usize] = self.screen;
        self.history_len += 1;
        self.screen = screen;
        self.opened_mask |= 1 << screen as u8;
    }
    fn home(&mut self) {
        self.screen = Screen::Desktop;
        self.overlay = 0;
        self.history_len = 0;
    }
    fn back(&mut self) {
        if self.overlay != 0 {
            self.overlay = 0;
            return;
        }
        if self.screen == Screen::Launcher && self.query_len != 0 {
            self.clear_query();
            return;
        }
        if self.history_len != 0 {
            self.history_len -= 1;
            self.screen = self.history[self.history_len as usize];
        } else {
            self.home();
        }
    }
    fn switch(&mut self) {
        for step in 1..=6 {
            let index = (self.screen as u32 + step) % 6;
            if self.opened_mask & (1 << index) != 0 {
                self.open(Screen::from_index(index));
                return;
            }
        }
    }
    fn activate(&mut self) {
        match self.screen {
            Screen::Desktop => self.open(SHORTCUTS[self.desktop_selected as usize]),
            Screen::Launcher => {
                if self.matches(APPS[self.launcher_selected as usize]) {
                    self.open(APPS[self.launcher_selected as usize]);
                }
            }
            Screen::Today => self.open(if self.today_selected == 0 {
                Screen::Launcher
            } else {
                Screen::Diagnostics
            }),
            Screen::Settings => {
                if self.settings_selected == 0 {
                    self.theme ^= 1;
                } else {
                    self.overlay = 3;
                    self.overlay_selected = 0;
                }
            }
            Screen::About | Screen::Diagnostics => {}
        }
    }
    fn menu(&mut self) {
        if self.overlay != 0 {
            self.overlay = 0;
            return;
        }
        if self.mode_available() {
            self.system_panel();
            return;
        }
        self.overlay = if self.screen == Screen::Launcher {
            2
        } else {
            1
        };
        self.overlay_selected = 0;
    }
    fn activate_overlay(&mut self) {
        let kind = self.overlay;
        let selected = self.overlay_selected;
        self.overlay = 0;
        match kind {
            1 => match selected {
                0 => self.open(Screen::Today),
                1 => self.open(Screen::Launcher),
                2 => self.open(Screen::Settings),
                3 => self.open(Screen::Diagnostics),
                4 => self.open(Screen::About),
                _ => self.switch(),
            },
            2 => match selected {
                0 => {
                    if self.launcher_matches() == 0 {
                        self.clear_query();
                    } else {
                        self.activate();
                    }
                }
                1 => self.home(),
                _ => self.open(Screen::About),
            },
            3 => {
                if selected == 0 {
                    self.theme = 0;
                }
            }
            4 => match selected {
                0 => self.home(),
                1 => self.open(Screen::Launcher),
                2 => self.back(),
                3 => self.switch(),
                4..=6 if self.mode_available() => self.set_mode(ChromeMode::from_u8(selected - 4)),
                _ => {}
            },
            _ => {}
        }
    }
    fn soft_left(&mut self) {
        if self.overlay != 0 {
            if self.overlay == 3 {
                self.overlay_selected = 0;
            }
            self.activate_overlay();
        } else if self.screen == Screen::Desktop {
            self.open(Screen::Launcher);
        } else if matches!(self.screen, Screen::About | Screen::Diagnostics) {
            self.back();
        } else {
            self.activate();
        }
    }
    /// Consumes one existing logical action. Event counters include ignored
    /// input, while redraw occurs only for visible changes. Private-use Unicode
    /// actions travel through the existing TextInput wire; no scan code coupling.
    pub fn handle(&mut self, action: Action) -> bool {
        let mut action = action.semantic();
        if matches!(action, Action::Pointer { x, y } if x >= geometry::WIDTH || y >= geometry::HEIGHT)
        {
            return false;
        }
        let before = *self;
        if action == Action::CancelInput {
            self.cancel_input();
            let changed =
                before.pointer.active && before.pointer.target != 0 && !before.pointer.cancelled;
            if changed {
                self.invalidate();
            }
            return changed;
        }
        self.events_processed = self.events_processed.wrapping_add(1);
        if let Action::HardwareKey { phase, key } = action {
            action = self
                .hardware_action(phase, key)
                .unwrap_or(Action::HardwareKey { phase, key });
        }
        if !matches!(
            action,
            Action::Pointer { .. }
                | Action::PointerEvent { .. }
                | Action::PointerHold { .. }
                | Action::HardwareKey { .. }
        ) {
            self.cancel_pointer();
        }
        if matches!(
            action,
            Action::Key(Event::Select | Event::Back | Event::Menu)
                | Action::Home
                | Action::Start
                | Action::SystemPanel
                | Action::SwitchTask
                | Action::SoftLeft
                | Action::SoftRight
        ) {
            self.actions_invoked = self.actions_invoked.wrapping_add(1);
        }
        if let Action::Pointer { x, y } = action {
            self.tap(x, y);
        } else if let Action::PointerEvent { phase, x, y } = action {
            self.pointer_event(phase, x, y);
        } else if let Action::PointerHold { millis } = action {
            self.pointer_hold(millis);
        } else if action == Action::Home {
            self.home();
        } else if action == Action::Start {
            self.open(Screen::Launcher);
        } else if action == Action::SystemPanel {
            if self.overlay == 4 {
                self.overlay = 0;
            } else {
                self.system_panel();
            }
        } else if action == Action::SwitchTask {
            self.overlay = 0;
            self.switch();
        } else if self.overlay != 0 {
            let count = self.overlay_count();
            match action {
                Action::Key(Event::Back) | Action::Key(Event::Menu) | Action::SoftRight => {
                    self.overlay = 0
                }
                Action::Key(Event::Select) => self.activate_overlay(),
                Action::SoftLeft => self.soft_left(),
                Action::Key(Event::Up) | Action::Key(Event::Left) => {
                    self.overlay_selected = (self.overlay_selected + count - 1) % count
                }
                Action::Key(Event::Down) | Action::Key(Event::Right) => {
                    self.overlay_selected = (self.overlay_selected + 1) % count
                }
                _ => {}
            }
        } else {
            match action {
                Action::Key(Event::Back) => self.back(),
                Action::Key(Event::Menu) | Action::SoftRight => self.menu(),
                Action::SoftLeft => self.soft_left(),
                Action::Key(Event::Select) => self.activate(),
                Action::Key(Event::Up) => self.move_focus(-1, 0),
                Action::Key(Event::Down) => self.move_focus(1, 0),
                Action::Key(Event::Left) => self.move_focus(0, -1),
                Action::Key(Event::Right) => self.move_focus(0, 1),
                Action::Key(Event::TextInput(ch)) => {
                    if self.screen == Screen::Launcher {
                        if ch == '\u{8}' {
                            if self.query_len > 0 {
                                self.query_len -= 1;
                                self.query[self.query_len as usize] = '\0';
                                self.query_changed();
                            }
                        } else if !ch.is_control() && (self.query_len as usize) < QUERY_CAPACITY {
                            self.query[self.query_len as usize] = ch;
                            self.query_len += 1;
                            self.query_changed();
                        }
                    }
                }
                _ => {}
            }
        }
        let changed = self.screen != before.screen
            || self.desktop_selected != before.desktop_selected
            || self.launcher_selected != before.launcher_selected
            || self.settings_selected != before.settings_selected
            || self.today_selected != before.today_selected
            || self.overlay != before.overlay
            || self.overlay_selected != before.overlay_selected
            || self.theme != before.theme
            || self.query != before.query
            || self.query_len != before.query_len
            || self.modes != before.modes
            || self.scroll != before.scroll
            || self.pressed_target() != before.pressed_target();
        if changed || self.screen == Screen::Diagnostics {
            if changed
                && before.screen == Screen::Desktop
                && self.screen == Screen::Desktop
                && before.theme == self.theme
            {
                self.dirty = true;
                if before.overlay != 0 || self.overlay != 0 {
                    self.desktop_dirty |= 0x40;
                    if before.overlay != 0 && self.overlay == 0 {
                        self.desktop_dirty |= 0x20;
                    }
                } else {
                    self.desktop_dirty |=
                        (1 << before.desktop_selected) | (1 << self.desktop_selected);
                }
                self.revision = self.revision.wrapping_add(1);
            } else {
                self.invalidate();
            }
        }
        changed
    }
    fn move_focus(&mut self, vertical: i8, horizontal: i8) {
        match self.screen {
            Screen::Desktop => {
                self.desktop_selected = (self.desktop_selected as i8 + vertical + horizontal)
                    .clamp(0, DESKTOP_COUNT as i8 - 1)
                    as u8;
            }
            Screen::Launcher => {
                let direction = vertical + horizontal;
                if direction < 0 {
                    if let Some(index) = (0..self.launcher_selected as usize)
                        .rev()
                        .find(|&index| self.matches(APPS[index]))
                    {
                        self.launcher_selected = index as u8;
                    }
                } else if direction > 0 {
                    if let Some(index) = (self.launcher_selected as usize + 1..APP_COUNT)
                        .find(|&index| self.matches(APPS[index]))
                    {
                        self.launcher_selected = index as u8;
                    }
                }
            }
            Screen::Today => {
                self.today_selected =
                    (self.today_selected as i8 + vertical + horizontal).clamp(0, 1) as u8
            }
            Screen::Settings => {
                self.settings_selected =
                    (self.settings_selected as i8 + vertical + horizontal).clamp(0, 1) as u8
            }
            Screen::About | Screen::Diagnostics => self.scroll_by(vertical + horizontal),
        }
    }
    /// Composes into the caller's sole framebuffer only on a dirty state. The
    /// existing Surface owns clipping, RGB565 pixels and dirty-rectangle retry.
    pub fn render(&mut self, surface: &mut Surface<'_>) -> bool {
        if !self.dirty {
            self.render_stats = RenderStats::ZERO;
            return false;
        }
        self.renders = self.renders.wrapping_add(1);
        let full = !(self.screen == Screen::Desktop && self.desktop_dirty & 0x80 == 0);
        let wallpaper = if !full {
            render::redraw_desktop_focus(self, surface, self.desktop_dirty)
        } else {
            render::draw(self, surface)
        };
        self.render_stats = RenderStats {
            wallpaper,
            dirty_rects: surface.dirty_rects().len() as u32,
            dirty_pixels: surface
                .dirty_rects()
                .iter()
                .map(|r| (r.width() * r.height()) as u32)
                .sum(),
            full: u32::from(full),
            rendered: 1,
        };
        self.dirty = false;
        self.desktop_dirty = 0;
        true
    }
}

fn fold(ch: char) -> char {
    match ch {
        'A'..='Z' | 'А'..='Я' => char::from_u32(ch as u32 + 32).unwrap_or(ch),
        'Ё' => 'ё',
        _ => ch,
    }
}

#[cfg(test)]
mod tests;
