use crosshair_ui::{
    DIRTY_CAPACITY, Rgb565, Surface,
    components::{
        self, AppsScreen, Area, Event, FILTER_CAPACITY, Focus, INPUT_CAPACITY, ITEMS, InputQueue,
        VISIBLE_ROWS, View,
    },
};

#[allow(dead_code)]
#[path = "../examples/apps.rs"]
mod apps;

fn invariant(screen: &AppsScreen) {
    let count = screen.match_count();
    assert!(count <= ITEMS.len());
    assert!(screen.filter().len() <= FILTER_CAPACITY);
    assert!(screen.scroll() <= count.saturating_sub(VISIBLE_ROWS));
    if count == 0 {
        assert_eq!(screen.selected_position(), 0);
        assert_eq!(screen.selected_item(), None);
    } else {
        assert!(screen.selected_position() < count);
        assert!(screen.selected_position() >= screen.scroll());
        assert!(screen.selected_position() < screen.scroll() + VISIBLE_ROWS);
        assert!((screen.selected_item().unwrap() as usize) < ITEMS.len());
    }
    assert!(screen.menu_selection() < 3);
    if matches!(screen.view(), View::Action(_)) {
        assert_ne!(screen.focus(), Focus::List);
    }
}

#[test]
fn keyboard_scroll_selection_and_real_preview_back_navigation() {
    let mut screen = AppsScreen::new();
    assert!(ITEMS.len() > VISIBLE_ROWS);
    for _ in 0..10 {
        assert!(screen.handle(Event::Down));
        invariant(&screen);
    }
    assert_eq!((screen.selected_item(), screen.scroll()), (Some(10), 3));
    screen.handle(Event::Select);
    assert_eq!(screen.view(), View::Action(10));
    assert_eq!(screen.opened_count(), 1);
    screen.handle(Event::Up);
    invariant(&screen);
    screen.handle(Event::Menu);
    assert_eq!(screen.view(), View::Menu);
    screen.handle(Event::Back);
    assert_eq!(screen.view(), View::Action(10));
    invariant(&screen);
    screen.handle(Event::Select); // visibly focused left softkey = Back
    assert_eq!(screen.view(), View::List);
    assert_eq!((screen.selected_item(), screen.scroll()), (Some(10), 3));
    for _ in 0..100 {
        screen.handle(Event::Down);
    }
    assert_eq!(screen.selected_item(), Some(15));
    invariant(&screen);
    for _ in 0..100 {
        screen.handle(Event::Up);
    }
    assert_eq!((screen.selected_item(), screen.scroll()), (Some(0), 0));
    invariant(&screen);
}

#[test]
fn softkey_focus_and_menu_are_fully_keyboard_accessible() {
    let mut screen = AppsScreen::new();
    screen.handle(Event::Right);
    assert_eq!(screen.focus(), Focus::RightSoftkey);
    screen.handle(Event::Select);
    assert_eq!(screen.view(), View::Menu);
    screen.handle(Event::Down);
    screen.handle(Event::Down);
    assert_eq!(screen.menu_selection(), 2);
    screen.handle(Event::Select);
    assert_eq!(screen.view(), View::List);
    screen.handle(Event::TextInput('т'));
    screen.handle(Event::Menu);
    screen.handle(Event::Select);
    assert!(screen.filter().is_empty());
    assert_eq!(screen.view(), View::List);
    screen.handle(Event::Left);
    assert_eq!(screen.focus(), Focus::LeftSoftkey);
    screen.handle(Event::Select);
    assert_eq!(screen.view(), View::Action(0));
    screen.handle(Event::Right);
    screen.handle(Event::Select);
    screen.handle(Event::Down);
    screen.handle(Event::Select); // Menu -> list
    assert_eq!(screen.view(), View::List);
    invariant(&screen);
}

