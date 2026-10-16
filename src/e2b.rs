#![no_std]
#![no_main]
#![deny(unsafe_op_in_unsafe_fn)]
//! Emulator-only CP15 translation and PXA26x GPIO execution probes.
//! Register sources and limitations: docs/E2B_CPU_GPIO_AUDIT.md.
mod arch;
#[path = "drivers/pxa_uart.rs"]
mod pxa_uart;

use core::arch::asm;
use core::panic::PanicInfo;
use core::ptr::{addr_of_mut, read_volatile, write_volatile};

const GPIO: usize = 0x40e0_0000;
const PIC: usize = 0x40d0_0000;
#[cfg(not(feature = "e2b-negative-test"))]
const PIN89: u32 = 1 << 25;
const SOURCES: [u32; 5] = [1 << 8, 1 << 9, 1 << 10, 1 << 10, 1 << 10];
const PINS: [u32; 5] = [0, 1, 2, 2, 89];

#[derive(Clone, Copy)]
#[repr(usize)]
enum F {
    Magic,
    Stage,
    Error,
    IrqCount,
    Midr,
    Ctr,
    ResetSctlr,
    ResetTtbr,
    ResetDacr,
    ResetPid,
    DebugId,
    CacheReadback,
    MmuReadback,
    AliasRead,
    AliasWrite,
    Restored,
    Pending,
    Edges,
    IrqSp,
    FaultKind,
    FaultLr,
    FaultPsr,
    Dfsr,
    Dfar,
    Direction,
    Alternate,
    Checks,
    ExpectedSource,
    #[cfg(feature = "e2b-negative-test")]
    ProbeSelector,
}
// The stable 29-word probe record is intentionally plain integers: QMP/QTest
// inspect it without a guest runtime or borrowed references into IRQ state.
#[unsafe(no_mangle)]
pub static mut CROSSHAIR_E2B_RECORD: [u32; 29] = [0; 29];

#[repr(C, align(16384))]
struct L1([u32; 4096]);
#[unsafe(no_mangle)]
static mut E2B_L1: L1 = L1([0; 4096]);

#[cfg(feature = "e2b-negative-test")]
const SELECTOR: usize = 0xa000_0100; // Own synthetic RAM, outside ELF/BSS.

unsafe fn put(field: F, value: u32) {
    // SAFETY: valid fixed index, aligned volatile u32, no shared references.
    // Main/IRQ field ownership and compound checks are described in run_gpio.
    unsafe {
        write_volatile(
            addr_of_mut!(CROSSHAIR_E2B_RECORD)
                .cast::<u32>()
                .add(field as usize),
            value,
        )
    }
}
unsafe fn get(field: F) -> u32 {
    // SAFETY: same ownership/bounds contract as put; no references are formed.
    unsafe {
        read_volatile(
            addr_of_mut!(CROSSHAIR_E2B_RECORD)
                .cast::<u32>()
                .add(field as usize),
        )
    }
}
unsafe fn read(address: usize) -> u32 {
    // SAFETY: private callers select audited, mapped, aligned model registers
    // or this test's synthetic RAM and identity/alias mapping.
    unsafe { read_volatile(address as *const u32) }
}
unsafe fn write(address: usize, value: u32) {
    // SAFETY: private callers exclusively own the model register/RAM location;
    // no physical device, DMA, concurrent CPU or runtime driver is involved.
    unsafe { write_volatile(address as *mut u32, value) }
}
macro_rules! cp_read {
    ($operands:literal) => {{
        let value: u32;
        // SAFETY: the audited CP15 register is available in privileged CPU260.
        asm!(concat!("mrc p15, 0, {value}, ", $operands), value=out(reg) value, options(nostack, nomem));
        value
    }};
}

fn mask_irq() {
    // SAFETY: privileged SVC ARM, keep FIQ masked, preserve the mode and stack.
    unsafe {
        asm!("mrs r0, cpsr", "orr r0, r0, #0x80", "msr cpsr_c, r0", out("r0") _, options(nostack));
    }
}
unsafe fn control(value: u32) {
    let wait: u32;
    // SAFETY: all executing code, stacks, vectors and MMIO remain identity
    // mapped through the transition. The XScale cpwait sequence flushes the
    // prefetched instruction path; memory clobber prevents compiler motion.
    unsafe {
        asm!("mcr p15, 0, {value}, c1, c0, 0", "mrc p15, 0, {wait}, c2, c0, 0",
             "mov {wait}, {wait}", "sub pc, pc, #4", value=in(reg) value,
             wait=lateout(reg) wait, options(nostack));
    }
    let _ = wait;
}

