use core::arch::global_asm;

// SAFETY: entry.S follows the linker memory contract, initializes an aligned
// stack and BSS before entering Rust, and never returns through a foreign LR.
#[cfg(not(any(feature = "pxa-reference", feature = "e2b")))]
global_asm!(include_str!("entry.S"));
// SAFETY: this reference-only entry also installs the banked IRQ stack and
// vectors. The synthetic QEMU flash segment is part of the ELF loader contract.
#[cfg(feature = "pxa-reference")]
global_asm!(include_str!("pxa_entry.S"), options(raw));
// SAFETY: the E2B entry supplies the same two stacks, with distinct exception
// vectors that pass the fault class, exception LR and SPSR to the Rust probe.
#[cfg(feature = "e2b")]
global_asm!(include_str!("e2b_entry.S"), options(raw));

unsafe extern "C" {
    fn kernel_idle() -> !;
}

pub fn idle() -> ! {
    // SAFETY: entry.S defines a non-returning ARM branch loop, with no memory
    // access or stack preconditions beyond the already established CPU state.
    unsafe { kernel_idle() }
}
