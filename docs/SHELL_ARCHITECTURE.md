# Crosshair Shell0.1.2 architecture

Wave007 adds a separately linked **User Mode Shell** to the existing ARMv5TE context/runtime and synthetic display experiment. This document describes source-confirmed contracts; executed scenarios, hashes, captures and measured allocations belong to [Wave007](../reports/WAVE_007.md). Physical PXA263, ATI W3200, TSC2200 and PDA keyboard behavior remain unverified. Wave001–Wave006 guests and reports remain separate regressions.

## Ownership and dependencies

| Layer | Owns | Boundary |
|---|---|---|
| [crosshair-shell](../shell/src/lib.rs) | Desktop/Today/Launcher/application-screen state, focus, bounded history, menu/dialog state and volatile theme | Dependency-free apart from existing `crosshair-ui`; `no_std`, `forbid(unsafe_code)`, no allocator, MMIO, scheduler authority or framebuffer allocation |
| [User adapter](../src/shell_user.rs) | User entry/BSS, one guarded RGB565 framebuffer, `Surface`, Shell instance and observation records | Requests presentation, metrics and input only through ARM SVC; no privileged pointer or peripheral handle |
| [Privileged brokers](../src/shell.rs) | Validated graphics publication, bounded event queue, copied diagnostic metrics, timer/PIC and task authority | IRQ/FIQ masked during handlers; no User reference survives context/address-space switching |
| [Task runtime](TASK_RUNTIME.md) | Fixed Task records, complete80B Context, exception entry/return and round-robin selection | Reuses existing Wave006 context/Task/policy/Assembly; separate Shell MMU tables extend only this guest's allocation contract |
| [Synthetic display/input](../crosshair-emulator/qemu/crosshair-blueangel-display-test.c) | Committed QEMU console surface and eight-word logical input FIFO | Existing test protocol; not an ATI display, physical keyboard or stylus controller |
| [Native viewer](../tools/crosshair_gui.swift) | Host window, semantic key edges and phased pointer translation | Blits actual QMP PPM pixels and forwards logical wires; it does not draw Shell controls or hold Shell state |

The four Launcher entries open real built-in screens: About, Diagnostics, Settings and Today. They currently execute within the Shell process, sharing its navigation state. They are not four newly created processes, installed packages or dynamically loaded applications. The independent Busy ARM workload is a separate isolated User task. Screen switching chooses among opened Shell views; it grants no task-control syscall or access to another address space.

