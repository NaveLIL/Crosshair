//! Single-task isolation experiment on the unchanged synthetic E2B platform.
#![no_std]
#![no_main]

use core::{
    arch::{asm, global_asm},
    panic::PanicInfo,
    ptr::{addr_of, addr_of_mut, read_volatile, write_volatile},
};
#[path = "drivers/pxa_uart.rs"]
mod pxa_uart;
mod security_policy;
use security_policy::{ENOSYS, MAX_COPY, USER_END, checked_copy};

// SAFETY: this entry sets all used banked stacks, clears BSS and supplies
// 64-byte exception frames; user return restores a trusted SVC call frame.
global_asm!(include_str!("arch/security_entry.S"), options(raw));

const USER_CODE: u32 = 0x0100_0000;
const USER_PA: usize = 0xa020_0000;
const DATA_PA: usize = USER_PA + 4096;
const STACK_PA: usize = USER_PA + 3 * 4096;
const MAGIC: u32 = 0x5345_4355;
const PAYLOAD: &[u8] = b"CROSSHAIR USER\n";

#[unsafe(no_mangle)]
static mut CROSSHAIR_SECURITY_RECORD: [u32; 72] = [0; 72];
#[unsafe(no_mangle)]
static mut SECURITY_RESUME_SP: u32 = 0;
#[unsafe(no_mangle)]
static mut KERNEL_CANARY: [u32; 16] = [0; 16];
#[repr(C, align(8))]
struct CopyBuffer {
    before: [u32; 4],
    bytes: [u8; 64],
    after: [u32; 4],
}
#[unsafe(no_mangle)]
static mut SECURITY_COPY: CopyBuffer = CopyBuffer {
    before: [0; 4],
    bytes: [0; 64],
    after: [0; 4],
};
#[repr(C, align(16384))]
struct L1([u32; 4096]);
#[repr(C, align(1024))]
struct L2([u32; 256]);
#[unsafe(no_mangle)]
static mut SECURITY_L1: L1 = L1([0; 4096]);
#[unsafe(no_mangle)]
static mut SECURITY_L2: L2 = L2([0; 256]);

unsafe extern "C" {
    fn security_run_user(entry: u32, selector: u32);
    fn kernel_idle() -> !;
    static security_user_start: u8;
    static security_user_end: u8;
}

unsafe fn load(address: usize) -> u32 {
    // SAFETY: private callers select aligned identity-mapped own RAM/MMIO.
    unsafe { read_volatile(address as *const u32) }
}
unsafe fn store(address: usize, value: u32) {
    // SAFETY: one privileged CPU, interrupts masked; validated synthetic RAM/MMIO.
    unsafe { write_volatile(address as *mut u32, value) }
}
unsafe fn put(i: usize, v: u32) {
    // SAFETY: fixed record indices below72; no Rust references to shared state.
    unsafe {
        write_volatile(
            addr_of_mut!(CROSSHAIR_SECURITY_RECORD).cast::<u32>().add(i),
            v,
        )
    }
}
unsafe fn get(i: usize) -> u32 {
    // SAFETY: same bounded single-writer record contract as put.
    unsafe { read_volatile(addr_of!(CROSSHAIR_SECURITY_RECORD).cast::<u32>().add(i)) }
}
unsafe fn inc(i: usize) {
    // SAFETY: no nested exceptions/IRQs, one counter writer at a time.
    unsafe { put(i, get(i) + 1) }
}

