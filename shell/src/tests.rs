extern crate std;
use super::*;
use crosshair_ui::{
    Surface,
    components::{Event, InputQueue},
};
use std::vec;

fn key(shell: &mut Shell, event: Event) {
    shell.handle(Action::Key(event));
}
fn settings(shell: &mut Shell) {
    shell.handle(Action::Home);
    key(shell, Event::Down);
    key(shell, Event::Select);
    assert_eq!(shell.screen, Screen::Settings);
}

#[test]
fn desktop_launcher_application_back_restores_selection_and_history() {
    let mut shell = Shell::new(BuildInfo::WAVE007);
    shell.handle(Action::SoftLeft);
    assert_eq!(shell.screen, Screen::Launcher);
    key(&mut shell, Event::Down);
    key(&mut shell, Event::Select);
    assert_eq!(shell.screen, Screen::Diagnostics);
    assert_eq!(shell.launcher_selected, 1);
    shell.handle(Action::SoftLeft);
    assert_eq!(shell.screen, Screen::Launcher);
    assert_eq!(shell.launcher_selected, 1);
    key(&mut shell, Event::Back);
    assert_eq!(shell.screen, Screen::Desktop);
    key(&mut shell, Event::Down);
    assert_eq!(shell.desktop_selected, 1);
    key(&mut shell, Event::Select);
    shell.handle(Action::Home);
    assert_eq!(shell.desktop_selected, 1);
    assert_eq!(shell.history_len, 0);
}

#[test]
fn menu_cancel_and_screen_switch_preserve_each_screen_state() {
    let mut shell = Shell::new(BuildInfo::WAVE007);
    shell.handle(Action::SoftLeft);
    key(&mut shell, Event::Down);
    key(&mut shell, Event::Down);
    key(&mut shell, Event::Menu);
    key(&mut shell, Event::Down);
    key(&mut shell, Event::Back);
    assert_eq!(shell.launcher_selected, 2);
    assert_eq!(shell.overlay, 0);
    key(&mut shell, Event::Select);
    assert_eq!(shell.screen, Screen::Settings);
    key(&mut shell, Event::Down);
    shell.handle(Action::Home);
    shell.handle(Action::SwitchTask);
    assert_eq!(shell.screen, Screen::Launcher);
    assert_eq!(shell.launcher_selected, 2);
    shell.handle(Action::SwitchTask);
    assert_eq!(shell.screen, Screen::Settings);
    assert_eq!(shell.settings_selected, 1);
    key(&mut shell, Event::Menu);
    shell.handle(Action::Home);
    assert_eq!(shell.overlay, 0);
    assert_eq!(shell.screen, Screen::Desktop);
}

#[test]
fn settings_changes_real_theme_and_dialog_confirm_cancel_are_distinct() {
    let mut shell = Shell::new(BuildInfo::WAVE007);
    settings(&mut shell);
    shell.handle(Action::SoftLeft);
    assert_eq!(shell.theme, 1);
    key(&mut shell, Event::Down);
    shell.handle(Action::SoftLeft);
    assert_eq!(shell.overlay, 3);
    key(&mut shell, Event::Right);
    key(&mut shell, Event::Select);
    assert_eq!(shell.theme, 1);
    assert_eq!(shell.overlay, 0);
    shell.handle(Action::SoftLeft);
    shell.handle(Action::SoftRight);
    assert_eq!(shell.theme, 1);
    shell.handle(Action::SoftLeft);
    shell.handle(Action::SoftLeft);
    assert_eq!(shell.theme, 0);
    assert_eq!(shell.settings_selected, 1);
    assert_eq!(shell.overlay, 0);
}

