# Crosshair Blue Angel E2A — host QEMU experiment

This directory contains **GPL-2.0-only host emulator code**, separate from the MIT Rust kernel. The complete license is in [COPYING.GPL-2.0](COPYING.GPL-2.0). The model is intentionally incomplete and synthetic. It is not a validated emulator of the owner's HTC, and it cannot boot the manufacturer's ROM.

The base is upstream QEMU **9.2.0**, commit `ae35f033b874c627d81d51070187fbf55f0bf1a7`, release archive SHA256 `f859f0bc65e1f533d040bbe8c92bcfecee5af2c921a6687c652fb44d089bd894`. `scripts/bootstrap-qemu-blueangel.sh` creates an isolated source/build tree, validates its overlay targets against that archive, and adds only this board, its small peripheral device, generic serial and generic loader. Existing QEMU 9.1/9.2 reference trees are not patched.

```sh
scripts/bootstrap-qemu-blueangel.sh
local/qemu-blueangel/bin/qemu-system-arm \
  -machine crosshair-blueangel-e2a -accel tcg -display none \
  -monitor none -serial stdio \
  -device loader,file=/absolute/path/to/our-kernel.elf,cpu-num=0
```

`CROSSHAIR_QEMU_BLUEANGEL_DIR` selects the isolated build/cache directory; `CROSSHAIR_QEMU_BASELINE_SOURCE` optionally identifies an existing upstream 9.2 source tree to copy. macOS uses `cp -cR` (private APFS clonefile copies); GNU `cp --reflink=auto` is used when available elsewhere. Fresh archive extraction is an implemented alternative. `CROSSHAIR_QEMU_ARCHIVE_DIR` and `CROSSHAIR_QEMU_BUILD_VENV` optionally reuse download and Python helper caches. The verified E2A build used a clone of the existing upstream baseline and its pinned helper venv; the fresh-extraction/installation branches were not separately exercised for E2A. No hard links, host block devices, vendor firmware, guest filesystem or external services are required.

When reusing a baseline, the script verifies its version and the original Kconfig/Meson overlay targets against the pinned archive. Other copied upstream files are assumed to remain unchanged from that baseline; the script does not claim a full tree comparison. The cache manifest records the archive, overlay and runtime executable hashes. Fresh archive extraction provides a separate reproducible route.

On macOS the script creates private pkg-config/Ninja/runtime copies, clears their copied extended metadata and applies an ad-hoc signature with no timestamp. These copies resolved observed launch stalls affecting unsigned Mach-O files; code validation is the suspected mechanism, rather than a kernel-level diagnosis. Empty FinderInfo/ResourceFork metadata also caused an explicit codesign rejection. Its C-only build uses a local subprocess PATH, avoiding pip/ensurepip's unrelated global Rust version probes. Shared helper executables and system security policy are preserved. The runtime executable hash is computed **after** signing. This path has been exercised on macOS x86_64; other host configurations require their own validation.

The board is named `crosshair-blueangel-e2a`; its description explicitly says synthetic/incomplete/experimental. CPU `pxa260` is an experimental PXA26x ISA proxy with QEMU's original MIDR `0x69052903`, not a spoofed PXA263. `pxa255` is permitted as another explicit CPU experiment. CPU revision, integrated flash and peripheral compatibility with the actual PXA263 remain unverified. See [CPU profile](../../docs/E2A_CPU_PROFILE.md).

| Model physical address | Implemented contract |
|---|---|
| `0xa0000000..0xa7ffffff` | Exactly 128 MiB RAM; different `-m` sizes are rejected |
| `0x00000000..0x0000003f` | Synthetic writable 64-byte low-vector scratch RAM; no flash alias |
| `0x40100000..0x40100fff` | Test-only diagnostic UART wrapper over QEMU generic 16550; actual register offsets `0x00,04,...,1c`; 1- or 4-byte access at those offsets |
| `0x40a00000..0x40a00fff` | Small timer subset below; aligned 32-bit accesses only |
| `0x40d00000..0x40d00fff` | Small PIC subset below; aligned 32-bit accesses only |

The diagnostic UART is a **test channel**. Historical Blue Angel FFUART is wired to the modem; this implementation is not permission or a procedure to send bytes through the physical FFUART. No PXA clock gating, GPIO mux, UUE, radio, pins or baud accuracy is claimed. Its generic UART interrupt is connected to PIC bit 22.

