//! Crosshair UI Design System 0.1: fixed RGB565 tokens, no runtime theme state.
//! A 240x320 utility UI informed by the existing gray-blue direction. No image
//! reference was attached or inspected, and no hardware-status values are drawn.

pub const VERSION: &str = "0.1";

pub mod colors {
    use crate::Rgb565;
    pub const BACKGROUND: Rgb565 = Rgb565(0xe73c);
    pub const SURFACE: Rgb565 = Rgb565(0xf79e);
    pub const INK: Rgb565 = Rgb565(0x1946);
    pub const MUTED: Rgb565 = Rgb565(0x5b4e);
    pub const HEADER: Rgb565 = Rgb565(0x2a4b);
    pub const SYSTEM: Rgb565 = INK;
    pub const SELECTED: Rgb565 = Rgb565(0xc6fb);
    pub const FOCUS: Rgb565 = Rgb565(0x21e8);
    pub const EDGE: Rgb565 = Rgb565(0x9cf3);
    pub const SOFTKEY: Rgb565 = Rgb565(0xdedb);
    pub const WHITE: Rgb565 = Rgb565(0xffff);
    pub const SCROLL_TRACK: Rgb565 = Rgb565(0xc638);
    pub const SCROLL_THUMB: Rgb565 = Rgb565(0x7452);
    // State/icon roles are shared tokens. Disabled/pressed widgets and system
    // status icons are specified, not implemented by the current AppsScreen.
    pub const DISABLED: Rgb565 = MUTED;
    pub const DISABLED_SURFACE: Rgb565 = BACKGROUND;
    pub const PRESSED: Rgb565 = SELECTED;
    pub const ACTIVE: Rgb565 = FOCUS;
    pub const WARNING: Rgb565 = Rgb565(0xfd20);
    pub const ERROR: Rgb565 = Rgb565(0xf986);
    pub const SYSTEM_ICON: Rgb565 = WHITE;
    pub const SYSTEM_ICON_DISABLED: Rgb565 = EDGE;
    pub const SYSTEM_ICON_ACTIVE: Rgb565 = SELECTED;
    pub const SYSTEM_ICON_WARNING: Rgb565 = WARNING;
    pub const SYSTEM_ICON_ERROR: Rgb565 = ERROR;
    pub const TEST_RED: Rgb565 = Rgb565(0xf800);
    pub const TEST_GREEN: Rgb565 = Rgb565(0x07e0);
    pub const TEST_BLUE: Rgb565 = Rgb565(0x001f);
}

pub mod layout {
    pub const WIDTH: u16 = 240;
    pub const HEIGHT: u16 = 320;
    pub const FONT_ADVANCE: u16 = crate::font::ADVANCE as u16;
    pub const FONT_INK_WIDTH: u16 = 8;
    pub const FONT_HEIGHT: u16 = crate::font::HEIGHT as u16;
    pub const LINE_HEIGHT: u16 = crate::font::LINE_HEIGHT as u16;
    pub const LABEL_PADDING: u16 = 4;
    pub const HEADER_PADDING: u16 = 8;
    pub const FOCUS_WIDTH: u16 = 2;
    pub const PAGE_LEFT: u16 = 6;
    pub const SYSTEM_TOP: u16 = 0;
    pub const SYSTEM_HEIGHT: u16 = 16;
    pub const SYSTEM_TEXT_Y: u16 = 1;
    pub const SYSTEM_RIGHT_X: u16 = 208;
    pub const HEADER_TOP: u16 = 16;
    pub const HEADER_HEIGHT: u16 = 28;
    pub const SEARCH_TOP: u16 = 44;
    pub const SEARCH_HEIGHT: u16 = 20;
    pub const SEARCH_TEXT_Y: u16 = 48;
    pub const FILTER_X: u16 = 50;
    pub const LIST_TOP: u16 = 68;
    pub const ROW_HEIGHT: u16 = 24;
    pub const ROW_PITCH: u16 = 26;
    pub const ROW_WIDTH: u16 = 224;
    pub const VISIBLE_ROWS: usize = 8;
    pub const SCROLL_X: u16 = 234;
    pub const SCROLL_WIDTH: u16 = 3;
    pub const SCROLL_HEIGHT: u16 = ROW_PITCH * VISIBLE_ROWS as u16;
    pub const SCROLL_MIN_THUMB: u16 = 8;
    pub const STATUS_TOP: u16 = 280;
    pub const STATUS_HEIGHT: u16 = 16;
    pub const STATUS_TEXT_Y: u16 = 281;
    pub const STATUS_SLASH_X: u16 = 24;
    pub const STATUS_TOTAL_X: u16 = 36;
    pub const STATUS_HINT_X: u16 = 132;
    pub const SOFTKEY_TOP: u16 = 296;
    pub const SOFTKEY_HEIGHT: u16 = 24;
    pub const SOFTKEY_WIDTH: u16 = 120;
    pub const MENU_TOP: u16 = 58;
    pub const MENU_PITCH: u16 = 30;
    pub const MENU_ROW_HEIGHT: u16 = 26;
    pub const ACTION_NAME_Y: u16 = 58;
    pub const ACTION_CAPTION_Y: u16 = 80;
    pub const PREVIEW_X: u16 = 12;
    pub const PREVIEW_Y: u16 = 106;
    pub const PREVIEW_WIDTH: u16 = 216;
    pub const PREVIEW_HEIGHT: u16 = 70;
    pub const COLOR_WIDTH: u16 = 64;
    pub const COLOR_HEIGHT: u16 = 48;
    pub const COLOR_PITCH: u16 = 72;
    pub const BACK_HINT_Y: u16 = 250;

    // Future control specifications; adding tokens does not add widget state,
    // hit testing, a modal manager or physical stylus support.
    pub const BORDER_WIDTH: u16 = 1;
    pub const CONTROL_GAP: u16 = LABEL_PADDING;
    pub const BUTTON_HEIGHT: u16 = ROW_HEIGHT;
    pub const BUTTON_MIN_WIDTH: u16 = 48;
    pub const BUTTON_PADDING: u16 = LABEL_PADDING;
    pub const INPUT_HEIGHT: u16 = BUTTON_HEIGHT;
    pub const INPUT_WIDTH: u16 = ROW_WIDTH;
    pub const INPUT_PADDING: u16 = LABEL_PADDING;
    pub const ICON_SIZE: u16 = 12;
    pub const ICON_PADDING: u16 = 2;
    pub const ICON_TEXT_GAP: u16 = CONTROL_GAP;
    pub const SCROLL_HIT_WIDTH: u16 = 8;
    pub const SCROLL_HIT_X: u16 = WIDTH - SCROLL_HIT_WIDTH;
    pub const DIALOG_X: u16 = PREVIEW_X;
    pub const DIALOG_Y: u16 = 64;
    pub const DIALOG_WIDTH: u16 = PREVIEW_WIDTH;
    pub const DIALOG_HEIGHT: u16 = 184;
    pub const DIALOG_PADDING: u16 = HEADER_PADDING;
    pub const DIALOG_HEADER_HEIGHT: u16 = BUTTON_HEIGHT;
    pub const DIALOG_FOOTER_HEIGHT: u16 = 32;
    pub const DIALOG_BUTTON_GAP: u16 = DIALOG_PADDING;
}
