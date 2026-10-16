#![no_std]
#![no_main]
#![deny(unsafe_op_in_unsafe_fn)]

mod arch;
#[cfg(feature = "versatilepb")]
#[path = "bsp/versatilepb.rs"]
mod bsp;
#[cfg(feature = "blueangel")]
#[path = "bsp/blueangel.rs"]
mod bsp;
#[cfg(feature = "versatilepb")]
mod drivers;

use core::panic::PanicInfo;
use core::ptr::{addr_of_mut, read_volatile, write_volatile};

const BANNER: &str = "CROSSHAIR BOOT 0.1 — HELLO FROM RUST\r\n";

#[repr(C)]
pub struct BootRecord {
    magic: u32,
    stage: u32, // 1=Rust entered, 2=idle, 3=panic, 4=UART timeout.
    incoming: [u32; 3],
    length: u32,
    message: [u8; 96],
}

// SAFETY: entry.S clears BSS before entry. This symbol's fixed C layout is
// deliberately visible to a stopped debugger. Only the single boot CPU writes.
#[unsafe(no_mangle)]
pub static mut CROSSHAIR_BOOT_RECORD: BootRecord = BootRecord {
    magic: 0,
    stage: 0,
    incoming: [0; 3],
    length: 0,
    message: [0; 96],
};

// A real initialized-data load, also checked at runtime (not constant folded).
static mut DATA_CHECK: u32 = 0x4352_4f53;

fn record(stage: u32, message: &str) {
    // SAFETY: single boot CPU, IRQ/FIQ disabled, no DMA/other aliases to this
    // in-image record. Bounds are capped at 96. Volatile keeps debugger evidence.
    unsafe {
        let p = addr_of_mut!(CROSSHAIR_BOOT_RECORD);
        write_volatile(addr_of_mut!((*p).magic), 0x4352_4f53);
        let len = message.len().min(96);
        for (i, byte) in message.bytes().take(len).enumerate() {
            write_volatile(addr_of_mut!((*p).message).cast::<u8>().add(i), byte);
        }
        write_volatile(addr_of_mut!((*p).length), len as u32);
        write_volatile(addr_of_mut!((*p).stage), stage);
    }
}

// SAFETY: entry.S is the sole caller, with an AAPCS-aligned valid stack and
// initialized RAM. r0-r2 are passed as integers; never treated as valid pointers.
#[unsafe(no_mangle)]
pub extern "C" fn rust_main(r0: u32, r1: u32, r2: u32) -> ! {
    // SAFETY: these statics reside within the linker-defined image RAM. No
    // concurrent writer exists. Reads deliberately verify BSS and data setup.
    unsafe {
        assert!(read_volatile(addr_of_mut!(CROSSHAIR_BOOT_RECORD.stage)) == 0);
        assert!(read_volatile(addr_of_mut!(DATA_CHECK)) == 0x4352_4f53);
        write_volatile(addr_of_mut!(CROSSHAIR_BOOT_RECORD.incoming), [r0, r1, r2]);
    }
    record(1, BANNER);
    #[cfg(feature = "panic-test")]
    panic!("requested panic-path test");
    #[cfg(not(feature = "panic-test"))]
    {
        if bsp::diagnostic(BANNER).is_err() {
            record(4, "CROSSHAIR UART TIMEOUT\r\n");
        } else {
            record(2, BANNER);
        }
        arch::idle()
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo<'_>) -> ! {
    const MESSAGE: &str = "CROSSHAIR PANIC — HALTED\r\n";
    record(3, MESSAGE);
    let _ = bsp::diagnostic(MESSAGE);
    arch::idle()
}
