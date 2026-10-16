# Adaptive Pocket PC Shell — Wave007.2

The current Shell uses one bounded policy for Standard, Compact and Immersive presentation. It shares the existing `Surface`, RGB565, Cozette font, Tabler masks, wallpaper, theme and events; it adds no graphics engine, compositor or application process. Sources: [policy/state](../shell/src/adaptive.rs), [composition](../shell/src/render.rs), [shared hit geometry](../shell/src/geometry.rs), [dense components](../ui/src/pda.rs). This is source-confirmed implementation with27 passing Shell host tests; exact ARM/QEMU results and final memory/code sizes belong to the Wave007.2 execution report. Physical PDA2k display/input remain untested.

## Audit of the accepted presentation

The accepted [Wave007.1 Desktop](../reports/wave007-1/frames/pointer/step-00.png), [Today](../reports/wave007-1/frames/pointer/step-19.png) and [About](../reports/wave007-1/frames/pointer/step-13.png) were inspected at240×320. Their original source/report evidence remains unchanged.

| Observed issue | Consequence | Change / architectural scope |
|---|---|---|
| Desktop has Start at top and bottom; all views reserve a24px footer |5760 pixels repeat commands available elsewhere |One persistent Start; remove compulsory footer; presentation and system-action policy |
| Today paints separate status rectangles and repeats long unavailable descriptions |Small facts consume most of the view; little hierarchy |Dense grouped key-value rows, small section icons, one concise unavailable-source line and inline real actions |
| About allocates38px cards for short pairs |Five facts consume190px before gaps; overflow is not reusable |Shared16px key-value/section rows, bounded row scrolling and real capability/licence facts |
| One fixed chrome policy serves every screen |An information/tool view cannot reclaim space |Per-built-in mode state; demonstrate all modes through existing About/Diagnostics |
| Atomic tap has no capture/release contract |Cannot distinguish cancellation, moving out or held gesture |Bounded capture state plus semantic pointer phases; no physical driver or new kernel authority |

The first three are composition/density problems. Capture, system ownership and adaptive viewport policy are state contracts. The existing renderer, MMU, scheduler and QEMU device model do not need replacement for either category.

## Chrome policy and ownership

All rectangles use guest pixels and half-open bounds. `ChromeMode::content()` is the authoritative viewport; drawing and hit tests consume the same geometry.

| Mode | Persistent bar | Content viewport | Demonstrated use |
|---|---|---|---|
|Standard0|Top24px|`[0,240)×[24,320)`,71040 pixels|Desktop, Today, Launcher, Settings; default About/Diagnostics|
|Compact1|Top16px|`[0,240)×[16,320)`,72960 pixels|Existing About/Diagnostics with compact metadata chrome|
|Immersive2|No reserved bar|`[0,240)×[0,320)`,76800 pixels|Existing About/Diagnostics with full viewport|

There is no persistent bottom softkey bar or bottom hit target. Standard has one top-left Start, a compact panel icon and application Back. Compact retains icon-sized Start plus panel/Back. Immersive has a small visible16×16 top-right system affordance containing a12px menu mask, overlaid on content rather than reserving a full bar. Its content viewport is still240×320. This recovery affordance is explicit; it is not a hidden hotspot or an assertion that every content pixel is free of overlays.

Only About/Diagnostics currently change modes. Their Standard/Compact/Immersive menu entries change actual viewport/chrome on those same built-ins. They are not new calculator/music/reader applications. The Shell owns mode selection, Home, Start, Back, Task Switch and panel routing before app context handling. Mode state and scroll offsets survive ordinary screen visits; Desktop remains Standard. A mode change adds no history entry and clamps the existing scroll offset to the new viewport.

## Temporary panel and recovery

`SystemPanel` opens a bounded modal overlay: Home, Start, Back, next opened view and Close. About/Diagnostics additionally offer Standard, Compact and Immersive. Existing system/context menus remain real overlays; Settings Reset remains a real two-button dialog. Closing an overlay restores underlying focus/history/query/mode. A tap outside a menu dismisses it without falling through; a tap outside dialog buttons performs no action.

