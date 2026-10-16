//! Privileged brokers for a separately linked User Shell on synthetic display.
//!
//! Unsafe boundary: one CPU with IRQ/FIQ masked throughout every handler;
//! assembly owns the banked80B frame, tables/pages are never freed or aliased
//! with Task/queue storage. Private volatile helpers access aligned own kernel
//! RAM or the unchanged synthetic MMIO contract. All User ranges are checked
//! before translation/copy; no borrowed User reference crosses TTBR changes.
//! PRESENT reads the sole User buffer synchronously while that User is stopped
//! in SVC. No DMA, caches, physical-device access or nested IRQ is assumed.
#![no_std]
#![no_main]
use core::{
    arch::{asm, global_asm},
    panic::PanicInfo,
    ptr::{addr_of, addr_of_mut, read_volatile, write_volatile},
};
#[path = "shell_runtime/memory.rs"]
mod memory;
#[allow(dead_code)]
mod security_policy;
#[allow(dead_code)]
mod task_runtime;
#[path = "drivers/pxa_uart.rs"]
mod uart;
use task_runtime::{EXITED, FAULTED, READY, RUNNING, TASKS, context::Context, scheduler};
const WAITING: u32 = 4;
const TIMER: usize = 0x40a00000;
const PIC: usize = 0x40d00000;
const DISPLAY: usize = 0x10000000;
const INPUT: usize = 0x10001000;
const EFAULT: u32 = (-14i32) as u32;
const EINVAL: u32 = (-22i32) as u32;
const ENOSYS: u32 = (-38i32) as u32;
const EPERM: u32 = (-1i32) as u32;
global_asm!(include_str!("arch/tasks_entry.S"), options(raw));
global_asm!(include_str!("arch/task_workloads.S"), options(raw));
global_asm!(include_str!("arch/shell_probe.S"), options(raw));
global_asm!(
    concat!(
        ".section .shell.user,\"ax\",%progbits\n.global shell_payload_start\nshell_payload_start:\n.incbin \"",
        env!("CARGO_MANIFEST_DIR"),
        "/target/artifacts/shell/user-image/crosshair-shell-user.bin\"\n.global shell_payload_end\nshell_payload_end:\n"
    ),
    options(raw)
);
#[unsafe(no_mangle)]
static mut CROSSHAIR_SHELL_RECORD: [u32; 32] = [0; 32];
#[unsafe(no_mangle)]
static mut TASK_CANARY: [u32; 16] = [0; 16];
#[unsafe(no_mangle)]
static mut SHELL_EVENT_QUEUE: [u32; 4] = [0; 4];
static mut QUEUE_HEAD: usize = 0;
#[repr(C, align(8))]
struct IdleStack([u32; 1024]);
#[unsafe(no_mangle)]
static mut SHELL_IDLE_STACK: IdleStack = IdleStack([0; 1024]);
#[unsafe(no_mangle)]
static mut SHELL_IDLE_CONTEXT: Context = Context::ZERO;
global_asm!(
    ".section .text.shell_idle,\"ax\",%progbits\n.global shell_idle_loop\nshell_idle_loop:\nb shell_idle_loop",
    options(raw)
);
unsafe extern "C" {
    fn task_enter(p: *const Context) -> !;
    fn kernel_idle() -> !;
    static __image_end: u8;
    static _start: u8;
    static __stack_bottom: u8;
    static __stack_top: u8;
    static __irq_stack_bottom: u8;
    static __irq_stack_top: u8;
    static __abort_stack_bottom: u8;
    static __abort_stack_top: u8;
    static __undef_stack_bottom: u8;
    static __undef_stack_top: u8;
    fn shell_idle_loop();
    static shell_role_probe: u8;
}
unsafe fn load(p: usize) -> u32 {
    unsafe { read_volatile(p as *const u32) }
}
unsafe fn store(p: usize, v: u32) {
    unsafe { write_volatile(p as *mut u32, v) }
}
unsafe fn get(i: usize) -> u32 {
    unsafe { read_volatile(addr_of!(CROSSHAIR_SHELL_RECORD).cast::<u32>().add(i)) }
}
unsafe fn put(i: usize, v: u32) {
    unsafe { write_volatile(addr_of_mut!(CROSSHAIR_SHELL_RECORD).cast::<u32>().add(i), v) }
}
unsafe fn inc(i: usize) {
    unsafe { put(i, get(i).wrapping_add(1)) }
}
fn stacks() -> [(usize, usize); 4] {
    [
        (
            addr_of!(__stack_bottom) as usize,
            addr_of!(__stack_top) as usize,
        ),
        (
            addr_of!(__irq_stack_bottom) as usize,
            addr_of!(__irq_stack_top) as usize,
        ),
        (
            addr_of!(__abort_stack_bottom) as usize,
            addr_of!(__abort_stack_top) as usize,
        ),
        (
            addr_of!(__undef_stack_bottom) as usize,
            addr_of!(__undef_stack_top) as usize,
        ),
    ]
}
unsafe fn integrity() {
    unsafe {
        for i in 0..16 {
            assert!(
                load(addr_of!(TASK_CANARY).cast::<u32>().add(i) as usize) == 0xcafe7000 ^ i as u32
            );
        }
        for (b, _) in stacks() {
            for i in 0..4 {
                assert!(load(b + i * 4) == 0xface6000 ^ i as u32);
            }
        }
        for i in 0..4 {
            assert!(
                load(addr_of!(SHELL_IDLE_STACK).cast::<u32>().add(i) as usize)
                    == 0x1d1e7000 ^ i as u32
            );
        }
        let (c, t, d, p) = memory::cp15();
        assert!(c == 0x79 && d == 1 && p == 0);
        put(18, t);
        put(19, c);
        put(20, d);
        put(21, p);
    }
}
unsafe fn timer(tasks: &mut [task_runtime::Task; 2], cur: Option<usize>, pointer: *const Context) {
    unsafe {
        assert!(load(PIC) == 1 << 26 && load(TIMER + 0x14) & 1 == 1);
        store(TIMER + 0x14, 1);
        store(TIMER, load(TIMER + 0x10).wrapping_add(36864));
        inc(4);
        put(25, pointer as u32);
        if let Some(cur) = cur {
            inc(14 + cur);
            tasks[cur].preemptions += 1;
            tasks[cur].state = READY;
        }
        put(31, load(0xa0201000));
        poll_input();
        if tasks[1].state == WAITING {
            if let Some(w) = pop() {
                tasks[1].context.regs[0] = w;
                tasks[1].state = READY;
                inc(13);
            }
        }
        if load(0xa0000100) == 1 && tasks[0].preemptions >= 2 && tasks[0].state == READY {
            store(0xa0201030, 5);
        }
    }
}
unsafe fn dispatch(tasks: &mut [task_runtime::Task; 2], previous: usize) -> *const Context {
    unsafe {
        match scheduler::next(tasks, previous) {
            Some(next) => {
                if next != previous || get(6) == u32::MAX {
                    inc(5)
                }
                tasks[next].state = RUNNING;
                tasks[next].dispatches += 1;
                memory::activate(next);
                put(18, memory::cp15().1);
                put(6, next as u32);
                addr_of!(tasks[next].context)
            }
            None => {
                // System mode is privileged but shares the User register bank. Its private
                // stack is restored only after all previous User registers were saved. On
                // timer return another full User context restores its own bank before use.
                put(6, u32::MAX);
                addr_of!(SHELL_IDLE_CONTEXT)
            }
        }
    }
}
unsafe fn pop() -> Option<u32> {
    unsafe {
        let n = get(10) as usize;
        if n == 0 {
            return None;
        }
        let head = read_volatile(addr_of!(QUEUE_HEAD));
        let q = addr_of_mut!(SHELL_EVENT_QUEUE).cast::<u32>();
        let event = read_volatile(q.add(head));
        write_volatile(q.add(head), 0);
        write_volatile(addr_of_mut!(QUEUE_HEAD), (head + 1) % 4);
        put(10, n as u32 - 1);
        inc(7);
        Some(event)
    }
}
unsafe fn poll_input() {
    unsafe {
        // Bounded synthetic hardware FIFO8 -> kernel queue4, tail drops counted.
        for _ in 0..8 {
            if load(INPUT) == 0 {
                break;
            }
            let w = load(INPUT + 4);
            inc(9);
            let count = get(10) as usize;
            if count == 4 {
                inc(11);
                continue;
            }
            let head = read_volatile(addr_of!(QUEUE_HEAD));
            write_volatile(
                addr_of_mut!(SHELL_EVENT_QUEUE)
                    .cast::<u32>()
                    .add((head + count) % 4),
                w,
            );
            put(10, count as u32 + 1);
        }
    }
}
fn user_data(index: usize, ptr: u32, len: u32) -> Result<usize, u32> {
    let (start, end, base) = if index == 1 {
        (memory::DATA, memory::DATA_END, memory::SHELL_BASE)
    } else {
        (0x01001000, 0x01002000, 0xa0200000)
    };
    let limit = ptr.checked_add(len).ok_or(EFAULT)?;
    if ptr < start || limit > end {
        return Err(EFAULT);
    }
    Ok(base + (ptr - 0x01000000) as usize)
}
unsafe fn metrics(index: usize, ptr: u32, len: u32, counts: [u32; 3]) -> u32 {
    unsafe {
        if len != 48 {
            return EINVAL;
        }
        let Ok(pa) = user_data(index, ptr, len) else {
            return EFAULT;
        };
        if ptr & 3 != 0 {
            return EFAULT;
        }
        // Reservation accounting: kernel extent + vectors + busy3pages + Shell
        // 16code/47data/8stack pages. Guard holes and flat gaps are not mapped RAM.
        let ram =
            addr_of!(__image_end) as u32 - addr_of!(_start) as u32 + 64 + 3 * 4096 + 71 * 4096;
        let words = [
            1,
            15,
            get(4),
            get(5),
            2,
            counts[0],
            counts[1],
            counts[2],
            ram,
            get(7),
            get(11) + load(INPUT + 0x10),
            0,
        ];
        for (i, v) in words.iter().enumerate() {
            store(pa + i * 4, *v)
        }
        48
    }
}
unsafe fn syscall(index: usize, t: &mut task_runtime::Task, counts: [u32; 3]) -> bool {
    unsafe {
        let f = &mut t.context;
        let Some(pc) = f.pc.checked_sub(4) else {
            t.state = FAULTED;
            return true;
        };
        let code_end = if index == 1 { 0x01010000 } else { 0x01001000 };
        if f.psr & 0x20 != 0 || pc & 3 != 0 || pc < 0x01000000 || pc >= code_end {
            t.state = FAULTED;
            return true;
        }
        let pa = if index == 1 {
            memory::pa(pc)
        } else {
            0xa0200000 + (pc - 0x01000000) as usize
        };
        t.svc_count += 1;
        if load(pa) != 0xef000000 {
            f.regs[0] = ENOSYS;
            return false;
        }
        let n = f.regs[7];
        let p = f.regs[0];
        let len = f.regs[1];
        let mut schedule = false;
        let ret = match n {
            0 => {
                t.state = EXITED;
                t.exit_code = p;
                schedule = true;
                0
            }
            1 => {
                if len > 64 {
                    EINVAL
                } else {
                    match user_data(index, p, len) {
                        Err(e) => e,
                        Ok(source) => {
                            // Diagnostic copy-in has no output capability. Read only validated own bytes.
                            for offset in 0..len {
                                let _ = read_volatile((source + offset as usize) as *const u8);
                            }
                            len
                        }
                    }
                }
            }
            2 => {
                t.yields += 1;
                t.state = READY;
                schedule = true;
                0
            }
            3..=5 if index != 1 => EPERM,
            3 => {
                put(22, p);
                put(23, len);
                if len != 153600 || f.regs[2] != 0 || f.regs[3] != (320 << 16 | 240) {
                    EINVAL
                } else if p != memory::FB || user_data(index, p, len).is_err() {
                    EFAULT
                } else {
                    // One User-owned buffer, no second guest framebuffer. User is suspended
                    // in SVC; unchanged QEMU display synchronously copies this committed frame.
                    asm!("", options(nostack, preserves_flags));
                    store(DISPLAY, memory::pa(p) as u32);
                    store(DISPLAY + 0x14, 1);
                    inc(8);
                    0
                }
            }
            4 => metrics(index, p, len, counts),
            5 => {
                if f.regs[..4] != [0, 0, 0, 0] {
                    EINVAL
                } else {
                    poll_input();
                    inc(12);
                    match pop() {
                        Some(w) => w,
                        None => {
                            t.state = WAITING;
                            schedule = true;
                            0
                        }
                    }
                }
            }
            _ => ENOSYS,
        };
        if matches!(ret, EFAULT | EINVAL | ENOSYS | EPERM) {
            inc(30)
        }
        f.regs[0] = ret;
        schedule
    }
}
#[unsafe(no_mangle)]
pub extern "C" fn rust_task_trap(pointer: *const Context) -> *const Context {
    // SAFETY: unchanged Wave006 assembly supplies80B kernel frame, all banked
    // stacks initialized, single CPU/IRQ+FIQ masked; no reference survives return.
    unsafe {
        let frame = read_volatile(pointer);
        let mode: u32;
        asm!("mrs {r},cpsr",r=out(reg)mode,options(nostack,nomem));
        assert!(mode & 0xc0 == 0xc0);
        let s = match frame.kind {
            0 => 1,
            1 => 3,
            2 => 0,
            3 | 4 => 2,
            _ => panic!(),
        };
        let (b, e) = stacks()[s];
        assert!(
            pointer as usize >= b + 16 && pointer as usize + 80 <= e && pointer as usize & 7 == 0
        );
        integrity();
        let cur = get(6) as usize;
        let tasks = &mut *addr_of_mut!(TASKS);
        if cur == u32::MAX as usize {
            assert!(
                frame.kind == 0
                    && frame.psr & 0xff == 0x5f
                    && frame.pc == shell_idle_loop as *const () as u32
                    && frame.sp == addr_of!(SHELL_IDLE_STACK) as u32 + 4096
            );
            timer(tasks, None, pointer);
            return dispatch(tasks, 1);
        }
        assert!(cur < 2 && frame.psr & 0xdf == 0x50);
        assert!(tasks[cur].state == RUNNING);
        tasks[cur].context = frame;
        let schedule = match frame.kind {
            0 => {
                timer(tasks, Some(cur), pointer);
                true
            }
            2 => {
                put(27, mode);
                put(28, frame.psr);
                if frame.regs[7] == 5 {
                    put(24, pointer as u32)
                }
                let counts = [
                    tasks.iter().filter(|t| t.state == READY).count() as u32,
                    tasks.iter().filter(|t| t.state == RUNNING).count() as u32,
                    tasks.iter().filter(|t| t.state == FAULTED).count() as u32,
                ];
                syscall(cur, &mut tasks[cur], counts)
            }
            _ => {
                let t = &mut tasks[cur];
                t.state = FAULTED;
                t.fault_kind = frame.kind;
                t.fault_lr = frame.raw_lr;
                t.fault_psr = frame.psr;
                t.fault_pc = frame.pc;
                asm!("mrc p15,0,{r},c5,c0,0",r=out(reg)t.dfsr,options(nostack,nomem));
                asm!("mrc p15,0,{r},c6,c0,0",r=out(reg)t.dfar,options(nostack,nomem));
                put(29, frame.kind);
                true
            }
        };
        if !schedule {
            return addr_of!(tasks[cur].context);
        }
        dispatch(tasks, cur)
    }
}
#[unsafe(no_mangle)]
pub extern "C" fn rust_main() -> ! {
    // SAFETY: trusted physical ELF reset with MMU/cache off. Fixed allocations
    // stay reserved for entire session, including faulted/waiting task pages.
    unsafe {
        put(0, 0x53484c4c);
        put(1, 1);
        put(2, 1);
        put(26, 4);
        for i in 0..4 {
            store(
                addr_of_mut!(SHELL_IDLE_STACK).cast::<u32>().add(i) as usize,
                0x1d1e7000 ^ i as u32,
            );
        }
        let idle = addr_of_mut!(SHELL_IDLE_CONTEXT);
        (*idle).pc = shell_idle_loop as *const () as u32;
        (*idle).psr = 0x5f;
        (*idle).sp = addr_of!(SHELL_IDLE_STACK) as u32 + 4096;
        for i in 0..16 {
            store(
                addr_of_mut!(TASK_CANARY).cast::<u32>().add(i) as usize,
                0xcafe7000 ^ i as u32,
            )
        }
        for (b, _) in stacks() {
            for i in 0..4 {
                store(b + i * 4, 0xface6000 ^ i as u32)
            }
        }
        for off in (0..4096).step_by(4) {
            store(0xa0201000 + off, 0);
            store(0xa0203000 + off, 0);
        }
        for i in 0..2 {
            let t = &mut (*addr_of_mut!(TASKS))[i];
            t.id = i as u32 + 1;
            t.context.pc = 0x01000000;
            t.context.sp = if i == 0 {
                0x01004000
            } else {
                memory::STACK_TOP
            };
            t.context.psr = 0x50;
        }
        assert!(load(0xa0000100) <= 2);
        if load(0xa0000100) == 2 {
            (*addr_of_mut!(TASKS))[0].context.pc =
                0x01000000 + (addr_of!(shell_role_probe) as u32 - 0xa0200000);
        }
        memory::init();
        store(PIC + 4, 0);
        store(PIC + 8, 0);
        store(TIMER + 0x1c, 0);
        for off in (0..16).step_by(4) {
            store(TIMER + off, u32::MAX)
        }
        store(TIMER + 0x10, 0);
        store(TIMER + 0x14, 0xf);
        store(TIMER, load(TIMER + 0x10).wrapping_add(36864));
        store(TIMER + 0x1c, 1);
        store(PIC + 4, 1 << 26);
        put(16, memory::pa(memory::FB) as u32);
        put(17, 153600);
        put(6, 0);
        (*addr_of_mut!(TASKS))[0].state = RUNNING;
        (*addr_of_mut!(TASKS))[0].dispatches = 1;
        integrity();
        put(2, 2);
        let mut serial = uart::ReferenceUart::init();
        let _ = serial.send("CROSSHAIR SHELL — USER SESSION START\r\n");
        task_enter(addr_of!((*addr_of!(TASKS))[0].context))
    }
}
#[panic_handler]
fn panic(_: &PanicInfo<'_>) -> ! {
    unsafe {
        put(3, 0xdead);
        put(2, 0xff);
        kernel_idle()
    }
}
