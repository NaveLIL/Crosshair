//! Shared fixed 240x320 presentation and single-tap bounds. Rectangles are
//! half-open, so adjacent controls never both accept a boundary coordinate.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Rect {
    pub x: u16,
    pub y: u16,
    pub width: u16,
    pub height: u16,
}
impl Rect {
    pub const fn new(x: u16, y: u16, width: u16, height: u16) -> Self {
        Self {
            x,
            y,
            width,
            height,
        }
    }
    pub const fn contains(self, x: u16, y: u16) -> bool {
        x >= self.x
            && y >= self.y
            && (x as u32) < self.x as u32 + self.width as u32
            && (y as u32) < self.y as u32 + self.height as u32
    }
}
pub const WIDTH: u16 = 240;
pub const HEIGHT: u16 = 320;
pub const TOP: Rect = Rect::new(0, 0, 240, 24);
pub const WORKSPACE: Rect = Rect::new(0, 24, 240, 272);
pub const START: Rect = Rect::new(0, 0, 58, 24);
pub const APP_BACK: Rect = Rect::new(216, 0, 24, 24);
pub const SOFT_LEFT: Rect = Rect::new(0, 296, 120, 24);
pub const SOFT_RIGHT: Rect = Rect::new(120, 296, 120, 24);
pub const DESKTOP: [Rect; 3] = [
    Rect::new(8, 42, 72, 58),
    Rect::new(8, 108, 72, 58),
    Rect::new(8, 174, 72, 58),
];
pub const SEARCH: Rect = Rect::new(8, 34, 224, 22);
pub const fn launcher_row(visible: usize) -> Rect {
    if visible < 4 {
        Rect::new(8, 66 + visible as u16 * 32, 224, 28)
    } else {
        Rect::new(0, 0, 0, 0)
    }
}
pub const TODAY_ACTIONS: [Rect; 2] = [Rect::new(8, 220, 224, 28), Rect::new(8, 254, 224, 28)];
pub const SETTINGS: [Rect; 2] = [Rect::new(8, 70, 224, 48), Rect::new(8, 126, 224, 48)];
pub const MENU: Rect = Rect::new(12, 60, 216, 190);
/// Union of the largest Desktop menu and shortcuts it can cover.
pub const DESKTOP_OVERLAY_RESTORE: Rect = Rect::new(8, 42, 220, 204);
pub const fn menu_row(index: usize) -> Rect {
    if index < 6 {
        Rect::new(16, 90 + index as u16 * 26, 208, 24)
    } else {
        Rect::new(0, 0, 0, 0)
    }
}
pub const DIALOG: Rect = Rect::new(12, 82, 216, 152);
pub const DIALOG_BUTTONS: [Rect; 2] = [Rect::new(24, 194, 92, 28), Rect::new(124, 194, 92, 28)];