#[test]
fn launcher_text_prefix_search_is_bounded_cyrillic_and_back_first_clears() {
    let mut shell = Shell::new(BuildInfo::WAVE007);
    shell.handle(Action::SoftLeft);
    for ch in ['д', 'И', 'а'] {
        key(&mut shell, Event::TextInput(ch));
    }
    assert_eq!(shell.launcher_matches(), 1);
    assert_eq!(shell.launcher_selected, 1);
    key(&mut shell, Event::Select);
    assert_eq!(shell.screen, Screen::Diagnostics);
    key(&mut shell, Event::Back);
    assert_eq!(shell.query(), &['д', 'И', 'а']);
    key(&mut shell, Event::TextInput('\u{8}'));
    assert_eq!(shell.query_len, 2);
    key(&mut shell, Event::Back);
    assert_eq!(shell.screen, Screen::Launcher);
    assert!(shell.query().is_empty());
    for _ in 0..40 {
        key(&mut shell, Event::TextInput('Ё'));
    }
    assert_eq!(shell.query_len as usize, QUERY_CAPACITY);
    assert_eq!(shell.launcher_matches(), 0);
    key(&mut shell, Event::Select);
    assert_eq!(shell.screen, Screen::Launcher);
    key(&mut shell, Event::Menu);
    shell.handle(Action::SoftLeft);
    assert!(shell.query().is_empty());
    key(&mut shell, Event::Back);
    assert_eq!(shell.screen, Screen::Desktop);
}

#[test]
fn existing_text_wire_special_actions_and_unknown_keys_do_not_corrupt_state() {
    let mut shell = Shell::new(BuildInfo::WAVE007);
    key(&mut shell, Event::TextInput('\u{e001}'));
    assert_eq!(shell.screen, Screen::Launcher);
    key(&mut shell, Event::TextInput('\u{e002}'));
    assert_eq!(shell.overlay, 2);
    key(&mut shell, Event::TextInput('\u{e000}'));
    assert_eq!(shell.screen, Screen::Desktop);
    assert_eq!(shell.overlay, 0);
    key(&mut shell, Event::TextInput('\u{e003}'));
    assert_eq!(shell.screen, Screen::Launcher);
    assert_eq!(fold('Ё'), 'ё');
    assert_eq!(fold('Й'), 'й');
    assert_eq!(Action::from_code(11), None);
}

#[test]
fn dirty_state_avoids_repaint_and_surface_present_keeps_failed_transfer() {
    let mut shell = Shell::new(BuildInfo::WAVE007);
    let mut pixels = vec![0; 240 * 320];
    let mut surface = Surface::new(&mut pixels, 240, 320, 240).unwrap();
    assert!(shell.render(&mut surface));
    assert_eq!(shell.renders, 1);
    assert!(!shell.render(&mut surface));
    assert!(!shell.handle(Action::Key(Event::Up)));
    assert!(!shell.render(&mut surface));
    assert_eq!(surface.present(|_, _, _| Err::<(), _>(7)), Err(7));
    assert!(!surface.dirty_rects().is_empty());
    surface.present(|_, _, _| Ok::<(), ()>(())).unwrap();
    assert!(surface.dirty_rects().is_empty());
    shell.handle(Action::SoftLeft);
    assert!(shell.render(&mut surface));
    assert_eq!(shell.renders, 2);
}

#[test]
fn runtime_unknown_version_masks_validity_and_updates_only_visible_info() {
    let mut shell = Shell::new(BuildInfo::WAVE007);
    let mut pixels = vec![0; 240 * 320];
    let mut surface = Surface::new(&mut pixels, 240, 320, 240).unwrap();
    shell.render(&mut surface);
    let mut info = RuntimeInfo::UNKNOWN;
    info.ticks = u32::MAX;
    info.valid = 15;
    info.version = 99;
    shell.update_runtime(info);
    assert_eq!(shell.snapshot().runtime_valid, 0);
    assert!(!shell.needs_render());
    key(&mut shell, Event::Select);
    assert_eq!(shell.screen, Screen::Today);
    shell.render(&mut surface);
    info.version = 1;
    shell.update_runtime(info);
    assert!(shell.needs_render());
    shell.render(&mut surface);
    assert_eq!(shell.snapshot().runtime_ticks, u32::MAX);
    info.reserved = 1;
    shell.update_runtime(info);
    assert_eq!(shell.snapshot().runtime_valid, 0);
    assert_eq!(RuntimeInfo::from_words(info.words()), info);
}

