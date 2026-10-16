# UI screens and implementation status

Crosshair now has two separate users of the same [Design System 0.1](UI_DESIGN_SYSTEM.md) 240×320 renderer: the preserved Wave004 diagnostic AppsScreen and the functional User Mode Shell, refined in Wave007.1 and Wave007.2. The original Wave004 work followed the written gray-blue direction; the [image approved on 16.10.2026](UI_DESIGN_SYSTEM.md#approved-visual-reference-for-crosshair-shell-01) supplies the Shell's artistic direction. Physical display/input remain unverified.

## Current adaptive Shell0.1.2 views

The [Shell state machine](../shell/src/lib.rs) and [composition](../shell/src/render.rs) are `no_std`, bounded and independent of the privileged kernel. The separately linked [User adapter](../src/shell_user.rs) obtains input/metrics and presents one framebuffer through checked SVC services. [Architecture](SHELL_ARCHITECTURE.md), [navigation and host keys](SHELL_NAVIGATION.md), and [Wave007 execution evidence](../reports/WAVE_007.md) distinguish source-confirmed behavior from actual test results.

| View | Functional content and interaction | State / current limit |
| --- | --- | --- |
| Desktop | Static wallpaper workspace through y320; one24px top/system bar, one Start, three small functional shortcuts (Today, Settings, Diagnostics); panel icon opens temporary system controls | Shared keyboard/tap focus persists across screen visits; the free workspace has no hidden actions; the complete catalog stays in Launcher |
| Today | Dense key-value observations for actual task/input/reserved-RAM state; small section icons, concise unavailable-source line and inline Launcher/Diagnostics actions | Separate view from Desktop; no invented appointments, notification counts or hardware status |
| Launcher | Four implemented built-in screens; visible 16-scalar case-insensitive Latin/Cyrillic prefix query, selection, context menu and Select | Backspace erases; Back first clears query; empty results cannot launch a hidden entry; selection/query survive ordinary app visits |
| About | Shared16px key-value/section rows for actual supplied build, architecture, licences and capability limits; bounded scrolling | Standard/Compact/Immersive demonstrations remain this same built-in; keyboard/panel/top Back restore caller |
| Diagnostics | Kernel snapshot of ticks, context switches, task states, mapped working-RAM reservation and input counters; actual local UI event/frame counts | Only valid supplied groups show numbers; bounded scrolling and mode demonstration; reserved RAM is not free/instantaneously used memory |
| Settings | Cold gray and night blue themes, actual in-memory toggle, reset confirmation with cancel | Theme affects real rendering and lasts until reboot; persistence and device/power settings absent |
| System / Launcher menu / temporary panel | Reachable actual commands; own bounded overlay selection; mode entries only for About/Diagnostics | Modal keyboard/pointer actions; closing restores focus/history/query/mode; no mandatory footer |
| Reset dialog | Explicit Reset/Cancel buttons with keyboard selection and modal tap handling | Only the volatile theme changes; no storage or physical operation |

These built-ins currently share one Shell process and its saved UI state. They are functional screen applications, not separately loaded tasks or packages. A separate uncooperative User Busy workload exercises the scheduler concurrently. No Files/Phone/SMS/network placeholder is offered as an installed working application. [Tabler Icons](UI_ASSET_SYSTEM.md) supplies the primary system-icon subset, preserving its MIT notice and following the approved reference without embedding that image as the UI. The experimental Mac viewer displays actual guest frames and forwards logical keyboard/tap events; it does not implement the state machine on the host.

## Preserved Wave004 diagnostic screens

| View | Contents and geometry | Actions and state effect | Status |
| --- | --- | --- | --- |
| «Приложения» | Static system/test strip, app header, one-line search, eight rows, real scrollbar when needed, selected/total and bottom actions | Up/Down select/scroll among sixteen diagnostic entries; text filters; Select opens a preview; Menu opens menu | Implemented; host tests/captures and actual Wave004 ARM execution |
| Empty filtered list | Same shell, filter text, focus rectangle around «Нет совпадений», counter 0/0 | Select has no effect; erase or Back changes the filter; softkeys/menu remain reachable | Implemented; boundary fixture/captures |
| «Проверка» | Selected entry name at y58, test caption at y80, actual text/color/geometry preview from `(12,106)`, Back hint, bottom actions | Increments invocation counter on entry; Back returns to the preserved list; Menu remains available | Implemented; canonical fixture/captures |
| «Меню» | Same compact strip/header; three rows from y58, pitch30; «Выбрать» / «Закрыть» | Clear/reset filter, return to list, or restore previous view | Implemented; canonical and boundary fixtures/captures |

The catalog remains the same sixteen entries: Текст, Цвета, Рамки, Линии, Кириллица, Обрезка, Фокус, События, Список, Прокрутка, Клавиши, Возврат, Кнопки, Выделение, Символы, Прямоугольники. These labels identify **diagnostic test selections**. A preview chooses one of three small drawing exercises by item ID, and displays the selected name. «Клавиши» is not a completed physical keyboard diagnostic, and «Возврат» is a selectable preview rather than an extra root-navigation command. The real Back navigation is defined by the logical event/softkey contract.

There are no invented contacts, fake SMS, synthetic successful calls, battery percentages or radio-strength indicators in these screens. The system strip's «Тест» label makes the current mode explicit. The [host example](../ui/examples/apps.rs) is a reproducible fixture driven by shared inputs; all drawing comes from the same library as an ARM caller.

## Planned application specifications

These rows define future scope and acceptance requirements. They are not additional implemented views, classes or empty modules.

| Planned screen | Required behavior and data boundary | Prerequisite / proof needed |
| --- | --- | --- |
| Home / Today extensions | Add real date/time and notifications to the implemented Shell Today without changing root navigation | Trusted time/notification sources and application lifetime remain future work; the current explicit unavailable sections are functional |
| Dynamic application catalog | Extend the implemented four-entry built-in Launcher to independently owned applications/packages | Loader/lifetime/authority/persistence contracts; the preserved Wave004 diagnostic catalog is a different test screen |
| File Manager | Keyboard list of mounted locations/directories/files; Select enters/opens supported items, Back goes to parent, Menu offers only implemented actions; preserve path/selection on return; bounded path/name buffers | Storage/filesystem drivers, path validation, safe error reporting and persistence; begin read-only; rename/delete require explicit confirmation and tested write/recovery paths; planned |
| Terminal | Fixed-cell text view with command line, bounded scrollback, wrapping, Backspace and keyboard scroll; nominal content x `[6,230)`, y `[44,296)` fits37 columns ×18 lines at the existing6-pixel advance/14-pixel line height | Owned kernel command interpreter and explicit buffer/output limits, UTF-8 scalar handling and unsupported-character fallback; no host shell, Linux/POSIX runtime or fabricated command output; planned |
| Contacts | Browse/search, view details, edit bounded fields, confirm destructive changes; disclose save success only after storage commits | Owned data model, persistence/recovery, text editing; no ROM/user contacts are bundled |
| Phone | Dial, incoming call, answer/reject, active-call and ended/error states; clear context/system-panel commands; keyboard access to each action | Proven modem protocol, audio routing, power policy and separate hardware authorization; a GSM test model must be identified as simulated |
| SMS | Message list, detail, bounded compose, explicit pending/sent/failed states and retry; never equate queued UI work with network delivery | Modem SMS contract, encoding/length policy and persistent queue; no test message may reach a real network implicitly |
| Settings extensions | Input language/layout, display and time settings with Back/cancel/apply semantics; preserve the implemented volatile theme toggle/reset | Proven capabilities and validation; no unverified power/charging register writes behind a UI toggle |
| Date/time | 24-hour `HH:MM`, date `DD.MM.YYYY`, explicit unset/error state, keyboard-editable fields | Trusted RTC/time source, timezone policy, calendar validation and width/refresh tests; currently no clock widget |
| Diagnostics extensions | Add verified device facts and controlled export to the implemented kernel/UI-counter snapshot | Proven hardware sources, privacy filtering and owner-approved observations; current counters are synthetic-session measurements, not physical drivers |
| Power/sleep | Show actual state, reliable resume and clear failure reporting | Tested hardware power/interrupt/wake contracts; no simulated battery indicator is shipped |

The Settings hierarchy below remains **planned** beyond the implemented Shell theme selection/reset. These hardware/backend sections do not follow automatically from the theme screen and do not authorize physical access. Every section must show unsupported capabilities explicitly, preserve keyboard focus/Back navigation, and distinguish pending changes, applied changes and backend errors.

| Settings section | Required controls/data | Required backend evidence |
| --- | --- | --- |
| Display | Brightness/backlight, timeout and supported orientation; current theme/font information; preview/revert for a reversible visual change | Verified LCD/backlight/orientation contracts; current bitmap font has no scaling implementation |
| Sound | Speaker/headset volume, mute, notification/ringtone selection and actual routing state | Audio/codec/amplifier and modem routing contracts; no audible preview or successful routing state without a working backend |
| Input | Active layout, Shift/Fn policy, repeat configuration and a separate stylus calibration flow | Proven scan/layout/modifier mapping, measured repeat policy, calibration and cancel/reset recovery |
| Network | GSM registration/data state, supported Wi-Fi scan/connect actions and an explicit radio-disable mode | Real modem/Wi-Fi protocol, credential handling and confirmed state changes; no simulated network connection shown as real |
| Bluetooth | Power/discovery, visible devices, pairing requests and paired-device management | Bluetooth transport/stack and secure pairing/data storage; discovery does not run implicitly |
| Power | Display/system sleep timeout, wake policy, measured battery/charging status and clear unavailable states | Verified power/wake/measurement contracts; no speculative charging-voltage or power-register controls |
| Information | Crosshair build/version, verified board facts, available memory/storage summaries, third-party licenses and diagnostic export | Proven sources and privacy filtering; serial/IMEI/SIM/user data are not displayed/exported automatically |

Date/time belongs to a separate validated Settings flow: `HH:MM` and `DD.MM.YYYY`, explicit unset state, timezone policy, cancel/apply and calendar validation. The current font-label fixture proves those strings fit, not that the clock/settings backend exists. Home/Today, File Manager and Terminal must remain useful through the hardware QWERTY and reserved semantic commands and the temporary system panel; touch cannot be their only route to an action.

All future screens retain hardware-QWERTY operation, visible focus and the same Back/Menu conventions unless a documented application requirement justifies a specific exception. Stylus is an additional path after calibration, not a replacement for keyboard reachability. Their storage, editing, modem and power failures must be represented as real state transitions; no static success page substitutes for a backend.

## Preserved Wave004 evidence and remaining hardware limits

The shared fixtures contain 37 canonical and 27 independent boundary events, producing twelve and eight selected raw565/PNG captures. Paths and schemas are specified in [UI_NAVIGATION.md](UI_NAVIGATION.md). `scripts/test-ui.sh` checks the entire unchanged canonical state trace, both capture manifests, raw hashes/dimensions, 24 host tests, the 20000 existing stress operations and actual ARM object layout/code attributes. The role/geometry/date-time label additions preserve all twenty capture bytes and the themed golden. The changed themed Apps golden is intentional; the primitive/font baseline remains unchanged.

Host captures prove actual software rendering at the specified dimensions. The separate [Wave004 integration](../reports/WAVE_004.md) now verifies real ARM execution, synthetic input burst/overflow/reset and all twenty canonical/boundary captures byte for byte, plus three burst checkpoints. No physical ATI W3200 screen, TSC2200 touch panel or sliding QWERTY has been exercised. The next integration boundary is proven hardware metadata and a separately specified real display/input backend.

Wave007 keeps those fixtures unchanged and adds its own [host state/render tests](../shell/src/tests.rs), [frame replay exporter](../shell/examples/export.rs) and [ARM oracle](../tools/smoke_shell.py). Shell keyframes and actual kernel snapshots are compared through the same renderer; exact counts/hashes/allocations belong to [Wave007](../reports/WAVE_007.md). A host screenshot or the approved concept alone is not evidence of a User session or hardware operation.

## Historical Wave007.1 presentation refinement

The six large Wave007 Desktop tiles remain visible in that wave's historical report. Accepted [Wave007.1](../reports/WAVE_007_1.md) replaced them with a wallpaper workspace and compact shortcuts; [shared rectangles](../shell/src/geometry.rs) define both the graphics and logical tap targets. Today remains a separate information screen using only supplied kernel observations and explicit unavailable services. All tap actions retain a keyboard path, including Start, application Back, menus, theme and confirmation.

In that accepted wave, static wallpaper decoding wrote directly into the sole borrowed RGB565 framebuffer. No runtime PNG/SVG decoder, additional full framebuffer, clock/radio fiction or new application/backend is introduced. Full Desktop entry/theme changes compose the workspace. Focus movement restores only old/new shortcut rectangles; opening or moving within Desktop's menu does not decode the wallpaper, and dismissal restores a bounded covered region. [Architecture and cost observations](SHELL_ARCHITECTURE.md#rendering-and-adaptive-input) distinguish this software work from the full-frame Present service. Physical stylus calibration and display operation remain untested.

## Wave007.2 hardware-first refinement

[Adaptive Shell](ADAPTIVE_SHELL.md) removes the permanent footer and duplicate Start. Standard/Compact/Immersive content rectangles extend to y320, with24/16/0 reserved top pixels. About/Diagnostics demonstrate all modes through a temporary Shell panel. Immersive retains a small visible recovery affordance plus top-edge pull, trusted hold and keyboard system commands. These are the same built-ins, not new reader/music/calculator apps.

[Shared dense components](../ui/src/pda.rs) serve Today/About/Diagnostics/Launcher/menus: text, headings, key-value rows, compact lists, inline actions and bounded scrolling. Current Shell host tests cover phased capture/release/leave/cancel, trusted stationary hold, key Press/Repeat/Release, invalid/source loss and pixel-equivalent partial redraw. Actual ARM/QEMU acceptance is a separate final-run claim. Existing Wave004 diagnostic pixels, font and old reports remain preserved.