Every command has keyboard access. Logical Start/Panel are IDs11/12; legacy direct context actions remain usable without drawn footer buttons. About/Diagnostics `Menu` opens the system panel. Standard/Compact expose a visible panel button; Immersive can recover through its visible corner affordance, a top-edge Press at y<4 followed by a downward Move to y>=12, or a valid held gesture. Home/Start/Back/Task Switch always remain Shell-owned logical commands. These thresholds are the synthetic interaction policy, not measured TSC2200 characteristics.

## Pointer capture and hardware edges

`Action::PointerEvent` has Press, Move, Release and Cancel. Press focuses and captures the enabled hit target without activating it. Release activates once only over the original still-enabled target, after an uncancelled capture. Moving outside that target permanently cancels the pending tap even if the pointer returns. Cancel, a new Press, keyboard navigation or a changed view cannot turn an old Release into activation of a replacement target. A legacy atomic `Pointer{x,y}` tap remains for earlier functional regression adapters.

`PointerHold{millis}` uses a trusted adapter's monotonic duration; the Shell has no invented clock. For an active uncancelled stationary capture of at least 600 ms, Launcher opens its real context menu (the same commands as F2); other views open the Shell panel. Stationary is deliberately strict in guest coordinates: any coordinate-changing Move suppresses hold for that gesture, even after returning. Hold consumes the pending tap; the later Release cannot activate a menu/panel row. Host duration saturates at4095ms. This is an experimental macOS test source, not physical stylus timing/calibration.

`HardwareKey{phase,key}` separates Press, Repeat and Release. IDs are semantic actions0..12, not scan codes. Press invokes once per held key; duplicate Press is ignored. Repeat invokes only already-held directions0..3. Select/system-command repeats do not activate again. Release clears held state and never activates. Printable text remains translated Unicode input; a future physical layout/modifier controller belongs before this boundary. [Hardware-first UX](HARDWARE_FIRST_UX.md) separates historical controls, proposed mappings and unknown signals.

## Shared wire interpretation and failure policy

The QEMU model remains unchanged: tags1..7 carry legacy logical keys; tag8 carries a scalar. Both User adapter and host exporter use `Action::from_wire`, avoiding separate interpretation implementations. These are **emulator-reserved scalar ranges**, deliberately excluded from normal text; they are not all Unicode private-use ranges and are not a permanent general text-input design.

| Tag8 scalar | Logical meaning |
|---|---|
|`0x90000 + (y<<8) + x`|Release|
|`0xB0000 + (y<<8) + x`|Move|
|`0xD0000 + (y<<8) + x`|Press|
|`0xF0000 + (y<<8) + x`|Legacy atomic tap|
|`U+E000..U+E003`|Legacy Home, direct context left/right, Task Switch|
|`U+E004`, `U+E005`|Start, SystemPanel|
|`U+E006`|Pointer Cancel|
|`U+E007`|CancelInput for source failure/capture loss|
|`0xE010 + (edge<<4) + key`|Hardware edge0Press/1Repeat/2Release; key0..12|
|`0xE100 + millis`|Trusted held duration0..4095ms|

Coordinate blocks are0x20000 scalars each, with `x<240`, `y<320`; base and packed coordinates are **added**, then ORed with tag8. Invalid reserved words become `CancelInput`, never query text or an activation. A valid pointer/key phase counts as one UI event, including ignored repeat/release; `CancelInput` clears capture/held state without increasing the UI event count. Actual kernel delivered-wire counters remain a separate observation.

`Shell::update_runtime` centrally cancels input when a previously valid input group becomes unavailable, or when a valid supplied overflow counter changes. Invalid-group counters are not trusted. Guest and host oracle share this policy. Source failure/resign also sends CancelInput. A lost Release can leave capture pending until cancellation/new Press/keyboard action; it does not block the task, run a timer loop or remove the independent Home/Panel recovery paths. The implementation does not claim automatic guest-side hold timeouts, guaranteed delivery at arbitrary rates, or that a future queued Press cannot establish a fresh capture after loss.

## Dense shared content and observations

