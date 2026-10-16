#![no_std]
#![no_main]
#![deny(unsafe_op_in_unsafe_fn)]

//! Executable PXA255/PXA270 reference test, not a Blue Angel BSP.
//! Exact model register contracts: docs/PXA_REFERENCE_CONTRACT.md.
mod arch;
#[path = "drivers/pxa_uart.rs"]
mod pxa_uart;

use core::arch::asm;
use core::panic::PanicInfo;
use core::ptr::{addr_of_mut, read_volatile, write_volatile};

const TIMER: usize = 0x40a0_0000;
const PIC: usize = 0x40d0_0000;
const TIMER_IRQ: u32 = 1 << 26;
const INTERVAL: u32 = 65_536;
#[cfg(not(feature = "e2a"))]
const PASS: &str = "CROSSHAIR PXA REFERENCE — UART TIMER IRQ PASS\r\n";
#[cfg(feature = "e2a")]
const PASS: &str = "CROSSHAIR E2A — UART TIMER IRQ PASS\r\n";

// The negative-test mailbox is in synthetic RAM outside all ELF load segments
// and BSS. QEMU's ROM reset restores ELF .data after data-loader reset hooks,
// so a .data selector would silently revert to its compiled default on reset.
// This address is an emulator test contract, never a physical BSP reservation.
#[cfg(feature = "e2a-mmio-test")]
core::arch::global_asm!(
    ".global CROSSHAIR_E2A_FAULT_SELECTOR",
    ".set CROSSHAIR_E2A_FAULT_SELECTOR, 0xa0000100"
);
#[cfg(feature = "e2a-mmio-test")]
unsafe extern "C" {
    static mut CROSSHAIR_E2A_FAULT_SELECTOR: u32;
}

#[repr(C)]
pub struct ReferenceRecord {
    magic: u32,
    stage: u32,
    irq_count: u32,
    first_counter: u32,
    last_counter: u32,
    cpu_id: u32,
    error: u32,
    pending_seen: u32,
    status_seen: u32,
    mask_done: u32,
    status_done: u32,
    irq_sp: u32,
}

// SAFETY: only the boot CPU accesses this record. Main reads shared fields with
// IRQ masked; the non-nested handler owns them while running on its IRQ stack.
#[unsafe(no_mangle)]
pub static mut CROSSHAIR_PXA_RECORD: ReferenceRecord = ReferenceRecord {
    magic: 0,
    stage: 0,
    irq_count: 0,
    first_counter: 0,
    last_counter: 0,
    cpu_id: 0,
    error: 0,
    pending_seen: 0,
    status_seen: 0,
    mask_done: 0,
    status_done: 0,
    irq_sp: 0,
};

unsafe fn read(address: usize) -> u32 {
    // SAFETY: private callers use only the mapped, aligned model registers.
    unsafe { read_volatile(address as *const u32) }
}

unsafe fn write(address: usize, value: u32) {
    // SAFETY: private callers use only mapped writable model registers, with
    // IRQ serialized and documented effects; never used by a hardware BSP.
    unsafe { write_volatile(address as *mut u32, value) }
}

fn mask_irq() -> u32 {
    let saved: u32;
    let masked: u32;
    // SAFETY: privileged ARM state. No stack change, FIQ remains masked. The
    // default memory clobber prevents accesses crossing this critical boundary.
    unsafe {
        asm!("mrs {saved}, cpsr", "orr {masked}, {saved}, #0x80", "msr cpsr_c, {masked}",
             saved = out(reg) saved, masked = out(reg) masked, options(nostack));
    }
    let _ = masked;
    saved
}

unsafe fn restore_irq(saved: u32) {
    // SAFETY: only restore the control byte saved in this same privileged mode;
    // no live references into IRQ-owned memory may cross this call.
    unsafe {
        asm!("msr cpsr_c, {saved}", saved = in(reg) saved, options(nostack));
    }
}