unsafe fn cpu_probe() {
    // SAFETY: entry established SVC/IRQ/FIQ masked and MMU/cache off on our
    // synthetic board. These are functional TCG probes, not a cache simulator
    // or a safe initialization recipe for a physical XScale processor.
    unsafe {
        let midr = cp_read!("c0, c0, 0");
        let ctr = cp_read!("c0, c0, 1");
        let reset = cp_read!("c1, c0, 0");
        let ttbr = cp_read!("c2, c0, 0");
        let dacr = cp_read!("c3, c0, 0");
        let pid = cp_read!("c13, c0, 0");
        let debug: u32;
        asm!("mrc p14, 0, {v}, c0, c0, 0", v=out(reg) debug, options(nostack, nomem));
        for (f, v) in [
            (F::Midr, midr),
            (F::Ctr, ctr),
            (F::ResetSctlr, reset),
            (F::ResetTtbr, ttbr),
            (F::ResetDacr, dacr),
            (F::ResetPid, pid),
            (F::DebugId, debug),
        ] {
            put(f, v);
        }
        assert!(midr == 0x6905_2903 && ctr == 0x0d17_2172 && reset == 0x78);
        assert!(ttbr == 0 && dacr == 0 && pid == 0 && debug == 0);
        // Readback of control/FCSE storage and recognized cache maintenance
        // instructions does not establish hardware cache/coherency behavior.
        let test_pid = 0x0200_0000u32;
        asm!("mcr p15, 0, {p}, c13, c0, 0", p=in(reg) test_pid, options(nostack));
        assert!(cp_read!("c13, c0, 0") == test_pid);
        asm!("mcr p15, 0, {p}, c13, c0, 0", p=in(reg) pid, options(nostack));
        control(reset | 0x1004);
        let cached = cp_read!("c1, c0, 0");
        put(F::CacheReadback, cached);
        assert!(cached == reset | 0x1004);
        let zero = 0u32;
        asm!("mcr p15, 0, {z}, c7, c7, 0", "mcr p15, 0, {z}, c7, c10, 4",
             "mcr p15, 0, {z}, c7, c5, 4", z=in(reg) zero, options(nostack));
        control(reset);
        let table = addr_of_mut!(E2B_L1).cast::<u32>();
        assert!(table as usize & 0x3fff == 0);
        for index in 0..4096 {
            write_volatile(table.add(index), 0);
        }
        // Section descriptors: AP3/domain0, C=B=0, no hardware cache claim.
        write_volatile(table, 0xc02); // Low exception vectors.
        for section in 0xa00..0xa80 {
            write_volatile(table.add(section), ((section as u32) << 20) | 0xc02);
        }
        for section in 0x400..0x410 {
            write_volatile(table.add(section), ((section as u32) << 20) | 0xc02);
        }
        write_volatile(table.add(0x200), 0xa000_0c02);
        write(0xa000_0200, 0x1357_9bdf);
        let base = table as u32;
        let client_domain0 = 1u32;
        asm!("mcr p15, 0, {base}, c2, c0, 0", "mcr p15, 0, {domain}, c3, c0, 0",
             "mcr p15, 0, {z}, c8, c7, 0", base=in(reg) base,
             domain=in(reg) client_domain0, z=in(reg) zero, options(nostack));
        assert!(cp_read!("c2, c0, 0") == base && cp_read!("c3, c0, 0") == 1);
        control(reset | 1);
        put(F::MmuReadback, cp_read!("c1, c0, 0"));
        let alias_read = read(0x2000_0200);
        write(0x2000_0200, 0x2468_ace0);
        let alias_write = read(0xa000_0200);
        put(F::AliasRead, alias_read);
        put(F::AliasWrite, alias_write);
        assert!(alias_read == 0x1357_9bdf && alias_write == 0x2468_ace0);
        control(reset);
        asm!("mcr p15, 0, {base}, c2, c0, 0", "mcr p15, 0, {domain}, c3, c0, 0",
             "mcr p15, 0, {z}, c8, c7, 0", base=in(reg) ttbr, domain=in(reg) dacr,
             z=in(reg) zero, options(nostack));
        assert!(cp_read!("c1, c0, 0") == reset && cp_read!("c2, c0, 0") == ttbr);
        assert!(cp_read!("c3, c0, 0") == dacr && cp_read!("c13, c0, 0") == pid);
        put(F::Restored, 1);
        put(F::Checks, 0xf);
    }
}

