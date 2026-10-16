//! Fixed ARMv5 legacy translation tables for the synthetic E2B task guest.
//!
//! Source contract: `src/security.rs::mmu_init` and
//! `docs/E2B_CPU_GPIO_AUDIT.md` (Q92 page walk / CP15 encodings and XScale
//! cpwait). All addresses below are guest VA or PA, never host pointers. This
//! module implements no allocator or physical-device initialization. ARMv5 has
//! no XN: the writable user pages are also executable.

use core::{
    arch::asm,
    ptr::{addr_of_mut, write_volatile},
};

pub const USER_CODE: u32 = 0x0100_0000;
pub const USER_DATA: u32 = USER_CODE + 0x1000;
/// Exclusive end of the data page accepted by the diagnostic Copy ABI.
pub const USER_END: u32 = USER_DATA + 0x1000;
pub const USER_STACK_TOP: u32 = USER_CODE + 0x4000;

const TASK_BASES: [usize; 2] = [0xa020_0000, 0xa030_0000];
const SECTION_PRIVILEGED: u32 = 0x402; // AP1, domain0, C=B=0, section.
const PAGE_USER_RO: u32 = 0xaa2; // AP2 in all four 1KiB subpages.
const PAGE_USER_RW: u32 = 0xff2; // AP3 in all four 1KiB subpages.
const CONTROL: u32 = 0x79; // MMU on; C/I/V/XP/S/R clear, reset bits retained.

#[repr(C, align(16384))]
pub struct L1(pub [u32; 4096]);
#[repr(C, align(1024))]
pub struct L2(pub [u32; 256]);

#[unsafe(no_mangle)]
pub static mut TASK_L1: [L1; 2] = [L1([0; 4096]), L1([0; 4096])];
#[unsafe(no_mangle)]
pub static mut TASK_L2: [L2; 2] = [L2([0; 256]), L2([0; 256])];

/// Physical code-page base. The linker places `.user_a` / `.user_b` here.
pub fn base(index: usize) -> usize {
    TASK_BASES[index]
}

/// Physical data-page base, disjoint from both task code and the guard page.
pub fn data(index: usize) -> usize {
    base(index) + 0x1000
}

/// Physical stack-page base. The preceding physical page is never user mapped.
pub fn stack(index: usize) -> usize {
    base(index) + 0x3000
}

/// Read SCTLR, TTBR, DACR and FCSE PID, in that order.
///
/// # Safety
/// Call only in privileged ARM state on the E2B CPU260 contract. These CP15
/// encodings are not a portable probe for an arbitrary or physical processor.
pub unsafe fn cp15() -> (u32, u32, u32, u32) {
    let sctlr: u32;
    let ttbr: u32;
    let dacr: u32;
    let pid: u32;
    // SAFETY: the caller guarantees privileged ARM state and audited CP15.
    unsafe {
        asm!("mrc p15, 0, {v}, c1, c0, 0", v=out(reg) sctlr, options(nostack, nomem));
        asm!("mrc p15, 0, {v}, c2, c0, 0", v=out(reg) ttbr, options(nostack, nomem));
        asm!("mrc p15, 0, {v}, c3, c0, 0", v=out(reg) dacr, options(nostack, nomem));
        asm!("mrc p15, 0, {v}, c13, c0, 0", v=out(reg) pid, options(nostack, nomem));
    }
    (sctlr, ttbr, dacr, pid)
}

/// Populate both address spaces and enable the MMU using task0's table.
///
/// Each task sees the same user VA layout but only its own PA code/data/stack.
/// VA `0x01002000..0x01003000` stays faulting. All synthetic RAM aliases
/// `0xa0000000..0xa8000000`, low vectors and MMIO `0x40000000..0x41000000`
/// are privileged AP1; they never provide a user route to another task.
///
/// # Safety
/// Invoke once per boot before user entry, on the sole privileged ARM CPU with
/// IRQ/FIQ masked, MMU and caches off, and no DMA/concurrent table users. The
/// linker must reserve and align these tables and all declared task pages; the
/// executing kernel, all banked stacks, vectors and tables must be within the
/// identity mappings. The caller initializes user data/stack separately. Tables
/// and task pages must remain reserved for the guest's entire lifetime.
pub unsafe fn init() {
    // SAFETY: the caller provides exclusive static table ownership before MMU
    // enable. Raw pointers avoid references to mutable statics. Each loop is
    // bounded by the corresponding fixed-size table, including array strides.
    unsafe {
        let (sctlr, _, _, _) = cp15();
        assert!(sctlr == 0x78);
        for task in 0..2 {
            let l1 = addr_of_mut!(TASK_L1).cast::<L1>().add(task).cast::<u32>();
            let l2 = addr_of_mut!(TASK_L2).cast::<L2>().add(task).cast::<u32>();
            assert!(l1 as usize & 0x3fff == 0 && l2 as usize & 0x3ff == 0);
            for word in 0..4096 {
                write_volatile(l1.add(word), 0);
            }
            for word in 0..256 {
                write_volatile(l2.add(word), 0);
            }
            write_volatile(l1, SECTION_PRIVILEGED);
            for section in 0xa00..0xa80 {
                write_volatile(
                    l1.add(section),
                    ((section as u32) << 20) | SECTION_PRIVILEGED,
                );
            }
            for section in 0x400..0x410 {
                write_volatile(
                    l1.add(section),
                    ((section as u32) << 20) | SECTION_PRIVILEGED,
                );
            }
            // Legacy coarse table, domain0 CLIENT. The AP fields apply to
            // every 1KiB subpage; no alternative user aliases are installed.
            write_volatile(l1.add((USER_CODE >> 20) as usize), l2 as u32 | 1);
            write_volatile(l2, base(task) as u32 | PAGE_USER_RO);
            write_volatile(l2.add(1), data(task) as u32 | PAGE_USER_RW);
            write_volatile(l2.add(3), stack(task) as u32 | PAGE_USER_RW);
        }
        install(0, true);
    }
}

/// Switch the current user address space, retaining common privileged aliases.
///
/// # Safety
/// `init` must have completed and `index` must select one of the two reserved
/// tasks. Execute on the sole privileged ARM CPU with IRQ/FIQ masked, outside
/// any user-page copy or borrowed user reference. Code, current banked stack
/// and exception frames must remain in the common privileged identity map.
/// Tables are immutable after initialization; caches stay off and PID stays0.
/// The caller updates its current-task identity before returning to User.
pub unsafe fn activate(index: usize) {
    assert!(index < 2);
    // SAFETY: the caller guarantees initialized tables and masked single-CPU
    // execution; the validated index selects a complete aligned table.
    unsafe { install(index, false) }
}

unsafe fn install(index: usize, enable: bool) {
    // SAFETY: only init/activate call with a validated index, exclusive table
    // ownership and common privileged mappings. With caches off, the drain
    // precedes TTBR replacement and full unified TLB invalidation discards all
    // translations from the previous task. No ASID or ARMv6+ barrier is used.
    // cpwait is the audited XScale MRC/dependent-MOV/pipeline-branch sequence.
    // QEMU's cache-maintenance NOPs do not prove real cache or drain behavior.
    unsafe {
        let table = addr_of_mut!(TASK_L1).cast::<L1>().add(index) as u32;
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
