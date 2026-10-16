//! Polled PL011 transmit, currently used only by QEMU VersatilePB.
//! Register contract: QEMU v9.2.0 hw/char/pl011.c; see BOOT.md.
use core::ptr::{read_volatile, write_volatile};

pub struct Pl011 {
    base: usize,
}

impl Pl011 {
    /// # Safety
    /// `base` must be a mapped, aligned PL011 register bank exclusively owned
    /// by this caller. MMU/caches must permit Device MMIO; IRQ/DMA users absent.
    pub unsafe fn new(base: usize) -> Self {
        Self { base }
    }

    fn read(&self, offset: usize) -> u32 {
        // SAFETY: the constructor contract establishes the mapped bank; all
        // offsets used here are aligned, documented 32-bit PL011 registers.
        unsafe { read_volatile((self.base + offset) as *const u32) }
    }

    fn write(&mut self, offset: usize, value: u32) {
        // SAFETY: same mapped/exclusive bank contract; callers use only the
        // documented writable 32-bit registers listed below.
        unsafe { write_volatile((self.base + offset) as *mut u32, value) }
    }

    pub fn init(&mut self) {
        self.write(0x30, 0); // CR: disable during setup (fresh QEMU reset).
        self.write(0x38, 0); // IMSC: no UART IRQs.
        self.write(0x44, 0x7ff); // ICR: clear pending IRQs.
        self.write(0x48, 0); // DMACR: no DMA.
        // Versatile UART clock 24 MHz / (16 * 115200) = 13 + 1/64.
        self.write(0x24, 13); // IBRD.
        self.write(0x28, 1); // FBRD.
        self.write(0x2c, 0x60); // LCR_H: 8 bits, no parity, one stop, FIFO off.
        self.write(0x30, 0x101); // CR: UARTEN | TXE.
    }

    pub fn send(&mut self, message: &str) -> Result<(), ()> {
        for byte in message.bytes() {
            let mut remaining = 1_000_000u32;
            while self.read(0x18) & (1 << 5) != 0 {
                remaining -= 1;
                if remaining == 0 {
                    return Err(());
                }
            }
            self.write(0, u32::from(byte));
        }
        Ok(())
    }
}
