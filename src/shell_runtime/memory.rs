//! ARMv5 legacy tables for the separate synthetic Shell experiment.
//!
//! Source contract: `src/task_runtime/memory.rs` and
//! `docs/E2B_CPU_GPIO_AUDIT.md` (Q92 page walk, CP15 encodings and XScale
//! cpwait). Addresses are guest VA/PA. The existing task guest is unchanged;
//! this module does not initialize a physical PDA. ARMv5 provides no page XN.
use core::{
    arch::asm,
    ptr::{addr_of_mut, write_volatile},
};

pub const SHELL_BASE: usize = 0xa040_0000;
pub const USER_CODE: u32 = 0x0100_0000;
pub const DATA: u32 = 0x0101_0000;
pub const DATA_END: u32 = 0x0103_f000;
pub const STACK_TOP: u32 = 0x0104_8000;
pub const FB: u32 = DATA + 0x40;

const PRIVILEGED: u32 = 0x402; // Section AP1/domain0/C=B=0.
const USER_RO: u32 = 0xaa2; // Small page AP2 in every1KiB subpage.
const USER_RW: u32 = 0xff2; // Small page AP3 in every1KiB subpage.
const CONTROL: u32 = 0x79; // M=1; C/I/V/XP/S/R remain0.

#[repr(C, align(16384))]
pub struct L1(pub [u32; 4096]);
#[repr(C, align(1024))]
pub struct L2(pub [u32; 256]);
#[unsafe(no_mangle)]
pub static mut SHELL_L1: [L1; 2] = [L1([0; 4096]), L1([0; 4096])];
#[unsafe(no_mangle)]
pub static mut SHELL_L2: [L2; 2] = [L2([0; 256]), L2([0; 256])];

/// Translate a validated Shell VA to its privileged physical alias.
///
/// This arithmetic covers the reserved extent, including the guard hole; it
/// grants no permission and does not validate a syscall range. Callers must
/// validate ownership, mapped pages and the complete byte range before access.
/// An address outside the Shell reserved extent is rejected before subtraction.
pub fn pa(va: u32) -> usize {
    assert!((USER_CODE..STACK_TOP).contains(&va));
    SHELL_BASE + (va - USER_CODE) as usize
}

/// Read SCTLR, TTBR, DACR and FCSE PID, in that order.
///
/// # Safety
/// Execute only in privileged ARM state on the audited synthetic CPU260
/// contract. These encodings are not a generic physical-processor probe.
pub unsafe fn cp15() -> (u32, u32, u32, u32) {
    let sctlr: u32;
    let ttbr: u32;
    let dacr: u32;
    let pid: u32;
    // SAFETY: the caller guarantees privileged state and supported registers.
    unsafe {
        asm!("mrc p15, 0, {v}, c1, c0, 0", v=out(reg) sctlr, options(nostack, nomem));
        asm!("mrc p15, 0, {v}, c2, c0, 0", v=out(reg) ttbr, options(nostack, nomem));
        asm!("mrc p15, 0, {v}, c3, c0, 0", v=out(reg) dacr, options(nostack, nomem));
        asm!("mrc p15, 0, {v}, c13, c0, 0", v=out(reg) pid, options(nostack, nomem));
    }
    (sctlr, ttbr, dacr, pid)
}