`ui::pda` provides bounded text, section headings, independent clipped key/value cells, compact rows, inline actions and `Scroll::clamp/reveal`. Ordinary rows are transparent; the parent paints the content canvas. Focus/selection paint only where needed. Today groups actual kernel task/input/reservation observations, clearly labels reserved RAM, and gives a short unavailable-source summary. About uses actual build/licence/capability facts. Diagnostics displays actual observations and their limits. Their information rows scroll through real overflow; no filler calendar, appointments, messages or battery bars are fabricated.

The existing64B Snapshot/48B RuntimeInfo/32B RenderStats remain separate. `UxSnapshot` is a new versioned80B observation with20 u32 words: version, chrome mode, content y/height, overlay, pointer active/target/cancelled, scroll offset/max, gesture serial, explicit keyboard/target command attempts, cancelled/cleared pointer captures, last pointer phase, panel invocations, mode changes, held key bits, last key phase/id and dispatched hardware-key commands. Attempt counters do not assert a visible effect: navigation can clamp and an informational Select can do nothing. Hold/top-edge panel recovery is counted by panel invocations; clearing only held keys is observable in held bits rather than adding a pointer-cancel count. It exports no pointer, authority or timing guarantee. Private capture/history/query state remains bounded within Shell.

Desktop still decodes wallpaper only for required regions: full entry covers y24..320; focus/pressed changes restore old/new shortcut rectangles; menus/panels draw over the existing background and dismissal restores a bounded covered union. Other views fully compose on relevant changes. `RenderStats` describes actual software decode/write/dirty work. Present still publishes one complete153600B frame after a successful render; partial composition does not reduce that transfer or establish cycle/FPS/display-latency performance. One caller-owned RGB565 framebuffer remains the only guest pixel allocation. Observation journals and Shell state are accounted separately from it and from read-only image/mask/code bytes.

## Future app and input contracts

These are interface recommendations, not installed applications or empty implementation modules.

| Future application | Recommended mode | Content and controls |
|---|---|---|
|Crosshair Music|Compact controls; optional Immersive content|Real playback state; hardware transport/context commands, Shell panel recovery; no invented player state|
|Engineering Calculator|Compact|Keyboard expression input, D-pad history, Select evaluate, stylus cells; system keys reserved|
|Notes|Compact|Shared text focus/commit/cancel, bounded selection and context actions; persistence prerequisite|
|File Manager|Standard|Dense directories, D-pad selection/Back, explicit file operations and stylus context; storage prerequisite|
|Terminal|Compact|Shared keyboard input, bounded scrollback and pointer scroll; no host-shell authority|
|Reader|Immersive|Content/page navigation, persistent reading position when storage exists, visible panel recovery|
|Clipboard History|Standard or Compact|At most ten broker-owned records; explicit select/paste/delete with origin/availability and bounded payload policy|

Future text input should identify the active application/view/editor generation, layout and composition/commit/cancel state. A focus replacement cancels pending input rather than delivering it into a new field. Applications request context actions; they cannot intercept reserved system actions or choose raw physical scan codes. The high scalar carrier used by today's synthetic adapter must be replaced or separately versioned before unrestricted Unicode text routing.

A future Clipboard Broker owns ten bounded entries and exposes opaque IDs plus explicitly supported types/length limits, availability and copy/paste error states. Clipboard selection is explicit, lifetime/permission checks precede delivery, and replacing focus invalidates a pending paste. Payload caps, persistence/privacy/authority and storage failure policy require a later concrete design. No broker, ten-entry clipboard data, general editor or new application is implemented in this wave.

## Validation boundaries

The27 Shell host tests preserve functional navigation/search/theme/history/queue/dirty tests and add viewport/panel/recovery, capture/leave/cancel/stale-release,600ms hold/stationarity, held-key repeat/system ownership, shared wire bounds, runtime loss and partial-vs-full pixel tests. Original UI primitive/font/diagnostic golden behavior remains separately tested. [Replay exporter](../shell/examples/export.rs) accepts actual raw wires and captured metrics, then exports Snapshot, UX20, RenderStats8 and native240×320 PNG/raw565 from the shared code. Host fixtures are not ARM execution proof. Actual kernel equality, Busy progress, frame guards, delivery/overflow/reset tests and guest/host/QEMU parity must be evidenced by the final run before claiming completion.
