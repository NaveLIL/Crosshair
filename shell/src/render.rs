//! Shell composition using the existing Surface/font/components/theme. Original
//! code-drawn icons and no decorative bitmap dependency or second framebuffer.
use crate::{APPS, Screen, Shell, VALID_INPUT, VALID_MEMORY, VALID_TASKS, VALID_TIMER, icons};
use crosshair_ui::{
    Rgb565, Surface,
    components::{self, Area},
    theme::{colors as c, layout},
};

#[derive(Clone, Copy)]
struct Palette {
    background: Rgb565,
    surface: Rgb565,
    ink: Rgb565,
    muted: Rgb565,
}
fn palette(shell: &Shell) -> Palette {
    if shell.theme == 0 {
        Palette {
            background: c::BACKGROUND,
            surface: c::SURFACE,
            ink: c::INK,
            muted: c::MUTED,
        }
    } else {
        Palette {
            background: c::SYSTEM,
            surface: c::HEADER,
            ink: c::WHITE,
            muted: c::SELECTED,
        }
    }
}
/// Cozette advances 6px, with up to 8px ink. Clip at the component bound, not
/// merely at the screen. No heap, substring byte slicing or newline expansion.
fn text(s: &mut Surface<'_>, x: i32, y: i32, width: u16, value: &str, color: Rgb565) {
    let limit = if width < 8 {
        0
    } else {
        (width as usize - 8) / 6 + 1
    };
    for (index, ch) in value
        .chars()
        .take(limit)
        .take_while(|c| *c != '\n')
        .enumerate()
    {
        let mut utf8 = [0; 4];
        s.text(x + index as i32 * 6, y, ch.encode_utf8(&mut utf8), color);
    }
}
fn number(s: &mut Surface<'_>, x: i32, y: i32, value: u32, color: Rgb565) {
    let mut digits = [b'0'; 10];
    let mut count = 0;
    let mut n = value;
    loop {
        count += 1;
        digits[10 - count] = b'0' + (n % 10) as u8;
        n /= 10;
        if n == 0 {
            break;
        }
    }
    // Every byte is one of the ten ASCII decimal digits.
    if let Ok(value) = core::str::from_utf8(&digits[10 - count..]) {
        text(s, x, y, 82, value, color);
    }
}
fn row(s: &mut Surface<'_>, y: i32, label: &str, value: Option<u32>, p: Palette) {
    s.fill_rect(8, y - 2, 224, 20, p.surface);
    text(s, 14, y, 130, label, p.ink);
    if let Some(value) = value {
        number(s, 148, y, value, p.ink);
    } else {
        text(s, 148, y, 78, "нет данных", p.muted);
    }
}
fn title(s: &mut Surface<'_>, shell: &Shell) {
    s.fill_rect(0, 0, 240, 16, c::SYSTEM);
    text(s, 4, 1, 150, "Crosshair", c::WHITE);
    text(s, 178, 1, 58, "Shell 0.1", c::SELECTED);
    components::title_bar(
        s,
        Area {
            x: 0,
            y: 16,
            width: 240,
            height: 28,
        },
        "",
    );
    let icon = match shell.screen {
        Screen::Desktop | Screen::Launcher => 0,
        Screen::Today => 1,
        Screen::Settings => 2,
        Screen::Diagnostics => 3,
        Screen::About => 4,
    };
    icons::draw(s, 8, 18, icon, c::WHITE, c::SELECTED);
    text(s, 40, 23, 192, shell.screen.title(), c::WHITE);
}
fn softkeys(s: &mut Surface<'_>, shell: &Shell) {
    let (left, right) = if shell.overlay == 3 {
        ("Сбросить", "Отмена")
    } else if shell.overlay != 0 {
        ("Выбор", "Отмена")
    } else {
        match shell.screen {
            Screen::About | Screen::Diagnostics => ("Назад", "Меню"),
            Screen::Settings => ("Изменить", "Меню"),
            _ => ("Открыть", "Меню"),
        }
    };
    s.fill_rect(0, 296, 240, 24, c::SYSTEM);
    s.stroke_rect(0, 296, 240, 24, c::EDGE);
    s.line(120, 296, 120, 319, c::EDGE);
    text(s, 12, 302, 100, left, c::WHITE);
    text(s, 132, 302, 100, right, c::WHITE);
    if shell.overlay == 0 && matches!(shell.screen, Screen::About | Screen::Diagnostics) {
        s.stroke_rect(2, 298, 116, 20, c::SELECTED);
    }
}
fn desktop(s: &mut Surface<'_>, shell: &Shell, p: Palette) {
    let labels = [
        "Приложения",
        "Сегодня",
        "Настройки",
        "Диагностика",
        "О системе",
        "Переключить",
    ];
    for (index, label) in labels.into_iter().enumerate() {
        let x = 8 + (index % 2) as i32 * 116;
        let y = 58 + (index / 2) as i32 * 72;
        let area = Area {
            x,
            y,
            width: 108,
            height: 62,
        };
        let selected = index == shell.desktop_selected as usize;
        if selected {
            components::selection(s, area, true);
        } else {
            s.fill_rect(x, y, 108, 62, p.surface);
            s.stroke_rect(x, y, 108, 62, c::EDGE);
        }
        let ink = if selected { c::INK } else { p.ink };
        icons::draw(
            s,
            x + 42,
            y + 7,
            index as u8,
            ink,
            if selected { c::HEADER } else { p.muted },
        );
        let width = (label.chars().count() * 6 + 2).min(100) as u16;
        text(s, x + (108 - width as i32) / 2, y + 41, 100, label, ink);
    }
    text(s, 12, 280, 216, shell.build.environment, p.muted);
}
fn launcher(s: &mut Surface<'_>, shell: &Shell, p: Palette) {
    s.fill_rect(8, 48, 224, 22, p.surface);
    s.stroke_rect(
        8,
        48,
        224,
        22,
        if shell.launcher_matches() == 0 {
            c::FOCUS
        } else {
            c::EDGE
        },
    );
    text(s, 12, 52, 42, "Поиск:", p.muted);
    for (index, ch) in shell.query().iter().enumerate() {
        let mut utf8 = [0; 4];
        text(
            s,
            56 + index as i32 * 6,
            52,
            8,
            ch.encode_utf8(&mut utf8),
            p.ink,
        );
    }
    let mut row_index = 0;
    for (index, app) in APPS.into_iter().enumerate() {
        if !shell.matches(app) {
            continue;
        }
        let y = 78 + row_index * 42;
        row_index += 1;
        let area = Area {
            x: 8,
            y,
            width: 224,
            height: 36,
        };
        let selected = index == shell.launcher_selected as usize;
        if selected {
            components::selection(s, area, true);
        } else {
            s.fill_rect(8, y, 224, 36, p.surface);
        }
        let ink = if selected { c::INK } else { p.ink };
        let icon = match app {
            Screen::About => 4,
            Screen::Diagnostics => 3,
            Screen::Settings => 2,
            _ => 1,
        };
        icons::draw(
            s,
            15,
            y + 6,
            icon,
            ink,
            if selected { c::HEADER } else { p.muted },
        );
        text(s, 49, y + 12, 176, app.title(), ink);
    }
    if row_index == 0 {
        text(s, 16, 99, 208, "Нет приложений", p.ink);
        text(s, 16, 121, 208, "Back — очистить поиск", p.muted);
    }
    text(s, 12, 257, 216, "Select — открыть", p.muted);
    text(s, 12, 275, 216, "Menu — действия", p.muted);
}
fn today(s: &mut Surface<'_>, shell: &Shell, p: Palette) {
    text(s, 12, 55, 216, "Только подтверждённое состояние", p.muted);
    let unavailable = [
        "Часы: служба недоступна",
        "Питание: нет данных",
        "Связь: служба недоступна",
    ];
    for (index, label) in unavailable.into_iter().enumerate() {
        let y = 80 + index as i32 * 25;
        s.fill_rect(8, y - 3, 224, 23, p.surface);
        text(s, 14, y, 212, label, p.ink);
    }
    row(
        s,
        159,
        "Задач",
        shell
            .runtime
            .has(VALID_TASKS)
            .then_some(shell.runtime.task_count),
        p,
    );
    row(
        s,
        183,
        "Событий ввода",
        shell
            .runtime
            .has(VALID_INPUT)
            .then_some(shell.runtime.events_delivered),
        p,
    );
    for (index, label) in ["Приложения", "Диагностика"].into_iter().enumerate()
    {
        components::list_row(
            s,
            Area {
                x: 8,
                y: 220 + index as i32 * 36,
                width: 224,
                height: 30,
            },
            label,
            shell.today_selected as usize == index,
            shell.today_selected as usize == index,
        );
    }
}
fn about(s: &mut Surface<'_>, shell: &Shell, p: Palette) {
    let fields = [
        ("Оболочка", "Crosshair Shell 0.1.0"),
        ("Сборка", shell.build.version),
        ("Архитектура", shell.build.architecture),
        ("Окружение", shell.build.environment),
        ("Код / шрифт", "MIT / Cozette MIT"),
    ];
    for (index, (label, value)) in fields.into_iter().enumerate() {
        let y = 57 + index as i32 * 42;
        s.fill_rect(8, y - 3, 224, 38, p.surface);
        text(s, 14, y, 212, label, p.muted);
        text(s, 14, y + 17, 212, value, p.ink);
    }
    text(s, 12, 273, 216, "Физическая плата не проверена", p.muted);
}
fn diagnostics(s: &mut Surface<'_>, shell: &Shell, p: Palette) {
    let r = shell.runtime;
    let rows = [
        ("Тики IRQ", r.has(VALID_TIMER).then_some(r.ticks)),
        ("Переключения", r.has(VALID_TIMER).then_some(r.switches)),
        ("Задач", r.has(VALID_TASKS).then_some(r.task_count)),
        ("Готовы", r.has(VALID_TASKS).then_some(r.ready_tasks)),
        ("В работе", r.has(VALID_TASKS).then_some(r.running_tasks)),
        ("С ошибкой", r.has(VALID_TASKS).then_some(r.faulted_tasks)),
        (
            "RAM, байт",
            r.has(VALID_MEMORY).then_some(r.working_ram_bytes),
        ),
        (
            "Ввод доставлен",
            r.has(VALID_INPUT).then_some(r.events_delivered),
        ),
        (
            "Очередь полна",
            r.has(VALID_INPUT).then_some(r.input_overflows),
        ),
        ("События UI", Some(shell.events_processed)),
        ("Кадров UI", Some(shell.renders)),
    ];
    for (index, (label, value)) in rows.into_iter().enumerate() {
        row(s, 57 + index as i32 * 20, label, value, p);
    }
    text(s, 12, 279, 216, "Снимок служб / счётчики UI", p.muted);
}
fn settings(s: &mut Surface<'_>, shell: &Shell, p: Palette) {
    text(s, 12, 55, 216, "Настройки интерфейса", p.muted);
    for index in 0..2 {
        let y = 82 + index * 66;
        let area = Area {
            x: 8,
            y,
            width: 224,
            height: 56,
        };
        let selected = index as u8 == shell.settings_selected;
        if selected {
            components::selection(s, area, true);
        } else {
            s.fill_rect(8, y, 224, 56, p.surface);
        }
        let ink = if selected { c::INK } else { p.ink };
        text(
            s,
            16,
            y + 8,
            208,
            if index == 0 {
                "Цветовая тема"
            } else {
                "Сбросить тему"
            },
            ink,
        );
        let detail = if index == 0 {
            if shell.theme == 0 {
                "Холодная серая"
            } else {
                "Ночная синяя"
            }
        } else {
            "С подтверждением"
        };
        text(s, 16, y + 30, 208, detail, ink);
    }
    text(s, 12, 234, 216, "Выбор действует до перезагрузки.", p.muted);
    text(s, 12, 254, 216, "Select — изменить", p.muted);
    text(s, 12, 274, 216, "Сохранение не подключено", p.muted);
}
fn overlay(s: &mut Surface<'_>, shell: &Shell) {
    if shell.overlay == 3 {
        s.fill_rect(12, 82, 216, 152, c::SURFACE);
        s.stroke_rect(12, 82, 216, 152, c::FOCUS);
        components::title_bar(
            s,
            Area {
                x: 13,
                y: 83,
                width: 214,
                height: 26,
            },
            "Сброс темы",
        );
        text(s, 24, 121, 192, "Вернуть холодную серую", c::INK);
        text(s, 24, 141, 192, "тему интерфейса?", c::INK);
        text(s, 24, 163, 192, "Другие данные не меняются.", c::MUTED);
        components::button(
            s,
            Area {
                x: 24,
                y: 194,
                width: 92,
                height: 28,
            },
            "Сбросить",
            shell.overlay_selected == 0,
        );
        components::button(
            s,
            Area {
                x: 124,
                y: 194,
                width: 92,
                height: 28,
            },
            "Отмена",
            shell.overlay_selected == 1,
        );
    } else {
        let system = [
            "Сегодня",
            "Приложения",
            "Настройки",
            "Диагностика",
            "О системе",
            "Следующий экран",
        ];
        let context = [
            if shell.launcher_matches() == 0 {
                "Сбросить поиск"
            } else {
                "Открыть"
            },
            "На рабочий стол",
            "О системе",
        ];
        let entries: &[&str] = if shell.overlay == 1 {
            &system
        } else {
            &context
        };
        let height = 28 + entries.len() as u32 * 27;
        s.fill_rect(12, 60, 216, height, c::SURFACE);
        s.stroke_rect(12, 60, 216, height, c::FOCUS);
        components::title_bar(
            s,
            Area {
                x: 13,
                y: 61,
                width: 214,
                height: 26,
            },
            if shell.overlay == 1 {
                "Системное меню"
            } else {
                "Действия приложения"
            },
        );
        for (index, label) in entries.iter().enumerate() {
            components::list_row(
                s,
                Area {
                    x: 16,
                    y: 90 + index as i32 * 27,
                    width: 208,
                    height: 24,
                },
                label,
                index == shell.overlay_selected as usize,
                index == shell.overlay_selected as usize,
            );
        }
    }
}
pub(super) fn draw(shell: &Shell, s: &mut Surface<'_>) {
    let p = palette(shell);
    s.fill(p.background);
    title(s, shell);
    match shell.screen {
        Screen::Desktop => desktop(s, shell, p),
        Screen::Launcher => launcher(s, shell, p),
        Screen::Today => today(s, shell, p),
        Screen::About => about(s, shell, p),
        Screen::Diagnostics => diagnostics(s, shell, p),
        Screen::Settings => settings(s, shell, p),
    }
    if shell.overlay != 0 {
        overlay(s, shell);
    }
    softkeys(s, shell);
    // The logical screen uses the existing fixed 240x320 layout contract.
    debug_assert!(layout::WIDTH == 240 && layout::HEIGHT == 320);
}