#[test]
fn cyrillic_filter_is_bounded_case_insensitive_and_scalar_based() {
    let mut screen = AppsScreen::new();
    for ch in "ЦВЕТ".chars() {
        screen.handle(Event::TextInput(ch));
    }
    assert_eq!(screen.filter(), &['Ц', 'В', 'Е', 'Т']);
    assert_eq!((screen.match_count(), screen.selected_item()), (1, Some(1)));
    screen.handle(Event::Select);
    assert_eq!(screen.view(), View::Action(1));
    assert!(!screen.handle(Event::TextInput('а'))); // text belongs only to list
    screen.handle(Event::Back);
    screen.handle(Event::TextInput('\u{8}'));
    assert_eq!(screen.filter(), &['Ц', 'В', 'Е']);
    screen.handle(Event::Back);
    assert!(screen.filter().is_empty());
    assert!(!screen.handle(Event::TextInput('💡')));
    assert!(!screen.handle(Event::TextInput('\n')));
    for _ in 0..FILTER_CAPACITY + 10 {
        screen.handle(Event::TextInput('ё'));
    }
    assert_eq!(screen.filter().len(), FILTER_CAPACITY);
    assert_eq!(screen.match_count(), 0);
    assert!(!screen.handle(Event::TextInput('я')));
    assert!(!screen.handle(Event::Select)); // empty list never opens a fake app
    invariant(&screen);
}

#[test]
fn fifo_wraparound_and_overflow_have_explicit_backpressure() {
    let mut queue = InputQueue::new();
    for _ in 0..INPUT_CAPACITY {
        assert_eq!(queue.push(Event::Down), Ok(()));
    }
    assert_eq!(queue.push(Event::Select), Err(Event::Select));
    assert_eq!(queue.len(), INPUT_CAPACITY);
    assert_eq!(queue.pop(), Some(Event::Down));
    assert_eq!(queue.push(Event::Select), Ok(()));
    for _ in 0..INPUT_CAPACITY - 1 {
        assert_eq!(queue.pop(), Some(Event::Down));
    }
    assert_eq!(queue.pop(), Some(Event::Select));
    assert!(queue.is_empty());
    assert_eq!(queue.pop(), None);
}

#[test]
fn component_ink_stays_inside_its_bounds_and_focus_is_visible() {
    let mut data = [0x1234; 48 * 48];
    let mut surface = Surface::new(&mut data, 48, 48, 48).unwrap();
    let area = Area {
        x: 9,
        y: 11,
        width: 21,
        height: 21,
    };
    components::button(&mut surface, area, "ЩЩЩЩ\nД", false);
    let without_focus = surface.pixels().to_vec();
    components::button(&mut surface, area, "ЩЩЩЩ\nД", true);
    assert_ne!(without_focus, surface.pixels());
    for y in 0..48 {
        for x in 0..48 {
            if !(9..30).contains(&x) || !(11..32).contains(&y) {
                assert_eq!(surface.pixels()[y * 48 + x], 0x1234);
            }
        }
    }
}

fn random(seed: &mut u64) -> u32 {
    *seed ^= *seed << 13;
    *seed ^= *seed >> 7;
    *seed ^= *seed << 17;
    *seed as u32
}

#[test]
fn seeded_ten_thousand_events_replay_and_preserve_focus_scroll_bounds() {
    let mut seed = 0x43524f5353484149;
    let mut first = AppsScreen::new();
    let mut replay = AppsScreen::new();
    let mut queue = InputQueue::new();
    let chars = ['К', 'и', 'р', 'ц', 'ё', ' ', '-', '4', '\u{8}', '💡', '\n'];
    let mut coverage = [false; 8];
    let mut view_coverage = [false; 3];
    let mut focus_coverage = [false; 3];
    for step in 0..10_000 {
        let r = random(&mut seed);
        let kind = (r % 8) as usize;
        coverage[kind] = true;
        let event = match kind {
            0 => Event::Up,
            1 => Event::Down,
            2 => Event::Left,
            3 => Event::Right,
            4 => Event::Select,
            5 => Event::Back,
            6 => Event::Menu,
            _ => Event::TextInput(chars[(r as usize / 8) % chars.len()]),
        };
        first.handle(event);
        queue.push(event).unwrap();
        if queue.len() == INPUT_CAPACITY || step == 9999 {
            while let Some(queued) = queue.pop() {
                replay.handle(queued);
                invariant(&replay);
            }
            assert_eq!(
                first, replay,
                "batched adapter replay diverged at seed step {step}"
            );
        }
        view_coverage[match first.view() {
            View::List => 0,
            View::Action(_) => 1,
            View::Menu => 2,
        }] = true;
        focus_coverage[match first.focus() {
            Focus::List => 0,
            Focus::LeftSoftkey => 1,
            Focus::RightSoftkey => 2,
        }] = true;
        invariant(&first);
    }
    assert!(coverage.into_iter().all(|x| x));
    assert!(view_coverage.into_iter().all(|x| x));
    assert!(focus_coverage.into_iter().all(|x| x));
}