#[test]
fn renderer_clips_small_surface_and_preserves_padding_and_outer_canaries() {
    let mut shell = Shell::new(BuildInfo::WAVE007);
    let mut backing = vec![0x55aa; 11 * 9 + 16];
    {
        let mut surface = Surface::new(&mut backing[8..8 + 99], 7, 9, 11).unwrap();
        for action in fixtures::SCENARIO {
            shell.handle(action);
            shell.render(&mut surface);
        }
    }
    assert!(backing[..8].iter().all(|&v| v == 0x55aa));
    assert!(backing[107..].iter().all(|&v| v == 0x55aa));
    for row in 0..9 {
        assert!(
            backing[8 + row * 11 + 7..8 + row * 11 + 11]
                .iter()
                .all(|&v| v == 0x55aa)
        );
    }
}

#[test]
fn bounded_queue_backpressure_retries_without_losing_actions() {
    let mut queue = InputQueue::new();
    let mut shell = Shell::new(BuildInfo::WAVE007);
    let events = [
        Event::Down,
        Event::Right,
        Event::Up,
        Event::Menu,
        Event::Down,
        Event::Back,
        Event::Select,
        Event::Back,
    ];
    for event in events {
        queue.push(event).unwrap();
    }
    assert_eq!(queue.push(Event::Menu), Err(Event::Menu));
    shell.handle(Action::Key(queue.pop().unwrap()));
    queue.push(Event::Menu).unwrap();
    while let Some(event) = queue.pop() {
        shell.handle(Action::Key(event));
    }
    assert_eq!(shell.events_processed, 9);
    assert!(queue.is_empty());
    assert!(shell.overlay != 0);
}

#[test]
fn burst_navigation_has_bounded_valid_focus_history_and_no_implicit_apps() {
    let mut shell = Shell::new(BuildInfo::WAVE007);
    let mut seed = 0x9e37_79b9u32;
    for n in 0..20_000u32 {
        seed ^= seed << 13;
        seed ^= seed >> 17;
        seed ^= seed << 5;
        let action = if n % 7 == 0 {
            Action::Key(Event::TextInput(if n % 2 == 0 { 'Ё' } else { '\u{8}' }))
        } else {
            Action::from_code(seed % 11).unwrap()
        };
        shell.handle(action);
        let state = shell.snapshot();
        assert!(
            state.screen <= 5
                && state.desktop_selected < DESKTOP_COUNT as u32
                && state.launcher_selected < 4
        );
        assert!(
            state.settings_selected < 2
                && state.today_selected < 2
                && state.overlay <= 3
                && state.theme <= 1
        );
        assert!(
            state.history_depth <= HISTORY_CAPACITY as u32
                && shell.query_len as usize <= QUERY_CAPACITY
        );
        assert!(state.opened_mask & (1 << state.screen) != 0);
        assert!(
            state.overlay == 0
                || state.overlay_selected
                    < match state.overlay {
                        1 => 6,
                        2 => 3,
                        _ => 2,
                    }
        );
    }
    assert_eq!(shell.events_processed, 20_000);
}

#[test]
fn canonical_fixture_uses_existing_renderer_without_heap_owned_shell_state() {
    let mut shell = Shell::new(BuildInfo::WAVE007);
    let mut pixels = vec![0; 240 * 320];
    let mut surface = Surface::new(&mut pixels, 240, 320, 240).unwrap();
    shell.render(&mut surface);
    let initial = surface.pixels().to_vec();
    for action in fixtures::SCENARIO {
        shell.handle(action);
        shell.render(&mut surface);
    }
    assert_eq!(shell.screen, Screen::Launcher);
    assert_eq!(shell.theme, 1);
    assert_ne!(initial, surface.pixels());
    assert!(core::mem::size_of::<Shell>() < 512);
    assert_eq!(core::mem::size_of::<RuntimeInfo>(), 48);
    assert_eq!(core::mem::size_of::<Snapshot>(), 64);
}

fn tap(shell: &mut Shell, x: u16, y: u16) -> bool {
    shell.handle(Action::Pointer { x, y })
}