fn hash(bytes: impl Iterator<Item = u8>) -> u32 {
    bytes.fold(0x811c_9dc5, |value, b| {
        (value ^ b as u32).wrapping_mul(0x0100_0193)
    })
}
unsafe fn code_hash() -> u32 {
    // SAFETY: linker bounds the immutable user ELF payload to one mapped page.
    unsafe {
        hash((USER_PA..addr_of!(security_user_end) as usize).map(|p| read_volatile(p as *const u8)))
    }
}
unsafe fn init_buffers() {
    // SAFETY: private kernel allocations are disjoint from user pages/tables.
    unsafe {
        for i in 0..16 {
            write_volatile(
                addr_of_mut!(KERNEL_CANARY).cast::<u32>().add(i),
                0xcafe_5100 ^ i as u32,
            );
        }
        for i in 0..4 {
            write_volatile(
                addr_of_mut!(SECURITY_COPY.before).cast::<u32>().add(i),
                0xace0_0000 ^ i as u32,
            );
            write_volatile(
                addr_of_mut!(SECURITY_COPY.after).cast::<u32>().add(i),
                0xace1_0000 ^ i as u32,
            );
        }
        for i in 0..64 {
            write_volatile(addr_of_mut!(SECURITY_COPY.bytes).cast::<u8>().add(i), 0xcc);
        }
    }
}
unsafe fn check_buffers() {
    // SAFETY: read only our private canaries; user AP permissions exclude them.
    unsafe {
        for i in 0..16 {
            assert!(
                read_volatile(addr_of!(KERNEL_CANARY).cast::<u32>().add(i))
                    == 0xcafe_5100 ^ i as u32
            );
        }
        for i in 0..4 {
            assert!(
                read_volatile(addr_of!(SECURITY_COPY.before).cast::<u32>().add(i))
                    == 0xace0_0000 ^ i as u32
            );
            assert!(
                read_volatile(addr_of!(SECURITY_COPY.after).cast::<u32>().add(i))
                    == 0xace1_0000 ^ i as u32
            );
        }
        put(22, 1);
        put(23, 1);
    }
}
unsafe fn init_user() {
    // SAFETY: no user context runs during reset; only these three physical pages
    // belong to the test task. Clear data/stack before each new context.
    unsafe {
        for i in 0..1024 {
            store(DATA_PA + i * 4, 0);
            store(STACK_PA + i * 4, 0);
        }
        for (i, b) in PAYLOAD.iter().enumerate() {
            write_volatile((DATA_PA + i) as *mut u8, *b);
        }
        for i in 0..64 {
            write_volatile((DATA_PA + 0x80 + i) as *mut u8, i as u8);
        }
        for off in [0x100, 0x104, 0x108] {
            store(DATA_PA + off, u32::MAX);
        }
        // Positive control: ARMv5 has no page XN. These benign user-owned words
        // execute in the RW data page, then return to the RO user code page.
        store(DATA_PA + 0x200, 0xe3a0_805a); // mov r8,#90
        store(DATA_PA + 0x204, 0xe12f_ff1e); // bx lr
        store(DATA_PA + 0x220, 0xe3a0_7001); // mov r7,#1
        store(DATA_PA + 0x224, 0xef00_0000); // ARM svc#0 outside RO ABI.
        store(DATA_PA + 0x240, 0x0000_df00); // Thumb svc#0 (16 bits).
        store(DATA_PA + 0x260, 0xe7f0_00f0); // ARM permanently undefined.
    }
}
unsafe fn mmu_init() {
    // SAFETY: exclusive own L1/L2, required linker alignment, no IRQ/DMA.
    // Domain0 is CLIENT(01), never manager. S/R remain0; caches stay disabled.
    unsafe {
        let l1 = addr_of_mut!(SECURITY_L1.0).cast::<u32>();
        let l2 = addr_of_mut!(SECURITY_L2.0).cast::<u32>();
        write_volatile(l1, 0x402); // privileged-only low vector section.
        for section in 0xa00..0xa80 {
            write_volatile(l1.add(section), ((section as u32) << 20) | 0x402);
        }
        for section in 0x400..0x410 {
            write_volatile(l1.add(section), ((section as u32) << 20) | 0x402);
        }
        write_volatile(l1.add(16), l2 as u32 | 1);
        write_volatile(l2, USER_PA as u32 | 0xaa2); // AP2 all1KiB subpages: user RO.
        write_volatile(l2.add(1), DATA_PA as u32 | 0xff2); // AP3: user RW.
        write_volatile(l2.add(3), STACK_PA as u32 | 0xff2);
        let zero = 0u32;
        let domain = 1u32;
        let control = 0x79u32;
        let tmp: u32;
        asm!("mcr p15,0,{z},c13,c0,0", "mcr p15,0,{base},c2,c0,0",
             "mcr p15,0,{domain},c3,c0,0", "mcr p15,0,{z},c8,c7,0",
             "mcr p15,0,{control},c1,c0,0", "mrc p15,0,{tmp},c2,c0,0",
             "mov {tmp},{tmp}", "sub pc,pc,#4", z=in(reg)zero,base=in(reg)l1,
             domain=in(reg)domain,control=in(reg)control,tmp=out(reg)tmp,options(nostack));
        let _ = tmp;
        let sctlr: u32;
        let ttbr: u32;
        let dacr: u32;
        let pid: u32;
        asm!("mrc p15,0,{r},c1,c0,0",r=out(reg)sctlr,options(nostack,nomem));
        asm!("mrc p15,0,{r},c2,c0,0",r=out(reg)ttbr,options(nostack,nomem));
        asm!("mrc p15,0,{r},c3,c0,0",r=out(reg)dacr,options(nostack,nomem));
        asm!("mrc p15,0,{r},c13,c0,0",r=out(reg)pid,options(nostack,nomem));
        assert!(sctlr == 0x79 && ttbr == l1 as u32 && dacr == 1 && pid == 0);
        put(29, sctlr);
        put(30, ttbr);
        put(31, dacr);
        put(62, pid);
        put(32, read_volatile(l1.add(16)));
        for i in 0..4 {
            put(33 + i, read_volatile(l2.add(i)));
        }
    }
}

