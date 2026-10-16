# Shell navigation and input

Crosshair Shell0.1 starts on **Desktop**, with a separate Today view and a four-entry Launcher. Source-confirmed state and actions live in [crosshair-shell](../shell/src/lib.rs); actual ARM captures/transitions belong to [Wave007](../reports/WAVE_007.md). The approved reference supplies the cold gray-blue Pocket PC composition, dark compact bars, icon grid, clear focus and bottom softkeys; it does not supply working clock, modem or battery services.

## Reachable views

| Screen | Real content / action | Preserved state |
|---|---|---|
|Desktop|2-column×3-row grid: Applications, Today, Settings, Diagnostics, About, Switch|Selected tile survives visits to other screens and Home|
|Today|Known runtime summaries and explicit unavailable time/phone/battery state; links to Launcher and Diagnostics|One of two action rows|
|Launcher|About, Diagnostics, Settings and Today; bounded16-character, case-insensitive prefix filter; Select opens only a matching built-in screen|Selection and query survive ordinary screen visits|
|About|Actual build/version strings, ARMv5TE and identified synthetic environment/capability limits|Back returns to caller|
|Diagnostics|Kernel-supplied ticks, switches, task counts, mapped working RAM and input counters, with unavailable states for invalid data groups|Back returns to caller|
|Settings|Two actual color themes; reset-to-default confirmation with cancel|Current theme and settings row; theme lasts until reboot|

Launcher labels identify implemented built-in screens within the Shell task. They do not claim separate application processes, a package registry or a general loader. The independent Busy User workload remains scheduled while Shell visits these views.

## Logical actions

| Action | Behavior |
|---|---|
|Up/Down/Left/Right|Desktop moves within the2×3 grid, clamped at edges; Launcher traverses matching entries; Today/Settings traverse their two rows. An open menu/dialog wraps among its own bounded entries|
|Select|Invokes selected tile/entry/setting/menu item; empty Launcher and informational screens perform no unavailable action|
|Back|Closes overlay first; otherwise clears a nonempty Launcher query before navigating back; otherwise restores previous screen or Desktop|
|Home|Closes overlays, clears screen history and returns to Desktop, preserving per-screen selections and current theme|
|Menu|Opens system menu; in Launcher opens its context menu; closes an already open overlay|
|Softkey Left|Invokes the displayed left action atomically. About/Diagnostics return Back; other screens open/change their selection. In reset confirmation it chooses the displayed Reset action|
|Softkey Right|Opens Menu in a normal view; cancels/closes an overlay|
|SwitchTask|Closes overlay and cycles through previously opened Shell views in fixed screen order|
|TextInput|In Launcher only: appends up to16 Unicode scalars; `U+0008` erases one scalar. Other views ignore text|

Screen history holds8 entries; entering a ninth drops the oldest while retaining the most recent return path. Home clears history. Each screen retains its own selection. A menu stores overlay selection separately, so closing it restores underlying screen focus. Empty search results have a visible search-area focus and cannot activate a hidden entry; Back/erase/menu remain usable. There are no inaccessible Launcher placeholders for Files, Phone, Messages or networking.

The system menu offers Today, Applications, Settings, Diagnostics, About and Switch. Launcher context actions open the selected matching entry (or clear an empty-result filter), return Home, or open About. Settings' second row opens a two-option reset confirmation; Reset sets theme0, Cancel preserves it. No storage write or device/power operation is hidden behind these actions.

## Existing wire protocol

The synthetic model remains unchanged: `wire=(tag<<24)|payload`, tags1..7 are Up, Down, Left, Right, Select, Back, Menu; tag8 carries a Unicode scalar. Shell's adapter reserves `TextInput(U+E000)` for Home, `U+E001` for direct SoftLeft, `U+E002` for direct SoftRight and `U+E003` for SwitchTask. These are integration commands, not PDA scan codes or new model register encodings. The Shell converts each into one action; a direct softkey is never expanded into a potentially interrupted pair of queued navigation events.

The model FIFO8 and kernel FIFO4 have explicit counted overflow; see [architecture](SHELL_ARCHITECTURE.md). Rapid input can drop new tail events when full, while accepted events retain FIFO order. Focus/state validation and subsequent Home/Back remain bounded. This is an honest finite queue rather than a promise that every arbitrarily fast host keypress is delivered.

## Native host controls

The [Mac viewer](../tools/crosshair_gui.swift) displays the running ARM guest's actual QMP frame. It forwards input to the [backend](../tools/run_shell.py), which injects the existing logical FIFO; the host never draws Shell widgets or performs screen transitions itself.

| Host key | Logical action |
|---|---|
|Arrow keys|Up/Down/Left/Right|
|Enter / keypad Enter|Select|
|Escape|Back|
|F10|Menu|
|Home|Home|
|F1 / F2|Direct left/right softkey|
|F3|Switch opened Shell view|
|Backspace / Delete|Erase Launcher scalar|
|Printable text|TextInput Unicode|
|Window close / Command-Q|Quit the viewer/backend's own emulation session|

On a Mac configured to use media/brightness keys, the Fn modifier may be needed to send F1/F2/F3/F10. These host shortcuts are a test adapter, not a claim about the physical PDA2k keyboard. Pointer/stylus events and touch hit testing are not implemented by this keyboard bridge. TSC2200 calibration and actual hardware input remain separate work.

The reproducible acceptance path uses the shared [logical trace](../shell/src/fixtures.rs): Desktop→Launcher→About→Back→Home→Settings→theme change→reset/cancel→Home→Diagnostics→Menu→Today, then opened-view switching and return. Additional queue/invalid-state checks and guest/host pixel comparisons belong to the executed report; a static screenshot alone does not prove these transitions.