#[test]
fn pointer_shortcuts_start_launcher_and_application_back_are_functional() {
    let mut shell = Shell::new(BuildInfo::WAVE007);
    let unchanged = shell.snapshot();
    assert!(!tap(&mut shell, 160, 150)); // free workspace
    assert_eq!(shell.screen, Screen::Desktop);
    assert_eq!(shell.desktop_selected, unchanged.desktop_selected as u8);
    for (index, expected) in SHORTCUTS.into_iter().enumerate() {
        shell.handle(Action::Home);
        let rect = geometry::DESKTOP[index];
        assert!(tap(&mut shell, rect.x + 1, rect.y + 1));
        assert_eq!(shell.screen, expected);
        assert_eq!(shell.desktop_selected as usize, index);
        assert!(tap(&mut shell, 228, 12)); // title Back
        assert_eq!(shell.screen, Screen::Desktop);
    }
    assert!(tap(&mut shell, 24, 12)); // Start
    assert_eq!(shell.screen, Screen::Launcher);
    for (index, expected) in APPS.into_iter().enumerate() {
        let rect = geometry::launcher_row(index);
        assert!(tap(&mut shell, rect.x + 3, rect.y + 3));
        assert_eq!(shell.screen, expected);
        assert_eq!(shell.launcher_selected as usize, index);
        tap(&mut shell, 228, 12);
        assert_eq!(shell.screen, Screen::Launcher);
    }
    for ch in ['д', 'и'] {
        key(&mut shell, Event::TextInput(ch));
    }
    let rect = geometry::launcher_row(0);
    tap(&mut shell, rect.x + 2, rect.y + 2);
    assert_eq!(shell.screen, Screen::Diagnostics); // filtered visible row maps to app1
}

#[test]
fn pointer_overlays_are_modal_and_dialog_cancel_confirm_are_distinct() {
    let mut shell = Shell::new(BuildInfo::WAVE007);
    tap(&mut shell, 40, 120); // Settings
    tap(&mut shell, 30, 80); // theme
    assert_eq!(shell.theme, 1);
    tap(&mut shell, 30, 138); // reset confirmation
    assert_eq!(shell.overlay, 3);
    assert!(!tap(&mut shell, 20, 45)); // cannot hit shortcut behind modal
    assert_eq!(shell.overlay, 3);
    tap(&mut shell, 150, 208); // Cancel
    assert_eq!(shell.theme, 1);
    assert_eq!(shell.overlay, 0);
    tap(&mut shell, 30, 138);
    tap(&mut shell, 40, 208); // Reset
    assert_eq!(shell.theme, 0);
    tap(&mut shell, 180, 308); // right softkey menu
    assert_eq!(shell.overlay, 1);
    tap(&mut shell, 30, 96); // Today
    assert_eq!(shell.screen, Screen::Today);
    tap(&mut shell, 30, 260); // Today Diagnostics action
    assert_eq!(shell.screen, Screen::Diagnostics);
    tap(&mut shell, 30, 308); // left Back
    assert_eq!(shell.screen, Screen::Today);
    key(&mut shell, Event::Menu);
    tap(&mut shell, 235, 40); // dismiss outside menu, no underlying action
    assert_eq!(shell.overlay, 0);
    assert_eq!(shell.screen, Screen::Today);
}

#[test]
fn pointer_half_open_bounds_invalid_wire_and_keyboard_interleave_preserve_state() {
    let mut shell = Shell::new(BuildInfo::WAVE007);
    for (x, y) in [(240, 0), (0, 320), (u16::MAX, u16::MAX)] {
        let before = shell;
        assert!(!tap(&mut shell, x, y));
        assert_eq!(shell, before);
    }
    for scalar in [
        POINTER_SCALAR_BASE + 240,
        POINTER_SCALAR_BASE + (320 << 8),
        0x10ffff,
    ] {
        let before = shell;
        key(
            &mut shell,
            Event::TextInput(char::from_u32(scalar).unwrap()),
        );
        assert_eq!(shell, before);
    }
    assert!(geometry::START.contains(0, 0));
    assert!(!geometry::START.contains(58, 0));
    assert!(!geometry::SOFT_LEFT.contains(120, 308));
    assert!(geometry::SOFT_RIGHT.contains(120, 308));
    assert!(!geometry::launcher_row(usize::MAX).contains(0, 0));
    assert!(!geometry::menu_row(usize::MAX).contains(0, 0));
    key(
        &mut shell,
        Event::TextInput(char::from_u32(POINTER_SCALAR_BASE + (12 << 8) + 24).unwrap()),
    );
    assert_eq!(shell.screen, Screen::Launcher);
    key(&mut shell, Event::Down);
    let rect = geometry::launcher_row(2);
    tap(&mut shell, rect.x, rect.y);
    assert_eq!(shell.screen, Screen::Settings);
    key(&mut shell, Event::Select);
    assert_eq!(shell.theme, 1);
    shell.handle(Action::Home);
    assert_eq!(shell.desktop_selected, 0);
}

