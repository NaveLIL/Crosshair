# UI 0.2: components, logical input and a scrollable test screen

This describes the accepted Wave003 baseline. Wave004 preserves its state/input API and adds central theme/geometry plus actual ARM guest execution: [Design System0.1](UI_DESIGN_SYSTEM.md), [integration proof](../reports/WAVE_004.md). The historical Apps golden below is deliberately superseded by that design change; primitive/font evidence remains unchanged.

Implemented and host-tested in Wave 003. The dependency-free [UI crate](../ui/Cargo.toml) remains `no_std` and `forbid(unsafe_code)`. The existing [UI 0.1](UI_0.1.md) drawing/dirty/present contract, all eleven earlier tests, font bytes, upstream MIT notice and original pixel golden remain unchanged. The renderer is compiled for ARMv5TE; this screen has not executed on the physical PDA or an emulated LCD.

## Components and application state

One [module](../ui/src/components.rs) adds `Area`, `selection`, `list_row`, `button`, `title_bar` and `bottom_softkeys`. Labels truncate by glyph ink width, including Cozette's two-pixel overhang, and stay inside component bounds. The selected row retains its background when focus moves to a softkey; a two-pixel border marks the current keyboard focus. Empty filtered results also retain a visible focus border. All drawing uses the caller's existing, exclusively borrowed RGB565 `Surface`.

`AppsScreen::new()`, `handle(Event) -> bool` and `render(&mut Surface)` provide a functional **«Приложения» test catalog**: sixteen static diagnostic entries, eight visible rows, clamped selection and scrolling that keeps selection visible. `Select` opens a real `View::Action(item)` state with that entry's name and a text/color/geometry preview; its invocation counter increments. These are diagnostic previews, not implemented phone/contact applications. Rendering uses the fixed 240×320 layout. A smaller validated surface safely clips it, but does not reflow it.

`handle` returns whether state changed; the caller chooses when to render and present. A state change currently repaints the full frame, so a full dirty region is expected. There is no retained scene tree, second framebuffer, allocator, hidden clock, input polling or display driver. `Surface::present` still clears dirty regions only after every transfer succeeds.

## Keyboard and text semantics

`Event` is `Up`, `Down`, `Left`, `Right`, `Select`, `Back`, `Menu` or `TextInput(char)`.

| Input | Behavior |
| --- | --- |
| Up / Down | Move one list/menu row without wrapping. From a softkey, first return focus to the list. In a preview, focus the visible «Назад» softkey. |
| Left / Right | Focus the left/right bottom softkey. Select then invokes its displayed action. |
| Select | Open the selected diagnostic preview, activate a menu entry or invoke the focused softkey. Empty results do not open anything. |
| Back | Preview → preserved list selection/scroll; menu → previous view. In the list, clear the filter and reset selection/scroll. At the root with no filter, reset focus/selection; there is no operating-system exit. |
| Menu | Open the menu from list/preview; close it when already open. The menu offers «Очистить фильтр», «К списку», «Закрыть меню». |
| TextInput | In the list only, append a permitted Unicode scalar to a sixteen-character inline buffer. Accept Russian letters including Ё/ё, ASCII letters/digits, space and hyphen. U+0008 erases one scalar. Unsupported characters and excess input are ignored. |

Filtering performs a case-insensitive substring match over the catalog, with explicit ASCII/Russian case conversion. Ё equals ё; it is not silently changed to е. Changing text resets selection/scroll and returns focus to the results. No UTF-8 character is split. The bounded filter is a search field, not a general text editor or keyboard-layout driver.

`InputQueue` is an eight-event FIFO. `push` returns `Err(original_event)` when full, preserving queued events and their order; the producer must retry or apply an explicit upstream policy. `pop` returns `None` when empty. The host test adapter feeds exactly these events. Interrupt synchronization, physical key codes, key release/debounce/repeat, Fn/layout mapping and calibrated stylus-to-action conversion remain outside this library; no unsupported physical driver is claimed. A future adapter must serialize queue access and must not treat a successful queue push as completed display presentation.

