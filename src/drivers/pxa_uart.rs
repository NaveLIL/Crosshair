//! QEMU 9.1 PXA reference UART: generic 16550 at FFUART, reg_shift=2.
//! Not a verified hardware PXA263 UART driver (UUE/clock gating are unmodelled).
use core::ptr::{read_volatile, write_volatile};

pub struct ReferenceUart;

const BASE: usize = 0x4010_0000;

impl ReferenceUart {
    /// # Safety
    /// Only on the QEMU PXA reference machines with serial backend 0 present,
    /// identity MMIO, caches off and exclusive UART ownership (no UART IRQ/DMA).
    pub unsafe fn init() -> Self {
        let mut uart = Self;
        uart.write(1, 0); // IER: UART interrupts off in the emulated 16550.
        uart.write(3, 0x80); // LCR.DLAB.
        uart.write(0, 8); // DLL, divisor for the model's baud clock.
        uart.write(1, 0); // DLM.
        uart.write(3, 3); // 8N1, DLAB off.
        uart.write(2, 7); // Enable and reset FIFO.
        uart
    }

    fn write(&mut self, register: usize, value: u32) {
        // SAFETY: constructor's contract; callers use only valid 16550 register
        // indices with 4-byte spacing and documented writable low 8 bits.
        unsafe { write_volatile((BASE + 4 * register) as *mut u32, value) }
    }

    pub fn send(&mut self, message: &str) -> Result<(), ()> {
        for byte in message.bytes() {
            let mut budget = 1_000_000u32;
            loop {
                // SAFETY: constructor contract and aligned LSR read (index 5).
                let ready = unsafe { read_volatile((BASE + 20) as *const u32) };
                if ready & 0x20 != 0 {
                    break;
                }
                budget -= 1;
                if budget == 0 {
                    return Err(());
                }
            }
            self.write(0, u32::from(byte));
        }
        Ok(())
    }
}