#[test]
fn desktop_focus_redraw_matches_full_render_and_limits_dirty_regions() {
    let mut partial = Shell::new(BuildInfo::WAVE007);
    let mut full = partial;
    let mut a = vec![0; 240 * 320];
    let mut b = vec![0; 240 * 320];
    let mut sa = Surface::new(&mut a, 240, 320, 240).unwrap();
    let mut sb = Surface::new(&mut b, 240, 320, 240).unwrap();
    partial.render(&mut sa);
    sa.present(|_, _, _| Ok::<(), ()>(())).unwrap();
    key(&mut partial, Event::Down);
    key(&mut full, Event::Down); // still has initial full-render obligation
    partial.render(&mut sa);
    full.render(&mut sb);
    assert_eq!(sa.pixels(), sb.pixels());
    assert_eq!(partial.render_stats().full, 0);
    assert_eq!(partial.render_stats().wallpaper.pixels_written, 2 * 72 * 58);
    assert!(!sa.dirty_rects().is_empty());
    for rect in sa.dirty_rects() {
        assert!(rect.x() >= 8 && rect.right() <= 80);
        assert!(rect.y() >= 42 && rect.bottom() <= 166);
    }
    // Multiple focus events before rendering restore every affected shortcut.
    key(&mut partial, Event::Down);
    key(&mut partial, Event::Up);
    key(&mut partial, Event::Up);
    key(&mut full, Event::Up);
    full.invalidate();
    partial.render(&mut sa);
    full.render(&mut sb);
    assert_eq!(sa.pixels(), sb.pixels());
}

#[test]
fn desktop_menu_overlay_reuses_wallpaper_and_dismissal_matches_fresh_composition() {
    let mut shell = Shell::new(BuildInfo::WAVE007_1);
    let mut pixels = vec![0; 240 * 320];
    let mut surface = Surface::new(&mut pixels, 240, 320, 240).unwrap();
    shell.render(&mut surface);
    assert_eq!(shell.render_stats().full, 1);
    assert_eq!(shell.render_stats().wallpaper.pixels_written, 240 * 272);
    surface.present(|_, _, _| Ok::<(), ()>(())).unwrap();
    assert!(!shell.render(&mut surface));
    assert_eq!(shell.render_stats(), RenderStats::ZERO);
    key(&mut shell, Event::Menu);
    shell.render(&mut surface);
    assert_eq!(shell.render_stats().full, 0);
    assert_eq!(
        shell.render_stats().wallpaper,
        wallpaper::DrawStats::default()
    );
    surface.present(|_, _, _| Ok::<(), ()>(())).unwrap();
    key(&mut shell, Event::Down);
    shell.render(&mut surface);
    assert_eq!(
        shell.render_stats().wallpaper,
        wallpaper::DrawStats::default()
    );
    key(&mut shell, Event::Back);
    let mut fresh = shell;
    fresh.invalidate();
    let mut expected = vec![0; 240 * 320];
    let mut expected_surface = Surface::new(&mut expected, 240, 320, 240).unwrap();
    shell.render(&mut surface);
    fresh.render(&mut expected_surface);
    assert_eq!(shell.render_stats().full, 0);
    assert_eq!(shell.render_stats().wallpaper.pixels_written, 220 * 204);
    assert_eq!(surface.pixels(), expected_surface.pixels());
}