#[repr(C)]
pub struct TrapFrame {
    regs: [u32; 13],
    lr: u32,
    psr: u32,
    kind: u32,
}

unsafe fn user_instruction(pc: u32, thumb: bool) -> Option<u32> {
    // SAFETY: only the three declared user pages may be inspected, through
    // their privileged physical aliases. Unknown/unaligned PC is never read.
    unsafe {
        let size = if thumb { 2 } else { 4 };
        if pc % size != 0 {
            return None;
        }
        let offset = pc.checked_sub(USER_CODE)?;
        let page = offset / 4096;
        if !matches!(page, 0 | 1 | 3) || offset % 4096 > 4096 - size {
            return None;
        }
        let physical = USER_PA + offset as usize;
        Some(if thumb {
            read_volatile(physical as *const u16) as u32
        } else {
            load(physical)
        })
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn rust_trap(pointer: *mut TrapFrame) -> u32 {
    // SAFETY: trusted assembly supplies a64B frame on a banked privileged
    // stack, inaccessible to user APs. No nested exceptions or shared references.
    unsafe {
        let f = &mut *pointer;
        let mode: u32;
        asm!("mrs {r},cpsr",r=out(reg)mode,options(nostack,nomem));
        // A privileged-origin fault is a kernel invariant violation. User
        // Thumb/state/PC choices below are rejected or terminated, never asserted.
        assert!(f.psr & 0x1f == 0x10);
        let thumb = f.psr & 0x20 != 0;
        let recovery = get(1) == 4;
        if f.kind != 2 {
            assert!(!recovery);
            put(
                4,
                if f.kind == 3 {
                    2
                } else if f.kind == 1 {
                    3
                } else {
                    4
                },
            );
            put(8, f.kind);
            put(9, f.lr);
            put(10, f.psr);
            put(44, mode);
            let dfsr: u32;
            let dfar: u32;
            asm!("mrc p15,0,{r},c5,c0,0",r=out(reg)dfsr,options(nostack,nomem));
            asm!("mrc p15,0,{r},c6,c0,0",r=out(reg)dfar,options(nostack,nomem));
            put(11, dfsr);
            put(12, dfar);
            let ifsr: u32;
            asm!("mrc p15,0,{r},c5,c0,1",r=out(reg)ifsr,options(nostack,nomem));
            put(68, ifsr);
            let pc = f.lr.wrapping_sub(if f.kind == 3 {
                8
            } else if f.kind == 4 || !thumb {
                4
            } else {
                2
            });
            let opcode = user_instruction(pc, thumb);
            put(13, opcode.unwrap_or(0));
            put(63, opcode.is_some() as u32);
            if f.kind == 1 {
                put(54, pointer as u32);
            } else {
                put(53, pointer as u32);
            }
            check_buffers();
            return 1; // Terminate task; assembly returns to saved trusted caller.
        }
        inc(67);
        let pc = f.lr.wrapping_sub(if thumb { 2 } else { 4 });
        let instruction = user_instruction(pc, thumb);
        let opcode = instruction.unwrap_or(0);
        // The narrow prototype SVC ABI permits ARM instructions only in its
        // installed RO code. Other user origins end the task, not the kernel.
        if thumb
            || pc < USER_CODE
            || pc >= USER_CODE + (addr_of!(security_user_end) as u32 - USER_PA as u32)
        {
            assert!(!recovery);
            put(4, 5);
            put(8, 2);
            put(9, f.lr);
            put(10, f.psr);
            put(13, opcode);
            put(63, instruction.is_some() as u32);
            put(44, mode);
            inc(5);
            put(14, f.lr);
            put(15, f.psr);
            put(16, opcode);
            put(17, f.regs[7]);
            put(18, f.regs[0]);
            put(19, f.regs[1]);
            put(45, mode);
            put(52, pointer as u32);
            check_buffers();
            return 1;
        }
        if f.regs[7] == 0 && opcode == 0xef00_0000 {
            if recovery {
                inc(48);
            } else {
                put(7, f.regs[0]);
                inc(47);
                put(4, 1);
            }
            return 1;
        }
        if recovery {
            inc(46);
            put(25, 0);
            put(26, f.psr);
            put(64, f.lr);
            put(65, opcode);
            put(66, f.regs[7]);
            put(69, mode);
        } else {
            inc(5);
            put(14, f.lr);
            put(15, f.psr);
            put(16, opcode);
            put(17, f.regs[7]);
            put(18, f.regs[0]);
            put(19, f.regs[1]);
            put(45, mode);
            put(52, pointer as u32);
        }
        let result = if opcode != 0xef00_0000 {
            if !recovery {
                inc(49);
            }
            Err(ENOSYS)
        } else if f.regs[7] != 1 {
            if !recovery {
                inc(50);
            }
            Err(ENOSYS)
        } else {
            checked_copy(f.regs[0], f.regs[1])
        };
        let ret = match result {
            Err(errno) => {
                if !recovery && opcode == 0xef00_0000 && f.regs[7] == 1 {
                    inc(51);
                }
                errno
            }
            Ok(len) => {
                // Pointer/length arithmetic and entire source region were
                // validated before even the first dereference. No user access
                // can race this single-CPU, IRQ/DMA-free bounded copy.
                for i in 0..len {
                    let b = read_volatile((f.regs[0] as usize + i) as *const u8);
                    write_volatile(addr_of_mut!(SECURITY_COPY.bytes).cast::<u8>().add(i), b);
                }
                let digest = hash(
                    (0..len)
                        .map(|i| read_volatile(addr_of!(SECURITY_COPY.bytes).cast::<u8>().add(i))),
                );
                inc(43);
                if recovery {
                    put(42, digest);
                } else {
                    put(20, len as u32);
                    put(21, digest);
                }
                len as u32
            }
        };
        if recovery {
            put(25, ret);
        } else {
            put(6, ret);
        }
        f.regs[0] = ret;
        check_buffers();
        0 // Return to the actual user SVC LR.
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn rust_main() -> ! {
    // SAFETY: own entry initialized privileged stacks/BSS with IRQ/FIQ masked;
    // only this synthetic RAM/MMIO contract is used, never physical hardware.
    unsafe {
        assert!(get(1) == 0);
        put(0, MAGIC);
        put(1, 1);
        let selector = load(0xa000_0100);
        assert!(selector < 24);
        put(3, selector);
        put(56, 24);
        put(57, MAX_COPY);
        put(58, USER_END);
        assert!(addr_of!(security_user_start) as usize == USER_PA);
        let code_len = addr_of!(security_user_end) as usize - USER_PA;
        put(59, code_len as u32);
        for p in USER_PA + code_len..USER_PA + 4096 {
            write_volatile(p as *mut u8, 0);
        }
        let id: u32;
        asm!("mrc p15,0,{r},c0,c0,0",r=out(reg)id,options(nostack,nomem));
        assert!(id == 0x6905_2903);
        put(28, id);
        init_buffers();
        init_user();
        put(70, code_hash());
        mmu_init();
        put(40, USER_CODE);
        put(1, 2);
        security_run_user(USER_CODE, selector);
        inc(41);
        put(37, load(DATA_PA + 0x100));
        put(38, load(DATA_PA + 0x104));
        put(39, load(DATA_PA + 0x108));
        put(55, read_volatile(addr_of!(SECURITY_RESUME_SP)));
        check_buffers();
        // Outcome/exit-code expectations belong to the external test oracle.
        // User exit values and trapped failures never select a kernel panic.
        put(1, 3);
        init_buffers();
        init_user();
        put(1, 4);
        security_run_user(USER_CODE, 0);
        inc(41);
        put(60, load(DATA_PA + 0x100));
        put(61, load(DATA_PA + 0x104));
        put(27, load(DATA_PA + 0x104));
        assert!(
            get(25) == 15
                && get(60) == 15
                && get(61) & 0xff == 0xd0
                && get(46) == 1
                && get(48) == 1
        );
        check_buffers();
        put(71, code_hash());
        assert!(get(70) == get(71));
        put(24, 1);
        let mut uart = pxa_uart::ReferenceUart::init();
        put(1, 5);
        assert!(
            uart.send("CROSSHAIR SECURITY — USER ISOLATION PASS\r\n")
                .is_ok()
        );
        kernel_idle()
    }
}
#[panic_handler]
fn panic(_: &PanicInfo<'_>) -> ! {
    // SAFETY: own privileged exception/kernel RAM stays mapped; terminal halt.
    unsafe {
        put(2, 0xdead);
        put(1, 0xff);
        kernel_idle()
    }
}
