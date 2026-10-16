//! Shared logical trace, not a physical keyboard or a simulated user database.
use crate::Action;
use crosshair_ui::components::Event;
pub const SCENARIO: [Action; 24] = [
    Action::SoftLeft,         // Desktop -> Launcher
    Action::SoftLeft,         // About
    Action::Key(Event::Back), // Launcher, selection retained
    Action::Home,
    Action::Key(Event::Down), // Settings shortcut
    Action::Key(Event::Select),
    Action::SoftLeft, // real volatile theme
    Action::Key(Event::Down),
    Action::SoftLeft,  // reset confirmation
    Action::SoftRight, // cancel, theme retained
    Action::Home,
    Action::Key(Event::Right), // Diagnostics shortcut, desktop selection retained
    Action::Key(Event::Select),
    Action::Key(Event::Back),
    Action::Key(Event::Menu),
    Action::SoftLeft, // Today
    Action::Key(Event::Down),
    Action::SoftLeft, // Diagnostics
    Action::SwitchTask,
    Action::Key(Event::Back),
    Action::Home,
    Action::Key(Event::Menu),
    Action::Key(Event::Down),
    Action::SoftLeft, // Launcher
];
