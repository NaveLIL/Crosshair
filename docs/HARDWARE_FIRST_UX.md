# Hardware-first UX contract

Wave007.2; accepted presentation baseline: [Wave007.1](../reports/WAVE_007_1.md), public commit `4cbb78509ca1188e7ae4bf7703702128184b16f6`. This document separates historical device evidence, Crosshair design policy and future application contracts. No physical PDA2k input driver or device execution is established here.

## Audit of the accepted interface

The actual accepted [Desktop](../reports/wave007-1/frames/pointer/step-00.png), [Today](../reports/wave007-1/frames/pointer/step-19.png) and [About](../reports/wave007-1/frames/pointer/step-13.png) are ARM/QEMU captures, rather than new drawings. Their issues have distinct causes:

| Observation in Wave007.1 | Consequence | Kind of change required |
|---|---|---|
| A 24 px top bar and 24 px bottom bar remain on every view | 48 of 320 rows are permanently reserved, leaving 272 content rows; 15% of vertical space is chrome | A bounded shared chrome policy, while preserving the current Surface |
| Desktop exposes Start in both top-left and bottom-left | Two persistent targets invoke the same Launcher | One persistent Start entry, with hardware/logical and temporary alternatives |
| Today repeats unavailable-service text in separate pale rows and keeps large action rectangles | Little verified information occupies a large area | Dense information rows/sections and concise unavailable values |
| About places short facts in separate large containers | Poor density, weak comparison of names and values | Reusable key-value rows, compact lists and explicit overflow |
| Buttons already have keyboard actions, but permanent lower controls remain mandatory | The screen continues paying for controls even when physical keys can provide them | Reserved system actions plus a temporary, discoverable panel |
| Wave007.1 mouse-down is interpreted as a complete tap | No press/release cancellation, move capture or trustworthy hold classification | A richer logical pointer lifecycle with independent tests |

Palette, mountain wallpaper, font readability and focus contrast are visual matters. Mandatory chrome, event ownership, focus restoration and input cancellation are architectural matters. A different color or static screenshot cannot fix the latter. The original [Surface](../ui/src/lib.rs), bitmap font, clipping, dirty rectangles and single RGB565 framebuffer remain the rendering foundation.

## Historical evidence and rights