#[cfg(not(feature = "e2b-negative-test"))]
unsafe fn gpio_probe() {
    // SAFETY: CPU IRQ remains masked, host inputs are initially low, and the
    // experimental GPIO controller is exclusively owned by this probe.
    unsafe {
        write(PIC + 4, 0);
        write(PIC + 8, 0);
        assert!(read(GPIO + 0xc) == 0 && read(GPIO + 0x14) == 0);
        assert!(read(GPIO + 0x54) == 0 && read(GPIO + 0x68) == 0);
        let p = 1 << 20;
        write(GPIO + 0xc, p);
        write(GPIO + 0x18, p);
        assert!(read(GPIO) & p != 0);
        write(GPIO + 0x24, p);
        assert!(read(GPIO) & p == 0);
        write(GPIO + 0xc, 0);
        write(GPIO + 0x18, p);
        assert!(read(GPIO) & p == 0); // Input samples the external test wire.
        write(GPIO + 0xc, p);
        assert!(read(GPIO) & p != 0);
        write(GPIO + 0x58, 1 << 8); // GPIO20 alternate AF1, GPIO disabled.
        assert!(read(GPIO) & p == 0);
        write(GPIO + 0x58, 0);
        assert!(read(GPIO) & p != 0);
        write(GPIO + 0x24, p);
        write(GPIO + 0xc, 0);
        write(GPIO + 0x68, 1 << 18); // GPIO89 is GPIO only in AF1.
        write(GPIO + 0x20, PIN89); // GPDR89=0 means output (inverted).
        assert!(read(GPIO + 8) & PIN89 != 0);
        write(GPIO + 0x2c, PIN89);
        write(GPIO + 0x14, PIN89); // GPDR89=1 means input.
        write(GPIO + 0x20, PIN89);
        assert!(read(GPIO + 8) & PIN89 == 0);
        write(GPIO + 0x14, 0);
        assert!(read(GPIO + 8) & PIN89 != 0);
        write(GPIO + 0x2c, PIN89);
        write(GPIO + 0x14, PIN89);
        put(F::Direction, read(GPIO + 0x14));
        put(F::Alternate, read(GPIO + 0x68));
        write(GPIO + 0x30, 7);
        write(GPIO + 0x38, PIN89); // Rising 0,1,2,89.
        write(GPIO + 0x3c, 4); // Falling 2.
        write(GPIO + 0x50, 0x03ff_ffff);
        write(GPIO + 0x48, u32::MAX);
        put(F::Checks, 0x1f);
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn rust_main() -> ! {
    // SAFETY: E2B entry initialized stacks/BSS in privileged ARM, no physical
    // device access; this guest only runs on its declared experimental board.
    unsafe {
        assert!(get(F::Stage) == 0);
        put(F::Magic, 0x4532_4243);
        // Capture reset register state even in negative images that do not
        // configure GPIO. These reads have no pin or acknowledgement effects.
        put(F::Direction, read(GPIO + 0x14));
        put(F::Alternate, read(GPIO + 0x68));
        assert!(get(F::Direction) == 0 && get(F::Alternate) == 0);
        cpu_probe();
        #[cfg(feature = "e2b-negative-test")]
        {
            negative_probe()
        }
        #[cfg(not(feature = "e2b-negative-test"))]
        {
            run_gpio()
        }
    }
}

#[cfg(not(feature = "e2b-negative-test"))]
unsafe fn run_gpio() -> ! {
    // SAFETY: cpu_probe restored the reset control state, IRQ/FIQ are masked.
    // Main samples aligned volatile counters without shared Rust references;
    // compound terminal checks occur only after masking the IRQ again.
    unsafe {
        gpio_probe();
        put(F::Stage, 1);
        let mut uart = pxa_uart::ReferenceUart::init();
        assert!(uart.send("CROSSHAIR E2B — GPIO READY\r\n").is_ok());
        asm!("msr cpsr_c, #0x53", options(nostack));
        // CPU IRQ is enabled, but the PIC still masks GPIO0. The first host
        // edge must latch GEDR/ICPR without entering our exception handler.
        while read(GPIO + 0x48) & 1 == 0 {
            core::hint::spin_loop();
        }
        assert!(read(PIC + 4) == 0 && read(PIC) == 0);
        assert!(read(PIC + 0x10) == 1 << 8 && get(F::IrqCount) == 0);
        put(F::Checks, 0x5f);
        write(PIC + 4, (1 << 8) | (1 << 9) | (1 << 10));
        while get(F::IrqCount) < 5 {
            if get(F::Error) != 0 {
                panic!("GPIO IRQ contract failed");
            }
            core::hint::spin_loop();
        }
        mask_irq();
        write(PIC + 4, 0);
        assert!(get(F::Error) == 0 && get(F::IrqCount) == 5);
        assert!(read(GPIO + 0x48) == 0 && read(GPIO + 0x50) == 0 && read(PIC) == 0);
        put(F::Checks, 0x7f);
        put(F::Stage, 2);
        assert!(
            uart.send("CROSSHAIR E2B — CP15 MMU GPIO IRQ PASS\r\n")
                .is_ok()
        );
    }
    arch::idle()
}

#[unsafe(no_mangle)]
pub extern "C" fn rust_irq() {
    // SAFETY: the assembly wrapper preserves C ABI registers/8-byte alignment
    // and SPSR, no nested IRQ/FIQ. All addresses belong to this model's GPIO/PIC.
    unsafe {
        let count = get(F::IrqCount) as usize;
        let pending = read(PIC);
        if count >= 5 || pending != SOURCES[count] {
            put(F::Error, 1);
            write(PIC + 4, 0);
            return;
        }
        let pin = PINS[count];
        let bank = (pin / 32) as usize;
        let bit = 1 << (pin % 32);
        let edges = read(GPIO + 0x48 + bank * 4);
        if edges != bit {
            put(F::Error, 2);
            write(PIC + 4, 0);
            return;
        }
        write(GPIO + 0x48 + bank * 4, bit);
        let sp: u32;
        asm!("mov {sp}, sp", sp=out(reg) sp, options(nostack, nomem));
        put(F::Pending, pending);
        put(F::ExpectedSource, SOURCES[count]);
        put(F::Edges, edges);
        put(F::IrqSp, sp);
        put(F::IrqCount, (count + 1) as u32);
    }
}

#[cfg(feature = "e2b-negative-test")]
unsafe fn negative_probe() -> ! {
    // SAFETY: deliberate faults in this emulator-only ELF. A test mailbox
    // chooses one invalid access; returning from it is always a failure.
    unsafe {
        let selector = read(SELECTOR);
        put(F::ProbeSelector, selector);
        put(F::Stage, 4);
        match selector {
            1 => {
                let _ = read(GPIO + 0x6c);
            }
            2 => write(GPIO, 1),
            3 => {
                let _ = read_volatile((GPIO + 0x14) as *const u8);
            }
            4 => {
                asm!("mrc p14, 0, r0, c6, c0, 0", out("r0") _, options(nostack));
            }
            5 => {
                asm!("mrc p14, 0, r0, c7, c0, 0", out("r0") _, options(nostack));
            }
            _ => panic!("invalid negative selector"),
        }
        panic!("negative probe did not trap");
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn rust_fault(kind: u32, lr: u32, psr: u32) -> ! {
    // SAFETY: terminal exception vector captured banked LR/SPSR before setting
    // SVC and our stack. All own RAM is identity mapped even during MMU probes.
    unsafe {
        put(F::FaultKind, kind);
        put(F::FaultLr, lr);
        put(F::FaultPsr, psr);
        let dfsr = cp_read!("c5, c0, 0");
        let dfar = cp_read!("c6, c0, 0");
        put(F::Dfsr, dfsr);
        put(F::Dfar, dfar);
        #[cfg(feature = "e2b-negative-test")]
        {
            let selector = get(F::ProbeSelector);
            let expected = match selector {
                1 => GPIO + 0x6c,
                2 => GPIO,
                3 => GPIO + 0x14,
                _ => 0,
            };
            if get(F::Stage) == 4
                && ((selector <= 3
                    && selector != 0
                    && kind == 3
                    && dfar as usize == expected
                    && dfsr & 0xf == 8
                    && dfsr & 0x1000 != 0)
                    || ((selector == 4 || selector == 5) && kind == 1))
            {
                put(F::Stage, 5);
                let _ = pxa_uart::ReferenceUart::init()
                    .send("CROSSHAIR E2B — EXPECTED EXCEPTION PASS\r\n");
                arch::idle();
            }
        }
        put(F::Error, 0xf000 | kind);
    }
    panic!("unexpected E2B exception");
}

#[panic_handler]
fn panic(_info: &PanicInfo<'_>) -> ! {
    mask_irq();
    // SAFETY: terminal SVC path, IRQ masked. Record and test UART are mapped
    // and exclusively owned; no interrupted caller may resume afterwards.
    unsafe {
        if get(F::Error) == 0 {
            put(F::Error, 0xbad0_0001);
        }
        put(F::Stage, 3);
        let _ = pxa_uart::ReferenceUart::init().send("CROSSHAIR E2B — FAIL\r\n");
    }
    arch::idle()
}
