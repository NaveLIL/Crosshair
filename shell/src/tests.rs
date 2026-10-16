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
    assert_eq!(Action::from_code(13), None);
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
                && state.overlay <= 4
                && state.theme <= 1
        );
        assert!(
            state.history_depth <= HISTORY_CAPACITY as u32
                && shell.query_len as usize <= QUERY_CAPACITY
        );
        assert!(state.opened_mask & (1 << state.screen) != 0);
        assert!(state.overlay == 0 || state.overlay_selected < shell.overlay_count() as u32);
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
    pointer_phase(&mut shell, PointerPhase::Press, 20, 45);
    pointer_phase(&mut shell, PointerPhase::Release, 20, 45);
    assert_eq!(shell.overlay, 3); // real mouse route also keeps dialog modal
    tap(&mut shell, 150, 208); // Cancel
    assert_eq!(shell.theme, 1);
    assert_eq!(shell.overlay, 0);
    tap(&mut shell, 30, 138);
    tap(&mut shell, 40, 208); // Reset
    assert_eq!(shell.theme, 0);
    shell.handle(Action::SoftRight); // keyboard context action; no permanent footer
    assert_eq!(shell.overlay, 1);
    tap(&mut shell, 30, 96); // Today
    assert_eq!(shell.screen, Screen::Today);
    tap(&mut shell, 30, 282); // Today Diagnostics inline action
    assert_eq!(shell.screen, Screen::Diagnostics);
    tap(&mut shell, 228, 12); // title Back
    assert_eq!(shell.screen, Screen::Today);
    key(&mut shell, Event::Menu);
    tap(&mut shell, 235, 40); // dismiss outside menu, no underlying action
    assert_eq!(shell.overlay, 0);
    assert_eq!(shell.screen, Screen::Today);
    shell.handle(Action::Home);
    shell.handle(Action::SystemPanel);
    let commands = shell.actions_invoked;
    // Outside the panel, but over the underlying Today shortcut: dismiss only.
    pointer_phase(&mut shell, PointerPhase::Press, 40, 45);
    pointer_phase(&mut shell, PointerPhase::Release, 40, 45);
    assert_eq!(shell.overlay, 0);
    assert_eq!(shell.screen, Screen::Desktop);
    assert_eq!(shell.actions_invoked, commands);
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
    assert!(!geometry::panel_button(ChromeMode::Standard).contains(216, 12));
    assert!(geometry::back(ChromeMode::Standard).contains(216, 12));
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
    assert_eq!(shell.render_stats().wallpaper.pixels_written, 240 * 296);
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
    assert_eq!(shell.render_stats().wallpaper.pixels_written, 220 * 242);
    assert_eq!(surface.pixels(), expected_surface.pixels());
}

fn pointer_phase(shell: &mut Shell, phase: PointerPhase, x: u16, y: u16) {
    shell.handle(Action::PointerEvent { phase, x, y });
}
fn edge(shell: &mut Shell, phase: KeyPhase, key: u8) {
    shell.handle(Action::HardwareKey { phase, key });
}
fn open_about(shell: &mut Shell) {
    shell.handle(Action::Home);
    shell.handle(Action::Start);
    key(shell, Event::Select);
    assert_eq!(shell.screen, Screen::About);
}
fn mode(shell: &mut Shell, mode: ChromeMode) {
    shell.handle(Action::SystemPanel);
    for _ in 0..4 + mode as u32 {
        key(shell, Event::Down);
    }
    key(shell, Event::Select);
    assert_eq!(shell.chrome_mode(), mode);
}

