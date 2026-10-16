//! HaRET compile-only adapter. No PDA MMIO is accessed.
//! A bounded memory log lives in this image's RAM. Its recovery on a physical
//! device is NOT established; it can currently be inspected only in an emulator
//! or debugger that maps this linked region. It survives neither BSS reset nor
//! an assumed return to Windows Mobile.
use core::ptr::{addr_of_mut, write_volatile};

// SAFETY: single boot CPU owns this fixed BSS buffer, with IRQ/FIQ masked.
#[unsafe(no_mangle)]
static mut BLUEANGEL_RAM_LOG: [u8; 96] = [0; 96];

pub fn diagnostic(message: &str) -> Result<(), ()> {
    if message.len() > 96 {
        return Err(());
    }
    // SAFETY: bounds checked above; no concurrent users or reference aliases.
    // Writes go to a linker-allocated buffer, not to a guessed hardware address.
    unsafe {
        let p = addr_of_mut!(BLUEANGEL_RAM_LOG).cast::<u8>();
        for (index, byte) in message.bytes().enumerate() {
            write_volatile(p.add(index), byte);
        }
    }
    Ok(())
}
