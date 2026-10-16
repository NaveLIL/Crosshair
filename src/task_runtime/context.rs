//! Kernel-owned complete ARM User context. The assembler offsets are asserted.
#[repr(C)]
#[derive(Clone, Copy)]
pub struct Context {
    pub regs: [u32; 13],
    pub sp: u32,
    pub lr: u32,
    pub pc: u32,
    pub psr: u32,
    pub kind: u32,
    pub raw_lr: u32,
    pub pad: u32,
}
impl Context {
    pub const ZERO: Self = Self {
        regs: [0; 13],
        sp: 0,
        lr: 0,
        pc: 0,
        psr: 0,
        kind: 0,
        raw_lr: 0,
        pad: 0,
    };
}
const _: () = {
    assert!(core::mem::size_of::<Context>() == 80);
    assert!(core::mem::offset_of!(Context, sp) == 52);
    assert!(core::mem::offset_of!(Context, lr) == 56);
    assert!(core::mem::offset_of!(Context, pc) == 60);
    assert!(core::mem::offset_of!(Context, psr) == 64);
};