#[test]
fn adaptive_modes_keep_content_history_focus_and_have_pointer_recovery() {
    let mut shell = Shell::new(BuildInfo::WAVE007_2);
    assert_eq!(shell.content_rect(), geometry::Rect::new(0, 24, 240, 296));
    let before = shell.snapshot();
    tap(&mut shell, 30, 308);
    assert_eq!(shell.screen, Screen::Desktop);
    assert_eq!(shell.desktop_selected, before.desktop_selected as u8);
    open_about(&mut shell);
    let history = shell.history_len;
    mode(&mut shell, ChromeMode::Compact);
    assert_eq!(shell.content_rect(), geometry::Rect::new(0, 16, 240, 304));
    assert_eq!(shell.history_len, history);
    for _ in 0..100 {
        key(&mut shell, Event::Down);
    }
    assert_eq!(shell.scroll_offset(), shell.scroll_max());
    mode(&mut shell, ChromeMode::Immersive);
    assert_eq!(shell.content_rect(), geometry::Rect::new(0, 0, 240, 320));
    assert!(!geometry::scroll_up(ChromeMode::Immersive).contains(232, 8));
    assert!(!geometry::IMMERSIVE_HANDLE.contains(232, 24));
    assert_eq!(shell.hit_target(232, 8), adaptive::target::PANEL);
    assert_eq!(
        shell.hit_target(232, geometry::scroll_up(ChromeMode::Immersive).y + 8),
        adaptive::target::SCROLL_UP
    );
    assert!(shell.scroll_offset() <= shell.scroll_max());
    tap(&mut shell, 232, 8);
    assert_eq!(shell.overlay, 4);
    key(&mut shell, Event::Back);
    pointer_phase(&mut shell, PointerPhase::Press, 4, 1);
    pointer_phase(&mut shell, PointerPhase::Move, 4, 14);
    assert_eq!(shell.overlay, 4);
    assert!(!shell.pointer.active);
    key(&mut shell, Event::Back);
    mode(&mut shell, ChromeMode::Standard);
    shell.handle(Action::Home);
    shell.handle(Action::SwitchTask);
    shell.handle(Action::SwitchTask);
    assert_eq!(shell.screen, Screen::About);
    assert_eq!(shell.chrome_mode(), ChromeMode::Standard);
    assert_eq!(shell.launcher_selected, 0);
    assert_eq!(core::mem::size_of::<UxSnapshot>(), 80);
    assert_eq!(shell.ux_snapshot().words().len(), UX_WORDS);
}

#[test]
fn pointer_press_release_capture_leave_cancel_and_stale_release_are_distinct() {
    let mut shell = Shell::new(BuildInfo::WAVE007_2);
    pointer_phase(&mut shell, PointerPhase::Press, 40, 120);
    assert_eq!(shell.screen, Screen::Desktop);
    assert_eq!(shell.desktop_selected, 1);
    assert!(shell.pointer.active);
    assert_eq!(shell.actions_invoked, 0);
    pointer_phase(&mut shell, PointerPhase::Release, 40, 120);
    assert_eq!(shell.screen, Screen::Settings);
    assert_eq!(shell.actions_invoked, 1);
    assert!(!shell.pointer.active);
    shell.handle(Action::Home);
    pointer_phase(&mut shell, PointerPhase::Press, 40, 68);
    pointer_phase(&mut shell, PointerPhase::Move, 120, 68);
    pointer_phase(&mut shell, PointerPhase::Move, 40, 68);
    pointer_phase(&mut shell, PointerPhase::Release, 40, 68);
    assert_eq!(shell.screen, Screen::Desktop);
    pointer_phase(&mut shell, PointerPhase::Press, 40, 68);
    pointer_phase(&mut shell, PointerPhase::Cancel, 0, 0);
    pointer_phase(&mut shell, PointerPhase::Release, 40, 68);
    assert_eq!(shell.screen, Screen::Desktop);
    pointer_phase(&mut shell, PointerPhase::Press, 40, 68);
    shell.handle(Action::Start);
    pointer_phase(&mut shell, PointerPhase::Release, 40, 68);
    assert_eq!(shell.screen, Screen::Launcher);
}