## Verified memory budget

The [compile-only layout probe](../ui/tools/layout_probe.rs) is compiled separately for the host and `armv5te-none-eabi`. The script reads actual read-only section bytes from both objects with LLVM; it does not infer target layout from host `usize`. Cargo's machine-readable artifacts select the exact built ARM `core`, even when other BSP builds have populated the cache.

| Object | x86_64 Darwin host bytes | ARMv5TE bytes |
| --- | ---: | ---: |
| Existing Surface handle, including eight dirty rectangles | 112 | 88 |
| AppsScreen, including sixteen `char` filter slots | 76 | 76 |
| InputQueue, including eight event slots | 36 | 36 |
| Event | 4 | 4 |
| Area | 12 | 12 |
| New state + queue versus UI 0.1 | **112** | **112** |
| Borrowed full framebuffer, unchanged | **153600** | **153600** |

Both measured `AppsScreen` alignments are four bytes. The new persistent state contains no pixels. Read-only catalog/font/code are separate from this writable state budget. These are compiler object-layout measurements, not a peak-stack measurement: `handle` temporarily copies the 76-byte state to report changes, and rendering uses bounded local values. The kernel must continue supplying framebuffer RAM/BSS or strips rather than a 153600-byte stack array. Host examples allocate their one framebuffer and trace strings with `std`; that host harness allocation is not a library requirement.

## Reproduction and reviewed evidence

```sh
RUSTUP_HOME="$PWD/local/toolchains/rustup" scripts/test-ui.sh
```

The existing neutral-directory host Cargo invocation remains in place. The script now derives the actual test count from successful test summaries and verifies the compiled ARM code objects as ARMv5TE/EABI5 without hard-float. **19 host tests pass:** the eleven unchanged primitive tests plus eight component/state/queue/golden/property tests.

Two fixed-seed tests perform 10000 operations each. Event testing covers every logical event kind, all views and all focus states, verifies filter/selection/scroll bounds after every event, and compares immediate handling with batched FIFO replay. Drawing testing varies signed/extreme coordinates and component bounds, checks outer sentinels and every stride-padding word, and requires every changed pixel to be covered by a valid dirty rectangle after every operation. It injects failed presentation and checks dirty retention before successful clear. Seeds are in [the tests](../ui/tests/components.rs); a failing assertion includes the replay step where relevant. This is deterministic stress coverage, not proof for every input sequence.

The [host fixture](../ui/examples/apps.rs) writes a machine-readable 37-event JSON trace, traverses preview/menu/filter/softkey/back actions and ends on item 11 «Возврат», scroll 4, three preview invocations. The final 240×320 PNG was visually inspected: eight rows, selected/focused row, position 12/16 and two reachable softkeys. The UI 0.2 raw565 FNV-1a golden is `10739668449275078947`. The unchanged UI 0.1 golden remains `5431880093368634183`.

Generated files stay ignored under `target/artifacts/ui/`: `ui02apps.raw565`, `ui02apps.png`, `ui02-input-trace.json`, `memory-layout.json`, `layout-host.o`, `layout-arm.o`, their LLVM text dumps, `validation.json` and the existing UI 0.1 artifacts. ARM objects/probes are inspected on the host, not executed. The pinned font's deterministic regeneration check actually passed; its [MIT license](../ui/third_party/cozette/LICENSE) and [provenance](../ui/third_party/cozette/PROVENANCE.json) are unchanged.

Unknown integration facts remain the ATI W3200 transfer contract, physical input mappings/calibration, interrupt-safe input ownership and measured target rendering/stack timing. The next concrete step is an explicitly bounded display-backend integration that consumes the existing dirty-present callback and the same logical input events, once its hardware/emulator contract is established.
