# UI navigation and input contract

This document preserves the Wave004 diagnostic AppsScreen contract and its future physical-input boundary. The current Shell has separate [adaptive navigation](SHELL_NAVIGATION.md) and [implemented capture/key-edge policy](ADAPTIVE_SHELL.md); its phase actions do not change this diagnostic Event enum or historical behavior. [AppsScreen](../ui/src/components.rs) is shared by the host fixture and ARM caller. It owns no device handle, timer, framebuffer or allocator. There are still exactly eight `Event` variants: `Up`, `Down`, `Left`, `Right`, `Select`, `Back`, `Menu`, `TextInput(char)`. No new event or wire encoding is introduced by the design system.

## Implemented keyboard behavior

| Input | List | Diagnostic preview | Menu |
| --- | --- | --- | --- |
| Up / Down | Move one matching item, clamped without wrapping; keep selection visible | Focus the visible left «Назад» action | Move among three entries, clamped |
| Up / Down from a softkey | First return focus to the list without moving selection | Focus «Назад» | First return focus to menu entries |
| Left / Right | Focus the corresponding bottom action | Same | Same |
| Select with list/entry focus | Open selected preview; do nothing for empty results | Not an attainable focus state | Invoke selected menu entry |
| Select with left softkey focus | «Открыть» | «Назад» → list | «Выбрать» → selected menu action |
| Select with right softkey focus | «Меню» | «Меню» | «Закрыть» → previous view |
| Back | Clear filter and reset selection/scroll/focus | Return to preserved list selection/scroll | Return to previous view |
| Menu | Open menu | Open menu | Close menu and restore previous view |

The root list has no OS-exit action. Back at the root resets its list state. A selected row keeps its tinted background when focus moves to a softkey. The active target has a two-pixel border. An empty result set keeps a visible list-focus border and cannot open an application. Opening a preview increments a saturating invocation counter; opening a menu does not. Returning from menu to a preview focuses its left Back action.

The menu offers «Очистить фильтр» (clear and reset list), «К списку» (return to current list state) and «Закрыть меню» (previous view). This is ordinary keyboard navigation, not a pointer-only overlay.

## Future semantic commands and modifier state

`Confirm` means the current `Event::Select`: activate the focused target. Physical Enter/centre-key scan mappings remain unknown. Direct `SoftkeyLeft` and `SoftkeyRight` are specified as **future semantic intents**, invoking the action currently displayed in that softkey independent of previous focus. They are not the current Left/Right navigation events and are not extra implemented `Event` variants.

The future intent boundary may be described as `UiIntent::{Confirm, SoftkeyLeft, SoftkeyRight, SwitchLayout(layout_id)}`; this is a documented contract, not a new Rust interface or wire format. Each direct softkey intent must be one serialized dispatch transaction: resolve the current view/action, establish visible focus and invoke it once, without another event interleaving. An adapter must not expand a physical softkey into queued `Left; Select` or `Right; Select`; an eight-event queue could fill between those events or the view could change. Current manual keyboard navigation remains Left/Right followed by Select. Supporting a direct physical softkey requires an explicit controller/API and transport-version update before mapping hardware to it.

Shift and Fn belong to adapter modifier state, updated by verified make/break events. Shift selects a case/symbol layer; Fn selects a separately defined function layer; neither emits a printable character by itself. A future `SwitchLayout(layout_id)` command changes the active layout (for example Russian/Latin) once as a logical command, and subsequent `TextInput` carries the translated Unicode scalar. It is not text inserted into the filter. The actual chord, scan matrix, Fn latching/hold behavior and persistence policy are unknown until researched. Do not invent a Shift/Fn key combination. Reset clears transient held/modifier state; loss of scan synchronization must cancel pending text/gestures and use a proved resynchronization procedure instead of guessing held keys.

## Text and the bounded queue

Text input applies only to the list's search filter. It stores at most sixteen Unicode scalars in an inline array; Cyrillic does not consume two character slots merely because its UTF-8 representation has two bytes. Accepted text is Russian А–я plus Ё/ё, ASCII letters/digits, space and hyphen. U+0008 erases one scalar. Newline, unsupported characters and the seventeenth character are ignored. There is no general editor, composition engine or heap string.

Matching is a substring search with explicit ASCII/Russian case conversion. Ё matches ё, not е. Editing resets selection/scroll and focuses results. Back at the root and the menu's Clear filter action clear the logical filter length; opening or closing the menu preserves it. Inactive inline slots are not a serialized public state or a secure-erasure guarantee. Compare public accessors and rendered pixels, not raw `memcmp` of Rust structs or their padding.

`InputQueue` holds eight events inline. `push` on full returns the original event in `Err`, leaving all queued events in FIFO order; `pop` on empty returns `None`. A caller must explicitly retry or report upstream overflow. Silent overwrite is not the UI contract. Queue mutation and screen handling currently require serialized ownership; the queue is not an interrupt-safe, atomic or lock-free structure. Repeated key presses are ordinary logical events, not elapsed host time.

## Scan codes, modifiers and stylus: specified boundaries, not implemented drivers

Physical input must first produce a proven hardware scan result. Hardware key IDs, make/break transitions, debounce, repeat timing, Russian layout, Shift/Fn layers and language switching belong to an input adapter before it emits navigation events or a final `TextInput(char)`. The UI must not guess electrical scan codes from glyphs. A release must not accidentally become a second press. A held-key repeat policy must honor bounded backpressure. No particular physical Shift/Fn combination or matrix address is established by this document; the [research plan](RESEARCH_NEXT.md) remains the source for those open tasks.