#[test]
fn trusted_hold_threshold_stationarity_and_later_release_suppression() {
    let mut shell = Shell::new(BuildInfo::WAVE007_2);
    pointer_phase(&mut shell, PointerPhase::Press, 40, 68);
    shell.handle(Action::PointerHold { millis: 599 });
    assert_eq!(shell.overlay, 0);
    shell.handle(Action::PointerHold { millis: 600 });
    assert_eq!(shell.overlay, 4);
    assert!(!shell.pointer.active);
    let selected = shell.overlay_selected;
    pointer_phase(&mut shell, PointerPhase::Release, 40, 68);
    assert_eq!(shell.overlay, 4);
    assert_eq!(shell.overlay_selected, selected);
    key(&mut shell, Event::Back);
    pointer_phase(&mut shell, PointerPhase::Press, 40, 68);
    pointer_phase(&mut shell, PointerPhase::Move, 41, 68);
    pointer_phase(&mut shell, PointerPhase::Move, 40, 68);
    shell.handle(Action::PointerHold { millis: 4095 });
    assert_eq!(shell.overlay, 0);
    pointer_phase(&mut shell, PointerPhase::Release, 40, 68);
    assert_eq!(shell.screen, Screen::Today);
    shell.handle(Action::Start);
    pointer_phase(&mut shell, PointerPhase::Press, 30, 70);
    shell.handle(Action::PointerHold { millis: 600 });
    assert_eq!(shell.overlay, 2); // actual Launcher context, also reachable by F2
    assert!(!shell.pointer.active);
    pointer_phase(&mut shell, PointerPhase::Release, 30, 70);
    assert_eq!(shell.overlay, 2); // hold suppresses the later tap
    assert_eq!(shell.screen, Screen::Launcher);
}

#[test]
fn physical_edges_repeat_only_held_navigation_and_system_commands_once() {
    let mut shell = Shell::new(BuildInfo::WAVE007_2);
    edge(&mut shell, KeyPhase::Press, 1);
    assert_eq!(shell.desktop_selected, 1);
    edge(&mut shell, KeyPhase::Repeat, 1);
    assert_eq!(shell.desktop_selected, 2);
    edge(&mut shell, KeyPhase::Release, 1);
    edge(&mut shell, KeyPhase::Repeat, 1);
    assert_eq!(shell.desktop_selected, 2);
    edge(&mut shell, KeyPhase::Press, 4);
    assert_eq!(shell.screen, Screen::Diagnostics);
    let actions = shell.key_actions;
    edge(&mut shell, KeyPhase::Repeat, 4);
    edge(&mut shell, KeyPhase::Press, 4);
    assert_eq!(shell.key_actions, actions);
    edge(&mut shell, KeyPhase::Release, 4);
    edge(&mut shell, KeyPhase::Press, 7);
    assert_eq!(shell.screen, Screen::Desktop);
    assert_ne!(shell.held_keys & (1 << 7), 0);
    let actions = shell.key_actions;
    edge(&mut shell, KeyPhase::Press, 7);
    edge(&mut shell, KeyPhase::Repeat, 7);
    assert_eq!(shell.key_actions, actions);
    edge(&mut shell, KeyPhase::Release, 7);
    assert_eq!(shell.held_keys, 0);
    pointer_phase(&mut shell, PointerPhase::Press, 40, 68);
    edge(&mut shell, KeyPhase::Press, 0);
    let count = shell.events_processed;
    shell.handle(Action::CancelInput);
    assert_eq!(shell.events_processed, count);
    assert_eq!(shell.held_keys, 0);
    assert!(!shell.pointer.active);
}