// SAFETY: called only through entry.S after stack/BSS setup. No inherited ABI
// pointers are used; the generic ELF loader does not supply Linux ATAG state.
#[unsafe(no_mangle)]
pub extern "C" fn rust_main() -> ! {
    let mut uart = unsafe {
        // SAFETY: this binary is linked/run only on the documented QEMU PXA
        // machines with serial0 instantiated; no UART interrupts or DMA users.
        pxa_uart::ReferenceUart::init()
    };
    // SAFETY: entry established SVC, low vectors and both banked stacks; all
    // accesses below are to documented model MMIO or private in-image BSS.
    unsafe {
        assert!(read_volatile(addr_of_mut!(CROSSHAIR_PXA_RECORD.stage)) == 0);
        write_volatile(addr_of_mut!(CROSSHAIR_PXA_RECORD.magic), 0x5058_4152);
        write_volatile(addr_of_mut!(CROSSHAIR_PXA_RECORD.stage), 1);
        let cpuid: u32;
        asm!("mrc p15, 0, {id}, c0, c0, 0", id=out(reg) cpuid, options(nostack, nomem));
        write_volatile(addr_of_mut!(CROSSHAIR_PXA_RECORD.cpu_id), cpuid);
        #[cfg(feature = "e2a-mmio-test")]
        fault_probe();
        write(PIC + 4, 0); // ICMR: mask everything during explicit init.
        write(PIC + 8, 0); // ICLR: route to IRQ, not FIQ.
        write(TIMER + 0x1c, 0); // OIER.
        for offset in [0, 4, 8, 12] {
            write(TIMER + offset, u32::MAX); // Keep old compare values far away.
        }
        write(TIMER + 0x10, 0); // OSCR.
        write(TIMER + 0x14, 0xf); // OSSR W1C after counter reinitialization.
        write(TIMER + 0x1c, 1);
        // Enable the source before setting a future compare. In this model a
        // match reached while OIER=0 is discarded, rather than latched.
        write(TIMER, read(TIMER + 0x10).wrapping_add(INTERVAL));
        write(PIC + 4, TIMER_IRQ);
        restore_irq(0x53); // SVC ARM, FIQ masked, IRQ enabled after full setup.
    }
    let mut complete = false;
    for _ in 0..20_000_000 {
        let saved = mask_irq();
        // SAFETY: main holds the IRQ mask, so the handler cannot mutate count.
        let count = unsafe { read_volatile(addr_of_mut!(CROSSHAIR_PXA_RECORD.irq_count)) };
        // SAFETY: all raw accesses completed; restore this iteration's state.
        unsafe {
            restore_irq(saved);
        }
        if count >= 3 {
            complete = true;
            break;
        }
    }
    mask_irq();
    // SAFETY: interrupts now disabled; record and peripheral ownership returns
    // to main, with no reference aliases or concurrent writers.
    unsafe {
        write(TIMER + 0x1c, 0);
        write(PIC + 4, 0);
        let p = addr_of_mut!(CROSSHAIR_PXA_RECORD);
        let count = read_volatile(addr_of_mut!((*p).irq_count));
        let first = read_volatile(addr_of_mut!((*p).first_counter));
        let last = read_volatile(addr_of_mut!((*p).last_counter));
        // QEMU floors deadline ns and counter ticks independently, so an
        // interrupt can observe one tick less than its programmed interval.
        assert!(
            complete
                && count == 3
                && first >= INTERVAL - 1
                && last.wrapping_sub(first) >= 2 * (INTERVAL - 1)
        );
        assert!(read_volatile(addr_of_mut!((*p).error)) == 0);
        let mask = read(PIC + 4);
        let status = read(TIMER + 0x14);
        assert!(mask == 0 && status & 1 == 0);
        write_volatile(addr_of_mut!((*p).mask_done), mask);
        write_volatile(addr_of_mut!((*p).status_done), status);
        write_volatile(addr_of_mut!((*p).stage), 2);
    }
    if uart.send(PASS).is_err() {
        // SAFETY: exclusive record ownership with IRQ masked.
        unsafe {
            write_volatile(addr_of_mut!(CROSSHAIR_PXA_RECORD.stage), 4);
        }
    }
    arch::idle()
}

