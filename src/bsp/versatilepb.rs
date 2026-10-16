use crate::drivers::pl011::Pl011;

pub fn diagnostic(message: &str) -> Result<(), ()> {
    // SAFETY: QEMU v9.2.0 versatilepb.c maps UART0 here. This BSP is built
    // separately from Blue Angel. Single CPU, masked IRQ/FIQ, no DMA and no
    // concurrent call paths; a panic is terminal and cannot resume the caller.
    let mut uart = unsafe { Pl011::new(0x101f_1000) };
    uart.init();
    uart.send(message)
}