#[test]
fn shared_wire_phase_bounds_text_and_key_edges_fail_closed() {
    for (base, phase) in [
        (0x90000, PointerPhase::Release),
        (0xb0000, PointerPhase::Move),
        (0xd0000, PointerPhase::Press),
    ] {
        for (x, y) in [(0, 0), (239, 319)] {
            assert_eq!(
                Action::from_wire(0x08000000 | (base + (y << 8) + x)),
                Action::PointerEvent {
                    phase,
                    x: x as u16,
                    y: y as u16
                }
            );
        }
        for (x, y) in [(240, 0), (255, 319), (0, 320), (255, 511)] {
            assert_eq!(
                Action::from_wire(0x08000000 | (base + (y << 8) + x)),
                Action::CancelInput
            );
        }
    }
    assert_eq!(Action::from_wire(0x080fefff), Action::CancelInput);
    assert_eq!(
        Action::from_wire(0x0800e006),
        Action::PointerEvent {
            phase: PointerPhase::Cancel,
            x: 0,
            y: 0
        }
    );
    assert_eq!(Action::from_wire(0x0800e007), Action::CancelInput);
    assert_eq!(
        Action::from_wire(0x0800e100 + 600),
        Action::PointerHold { millis: 600 }
    );
    assert_eq!(
        Action::from_wire(0x0800f0ff),
        Action::PointerHold { millis: 4095 }
    );
    for phase in [KeyPhase::Press, KeyPhase::Repeat, KeyPhase::Release] {
        for key in 0..=12 {
            assert_eq!(
                Action::from_wire(0x0800e010 + ((phase as u32) << 4) + key),
                Action::HardwareKey {
                    phase,
                    key: key as u8
                }
            );
        }
    }
    for wire in [
        0, 0x01000001, 0x09000000, 0x0800d800, 0x08110000, 0x0800e01d,
    ] {
        assert_eq!(Action::from_wire(wire), Action::CancelInput);
    }
    assert_eq!(
        Action::from_wire(0x0800041e),
        Action::Key(Event::TextInput('О'))
    );
}

#[test]
fn input_loss_clears_capture_and_held_state_without_fabricated_actions() {
    let mut shell = Shell::new(BuildInfo::WAVE007_2);
    let mut r = RuntimeInfo::UNKNOWN;
    r.valid = VALID_INPUT;
    shell.update_runtime(r);
    edge(&mut shell, KeyPhase::Press, 0);
    pointer_phase(&mut shell, PointerPhase::Press, 40, 68);
    let events = shell.events_processed;
    r.input_overflows = 1;
    shell.update_runtime(r);
    assert_eq!(shell.events_processed, events);
    assert!(!shell.pointer.active);
    assert_eq!(shell.held_keys, 0);
    pointer_phase(&mut shell, PointerPhase::Release, 40, 68);
    assert_eq!(shell.screen, Screen::Desktop);
    edge(&mut shell, KeyPhase::Press, 0);
    pointer_phase(&mut shell, PointerPhase::Press, 40, 68);
    r.version = 99;
    shell.update_runtime(r);
    assert!(!shell.pointer.active);
    assert_eq!(shell.held_keys, 0);
    // Invalid groups cannot smuggle an invented counter change into policy.
    pointer_phase(&mut shell, PointerPhase::Press, 40, 68);
    r.input_overflows = 9;
    shell.update_runtime(r);
    assert!(shell.pointer.active);
    shell.handle(Action::CancelInput);
    tap(&mut shell, 24, 12);
    assert_eq!(shell.screen, Screen::Launcher);
}

#[test]
fn pressed_partial_render_matches_fresh_frame_and_bottom_is_wallpaper() {
    let mut shell = Shell::new(BuildInfo::WAVE007_2);
    let mut a = vec![0; 240 * 320];
    let mut s = Surface::new(&mut a, 240, 320, 240).unwrap();
    shell.render(&mut s);
    s.present(|_, _, _| Ok::<(), ()>(())).unwrap();
    let mut wallpaper = vec![0; 240 * 320];
    let mut w = Surface::new(&mut wallpaper, 240, 320, 240).unwrap();
    wallpaper::draw_region(&mut w, 0, 296, 240, 24, false);
    assert_eq!(&s.pixels()[296 * 240..], &w.pixels()[296 * 240..]);
    pointer_phase(&mut shell, PointerPhase::Press, 40, 120);
    let mut fresh = shell;
    fresh.invalidate();
    let mut b = vec![0; 240 * 320];
    let mut full = Surface::new(&mut b, 240, 320, 240).unwrap();
    shell.render(&mut s);
    fresh.render(&mut full);
    assert_eq!(s.pixels(), full.pixels());
    assert_eq!(shell.render_stats().wallpaper.pixels_written, 8352);
    pointer_phase(&mut shell, PointerPhase::Move, 120, 120);
    let mut fresh = shell;
    fresh.invalidate();
    shell.render(&mut s);
    fresh.render(&mut full);
    assert_eq!(s.pixels(), full.pixels());
}
