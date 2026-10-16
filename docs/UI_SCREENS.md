# UI screens and implementation status

The implemented surface is the [Design System 0.1](UI_DESIGN_SYSTEM.md) 240×320 diagnostic UI. It has three real view states: list, selected diagnostic preview and menu. It is not a complete desktop or a finished set of PDA applications. The written gray-blue direction was used; an image reference was not supplied for inspection.

## Implemented screens

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
| Home / Today | Compact date/time and only real summaries/notifications; direct keyboard entry to Applications; empty/unavailable sections say so; Menu and Back have stable root behavior | Real time, notification and application-lifetime sources; no appointments, unread counts or phone status are invented; planned |
| Application catalog | Launch only applications that actually exist; preserve list position on return; keyboard filtering/focus remains complete | Application lifetime/navigation model and memory budget; current diagnostic catalog is not a process launcher |
| File Manager | Keyboard list of mounted locations/directories/files; Select enters/opens supported items, Back goes to parent, Menu offers only implemented actions; preserve path/selection on return; bounded path/name buffers | Storage/filesystem drivers, path validation, safe error reporting and persistence; begin read-only; rename/delete require explicit confirmation and tested write/recovery paths; planned |
| Terminal | Fixed-cell text view with command line, bounded scrollback, wrapping, Backspace and keyboard scroll; nominal content x `[6,230)`, y `[44,296)` fits37 columns ×18 lines at the existing6-pixel advance/14-pixel line height | Owned kernel command interpreter and explicit buffer/output limits, UTF-8 scalar handling and unsupported-character fallback; no host shell, Linux/POSIX runtime or fabricated command output; planned |
| Contacts | Browse/search, view details, edit bounded fields, confirm destructive changes; disclose save success only after storage commits | Owned data model, persistence/recovery, text editing; no ROM/user contacts are bundled |
| Phone | Dial, incoming call, answer/reject, active-call and ended/error states; clear softkey meanings; keyboard access to each action | Proven modem protocol, audio routing, power policy and separate hardware authorization; a GSM test model must be identified as simulated |
| SMS | Message list, detail, bounded compose, explicit pending/sent/failed states and retry; never equate queued UI work with network delivery | Modem SMS contract, encoding/length policy and persistent queue; no test message may reach a real network implicitly |
| Settings | Input language/layout, display and time settings with Back/cancel/apply semantics | Proven capabilities and validation; no unverified power/charging register writes behind a UI toggle |
| Date/time | 24-hour `HH:MM`, date `DD.MM.YYYY`, explicit unset/error state, keyboard-editable fields | Trusted RTC/time source, timezone policy, calendar validation and width/refresh tests; currently no clock widget |
| Diagnostics | Show measured version/device/test facts and explicit unknowns; controlled export of logs | Proven sources, privacy filtering and owner-approved hardware observations; diagnostic preview labels alone are not drivers |
| Power/sleep | Show actual state, reliable resume and clear failure reporting | Tested hardware power/interrupt/wake contracts; no simulated battery indicator is shipped |

The Settings hierarchy is fully specified below as **planned**. None of these sections is an implemented settings screen or permission to access physical hardware. Every section must show unsupported capabilities explicitly, preserve keyboard focus/Back navigation, and distinguish pending changes, applied changes and backend errors.

| Settings section | Required controls/data | Required backend evidence |
| --- | --- | --- |
| Display | Brightness/backlight, timeout and supported orientation; current theme/font information; preview/revert for a reversible visual change | Verified LCD/backlight/orientation contracts; current bitmap font has no scaling implementation |
| Sound | Speaker/headset volume, mute, notification/ringtone selection and actual routing state | Audio/codec/amplifier and modem routing contracts; no audible preview or successful routing state without a working backend |
| Input | Active layout, Shift/Fn policy, repeat configuration and a separate stylus calibration flow | Proven scan/layout/modifier mapping, measured repeat policy, calibration and cancel/reset recovery |
| Network | GSM registration/data state, supported Wi-Fi scan/connect actions and an explicit radio-disable mode | Real modem/Wi-Fi protocol, credential handling and confirmed state changes; no simulated network connection shown as real |
| Bluetooth | Power/discovery, visible devices, pairing requests and paired-device management | Bluetooth transport/stack and secure pairing/data storage; discovery does not run implicitly |
| Power | Display/system sleep timeout, wake policy, measured battery/charging status and clear unavailable states | Verified power/wake/measurement contracts; no speculative charging-voltage or power-register controls |
| Information | Crosshair build/version, verified board facts, available memory/storage summaries, third-party licenses and diagnostic export | Proven sources and privacy filtering; serial/IMEI/SIM/user data are not displayed/exported automatically |

Date/time belongs to a separate validated Settings flow: `HH:MM` and `DD.MM.YYYY`, explicit unset state, timezone policy, cancel/apply and calendar validation. The current font-label fixture proves those strings fit, not that the clock/settings backend exists. Home/Today, File Manager and Terminal must remain useful through the hardware QWERTY and the future semantic softkey contract; touch cannot be their only route to an action.

All future screens retain hardware-QWERTY operation, visible focus and the same Back/Menu conventions unless a documented application requirement justifies a specific exception. Stylus is an additional path after calibration, not a replacement for keyboard reachability. Their storage, editing, modem and power failures must be represented as real state transitions; no static success page substitutes for a backend.

## Evidence and remaining limits

The shared fixtures contain 37 canonical and 27 independent boundary events, producing twelve and eight selected raw565/PNG captures. Paths and schemas are specified in [UI_NAVIGATION.md](UI_NAVIGATION.md). `scripts/test-ui.sh` checks the entire unchanged canonical state trace, both capture manifests, raw hashes/dimensions, 24 host tests, the 20000 existing stress operations and actual ARM object layout/code attributes. The role/geometry/date-time label additions preserve all twenty capture bytes and the themed golden. The changed themed Apps golden is intentional; the primitive/font baseline remains unchanged.

Host captures prove actual software rendering at the specified dimensions. The separate [Wave004 integration](../reports/WAVE_004.md) now verifies real ARM execution, synthetic input burst/overflow/reset and all twenty canonical/boundary captures byte for byte, plus three burst checkpoints. No physical ATI W3200 screen, TSC2200 touch panel or sliding QWERTY has been exercised. The next integration boundary is proven hardware metadata and a separately specified real display/input backend.