**DOCUMENT, not measured on the owner's unit.** The primary authored source is HTC's *PH20B UserMan revised0816*, FCC exhibit 460916, submitted 18 August 2004 and available 27 August 2004. [FCC exhibit metadata](https://fccid.io/NM8BLUEANGEL/User-Manual/CRN-27382-Q1-and-2-revised-user-manual-460916), [original FCC attachment](https://apps.fcc.gov/eas/GetApplicationAttachment.html?id=460916), [PDF mirror](https://fccid.io/NM8BLUEANGEL/User-Manual/CRN-27382-Q1-and-2-revised-user-manual-460916.pdf). The downloaded 154-page PDF was hash-checked against the exhibit catalog: SHA256 `475a2e4e2e46210482f02bf6251ffdbcd827adf08ae5c57d4fec4eb43119240a`. Printed page numbers equal PDF page numbers for the cited pages. Pages 8 and 56 were visually inspected; pages 9 and 150 were checked for device controls. Official FCC retrieval returned 403 in this session; the mirrored bytes matched the published hash.

The manual is manufacturer material with no open-source licence inferred. Its PDF, page renders and complete extracted text remain outside this public tree; this document provides brief factual paraphrases and references. It is the GSM PH20B/Blue Angel filing, rather than the similarly named CDMA PDA2K EVDO manual.

| Confirmed physical control | Historical purpose | Locator / status |
|---|---|---|
| D-pad directions and center Action | Navigate and select | Manual p. 8; DOCUMENT |
| Contacts, Calendar | Dedicated application shortcuts | Manual p. 8; DOCUMENT |
| Start, Messaging, Pocket IE, OK/Close | Front program controls | Manual p. 8 and assignment diagram p. 56; DOCUMENT |
| Send, End | Call handling | Manual p. 8; DOCUMENT |
| Record, Camera, volume up/down | Recording, photography, audio level | Manual p. 8; DOCUMENT |
| Power/backlight; recessed reset | Power/display and reset controls | Manual pp. 8–9; DOCUMENT |
| Sliding QWERTY and stylus | Text and direct pointing | Manual pp. 8–9; DOCUMENT |
| Program-button reassignment and directional repeat settings | User configuration | Manual p. 56; DOCUMENT |

The numbered 1..9 entries on p. 56 are program-assignment identifiers, not scan codes. The ninth illustrated shortcut is on the keyboard. Page 150's summary counts eight program buttons and uses inconsistent abbreviated labels; the labeled diagrams on pp. 8/56 are the stronger locator for individual controls. No electrical identity follows from a picture or application name.

A second primary implementation source is the historical [PXADroid kernel](https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/), fixed commit `3712fd6f197113f19959eba85b3628b202e30d64`. [blueangel.c](https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/arch/arm/mach-pxa/blueangel.c) declares GPIO buttons at lines 159–188, TSC2200 keypad/touch configuration at 843–902 and ASIC keyboard mappings at 905–1021. Its header names i-mate PDA2k among supported Blue Angel models; copyrights credit Marcel Beck and earlier Xanadux/Michael Horne/Philipp Zabel work under GPL version 2. The inspected file SHA256 is `1fe00b4f1335e9a42dd5d6cba1486620535a7e0d273730276afa745d07a88aac`. No GPL driver code is copied into Crosshair's MIT implementation.

| Historical source claim | What it establishes | What remains unknown for Crosshair |
|---|---|---|
| TSC2200 key bitmap separates pad/center, Contacts/Calendar and call controls | A source-backed candidate transport/map | Actual owner-unit responses, IRQ polarity, debounce and scan traces |
| ASIC3 GPIO keys include program/side controls | A different input path from the pad | Board-revision wiring and actual transitions |
| Sliding keyboard uses ASIC SPI and a key table with modifiers | A candidate raw protocol and layout | Complete press/release/Fn behavior, Russian layout and controller recovery |
| Linux names such as `KEY_HOME`, `KEY_BACK`, `KEY_WWW` | That port's logical Linux input assignments | Neither electrical scan codes nor Crosshair system semantics |

GPIO names and table values are historical source evidence, not confirmed measurements or an implemented driver. No GPIO/MMIO probing, reset combination or phone operation was performed. The next hardware step remains separate recorded-input/driver research, following [the existing research boundary](RESEARCH_NEXT.md).

## Four distinct input layers

1. **Physical acquisition:** controller/board identity, raw packet or GPIO transition, press/release, timestamp provenance and device reset. This layer owns debounce and transport errors. Raw signals never become application commands by numeric coincidence.
2. **Semantic system actions:** `Home`, `Start`, `Back`, `TaskSwitch`, `SystemPanel`. Shell resolves these before application context. Their identities do not depend on a scan code, host key number or glyph.
3. **Application context:** navigation, selection, text editing and declared commands for the active view. An application can expose capabilities and an unsaved-change response; it cannot remove the system escape route or acquire power/phone authority.
4. **User bindings:** validated mappings from available logical keys/chords to permitted commands. Changing an application shortcut does not authorize changing protected system routing. A binding update must retain keyboard and pointer access to the five system actions.

The current QEMU FIFO and Mac adapter are test transports. Wave007.2 reserves scalar blocks U+90000..U+EFFFF for atomic Release/Move/Press and retains U+F0000..U+10FFFF for the older Tap carrier. The new blocks are reserved by this emulator convention; they are not Unicode private-use ranges. Small U+E000-series control scalars carry system commands, key edges, Cancel and measured hold duration; these are not physical scan codes. A Mac `NSEvent.keyCode`, an emulator-reserved Unicode scalar carried by tag 8, a Windows program-button number and a historical Linux key symbol are different namespaces. None is published here as a PDA2k scan code. [Navigation](SHELL_NAVIGATION.md) and [adaptive chrome](ADAPTIVE_SHELL.md) describe the actual implemented logical routes separately.

The [Mac adapter](../tools/crosshair_gui.swift) maps F4 (`keyCode` 118) and an external Home key (115) to semantic Home. On a MacBook with media-key behavior, F4 may require Fn+F4. Fn+Left is not a verified Home route in this adapter. These host conveniences do not select a physical Blue Angel binding.

## Reserved actions and proposed physical bindings

**PROPOSAL for a future verified PDA driver**, not an applied remap. The existing assignable program controls permit a mapping that does not depend on detecting a long hold:

| Physical label | Proposed short action | Reservation |
|---|---|---|
| Start | `Start` | Open Launcher/system application entry |
| OK/Close | `Back` | Dismiss overlay, then bounded return; never silently kill a task |
| Contacts | `Home` | Return to Desktop while preserving app state |
| Calendar | `TaskSwitch` | Choose among opened views; future task lifecycle remains separate |
| Pocket IE | `SystemPanel` | Temporary real system/context actions |
| Messaging and keyboard shortcuts | Active-context or user-chosen command | Subject to reserved-action conflict checks |
| Send/End, Power, Camera, Record, volume | Keep dedicated domains | No generic UI reassignment by default |

These candidate assignments trade legacy application labels for explicit system commands and remain user-reviewable. No long press of a call/power/camera/record key is borrowed for navigation. A verified future driver may offer alternative bindings, but Home/Start/Back/TaskSwitch/SystemPanel must remain reachable. A system panel also provides pointer navigation while physical drivers are absent.

`Back` first cancels an active pointer gesture, closes the top modal/panel, then follows the current view's return policy. A view can request an explicit save/discard decision; it cannot consume every Back indefinitely. `Home` is the independent escape to Desktop. Opening/closing a system panel preserves the underlying view, focus, text selection, scroll and bounded navigation history. Home or a task switch cancels any pointer capture; a later release cannot activate a control in another view.

## Key lifecycle and recovery

`Press`, `Release`, `ShortPress`, `LongPress` and `Repeat` are distinct logical concepts. A raw down transition is not a repeat, and repeated down packets do not constitute elapsed time. For a future physical key binding that has both short and long actions, the proposed policy classifies one short action on release or one long action after a trusted duration, then suppresses the other. This future policy does not describe the current emulator hardware-key adapter: its first Press invokes one action immediately, repeated Press is suppressed until Release, and only held directional keys accept Repeat. A long hold is delivered once until release. Directional/text repeat is permitted only for declared repeatable actions; opening a panel, Home, task switching, power, calling or destructive actions do not auto-repeat.

Duration requires a monotonic source with a documented unit and reset/discontinuity policy. Missing or invalid time disables long classification; it must not synthesize a hold from loop counts or screenshots. Repeat delay/rate are future configurable policy, not measured PDA values. Driver loss, invalid sequence, focus change or overflow cancels held state and capture, stops repeat and leaves the system escape actions available. An unmatched release is harmless. All queues and repeat admission remain bounded; dropped events are counted, rather than retried in an infinite transition loop.

For pointing, a single active logical pointer has Press/Move/Release/Cancel. Hit testing uses shared half-open component geometry after a single coordinate conversion. Press captures one target; moving outside cancels its activation unless that component explicitly supports a captured drag. Release may produce one Tap only when the matching press remains eligible. LongPress requires trustworthy elapsed time and suppresses the later Tap. The current native pointer adapter measures a stationary hold from `ProcessInfo.processInfo.systemUptime` and reports elapsed milliseconds; Shell requires at least 600 ms and an eligible active capture. In Launcher this opens its real context menu; elsewhere it opens the system panel. An eligible outside-panel Release dismisses the panel without activating the view underneath; a reset dialog consumes the outside gesture and stays open. This is a Mac test clock, not a verified PDA timer/input driver. Native scaling, letterboxing, coordinate bounds and malformed sequences require tests; no physical TSC2200 calibration is inferred.

## Future application profiles

The following are design contracts for applications that are **not implemented by this wave**. Mode requests change the shared content rectangle/chrome policy, not framebuffer ownership or rendering engines. A Shell-controlled temporary panel and reserved hardware/logical actions stay available in every mode. Demonstration Compact/Immersive views prove composition and recovery only; they are not working versions of these applications.

| Future application | Recommended mode | Content/context input | System path retained |
|---|---|---|---|
| Crosshair Music | Immersive, optional Compact queue | Pad navigates tracks; center invokes the focused real transport command; volume stays in audio policy | SystemPanel, Home, Back, TaskSwitch; do not invent playback or route call keys into transport |
| Engineering Calculator | Compact; Standard settings/dialogs | QWERTY expressions, pad/caret movement, Enter evaluation; pointer keys are optional equivalents | Back cancels the current subview through Shell; panel exposes real functions |
| Notes | Compact editor; Standard file/options views | Shared text/selection, pad navigation, pointer caret and contextual editing | Home/TaskSwitch preserve a draft; explicit unsaved-change policy |
| File Manager | Standard | Compact rows, pad/select/parent navigation and pointer context commands | Shell Back/Start/panel; destructive actions require an explicit real operation |
| Terminal | Compact | Text commits and declared terminal-control commands; bounded scrollback | System escape commands are not sent as terminal bytes; phone End is not Ctrl-C |
| Reader | Immersive; Compact search/annotations | Pad pages/scrolls; pointer selection; hold menus only with valid time | Temporary panel, Back, Home and task switching |
| Clipboard History | Compact bounded list; Standard confirmation | Up/down selects, explicit user Paste/Copy/Clear, pointer equivalents | Shell retains focus/destination authority and safe dismissal |

Every profile supports keyboard access to content and its actual context commands. Screen buttons are an alternative route; permanent paired softkey bars are not a requirement. Lists expose actual selection/overflow, use clipped compact rows and retain focus on return. Applications must not draw convincing but unavailable battery, clock, radio or notification data.

## Shared text and ten-record clipboard contract

**FUTURE CONTRACT; no Clipboard Broker, history application, new IPC or global editor is implemented now.** Physical layout, modifiers and composition belong upstream of text commits. The editing boundary carries Unicode text plus semantic edit commands, rather than reinterpreted hardware scan codes. Text fields declare UTF-8/scalar limits, cursor/selection units and whether copy/cut/paste is allowed; invalid encoding and oversized commits fail explicitly. A Launcher query is still a bounded query, not a general Notes editor.

A future clipboard owns at most **ten records**, newest first, with fixed bounded storage and no mandatory heap. Proposed initial payload cap: 256 UTF-8 bytes per record, subject to an explicit implementation RAM budget. Oversized copy must return `TooLarge` without truncation or modifying the source. The reserved payload is ten times that cap; record headers, ring state, IPC copy buffers and actual target alignment must be measured separately. This proposal is not current allocated RAM.

The initial type is plain UTF-8 text; images, arbitrary MIME payloads, executable objects and User pointers are outside the contract. A successful copy validates a complete payload atomically, records trusted source identity, and evicts the oldest record only if capacity is full. An identical text copy may move the existing record to the front without consuming another slot. Handles contain a stable ID plus generation/epoch; stale selections cannot paste a different evicted record. Wraparound and Clear invalidate old handles explicitly.

Paste requires an explicit user action, a selected record and a currently authorized focused text destination. Focus/destination version is checked again before commit; switching applications cannot redirect an in-flight paste. Applications do not gain unrestricted background access to clipboard history. History metadata and payload retrieval use bounded copied messages; no borrowed User pointer survives a context switch. Sensitive fields may prohibit history entirely. Clipboard content is not added to diagnostic/UART/normal GUI transcripts.

Cut copies first and deletes only after successful storage acknowledgement and a matching source selection/version. Failure leaves the source intact. Paste failure leaves both record and destination unchanged. Clear removes records, invalidates handles and resets occupancy; secure erasure across caches/storage is not claimed. The initial history is volatile, with no filesystem synchronization or persistence. Future broker authority, lifecycle and tests must be reviewed separately before an application can advertise clipboard integration.

## Evidence boundary

Executed host/ARM input, mode, focus, framebuffer guard and pixel-parity results belong to the Wave007.2 execution report after its final full run. The historical facts above establish suitable physical controls and source candidates; they establish neither verified scan codes nor running PDA2k drivers. No physical code execution, factory-ROM change, phone command or GPIO operation is part of this UX work.