/// Create Busy task0 and Shell task1 spaces; enable the MMU using task0.
///
/// Only each task's own code/data/stack pages are User accessible. Low vectors,
/// kernel RAM aliases `[a0000000,a8000000)`, peripherals
/// `[40000000,41000000)` and the synthetic display/input section at10000000
/// have privileged AP1 mappings in both spaces. All other descriptors fault.
///
/// # Safety
/// Call once per boot before User entry, on one privileged ARM CPU with IRQ/FIQ
/// masked, no DMA or other table users, and reset SCTLR0x78 (MMU/caches off).
/// The linker must align/reserve these tables, kernel and all User allocations.
/// Executing code, banked stacks, frames and tables must fit the common RAM
/// identity map. The caller initializes task data/stacks separately. No task
/// page, table or context allocation may be reused until the whole guest ends.
pub unsafe fn init() {
    // SAFETY: exclusive pre-entry table initialization. Raw pointers avoid
    // mutable-static references; every index is bounded by its actual array.
    unsafe {
        assert!(cp15().0 == 0x78);
        for task in 0..2 {
            let l1 = addr_of_mut!(SHELL_L1).cast::<L1>().add(task).cast::<u32>();
            let l2 = addr_of_mut!(SHELL_L2).cast::<L2>().add(task).cast::<u32>();
            assert!(l1 as usize & 0x3fff == 0 && l2 as usize & 0x3ff == 0);
            for word in 0..4096 {
                write_volatile(l1.add(word), 0);
            }
            for word in 0..256 {
                write_volatile(l2.add(word), 0);
            }
            write_volatile(l1, PRIVILEGED);
            for section in 0xa00..0xa80 {
                write_volatile(l1.add(section), ((section as u32) << 20) | PRIVILEGED);
            }
            for section in 0x400..0x410 {
                write_volatile(l1.add(section), ((section as u32) << 20) | PRIVILEGED);
            }
            write_volatile(l1.add(0x100), 0x1000_0000 | PRIVILEGED);
            write_volatile(l1.add((USER_CODE >> 20) as usize), l2 as u32 | 1);
            if task == 0 {
                write_volatile(l2, 0xa020_0000 | USER_RO);
                write_volatile(l2.add(1), 0xa020_1000 | USER_RW);
                // Page2 is a faulting guard; only page3 supplies its stack.
                write_volatile(l2.add(3), 0xa020_3000 | USER_RW);
            } else {
                for page in 0..16 {
                    write_volatile(l2.add(page), (SHELL_BASE + page * 4096) as u32 | USER_RO);
                }
                for page in 16..63 {
                    write_volatile(l2.add(page), (SHELL_BASE + page * 4096) as u32 | USER_RW);
                }
                // Page63 is the faulting guard below the32KiB User stack.
                for page in 64..72 {
                    write_volatile(l2.add(page), (SHELL_BASE + page * 4096) as u32 | USER_RW);
                }
            }
        }
        install(0, true);
    }
}

/// Install one initialized address space with full unified TLB invalidation.
///
/// # Safety
/// `init` has completed and index selects Busy0 or Shell1. Call on the sole
/// privileged ARM CPU with IRQ/FIQ masked, caches off and no DMA. All validated
/// User copies and borrowed User references must have ended before switching.
/// Executing code/current banked stack/frames remain in common privileged RAM.
/// Tables stay immutable and allocations stay reserved for the guest lifetime.
/// The caller makes current-task identity consistent before returning to User.
pub unsafe fn activate(index: usize) {
    assert!(index < 2);
    // SAFETY: the caller supplies initialized tables and the switching contract.
    unsafe { install(index, false) }
}

unsafe fn install(index: usize, enable: bool) {
    // SAFETY: only validated init/activate call this routine. Drain before TTBR
    // replacement; PID0 and domain0 CLIENT; no ASID or ARMv6+ barrier. The full
    // unified TLBI removes the previous task's translations. XScale cpwait is
    // MRC TTBR/dependent MOV/pipeline branch. QEMU cache-maintenance NOPs cannot
    // establish real hardware ordering, cache coherence or drain completion.
    unsafe {
        let table = addr_of_mut!(SHELL_L1).cast::<L1>().add(index) as u32;
        let zero = 0u32;
        let client = 1u32;
        let wait: u32;
        asm!(
            "mcr p15, 0, {zero}, c7, c10, 4",
            "mcr p15, 0, {zero}, c13, c0, 0",
            "mcr p15, 0, {client}, c3, c0, 0",
            "mcr p15, 0, {table}, c2, c0, 0",
            "mcr p15, 0, {zero}, c8, c7, 0",
            "mcr p15, 0, {zero}, c7, c5, 4",
            "mrc p15, 0, {wait}, c2, c0, 0",
            "mov {wait}, {wait}",
            "sub pc, pc, #4",
            zero=in(reg) zero, client=in(reg) client, table=in(reg) table,
            wait=out(reg) wait, options(nostack),
        );
        let _ = wait;
        if enable {
            let wait: u32;
            asm!(
                "mcr p15, 0, {control}, c1, c0, 0",
                "mrc p15, 0, {wait}, c2, c0, 0",
                "mov {wait}, {wait}",
                "sub pc, pc, #4",
                control=in(reg) CONTROL, wait=out(reg) wait, options(nostack),
            );
            let _ = wait;
        }
    }
}