The hardware QWERTY is a full input path, not a fallback to touch. Every implemented action already has keyboard reachability. A future stylus adapter must verify calibration, orientation, pressure/down/up semantics, coordinate range and display geometry before hit testing. It should resolve a hit into the same action/state transition used by keyboard navigation. The current `Event` API has no coordinate event, so direct row hit selection or focus-by-point requires a separately specified adapter/API change; no hidden stylus driver or fabricated arrow sequence is implemented here. Touch target sizing on real hardware remains unverified.

The future stylus controller has the following required behavior; none is a claim of an implemented physical driver or gesture recognizer:

| Gesture/phase | Trigger, capture and cancellation contract | Keyboard equivalent |
| --- | --- | --- |
| Down | Accept only a calibrated in-range `(x,y)` in `[0,240)×[0,320)`; focus an enabled target and capture its identity plus view generation; show PRESSED feedback; do not activate yet | Move focus with directions |
| Tap/up | Activate exactly once only if the captured target is still enabled, in the same view and released over that target; a row tap selects/focuses it, while Open/Confirm launches it | Directions to select a row; Confirm or displayed softkey to open |
| Hold | On a verified hold gesture, select the captured row and open its context menu once; suppress the later tap; controls without a defined hold action do nothing extra | Select row, then Menu |
| Scroll | Recognized list dragging captures that list and cancels the pending tap; emit bounded logical row-scroll intents, clamp viewport and keep a visible selection, moving selection to the nearest visible edge if needed | Repeated Up/Down moves selection and scrolls when it reaches an edge |
| Leave/cancel | Leaving a button cancels its pending activation; capture loss, invalid coordinate, focus/view replacement, reset or Back clears pressed/capture state and prevents a late up from activating a new target | Back cancels/navigation according to the current view |

ScrollRows, context-menu-for-target and pointer focus intents are planned controller operations, not existing `Event` cases. A hold threshold, movement threshold, pressure cutoff, repeat rate and tap timing must be measured/configured against the proven driver; no electrical range or millisecond/pixel threshold is fabricated here. A disabled target may remain readable but must never capture activation. Modal dialogs must capture focus and cancel older pointer gestures before accepting a new target.

Backpressure applies to semantic actions as well as keys. A future adapter may coalesce uncommitted pointer-move samples to the newest position, but must preserve down/up/cancel order and never overwrite a queued activation. If its queue is full on release, it must clear physical pressed/capture state and retain at most one bounded pending semantic intent with its original target/view generation, then retry or report overflow. A changed generation cancels that pending intent; it must not activate whatever appears later at the same coordinate. This extra pending state needs an explicit memory budget when implemented. The current queue remains the existing serialized eight-event FIFO; these rules do not add hidden allocation or an unimplemented gesture module.

## Shared replay fixtures

[`ui::fixtures`](../ui/src/fixtures.rs) is dependency-free and contains the exact arrays used by both environments. `components::SCENARIO` re-exports the canonical array for compatibility. A state number `n` means after the first `n` events; state 0 is a fresh `AppsScreen::new()`. Input trace `step` remains zero based, so record `step=0` describes state 1.

| Fixture | Events | Captured state numbers | Purpose |
| --- | ---: | --- | --- |
| SCENARIO | 37 | `0,10,11,12,15,17,20,21,24,25,26,37` | Selection, real scrolling, preview, menu, filter, softkey focus and Back |
| BOUNDARY_SCENARIO | 27 | `0,2,3,6,23,24,26,27` | Fresh-state Up, Ё, erase, Й/Ъ/Ь, empty results, sixteen-character capacity and ignored seventeenth character |

The boundary scenario starts fresh; it is not appended to the canonical scenario. Its sequence is Up; Ё; U+0008; Й; Ъ; Ь; Back; sixteen А; one excess А; Back; Menu; Back. State 23 has exactly sixteen А, state 24 is unchanged by excess input, state 26 is Menu, state 27 returns to the initial visible state. All eight event kinds are exercised across both arrays. Burst/overflow transport tests may replay these through a synthetic guest input device; that device is not the physical keyboard protocol.

The [host example](../ui/examples/apps.rs) feeds the same bounded queue and renders with `AppsScreen::render`; it does not duplicate graphics. It writes `target/artifacts/ui/ui02-input-trace.json` and `target/artifacts/ui/design-system/boundary-trace.json`. Both use `crosshair-ui-input-trace-v1`: `events[].step`, `event.kind`, optional `event.text`, `changed`, `view`, `focus`, `selected_item`, `scroll`, `matches`, `filter_len`, `opened`. The unchanged canonical trace SHA-256 is `4eda390806a0b35041730f7448c8bd1ef8dae282ced8a90c616179b40638e2c5`.

`frames.json` and `boundary-frames.json` under the same generated design-system directory use `crosshair-ui-frames-v1`. Each entry records `state`, relative `file`, width 240, height 320, stride 240, byte count 153600, `fnv1a64` as a `0x`-prefixed hex string and public state fields. Files are `step-NN.raw565` or `boundary-step-NN.raw565`, little endian, with PNG previews. Hashing is FNV-1a64 over the raw little-endian bytes. These are host expected frames; a guest must actually render before parity can be claimed. A pixel comparison must check all bytes/coordinates, not only the hash or selected screenshots.
