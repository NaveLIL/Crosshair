//! Bounded Shell-owned chrome, pointer capture and observation. No clocks,
//! hardware button codes, allocation or application-owned system commands.
use crate::{APPS, Action, Screen, Shell, geometry as g};

#[repr(u32)]
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum ChromeMode {
    #[default]
    Standard = 0,
    Compact = 1,
    Immersive = 2,
}
impl ChromeMode {
    pub const fn top(self) -> u16 {
        match self {
            Self::Standard => 24,
            Self::Compact => 16,
            Self::Immersive => 0,
        }
    }
    pub const fn content(self) -> g::Rect {
        g::Rect::new(0, self.top(), 240, 320 - self.top())
    }
    pub const fn from_u8(value: u8) -> Self {
        match value {
            1 => Self::Compact,
            2 => Self::Immersive,
            _ => Self::Standard,
        }
    }
}
#[repr(u32)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PointerPhase {
    Press = 1,
    Move = 2,
    Release = 3,
    Cancel = 4,
}
impl PointerPhase {
    pub const fn from_code(value: u32) -> Option<Self> {
        Some(match value {
            1 => Self::Press,
            2 => Self::Move,
            3 => Self::Release,
            4 => Self::Cancel,
            _ => return None,
        })
    }
}
#[repr(u32)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum KeyPhase {
    Press = 0,
    Repeat = 1,
    Release = 2,
}
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(crate) struct PointerState {
    pub active: bool,
    pub cancelled: bool,
    pub target: u16,
    pub start_y: u16,
    pub x: u16,
    pub y: u16,
    pub stationary: bool,
}
impl PointerState {
    pub const EMPTY: Self = Self {
        active: false,
        cancelled: false,
        target: 0,
        start_y: 0,
        x: 0,
        y: 0,
        stationary: false,
    };
}
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct UxSnapshot {
    pub version: u32,
    pub chrome_mode: u32,
    pub content_y: u32,
    pub content_height: u32,
    pub panel: u32,
    pub pointer_active: u32,
    pub pointer_target: u32,
    pub pointer_cancelled: u32,
    pub scroll_offset: u32,
    pub scroll_max: u32,
    pub gesture_serial: u32,
    pub actions_invoked: u32,
    pub input_cancels: u32,
    pub last_phase: u32,
    pub panel_invocations: u32,
    pub mode_changes: u32,
    pub held_keys: u32,
    pub last_key_phase: u32,
    pub last_key: u32,
    pub key_actions: u32,
}
impl UxSnapshot {
    pub const fn words(self) -> [u32; 20] {
        [
            self.version,
            self.chrome_mode,
            self.content_y,
            self.content_height,
            self.panel,
            self.pointer_active,
            self.pointer_target,
            self.pointer_cancelled,
            self.scroll_offset,
            self.scroll_max,
            self.gesture_serial,
            self.actions_invoked,
            self.input_cancels,
            self.last_phase,
            self.panel_invocations,
            self.mode_changes,
            self.held_keys,
            self.last_key_phase,
            self.last_key,
            self.key_actions,
        ]
    }
}
const _: () = assert!(core::mem::size_of::<UxSnapshot>() == 80);