// SAFETY: IRQ assembly saves all C caller-saved registers and adjusted LR,
// maintains AAPCS stack alignment, and restores SPSR on exception return.
#[unsafe(no_mangle)]
pub extern "C" fn rust_irq() {
    // SAFETY: IRQ/FIQ masked during handler, no nesting; all registers are from
    // this QEMU reference's model map and all record fields are privately owned.
    unsafe {
        let pending = read(PIC);
        let status = read(TIMER + 0x14);
        let p = addr_of_mut!(CROSSHAIR_PXA_RECORD);
        if pending & TIMER_IRQ == 0 || status & 1 == 0 {
            write_volatile(addr_of_mut!((*p).error), 1);
            write(PIC + 4, 0);
            return;
        }
        let now = read(TIMER + 0x10);
        write(TIMER + 0x14, 1); // Acknowledge the source before exception return.
        let count = read_volatile(addr_of_mut!((*p).irq_count)) + 1;
        if count == 1 {
            write_volatile(addr_of_mut!((*p).first_counter), now);
        }
        write_volatile(addr_of_mut!((*p).last_counter), now);
        write_volatile(addr_of_mut!((*p).pending_seen), pending);
        write_volatile(addr_of_mut!((*p).status_seen), status);
        let sp: u32;
        asm!("mov {sp}, sp", sp=out(reg) sp, options(nostack, nomem));
        write_volatile(addr_of_mut!((*p).irq_sp), sp);
        write_volatile(addr_of_mut!((*p).irq_count), count);
        if count < 3 {
            write(TIMER, now.wrapping_add(INTERVAL));
        } else {
            write(TIMER + 0x1c, 0);
            write(PIC + 4, 0);
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn rust_fault() -> ! {
    #[cfg(feature = "e2a-mmio-test")]
    {
        // SAFETY: the abort vector switched to SVC and reloaded our stack.
        // Only the synthetic emulator model reaches this test; CP15 fault
        // registers are read-only diagnostic state. IRQ remains masked.
        unsafe {
            let dfsr: u32;
            let dfar: u32;
            asm!("mrc p15, 0, {s}, c5, c0, 0", "mrc p15, 0, {a}, c6, c0, 0",
                 s = out(reg) dfsr, a = out(reg) dfar, options(nostack, nomem));
            let selector = read_volatile(addr_of_mut!(CROSSHAIR_E2A_FAULT_SELECTOR));
            let expected = match selector {
                1 => TIMER + 0x20,
                2 => PIC,
                3 => TIMER + 0x10,
                4 => 0x5000_0000,
                _ => 0,
            };
            let p = addr_of_mut!(CROSSHAIR_PXA_RECORD);
            write_volatile(addr_of_mut!((*p).pending_seen), dfsr);
            write_volatile(addr_of_mut!((*p).status_seen), dfar);
            if read_volatile(addr_of_mut!((*p).error)) == selector
                && expected != 0
                && dfar as usize == expected
                && dfsr & 0xf == 8
            {
                write_volatile(addr_of_mut!((*p).stage), 5);
                let _ = pxa_uart::ReferenceUart::init().send("CROSSHAIR E2A — DATA ABORT PASS\r\n");
                arch::idle();
            }
        }
    }
    panic!("PXA reference exception");
}

#[cfg(feature = "e2a-mmio-test")]
unsafe fn fault_probe() {
    // SAFETY: isolated emulator negative-test binary only. The addresses are
    // deliberately invalid under its strict E2A contract. Each transaction
    // must enter the real ARM data-abort vector; reaching the final panic is
    // a test failure. No hardware build can enable this code implicitly.
    unsafe {
        let selector = read_volatile(addr_of_mut!(CROSSHAIR_E2A_FAULT_SELECTOR));
        write_volatile(addr_of_mut!(CROSSHAIR_PXA_RECORD.error), selector);
        match selector {
            1 => {
                let _ = read(TIMER + 0x20);
            }
            2 => write(PIC, 1),
            3 => {
                let _ = read_volatile((TIMER + 0x10) as *const u8);
            }
            4 => {
                let _ = read(0x5000_0000);
            }
            _ => panic!("invalid fault selector"),
        }
        panic!("MMIO transaction failed to abort");
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo<'_>) -> ! {
    mask_irq();
    // SAFETY: IRQ masked; this is terminal, so UART ownership cannot return to
    // an interrupted sender. Record is always in mapped RAM in this ELF.
    unsafe {
        write_volatile(addr_of_mut!(CROSSHAIR_PXA_RECORD.stage), 3);
        let _ = pxa_uart::ReferenceUart::init().send("CROSSHAIR PXA REFERENCE — FAIL\r\n");
    }
    arch::idle()
}