System/context menus, the transient adaptive panel and theme-reset confirmation are bounded Shell overlays. Standard/Compact/Immersive policy, held-key ownership and pointer capture live in the Shell, with separate UX observations; [adaptive contract](ADAPTIVE_SHELL.md). The permanent bottom action bar is removed, leaving one persistent Start and content through y320. A notification daemon, general window manager, application installer and universal IPC service are not implemented. The existing shared renderer, Cyrillic bitmap font, RGB565 types, clipping and dirty rectangles remain the graphics foundation. [Pinned Tabler masks](UI_ASSET_SYSTEM.md) are the primary system-icon source, following the [approved visual direction](UI_DESIGN_SYSTEM.md#approved-visual-reference-for-crosshair-shell-01); the reference image is not used as a background framebuffer. The guest embeds2196B raw read-only masks and no SVG parser/renderer or additional mutable icon state.

## Address spaces and lifetime

Addresses below are **guest VA/PA**, half-open ranges; they are not physical PDA instructions. Source: [Shell tables](../src/shell_runtime/memory.rs), [kernel linker](../link/shell.ld) and [User linker](../link/shell-user.ld).

| Owner / region | User VA | Backing PA | User permission |
|---|---|---|---|
| Busy code | `01000000..01001000` | `a0200000..a0201000` | AP2 RO |
| Busy data | `01001000..01002000` | `a0201000..a0202000` | AP3 RW |
| Busy guard | `01002000..01003000` | No mapping | Fault |
| Busy stack | `01003000..01004000` | `a0203000..a0204000` | AP3 RW |
| Shell code,16pages | `01000000..01010000` | `a0400000..a0410000` | AP2 RO |
| Shell data,47pages | `01010000..0103f000` | `a0410000..a043f000` | AP3 RW |
| Shell guard | `0103f000..01040000` | No mapping | Fault |
| Shell stack,8pages | `01040000..01048000` | `a0440000..a0448000` | AP3 RW |

Two16KiB-aligned L1 and two1KiB-aligned coarse L2 tables install separate spaces. Common vectors, RAM identity aliases `a0000000..a8000000`, peripheral sections `40000000..41000000` and display/input section `10000000..10100000` are privileged AP1. Other descriptors fault. Domain0 remains Client (`DACR=1`), FCSE PID0, caches off (`SCTLR=79`). Every dispatch installs the selected TTBR, drains the write buffer, invalidates the full unified TLB and uses audited ARMv5/XScale prefetch/cpwait synchronization. QEMU cache-maintenance NOPs cannot establish physical cache/coherency guarantees.

The Shell framebuffer starts at VA`01010040`, PA`a0410040`, with153600 pixel bytes and64-byte canaries before/after. It is the sole guest framebuffer. Its allocation is within Shell data; a separate32KiB User stack prevents placing the framebuffer on a kernel stack. Task0 cannot access Shell backing pages through either User mappings or privileged PA aliases. All User pages/tables/contexts remain reserved for the whole guest lifetime, including Faulted/Exited/Waiting states; there is no memory recycling or loader.

ARMv5 has no XN: writable data/stack remain executable. AP2 code and checked syscall origin provide a useful boundary without claiming W^X, DMA isolation or secure boot. Trusted host loader/QMP/QTest and privileged kernel/drivers remain outside User isolation.

## Narrow SVC services

Source: [syscall dispatch and validation](../src/shell.rs#L268), [AAPCS User adapter](../src/shell_user.rs#L27). ARM `svc #0`, number in `r7`; results in `r0`. Origin must be aligned ARM code in the caller's mapped RO window: Shell VA`01000000..01010000`, Busy VA`01000000..01001000`. The check bounds a complete instruction within mapped pages; it does not assert that every accepted address belongs to the ELF's shorter `.text` extent. Thumb/data/stack origin ends only the caller. Unsupported immediate/number returns `-ENOSYS`. Kernel-owned task index determines rights; user arguments do not select another identity.

| r7 | Operation / arguments | Result and bounds |
|---|---|---|
|0|Exit, `r0=status`|Retains status and marks Exited; no return|
|1|Diagnostic Copy, `r0=ptr`, `r1=len`|Reads only the caller's own data range, cap64B before checked-add/range checks; returns length, without file/device/output authority|
|2|Yield|Returns0 and makes caller Ready before scheduling|
|3|Present, `r0=FB`, `r1=153600`, `r2=0`, `r3=(320<<16)|240`|Shell task only; exact fixed framebuffer, extent and full-screen geometry required; synchronous publication returns0|
|4|Metrics, `r0=destination`, `r1=48`|Shell task only; aligned complete own-data destination, exact48B copyout; returns48|
|5|EventWait, `r0..r3=0`|Shell task only; returns one logical wire immediately or suspends caller until an event is available|

Errors are32-bit two's complement: `-EFAULT=-14`, `-EINVAL=-22`, `-ENOSYS=-38`, `-EPERM=-1`. Pointer addition must not overflow; the full range must lie in the caller's data allocation before the first access. Present additionally accepts only its designated framebuffer, so it cannot expose kernel/foreign RAM through QEMU. Metrics exports scalar observations rather than pointers or task-control handles. Restricted services invoked by Busy are denied. No Sleep syscall, arbitrary drawing command or general shared-memory capability is added.

A48B `RuntimeInfo` snapshot contains version/valid-group flags, timer ticks, context switches, task/Ready/Running/Faulted counts, reserved mapped working-RAM bytes, delivered events and input overflows. Missing required valid bits, version mismatch or nonzero reserved word displays unavailable state. These values originate from the kernel; host parity rendering consumes the same captured snapshot rather than inventing a plausible diagnostic value. Working-RAM accounting describes reserved mapped extents, not free heap, instantaneous stack usage or the sparse flat file size. [Shell Snapshot](../shell/src/lib.rs) is a separate64B observation with16 scalar words; it exports view/focus/theme/history/event/render state, not pointers or capabilities.

## Input, waiting and preemption

The existing synthetic hardware FIFO holds8 wires. Privileged polling drains at most8 per pass into a4-word kernel FIFO; a full kernel FIFO drops the newly arriving tail event and increments an overflow counter. Old entries retain order. Hardware rejects and kernel drops remain observable. The Shell consumes one returned event at a time and uses existing semantic `Event` values plus the adapter commands described in [navigation](SHELL_NAVIGATION.md).

If EventWait has no queued event, Shell becomes Waiting and another Ready task runs. The timer remains kernel-owned: IRQ26, compare interval36864 at the existing3686400Hz model clock (10ms virtual time), ACK/rearm in the masked handler. A noncooperative Busy loop therefore cannot retain the CPU indefinitely. User mode enables IRQ and keeps FIQ masked; nested kernel IRQ is not enabled.

When no User task is Ready, a separate privileged **System-mode Idle context** uses its own4KiB kernel stack and IRQ-enabled CPSR`5f`. Its exact loop address and kernel-owned current-task sentinel identify the only admitted privileged timer origin. The timer continues polling input and wakes Waiting Shell. User contexts are saved before entering Idle; complete User banked SP/LR and SPSR/register state are restored before returning to a User task. Idle is an interruptible branch loop, not hardware sleep or a claim of low power. This avoids losing input after the companion task faults and Shell waits with an empty queue.

## Rendering and adaptive input

[Adaptive policy/capture](../shell/src/adaptive.rs) and [shared geometry](../shell/src/geometry.rs) define Standard top24/content24..320, Compact top16/content16..320 and Immersive content0..320. The last mode retains a small visible corner recovery affordance over content, with no reserved full-width bar. About/Diagnostics demonstrate modes as the same built-ins; Desktop/Today/Launcher/Settings retain Standard. All system commands route through Shell before app context. No bottom action band is reserved or hit-tested. See [navigation](SHELL_NAVIGATION.md) and [full adaptive contract](ADAPTIVE_SHELL.md).

The shared [PDA components](../ui/src/pda.rs) implement bounded text, section/key-value/compact rows, inline actions and row scrolling. Today/metadata use dense real facts without filled cards for every short field. Mode and scroll state are bounded per view, history remains8 entries, and panels/capture do not create new tasks or framebuffer owners. About/Desktop/Launcher do not repaint merely because kernel counters advance; Today/Diagnostics can invalidate on a new supplied snapshot. There is no fabricated clock or free-running animation.

Full Desktop composition decodes only workspace y24..320 into the sole framebuffer; opaque top chrome covers the other24 rows. A bounded dirty mask accumulates old/new shortcut focus/pressed regions. Menu/panel opening draws over existing pixels without wallpaper decode; dismissal restores a bounded covered union. Other views fully compose after relevant changes. A32B RenderStats describes wallpaper packets/source pixels/destination pixels/runs, Surface dirty count/area, full strategy and rendered flag. No-op clears all eight words. These counters are software work, not cycles/FPS or physical display latency.

Present still accepts only one fixed240×320 frame. The adapter coalesces dirty callbacks into one successful full153600B publication per render. Partial composition does not reduce publication size. Surface retains dirty regions on failure; publication is synchronous while User is stopped in SVC. An asynchronous ATI/DMA path would require a new completion/cache/lifetime contract. QEMU committed pixels and exported host images are separate from guest working RAM.

Pointer Press/Move/Release/Cancel and trusted PointerHold are decoded by shared `Action::from_wire`; capture never grants an application system-command ownership. Press focuses without activation, moving outside cancels tap, Release activates the original target once, and hold>=600ms requires an active strictly stationary capture. The adapter supplies monotonic held time; no guest clock/timeout loop is invented. Hardware edges separate Press/Repeat/Release with bounded held bits; only held directions repeat. Invalid transport/source failure and known runtime input loss cancel held/capture state without activating a replacement target. The unchanged QEMU tag8 carries explicit emulator-reserved scalars, not an unrestricted Unicode text protocol. Physical input still needs a verified TSC2200/keyboard/controller layer.

A new versioned80B UxSnapshot exports20 scalar words for mode/viewport/overlay/capture/scroll/held-key state and command counters; existing Snapshot64B, RuntimeInfo48B and RenderStats32B contracts stay separate. Guest observation journals and actual ARM type sizes are accounted separately from code/RO assets, framebuffer, mapped reservations and temporary stack work. Exact current BSS/type/ROM values and actual execution claims belong to the Wave007.2 report; earlier Wave007/007.1 measurements remain historical.

## Static review and unsafe contracts

**Source-confirmed review:** the [80B frame handler](../src/shell.rs#L368) consumes only an Assembly-supplied privileged stack frame and validates mode, bounds/alignment and kernel canaries. It copies the frame into the kernel-owned Task before scheduling. Task-state counts are computed before borrowing a particular Task for syscall mutation. Metrics writes only validated own User data, with no live Rust reference to the destination; framebuffer publication reads pixels while `Surface::present` supplies read-only access and the User task is suspended. No User copy or borrowed User data crosses `memory::activate`.

**Source-confirmed review:** only the kernel current-task sentinel plus exact System CPSR/loop-PC admit Idle IRQ origin. Its fixed context/private stack are never exposed through User mappings. Empty EventWait and Waiting→Ready wakeup run with IRQ/FIQ masked; input arriving after the empty check remains pending for the next timer poll. The synthetic FIFO is not an interrupt-driven physical input driver. These observations are a static correctness review, not a full vulnerability scan or substitute for the executed idle/wakeup/fault/reset tests in [Wave007](../reports/WAVE_007.md).

A later application loader should preserve these ownership boundaries while giving real applications distinct identities, memory and authority. Extracting built-in screens into tasks will require explicit application lifecycle/IPC, not a claim that opening a panel already launches a process. Persistence, filesystem, real time, notification sources, phone/network services and physical display/input remain future work. [Task runtime](TASK_RUNTIME.md) records the existing loader/teardown obligations.