| Timer offset | Access | Meaning |
|---|---|---|
| `0x00,04,08,0c` | RW | OSMR0..3, four 32-bit matches |
| `0x10` | RW | OSCR, continuously advancing at 3,686,400 ticks per virtual second; writes restart its time origin |
| `0x14` | R/W1C | OSSR bits 0..3; writing 1 clears only the corresponding latched event |
| `0x1c` | RW | OIER low four bits; enables match → OSSR latching |

Timer match 0..3 corresponds to PIC source 26..29. A match with its OIER bit clear does not latch OSSR, and enabling later does not recreate a missed match. Once OSSR is set, clearing OIER does not clear status or lower the asserted source; W1C does. This follows the QEMU 9.1 comparator and the documented PXA26x status-routing interpretation; it remains separately subject to hardware validation. Reserved OIER/OSSR value bits are ignored. No watchdog/OWER or PXA270 extra timer channels are supplied.

Deadlines use integer virtual nanoseconds rounded **up** to the counter edge, not an early rounded-down match. Counts wrap modulo `2^32`; comparisons repeat on the next wrap. Writing a match equal to the current count schedules its next occurrence after a full wrap, avoiding a zero-time recurring callback. This timing detail is an explicit E2A experiment, not a measured silicon property.

| PIC offset | Access | Meaning |
|---|---|---|
| `0x00` | RO | ICIP = pending & mask & ~FIQ-route |
| `0x04` | RW | ICMR mask |
| `0x08` | RW | ICLR FIQ route; 0 selects IRQ |
| `0x0c` | RO | ICFP = pending & mask & FIQ-route |
| `0x10` | RO | ICPR raw pending source levels |

The combined SysBus device has stable QOM path **`/machine/e2a`**, output group **`sysbus-irq`**, pin **0 = IRQ**, **1 = FIQ**. QTest can observe transitions using:

```text
irq_intercept_out /machine/e2a sysbus-irq
```

Unsupported offsets, disallowed widths, unaligned accesses and writes to read-only PIC registers return `MEMTX_ERROR` from `read_with_attrs`/`write_with_attrs`. The board explicitly sets `ignore_memory_transaction_failures=false`, permitting ARM data aborts. The UART wrapper also rejects unsupported offsets/widths and writes to LSR/MSR. All ordinary MMIO widths reach the attrs callbacks without being split into smaller successful accesses first. Unmapped regions remain unassigned; they are not silent fake peripheral blocks.

**Synthetic reset contract:** device reset cancels old timer deadlines, restarts OSCR at zero at the current virtual time, clears OSMR0..3/OIER/OSSR, clears PIC pending/mask/routing and lowers IRQ/FIQ. New zero matches are next due after one full counter wrap. The generic serial device supplies its own UART reset. Ordinary RAM and the synthetic low-vector RAM persist across warm reset. The timer reset deliberately differs from QEMU 9.1's missing PXA timer reset callback. Migration/save-state is explicitly unsupported by this device; no partial state transfer is advertised.

