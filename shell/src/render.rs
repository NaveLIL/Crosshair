//! One shared Surface, dense PDA components and Shell-owned adaptive chrome.
use crate::{
    APPS, ChromeMode, Screen, Shell, VALID_INPUT, VALID_MEMORY, VALID_TASKS, VALID_TIMER,
    adaptive::target as t, geometry as g, icons,
};
use crosshair_ui::{
    Rgb565, Surface,
    components::{self, Area},
    pda::{self, Palette},
    theme::colors as c,
};
fn palette(shell: &Shell) -> Palette {
    Palette {
        ink: if shell.theme == 0 { c::INK } else { c::WHITE },
        muted: if shell.theme == 0 {
            c::MUTED
        } else {
            c::SELECTED
        },
        surface: if shell.theme == 0 {
            c::SURFACE
        } else {
            c::HEADER
        },
        edge: c::EDGE,
        focus: if shell.theme == 0 {
            c::FOCUS
        } else {
            c::SELECTED
        },
        selected: c::SELECTED,
    }
}
fn selected(mut p: Palette, yes: bool) -> Palette {
    if yes {
        p.ink = c::INK;
        p.focus = c::FOCUS;
    }
    p
}
fn area(r: g::Rect) -> Area {
    Area {
        x: r.x as i32,
        y: r.y as i32,
        width: r.width,
        height: r.height,
    }
}
fn text(s: &mut Surface<'_>, x: i32, y: i32, width: u16, value: &str, color: Rgb565) {
    pda::text(
        s,
        Area {
            x,
            y,
            width,
            height: 13,
        },
        value,
        color,
    );
}
fn decimal(mut value: u32, out: &mut [u8; 10]) -> &str {
    let mut start = 10;
    loop {
        start -= 1;
        out[start] = b'0' + (value % 10) as u8;
        value /= 10;
        if value == 0 {
            break;
        }
    }
    core::str::from_utf8(&out[start..]).unwrap_or("")
}
fn fact(s: &mut Surface<'_>, y: u16, label: &str, value: &str, p: Palette) {
    pda::key_value(
        s,
        Area {
            x: 8,
            y: y as i32,
            width: 212,
            height: 16,
        },
        label,
        value,
        p,
    );
}
fn heading(s: &mut Surface<'_>, y: u16, value: &str, p: Palette) {
    pda::section_heading(
        s,
        Area {
            x: 8,
            y: y as i32,
            width: 212,
            height: 18,
        },
        value,
        p,
    );
}
fn section_icon(s: &mut Surface<'_>, y: u16, label: &str, icon: icons::IconId, p: Palette) {
    icons::draw_icon(s, 8, y as i32 + 2, icon, 12, p.muted);
    pda::section_heading(
        s,
        Area {
            x: 24,
            y: y as i32,
            width: 196,
            height: 18,
        },
        label,
        p,
    );
}
fn title(s: &mut Surface<'_>, shell: &Shell) {
    let mode = shell.chrome_mode();
    if mode == ChromeMode::Immersive {
        let r = g::IMMERSIVE_HANDLE;
        s.fill_rect(
            r.x as i32,
            r.y as i32,
            r.width as u32,
            r.height as u32,
            c::SYSTEM,
        );
        icons::draw_icon(s, 226, 2, icons::IconId::Menu, 12, c::WHITE);
        return;
    }
    let h = mode.top();
    s.fill_rect(0, 0, 240, h as u32, c::SYSTEM);
    let icon = if mode == ChromeMode::Compact { 12 } else { 16 };
    icons::draw_icon(
        s,
        4,
        ((h - icon as u16) / 2) as i32,
        icons::IconId::Applications,
        icon,
        c::WHITE,
    );
    let title_x = if mode == ChromeMode::Compact { 28 } else { 65 };
    if mode == ChromeMode::Standard {
        text(s, 23, 6, 34, "Пуск", c::WHITE);
        s.line(58, 3, 58, 20, c::EDGE);
    }
    text(
        s,
        title_x,
        (h as i32 - 13) / 2,
        (190 - title_x) as u16,
        if shell.screen == Screen::Desktop {
            "Crosshair"
        } else {
            shell.screen.title()
        },
        c::WHITE,
    );
    icons::draw_icon(
        s,
        198,
        ((h - 12) / 2) as i32,
        icons::IconId::Menu,
        12,
        c::WHITE,
    );
    if shell.screen != Screen::Desktop {
        icons::draw_icon(
            s,
            222,
            ((h - 12) / 2) as i32,
            icons::IconId::Back,
            12,
            c::WHITE,
        );
    }
    s.line(0, h as i32 - 1, 239, h as i32 - 1, c::EDGE);
}
fn shortcut(s: &mut Surface<'_>, shell: &Shell, index: usize) {
    let r = g::DESKTOP[index];
    let x = r.x as i32;
    let y = r.y as i32;
    let selected = shell.desktop_selected as usize == index;
    let pressed = shell.pressed(t::DESKTOP + index as u16);
    s.fill_rect(
        x + 20,
        y + 1,
        32,
        32,
        if pressed { c::SELECTED } else { c::HEADER },
    );
    if selected {
        s.stroke_rect(x + 19, y, 34, 34, c::SELECTED);
    }
    icons::draw(
        s,
        x + 24,
        y + 5,
        index as u8 + 1,
        if pressed { c::INK } else { c::WHITE },
        c::SELECTED,
    );
    s.fill_rect(
        x,
        y + 38,
        72,
        18,
        if selected { c::SELECTED } else { c::SYSTEM },
    );
    let label = ["Сегодня", "Настройки", "Диагностика"][index];
    let width = (label.chars().count() * 6 + 2).min(70) as u16;
    text(
        s,
        x + (72 - width as i32) / 2,
        y + 40,
        70,
        label,
        if selected { c::INK } else { c::WHITE },
    );
}
fn desktop(s: &mut Surface<'_>, shell: &Shell) {
    for index in 0..3 {
        shortcut(s, shell, index);
    }
}
fn add_stats(a: &mut crate::wallpaper::DrawStats, b: crate::wallpaper::DrawStats) {
    a.packets_decoded += b.packets_decoded;
    a.pixels_decoded += b.pixels_decoded;
    a.pixels_written += b.pixels_written;
    a.runs_written += b.runs_written;
}
pub(super) fn redraw_desktop_focus(
    shell: &Shell,
    s: &mut Surface<'_>,
    dirty: u8,
) -> crate::wallpaper::DrawStats {
    let mut stats = crate::wallpaper::DrawStats::default();
    if dirty & 0x20 != 0 {
        let r = g::DESKTOP_OVERLAY_RESTORE;
        stats = crate::wallpaper::draw_region(s, r.x, r.y, r.width, r.height, shell.theme != 0);
        desktop(s, shell);
    }
    for (index, r) in g::DESKTOP.into_iter().enumerate() {
        if dirty & 0x20 == 0 && dirty & (1 << index) != 0 {
            add_stats(
                &mut stats,
                crate::wallpaper::draw_region(s, r.x, r.y, r.width, r.height, shell.theme != 0),
            );
            shortcut(s, shell, index);
        }
    }
    if dirty & 0x40 != 0 && shell.overlay != 0 {
        overlay(s, shell);
    }
    stats
}
fn launcher(s: &mut Surface<'_>, shell: &Shell, p: Palette) {
    s.stroke_rect(
        8,
        g::SEARCH.y as i32,
        224,
        22,
        if shell.launcher_matches() == 0 {
            c::FOCUS
        } else {
            c::EDGE
        },
    );
    text(s, 12, 38, 42, "Поиск:", p.muted);
    for (index, ch) in shell.query().iter().enumerate() {
        let mut utf8 = [0; 4];
        text(
            s,
            56 + index as i32 * 6,
            38,
            8,
            ch.encode_utf8(&mut utf8),
            p.ink,
        );
    }
    let mut visible = 0;
    for (index, app) in APPS.into_iter().enumerate() {
        if !shell.matches(app) {
            continue;
        }
        let r = g::launcher_row(visible);
        visible += 1;
        let focus = shell.launcher_selected as usize == index;
        let rp = selected(p, focus);
        pda::compact_row(s, area(r), "", focus, rp);
        let icon = match app {
            Screen::About => icons::IconId::Information,
            Screen::Diagnostics => icons::IconId::Diagnostics,
            Screen::Settings => icons::IconId::Settings,
            _ => icons::IconId::Today,
        };
        icons::draw_icon(s, 15, r.y as i32 + 6, icon, 16, rp.ink);
        text(s, 40, r.y as i32 + 7, 184, app.title(), rp.ink);
        if shell.pressed(t::LAUNCHER + index as u16) {
            s.stroke_rect(10, r.y as i32 + 2, 220, r.height as u32 - 4, p.focus);
        }
    }
    if visible == 0 {
        text(s, 12, 72, 212, "Нет приложений", p.ink);
    }
    heading(s, 210, "Встроенные приложения", p);
    text(s, 12, 234, 216, "Текст — поиск; Enter — открыть", p.muted);
    text(s, 12, 252, 216, "Esc — назад / очистить поиск", p.muted);
}
fn today(s: &mut Surface<'_>, shell: &Shell, p: Palette) {
    let r = shell.runtime;
    section_icon(
        s,
        30,
        "Сегодня — сеанс Crosshair",
        icons::IconId::Diagnostics,
        p,
    );
    let values = [
        ("Задач", r.has(VALID_TASKS).then_some(r.task_count)),
        ("Готовы", r.has(VALID_TASKS).then_some(r.ready_tasks)),
        ("В работе", r.has(VALID_TASKS).then_some(r.running_tasks)),
        ("С ошибкой", r.has(VALID_TASKS).then_some(r.faulted_tasks)),
        (
            "RAM резерв",
            r.has(VALID_MEMORY).then_some(r.working_ram_bytes),
        ),
        ("Ввод", r.has(VALID_INPUT).then_some(r.events_delivered)),
        (
            "Переполнения",
            r.has(VALID_INPUT).then_some(r.input_overflows),
        ),
    ];
    for (index, (label, value)) in values.into_iter().enumerate() {
        let mut n = [0; 10];
        fact(
            s,
            52 + index as u16 * 16,
            label,
            value.map_or("—", |v| decimal(v, &mut n)),
            p,
        );
    }
    section_icon(
        s,
        170,
        "Источники устройства",
        icons::IconId::Information,
        p,
    );
    text(s, 10, 194, 212, "Часы / питание / связь: —", p.muted);
    text(s, 10, 212, 212, "Физическая плата не проверена", p.muted);
    for (index, label) in ["Приложения", "Диагностика"].into_iter().enumerate()
    {
        let focus = shell.today_selected as usize == index;
        pda::inline_action(
            s,
            area(g::TODAY_ACTIONS[index]),
            label,
            focus,
            selected(p, focus),
        );
    }
}
fn content_rows(s: &mut Surface<'_>, shell: &Shell, rows: &[(&str, &str)], p: Palette) {
    let content = shell.content_rect();
    let visible = content.height.saturating_sub(8) / 16;
    for (index, (label, value)) in rows
        .iter()
        .skip(shell.scroll_offset() as usize)
        .take(visible as usize)
        .enumerate()
    {
        let y = content.y + 4 + index as u16 * 16;
        if label.is_empty() {
            pda::section_heading(
                s,
                Area {
                    x: 8,
                    y: y as i32,
                    width: 212,
                    height: 16,
                },
                value,
                p,
            );
        } else {
            fact(s, y, label, value, p);
        }
    }
    if shell.scroll_max() > 0 {
        icons::draw_icon(
            s,
            226,
            g::scroll_up(shell.chrome_mode()).y as i32 + 2,
            icons::IconId::Up,
            12,
            p.ink,
        );
        icons::draw_icon(s, 226, 306, icons::IconId::Down, 12, p.ink);
        let track_y = g::scroll_up(shell.chrome_mode()).y + 20;
        let track_h = 304u16.saturating_sub(track_y);
        s.fill_rect(231, track_y as i32, 2, track_h as u32, c::EDGE);
        let thumb = 8;
        let y = track_y + (track_h - thumb) * shell.scroll_offset() / shell.scroll_max();
        s.fill_rect(229, y as i32, 6, thumb as u32, p.muted);
    }
}
fn about(s: &mut Surface<'_>, shell: &Shell, p: Palette) {
    let rows = [
        ("", "Система"),
        ("Оболочка", crate::VERSION),
        ("Сборка", shell.build.version),
        ("Архитектура", shell.build.architecture),
        ("Окружение", shell.build.environment),
        ("Экран", "240x320 RGB565"),
        ("", "Лицензии"),
        ("Свой код", "MIT"),
        ("Шрифт", "Cozette MIT"),
        ("Значки", "Tabler MIT"),
        ("Обои", "Ресурс Crosshair"),
        ("", "Возможности"),
        ("Framebuffer", "Один, 153600B"),
        ("Изоляция", "User / MMU"),
        ("Приложения", "4 встроенных"),
        ("Файлы / сеть", "Нет служб"),
        ("Сохранение", "Не подключено"),
        ("Часы/питание", "Нет источника"),
        ("Физ. плата", "Не проверена"),
        ("Буфер", "Нет службы"),
        ("", "Управление"),
        ("Menu / F2", "Системная панель"),
        ("Home", "Рабочий стол"),
        ("Стилус", "Tap / hold 600ms"),
        ("Ввод PDA2k", "Не проверен"),
    ];
    content_rows(s, shell, &rows, p);
}
fn diagnostics(s: &mut Surface<'_>, shell: &Shell, p: Palette) {
    let r = shell.runtime;
    let values = [
        ("Тики IRQ", r.has(VALID_TIMER).then_some(r.ticks)),
        ("Переключения", r.has(VALID_TIMER).then_some(r.switches)),
        ("Задач", r.has(VALID_TASKS).then_some(r.task_count)),
        ("Готовы", r.has(VALID_TASKS).then_some(r.ready_tasks)),
        ("В работе", r.has(VALID_TASKS).then_some(r.running_tasks)),
        ("С ошибкой", r.has(VALID_TASKS).then_some(r.faulted_tasks)),
        (
            "RAM резерв",
            r.has(VALID_MEMORY).then_some(r.working_ram_bytes),
        ),
        (
            "Ввод принят",
            r.has(VALID_INPUT).then_some(r.events_delivered),
        ),
        (
            "Очередь полна",
            r.has(VALID_INPUT).then_some(r.input_overflows),
        ),
        ("События UI", Some(shell.events_processed)),
        ("Кадры UI", Some(shell.renders)),
    ];
    let mut numbers = [[0; 10]; 11];
    let mut rows = [("", ""); 22];
    rows[0] = ("", "Наблюдения ядра / UI");
    for (index, ((label, value), digits)) in values.into_iter().zip(numbers.iter_mut()).enumerate()
    {
        let value = if let Some(v) = value {
            decimal(v, digits)
        } else {
            "—"
        };
        rows[index + 1] = (label, value);
    }
    rows[12] = ("", "Границы измерений");
    rows[13] = ("Present", "Полный кадр");
    rows[14] = ("Передача", "153600B / render");
    rows[15] = ("Стоимость", "Счётчики работы");
    rows[16] = ("Циклы CPU", "Не измерены");
    rows[17] = ("Физ. LCD", "Не проверен");
    rows[18] = ("", "Управление");
    rows[19] = ("Menu / F2", "Системная панель");
    rows[20] = ("Home", "Рабочий стол");
    rows[21] = ("Стилус", "Tap / hold 600ms");
    content_rows(s, shell, &rows, p);
}
fn settings(s: &mut Surface<'_>, shell: &Shell, p: Palette) {
    heading(s, 30, "Интерфейс", p);
    for index in 0..2 {
        let r = g::SETTINGS[index];
        let focus = shell.settings_selected as usize == index;
        let rp = selected(p, focus);
        pda::compact_row(s, area(r), "", focus, rp);
        text(
            s,
            14,
            r.y as i32 + 7,
            212,
            if index == 0 {
                "Цветовая тема"
            } else {
                "Сбросить тему"
            },
            rp.ink,
        );
        text(
            s,
            14,
            r.y as i32 + 26,
            212,
            if index == 1 {
                "С подтверждением"
            } else if shell.theme == 0 {
                "Холодная серая"
            } else {
                "Ночная синяя"
            },
            rp.ink,
        );
    }
    text(s, 10, 196, 216, "Тема действует до перезагрузки.", p.muted);
    text(s, 10, 216, 216, "Сохранение не подключено", p.muted);
}
fn overlay(s: &mut Surface<'_>, shell: &Shell) {
    let p = Palette {
        ink: c::INK,
        muted: c::MUTED,
        surface: c::SURFACE,
        edge: c::EDGE,
        focus: c::FOCUS,
        selected: c::SELECTED,
    };
    if shell.overlay == 3 {
        let r = g::DIALOG;
        s.fill_rect(
            r.x as i32,
            r.y as i32,
            r.width as u32,
            r.height as u32,
            c::SURFACE,
        );
        s.stroke_rect(
            r.x as i32,
            r.y as i32,
            r.width as u32,
            r.height as u32,
            c::FOCUS,
        );
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
        for (index, label) in ["Сбросить", "Отмена"].into_iter().enumerate() {
            components::button(
                s,
                area(g::DIALOG_BUTTONS[index]),
                label,
                shell.overlay_selected as usize == index,
            );
        }
        return;
    }
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
    let panel = [
        "Рабочий стол",
        "Пуск",
        "Назад",
        "Следующий экран",
        "Standard",
        "Compact",
        "Immersive",
        "Закрыть",
    ];
    let simple_panel = [
        "Рабочий стол",
        "Пуск",
        "Назад",
        "Следующий экран",
        "Закрыть",
    ];
    let (entries, bounds, title) = if shell.overlay == 4 {
        (
            if shell.mode_available() {
                &panel[..]
            } else {
                &simple_panel[..]
            },
            g::panel_bounds(shell.overlay_count()),
            "Системная панель",
        )
    } else if shell.overlay == 1 {
        (&system[..], g::menu_bounds(6), "Системное меню")
    } else {
        (&context[..], g::menu_bounds(3), "Действия приложения")
    };
    s.fill_rect(
        bounds.x as i32,
        bounds.y as i32,
        bounds.width as u32,
        bounds.height as u32,
        c::SURFACE,
    );
    s.stroke_rect(
        bounds.x as i32,
        bounds.y as i32,
        bounds.width as u32,
        bounds.height as u32,
        c::FOCUS,
    );
    components::title_bar(
        s,
        Area {
            x: bounds.x as i32 + 1,
            y: bounds.y as i32 + 1,
            width: bounds.width - 2,
            height: 26,
        },
        title,
    );
    for (index, label) in entries.iter().enumerate() {
        let rect = if shell.overlay == 4 {
            g::panel_row(index)
        } else {
            g::menu_row(index)
        };
        pda::compact_row(
            s,
            area(rect),
            label,
            shell.overlay_selected as usize == index,
            p,
        );
    }
}
pub(super) fn draw(shell: &Shell, s: &mut Surface<'_>) -> crate::wallpaper::DrawStats {
    let p = palette(shell);
    let stats = if shell.screen == Screen::Desktop {
        let r = g::WORKSPACE;
        crate::wallpaper::draw_region(s, r.x, r.y, r.width, r.height, shell.theme != 0)
    } else {
        s.fill(if shell.theme == 0 {
            c::BACKGROUND
        } else {
            c::SYSTEM
        });
        crate::wallpaper::DrawStats::default()
    };
    match shell.screen {
        Screen::Desktop => desktop(s, shell),
        Screen::Launcher => launcher(s, shell, p),
        Screen::Today => today(s, shell, p),
        Screen::About => about(s, shell, p),
        Screen::Diagnostics => diagnostics(s, shell, p),
        Screen::Settings => settings(s, shell, p),
    }
    title(s, shell);
    if shell.overlay != 0 {
        overlay(s, shell);
    }
    stats
}