#[test]
fn seeded_ten_thousand_draws_preserve_guards_and_cover_every_changed_pixel() {
    const W: usize = 47;
    const H: usize = 31;
    const STRIDE: usize = 51;
    let mut data = vec![0xa55a; STRIDE * H + 4];
    let mut seed = 0x55495f434c495050;
    let mut surface = Surface::new(&mut data[2..2 + STRIDE * H], W, H, STRIDE).unwrap();
    surface.present(|_, _, _| Ok::<(), ()>(())).unwrap();
    let mut coverage = [false; 6];
    for step in 0..10_000 {
        let before = surface.pixels().to_vec();
        let r = random(&mut seed);
        let kind = (r % 6) as usize;
        coverage[kind] = true;
        let x = if step % 101 == 0 {
            i32::MIN
        } else {
            (r % 130) as i32 - 65
        };
        let y = if step % 103 == 0 {
            i32::MAX
        } else {
            ((r >> 8) % 100) as i32 - 50
        };
        let area = Area {
            x,
            y,
            width: ((r >> 16) % 120) as u16,
            height: ((r >> 24) % 70) as u16,
        };
        match kind {
            0 => surface.fill_rect(
                x,
                y,
                area.width as u32,
                area.height as u32,
                Rgb565(r as u16),
            ),
            1 => surface.line(
                x,
                y,
                x.saturating_add(70),
                y.saturating_add(40),
                Rgb565(r as u16),
            ),
            2 => components::list_row(&mut surface, area, "ЩъЁ Кириллица", true, r & 0x40 != 0),
            3 => components::button(&mut surface, area, "Кнопка", r & 0x40 != 0),
            4 => components::title_bar(&mut surface, area, "Заголовок"),
            _ => surface.text(x, y, "ДЩ💡\nй", Rgb565(r as u16)),
        }
        assert!(surface.dirty_rects().len() <= DIRTY_CAPACITY);
        for rect in surface.dirty_rects() {
            assert!(rect.right() <= W && rect.bottom() <= H);
        }
        for row in 0..H {
            for col in 0..STRIDE {
                let index = row * STRIDE + col;
                if col >= W {
                    assert_eq!(
                        surface.pixels()[index],
                        0xa55a,
                        "padding at seed step {step}"
                    );
                } else if before[index] != surface.pixels()[index] {
                    assert!(
                        surface.dirty_rects().iter().any(|d| d.x() <= col
                            && col < d.right()
                            && d.y() <= row
                            && row < d.bottom()),
                        "uncovered changed pixel at seed step {step}"
                    );
                }
            }
        }
        if step % 37 == 0 {
            let dirty = surface.dirty_rects().to_vec();
            assert_eq!(
                surface.present(|_, _, _| Err::<(), _>("injected")),
                if dirty.is_empty() {
                    Ok(0)
                } else {
                    Err("injected")
                }
            );
            assert_eq!(surface.dirty_rects(), dirty);
        }
        surface.present(|_, _, _| Ok::<(), ()>(())).unwrap();
        assert!(surface.dirty_rects().is_empty());
    }
    assert!(coverage.into_iter().all(|x| x));
    drop(surface);
    assert_eq!(&data[..2], &[0xa55a; 2]);
    assert_eq!(&data[data.len() - 2..], &[0xa55a; 2]);
}

#[test]
fn scenario_has_reviewable_selection_scroll_and_pixel_golden() {
    let screen = apps::scenario();
    invariant(&screen);
    assert_eq!(screen.view(), View::List);
    assert_eq!(
        (
            screen.selected_item(),
            screen.scroll(),
            screen.opened_count()
        ),
        (Some(11), 4, 3)
    );
    let mut data = vec![0; 240 * 320];
    let mut surface = Surface::new(&mut data, 240, 320, 240).unwrap();
    screen.render(&mut surface);
    let mut hash = 0xcbf29ce484222325u64;
    for pixel in surface.pixels() {
        for byte in pixel.to_le_bytes() {
            hash = (hash ^ byte as u64).wrapping_mul(0x100000001b3);
        }
    }
    assert_eq!(hash, 10739668449275078947, "UI0.2 reviewed raw565 golden");
}