Provenance: the timer/PIC register layout and interrupt-update structure were adapted from QEMU 9.1.0 [pxa2xx_timer.c](https://gitlab.com/qemu-project/qemu/-/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/hw/timer/pxa2xx_timer.c) and [pxa2xx_pic.c](https://gitlab.com/qemu-project/qemu/-/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/hw/arm/pxa2xx_pic.c). Their 2006 Openedhand/Thorsten Zitterell attribution and original PIC author credit are retained in the C header. Reset, strict attrs errors, scheduling, small board integration and UART wrapper are new E2A work. The underlying generic serial implementation remains upstream QEMU code under its original terms. No PXA GPL implementation was copied into the MIT guest.

Build evidence is written under the selected cache's `evidence/`: upstream tag, source/binary/overlay hashes, host tools, selected devices, machines, CPU list and generic-loader help. Guest and QTest execution reports are produced by the separate E2A harness; successful compilation alone is not described as execution or hardware validation.

## Separate E2B GPIO experiment

`scripts/bootstrap-qemu-e2b.sh` builds **`crosshair-blueangel-e2b`** in its own
`local/qemu-e2b` cache (`CROSSHAIR_QEMU_E2B_DIR` overrides it). It reuses the
pinned 9.2 source/dependencies/bootstrap above, leaving the E2A and reference
caches untouched. The new translation unit includes the unchanged E2A C file;
only the E2B unit is compiled, registering both machines without duplicate QOM
types. E2B accepts only the experimental `pxa260` CPU proxy. Its RAM, low vectors,
timer, PIC and diagnostic UART retain the E2A contract.

The new GPL GPIO implementation follows the documented PXA26x subset in
[the primary-source audit](../../docs/E2B_CPU_GPIO_AUDIT.md). This adds no ASIC3,
keyboard matrix, peripheral mux driver, pull/voltage, contention, sleep or wake
model. At PA **`0x40e00000`**, a 4 KiB MMIO aperture implements only the following
aligned 32-bit accesses. Unknown offsets, wrong widths/alignment and accesses
in the wrong direction return `MEMTX_ERROR`; rejected wide writes are not split
into smaller successful mutations.

| Register | Bank0 / 1 / 2 offsets | Contract |
|---|---|---|
| GPLR | `00 / 04 / 08` | RO pin sample |
| GPDR | `0c / 10 / 14` | RW direction |
| GPSR | `18 / 1c / 20` | WO output latch W1S, including preload while input |
| GPCR | `24 / 28 / 2c` | WO output latch W1C |
| GRER | `30 / 34 / 38` | RW rising-edge enable |
| GFER | `3c / 40 / 44` | RW falling-edge enable |
| GEDR | `48 / 4c / 50` | R/W1C sticky edge status |
| GAFR | `54,58 / 5c,60 / 64,68` | RW two-bit alternate function per pin |

Bank masks are `ffffffff / ffffffff / 03ffffff`; the final GAFR word mask is
`000fffff`. Pins **0..85** use AF0 for GPIO, GPDR0=input/1=output. Pins **86..89**
use **AF1** for GPIO and **inverted GPDR**: 0=output/1=input. All four AF encodings
are stored, but only that GPIO selection drives the GPIO output adapter.

Stable QOM path **`/machine/gpio`** exposes 90 `unnamed-gpio-in` test wires,
90 output lines in group **`gpio-out`** and 90 output-enable lines in
**`gpio-oe`**. GPIO output is valid only with OE=1; disconnected outputs signal
out=0/OE=0. GPIO-mode output GPLR samples the latch. Input and unmodeled AF GPLR
sample the external test wire; this is a deterministic adapter choice, not a
claim about an unmodeled dedicated driver. Default external levels are zero.

```text
set_irq_in /machine/gpio unnamed-gpio-in 89 1
irq_intercept_out /machine/gpio gpio-out
```

QTest can intercept only one output group per session; the test uses fresh
processes for `gpio-out`, `gpio-oe` and `/machine/e2a sysbus-irq`. The three GPIO
SysBus IRQ outputs connect to PIC8 (pin0), PIC9 (pin1), PIC10 (OR pins2..89).
Interrupts remain latched across PIC mask/route and edge-enable changes until
the corresponding GEDR W1C. An edge is an external transition while in GPIO
mode and effective input direction, with GRER/GFER enabled. This AF/input gate
is an explicitly documented interpretation of the limited model; GPDR/GAFR
reconfiguration and output writes do not synthesize edges.

**E2B reset:** all direction/AF/edge/status registers and the output latch clear
to zero, GPIO IRQ outputs deassert, GPIO output drivers disconnect. External
adapter wire levels persist across warm reset. Latch0 and external-wire
retention are synthetic choices, not electrical reset guarantees. With reset
AF0, pins86..89 are dedicated outputs in the hardware definition; their
dedicated drivers and actual levels are unmodeled here. Migration remains
unsupported.

`python3 tools/qtest_e2b.py --qemu /absolute/path/to/qemu-e2b/bin/qemu-system-arm`
exercises all 90 pins' directions, AF encodings, preload, edges/W1C, PIC routing,
actual IRQ/FIQ/output/OE transitions, reset and invalid-access side effects.
It writes JSON and protocol logs under `target/artifacts/e2b-qtest`. QTest does
not expose `MemTxResult`; its invalid-access assertions concern diagnostics
and state preservation, while actual CPU exceptions require the TCG harness.
