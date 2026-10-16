# Shell navigation and hardware-first input

Crosshair Shell0.1.2 (Wave007.2) starts on Desktop, with separate Today/Launcher and the existing four built-ins. [Adaptive Shell](ADAPTIVE_SHELL.md) defines viewport, pointer, held-key and recovery policy; [state](../shell/src/lib.rs), [capture](../shell/src/adaptive.rs) and [shared rectangles](../shell/src/geometry.rs) are authoritative. Earlier [Wave007](../reports/WAVE_007.md) and [Wave007.1](../reports/WAVE_007_1.md) captures remain historical evidence. Physical PDA keys/stylus remain unverified.

## Views and state

| View | Real content / commands | Retained state |
|---|---|---|
|Desktop|Mountain wallpaper through the bottom of the screen; Today/Settings/Diagnostics shortcuts; one top Start; visible panel icon|Selected shortcut survives visits/Home|
|Today|Dense grouped task/input/reserved-RAM observations, small section icons, concise unavailable sources and Launcher/Diagnostics inline actions|Selected action|
|Launcher|About, Diagnostics, Settings, Today;16-scalar Latin/Cyrillic prefix query; only matching entries open|Query/selection survive visits; Backspace erases, Back first clears query|
|About|Actual version/build/architecture/environment/licences and capability limits in shared key-value rows|Bounded scroll; per-view Standard/Compact/Immersive mode|
|Diagnostics|Actual kernel/UI observations and explicit measurement limits|Bounded scroll; per-view mode|
|Settings|Two volatile themes and reset confirmation|Selected row/theme; no storage/power write|

These built-ins remain one Shell process; selecting a screen does not load a new task or grant scheduler authority. No Files/Phone/SMS/network placeholder is offered as a working app. Separate Busy User work continues to exercise preemption.

## Semantic commands

| Command | Behavior |
|---|---|
|Directions|Desktop previous/next shortcut, clamped; Launcher matching entries; Today/Settings rows; About/Diagnostics bounded scroll. Open overlays wrap their own entries|
|Select|Invoke selected real target; an empty Launcher/informational row cannot launch a hidden entry|
|Back|Close overlay; otherwise clear nonempty Launcher query; otherwise restore history or Desktop|
|Home|Return Desktop and clear navigation history; preserve per-view selections/modes/theme|
|Start|Open Launcher from any view through Shell-owned routing|
|SystemPanel|Toggle temporary system panel; preserve underlying state|
|Menu / context right|Close existing overlay, otherwise system/context menu; About/Diagnostics open the adaptive panel|
|Legacy context left|Desktop Start; About/Diagnostics Back; other views invoke current selection; reset dialog chooses Reset|
|Task Switch|Close overlay and cycle previously opened Shell views in fixed ID order|
|TextInput|Launcher query only;16 scalars, `U+0008` erases. Synthetic reserved input carriers are excluded|

There is **no permanent bottom action bar or bottom action hit target**. Context commands remain logical actions; they do not require duplicate on-screen softkeys. Screen history holds8 entries and drops the oldest on a ninth; Home clears it. Per-view focus/query/scroll/mode persist. Menus/dialogs have their own selection, and closing them restores underlying focus.

## Adaptive panels and keyboard paths

Standard reserves top24px, Compact top16px, Immersive no full-width bar; content extends to y320. About/Diagnostics demonstrate mode changes without adding apps. Their panel entries are Home, Start, Back, next view, Standard, Compact, Immersive, Close; other screens show the same actual system commands without unavailable mode entries. From About, SystemPanel→five Down→Select chooses Compact; six Down chooses Immersive; four Down chooses Standard. Modes do not add history entries.

Standard/Compact have visible Start, panel and Back targets. Immersive has a visible16×16 top-right recovery affordance with12px menu icon, plus top-edge pull and trusted hold. Keyboard Home/Start/Back/Panel/Task Switch remain available in every mode. A panel is modal: it never passes a release/tap through to underlying content. Settings Reset/Cancel remain distinct.

## Pointer contract

Press captures/focuses an enabled target without activation. Release invokes once only on the original enabled target after an uncancelled capture. An eligible outside-menu release dismisses the menu without activating content beneath it; outside-dialog release remains inert. Move outside the captured target cancels pending activation permanently for the gesture. Cancel, source loss, new Press or keyboard navigation clear capture; stale Release cannot invoke a newly appearing control. A trusted stationary hold of at least 600 ms opens Launcher's actual context menu, or the Shell panel in other views, and suppresses later tap. Any changed guest coordinate suppresses hold for that capture. These are synthetic interaction rules, not physical TSC2200 timing/calibration.

