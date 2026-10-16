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
    shell.handle(Action::SoftLeft);
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
    assert_eq!(shell.desktop_selected, 2);
    key(&mut shell, Event::Select);
    shell.handle(Action::Home);
    assert_eq!(shell.desktop_selected, 2);
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
    key(&mut shell, Event::Right);
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
        assert!(state.screen <= 5 && state.desktop_selected < 6 && state.launcher_selected < 4);
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