pub(crate) mod target {
    pub const NONE: u16 = 0;
    pub const START: u16 = 1;
    pub const BACK: u16 = 2;
    pub const PANEL: u16 = 3;
    pub const DESKTOP: u16 = 16;
    pub const LAUNCHER: u16 = 32;
    pub const TODAY: u16 = 48;
    pub const SETTINGS: u16 = 64;
    pub const MENU: u16 = 80;
    pub const PANEL_ROW: u16 = 96;
    pub const DIALOG: u16 = 112;
    pub const SCROLL_UP: u16 = 120;
    pub const SCROLL_DOWN: u16 = 121;
}
impl Shell {
    pub const fn chrome_mode(&self) -> ChromeMode {
        ChromeMode::from_u8(self.modes[self.screen as usize])
    }
    pub const fn content_rect(&self) -> g::Rect {
        self.chrome_mode().content()
    }
    pub const fn mode_available(&self) -> bool {
        matches!(self.screen, Screen::About | Screen::Diagnostics)
    }
    pub fn scroll_max(&self) -> u16 {
        let rows: u16 = if self.screen == Screen::About {
            25
        } else if self.screen == Screen::Diagnostics {
            22
        } else {
            0
        };
        rows.saturating_sub(self.content_rect().height.saturating_sub(8) / 16)
    }
    pub const fn scroll_offset(&self) -> u16 {
        self.scroll[self.screen as usize]
    }
    pub fn ux_snapshot(&self) -> UxSnapshot {
        let content = self.content_rect();
        UxSnapshot {
            version: 1,
            chrome_mode: self.chrome_mode() as u32,
            content_y: content.y as u32,
            content_height: content.height as u32,
            panel: self.overlay as u32,
            pointer_active: self.pointer.active as u32,
            pointer_target: self.pointer.target as u32,
            pointer_cancelled: self.pointer.cancelled as u32,
            scroll_offset: self.scroll_offset() as u32,
            scroll_max: self.scroll_max() as u32,
            gesture_serial: self.gesture_serial,
            actions_invoked: self.actions_invoked,
            input_cancels: self.input_cancels,
            last_phase: self.last_phase,
            panel_invocations: self.panel_invocations,
            mode_changes: self.mode_changes,
            held_keys: self.held_keys as u32,
            last_key_phase: self.last_key_phase,
            last_key: self.last_key,
            key_actions: self.key_actions,
        }
    }
    pub(crate) fn cancel_pointer(&mut self) {
        if self.pointer.active {
            self.input_cancels = self.input_cancels.wrapping_add(1);
        }
        self.pointer = PointerState::default();
    }
    pub(crate) fn cancel_input(&mut self) {
        self.cancel_pointer();
        self.held_keys = 0;
    }
    pub(crate) fn hardware_action(&mut self, phase: KeyPhase, key: u8) -> Option<Action> {
        if key > 12 {
            self.cancel_input();
            return None;
        }
        self.last_key_phase = phase as u32;
        self.last_key = key as u32;
        let bit = 1u16 << key;
        let invoke = match phase {
            KeyPhase::Press => {
                let fresh = self.held_keys & bit == 0;
                self.held_keys |= bit;
                fresh
            }
            KeyPhase::Repeat => key < 4 && self.held_keys & bit != 0,
            KeyPhase::Release => {
                self.held_keys &= !bit;
                false
            }
        };
        if invoke {
            self.key_actions = self.key_actions.wrapping_add(1);
            Action::from_code(key as u32)
        } else {
            None
        }
    }
    pub(crate) fn system_panel(&mut self) {
        self.cancel_pointer();
        self.overlay = 4;
        self.overlay_selected = 0;
        self.panel_invocations = self.panel_invocations.wrapping_add(1);
    }
    pub(crate) fn set_mode(&mut self, mode: ChromeMode) {
        if self.mode_available() && self.chrome_mode() != mode {
            self.modes[self.screen as usize] = mode as u8;
            let mut scroll = crosshair_ui::pda::Scroll {
                offset: self.scroll_offset(),
            };
            let total = if self.screen == Screen::About { 25 } else { 22 };
            scroll.clamp(total, self.content_rect().height.saturating_sub(8) / 16);
            self.scroll[self.screen as usize] = scroll.offset;
            self.mode_changes = self.mode_changes.wrapping_add(1);
        }
    }
    pub(crate) fn overlay_count(&self) -> u8 {
        match self.overlay {
            1 => 6,
            2 => 3,
            3 => 2,
            4 => {
                if self.mode_available() {
                    8
                } else {
                    5
                }
            }
            _ => 0,
        }
    }
    pub(crate) fn scroll_by(&mut self, direction: i8) {
        let next =
            (self.scroll_offset() as i32 + direction as i32).clamp(0, self.scroll_max() as i32);
        let mut scroll = crosshair_ui::pda::Scroll {
            offset: next as u16,
        };
        let total = if self.screen == Screen::About {
            25
        } else if self.screen == Screen::Diagnostics {
            22
        } else {
            0
        };
        scroll.clamp(total, self.content_rect().height.saturating_sub(8) / 16);
        self.scroll[self.screen as usize] = scroll.offset;
    }
    pub(crate) fn hit_target(&self, x: u16, y: u16) -> u16 {
        use self::target as t;
        if x >= g::WIDTH || y >= g::HEIGHT {
            return t::NONE;
        }
        if self.overlay != 0 {
            if self.overlay == 3 {
                return g::DIALOG_BUTTONS
                    .iter()
                    .position(|r| r.contains(x, y))
                    .map_or(t::NONE, |i| t::DIALOG + i as u16);
            }
            let row = if self.overlay == 4 {
                g::panel_row
            } else {
                g::menu_row
            };
            return (0..self.overlay_count() as usize).find(|&i|row(i).contains(x,y)).map_or(t::NONE,|i|if self.overlay==4{t::PANEL_ROW}else{t::MENU}+i as u16);
        }
        let mode = self.chrome_mode();
        if mode == ChromeMode::Immersive {
            if g::IMMERSIVE_HANDLE.contains(x, y) {
                return t::PANEL;
            }
        } else {
            if g::start(mode).contains(x, y) {
                return t::START;
            }
            if g::panel_button(mode).contains(x, y) {
                return t::PANEL;
            }
            if self.screen != Screen::Desktop && g::back(mode).contains(x, y) {
                return t::BACK;
            }
        }
        match self.screen {
            Screen::Desktop => g::DESKTOP
                .iter()
                .position(|r| r.contains(x, y))
                .map_or(t::NONE, |i| t::DESKTOP + i as u16),
            Screen::Launcher => {
                let mut visible = 0;
                for (index, app) in APPS.into_iter().enumerate() {
                    if self.matches(app) {
                        if g::launcher_row(visible).contains(x, y) {
                            return t::LAUNCHER + index as u16;
                        }
                        visible += 1;
                    }
                }
                t::NONE
            }
            Screen::Today => g::TODAY_ACTIONS
                .iter()
                .position(|r| r.contains(x, y))
                .map_or(t::NONE, |i| t::TODAY + i as u16),
            Screen::Settings => g::SETTINGS
                .iter()
                .position(|r| r.contains(x, y))
                .map_or(t::NONE, |i| t::SETTINGS + i as u16),
            Screen::About | Screen::Diagnostics => {
                if self.scroll_max() > 0 && g::scroll_up(mode).contains(x, y) {
                    t::SCROLL_UP
                } else if self.scroll_max() > 0 && g::scroll_down(mode).contains(x, y) {
                    t::SCROLL_DOWN
                } else {
                    t::NONE
                }
            }
        }
    }
    pub(crate) fn focus_target(&mut self, target: u16) {
        use self::target as t;
        match target {
            16..=18 => self.desktop_selected = (target - t::DESKTOP) as u8,
            32..=35 => self.launcher_selected = (target - t::LAUNCHER) as u8,
            48..=49 => self.today_selected = (target - t::TODAY) as u8,
            64..=65 => self.settings_selected = (target - t::SETTINGS) as u8,
            80..=88 => self.overlay_selected = (target - t::MENU) as u8,
            96..=103 => self.overlay_selected = (target - t::PANEL_ROW) as u8,
            112..=113 => self.overlay_selected = (target - t::DIALOG) as u8,
            _ => {}
        }
    }
    pub(crate) fn invoke_target(&mut self, target: u16) {
        use self::target as t;
        self.focus_target(target);
        if target != t::NONE {
            self.actions_invoked = self.actions_invoked.wrapping_add(1);
        }
        match target {
            t::START => self.open(Screen::Launcher),
            t::BACK => self.back(),
            t::PANEL => self.system_panel(),
            16..=18 | 32..=35 | 48..=49 | 64..=65 => self.activate(),
            80..=88 | 96..=103 | 112..=113 => self.activate_overlay(),
            t::SCROLL_UP => self.scroll_by(-1),
            t::SCROLL_DOWN => self.scroll_by(1),
            _ => {}
        }
    }
    pub(crate) fn tap(&mut self, x: u16, y: u16) {
        self.cancel_pointer();
        let hit = self.hit_target(x, y);
        if hit == target::NONE && self.overlay != 0 && self.overlay != 3 {
            let bounds = if self.overlay == 4 {
                g::panel_bounds(self.overlay_count())
            } else {
                g::menu_bounds(self.overlay_count())
            };
            if !bounds.contains(x, y) {
                self.overlay = 0;
            }
        } else {
            self.invoke_target(hit);
        }
    }
    pub(crate) fn pointer_event(&mut self, phase: PointerPhase, x: u16, y: u16) {
        self.last_phase = phase as u32;
        let valid = x < g::WIDTH && y < g::HEIGHT;
        match phase {
            PointerPhase::Press => {
                self.cancel_pointer();
                if valid {
                    let target = self.hit_target(x, y);
                    self.focus_target(target);
                    self.pointer = PointerState {
                        active: true,
                        cancelled: false,
                        target,
                        start_y: y,
                        x,
                        y,
                        stationary: true,
                    };
                    self.gesture_serial = self.gesture_serial.wrapping_add(1);
                }
            }
            PointerPhase::Move => {
                if self.pointer.active {
                    if self.chrome_mode() == ChromeMode::Immersive
                        && self.overlay == 0
                        && self.pointer.start_y < 4
                        && valid
                        && y >= 12
                    {
                        self.system_panel();
                        return;
                    }
                    if self.pointer.x != x || self.pointer.y != y {
                        self.pointer.stationary = false;
                    }
                    self.pointer.x = x;
                    self.pointer.y = y;
                    if !valid || self.hit_target(x, y) != self.pointer.target {
                        self.pointer.cancelled = true;
                    }
                }
            }
            PointerPhase::Release => {
                if self.pointer.active {
                    let target = self.pointer.target;
                    let activate =
                        valid && !self.pointer.cancelled && self.hit_target(x, y) == target;
                    self.pointer = PointerState::default();
                    if activate {
                        // Use the same modal dismissal/no-fall-through policy
                        // as a legacy atomic tap, including an outside hit.
                        self.tap(x, y);
                    } else {
                        self.input_cancels = self.input_cancels.wrapping_add(1);
                    }
                }
            }
            PointerPhase::Cancel => self.cancel_pointer(),
        }
    }
    pub(crate) fn pointer_hold(&mut self, millis: u16) {
        self.last_phase = 5;
        if millis >= 600
            && self.pointer.active
            && !self.pointer.cancelled
            && self.pointer.stationary
        {
            self.focus_target(self.pointer.target);
            if self.screen == Screen::Launcher && self.overlay == 0 {
                self.cancel_pointer();
                self.menu();
            } else {
                self.system_panel();
            }
        }
    }
    pub(crate) fn pressed(&self, target: u16) -> bool {
        self.pointer.active && !self.pointer.cancelled && self.pointer.target == target
    }
    pub(crate) fn pressed_target(&self) -> u16 {
        if self.pointer.active && !self.pointer.cancelled {
            self.pointer.target
        } else {
            0
        }
    }
}