Legacy atomic tap remains for earlier functional regression callers. The new native adapter emits actual Press/Move/Release/Cancel and monotonic hold observations. Mouse/window coordinates are transformed to guest pixels before transport; Shell itself performs hit testing. Letterbox/outside coordinates do not activate content. No drag-scroll, handwriting, double-tap or physical stylus driver is claimed. Scrollable info views expose separate small up/down content controls as well as keyboard directions.

Desktop shortcuts remain x`[8,80)` at y`[42,100)`, `[108,166)`, `[174,232)`. Standard top Start is x`[0,58)`, panel x`[192,216)`, Back x`[216,240)`; Compact Start shrinks to x`[0,24)`. Immersive recovery is x`[224,240)`, y`[0,16)`; its scroll-up control starts at y20 to avoid overlap. Launcher query is x`[8,232)`, y`[34,56)`; visible matching row i is y`[66+32i,94+32i)`. Today inline links are y`[244,266)` and `[272,294)`. All rectangles are half-open and shared with rendering.

## Native macOS controls

The [viewer](../tools/crosshair_gui.swift) blits actual QMP pixels and forwards input to the [adapter](../tools/run_shell.py); it does not draw controls or perform Shell transitions.

| Host control | Semantic input |
|---|---|
|Arrows|Direction Press/OS repeat/Release|
|Enter / keypad Enter|Select Press/Release; repeats ignored|
|Escape|Back Press/Release|
|F1|Start|
|F10|SystemPanel|
|F2|Context right/menu|
|F3|Task Switch|
|F4 or external Home key|Home|
|Backspace / Delete|Erase query scalar|
|Printable text|Translated Unicode key-down/repeat input|
|Mouse down / move / up|Pointer Press/Move/Release; trusted hold measured monotonically|
|Window resign/capture loss|CancelInput clears held keys/capture|
|Close / Command-Q|End only that viewer/backend emulation session|

Fn may be needed for function keys on media-key keyboards. Fn+Left is not established as a Home shortcut. These are host test mappings, not PDA scan codes. [Hardware-first UX](HARDWARE_FIRST_UX.md) records the separate historical device-control evidence and proposed semantic mapping boundary.

## Shared wire, failure and observations

[Action::from_wire](../shell/src/lib.rs) is shared by User and host replay. Existing tag1..7 legacy keys remain; tag8 encodes ordinary text or explicit emulator-reserved system/phase carriers. Release/Move/Press/legacy tap use scalar bases `90000/B0000/D0000/F0000` plus `(y<<8)+x`, with x<240/y<320. They are not all Unicode private-use ranges. `E004/E005` are Start/Panel, `E006` pointer Cancel, `E007` input-source cancellation, `E010+(edge<<4)+id` key edges and `E100+millis` trusted hold0..4095ms. [Full encoding and limits](ADAPTIVE_SHELL.md#shared-wire-interpretation-and-failure-policy).

Press acts once per held semantic key; only held directions repeat; Release clears held state without activation. Invalid reserved wires cancel pending input rather than becoming text. `Shell::update_runtime` cancels held/capture state on a valid input-group loss or valid overflow-counter change. Transport delivery, UI event count, dispatched key commands and explicit target-command attempts are separate observations; they do not assert a visible effect. Valid phases count as UI events even when repeat/release performs no action; CancelInput is recovery and does not increase UI events.

Model FIFO8/kernel FIFO4 remain bounded and unchanged. New tail input may be dropped when full. The implementation detects known source/queue loss and preserves recovery paths; it does not promise every event is delivered or fabricate a physical interrupt driver. Capture cannot monopolize the CPU: no guest hold-timing loop or mandatory animation is added.

The64B Snapshot keeps its16 words/screen IDs. A separate80B UX observation records mode/viewport/panel/capture/scroll/held-key state and counters;32B RenderStats still distinguishes software composition from full-frame publication. [Host exporter](../shell/examples/export.rs) replays raw wires with actual supplied metrics and writes UX20, Snapshot16, RenderStats8 and native PNG/raw565. Canonical keyboard traces preserve functional intent after deliberate presentation changes; old reports/captures remain unchanged. Actual ARM/reset/burst/fault/preemption/parity results belong to the final execution report.
