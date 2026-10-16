//! Wave006: real User task preemption on the unchanged experimental E2B board.
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
mod task_runtime;
use task_runtime::{FAULTED, READY, RUNNING, TASKS, context::Context, memory, scheduler, syscall};

// SAFETY: boot initializes all used banked stacks and BSS. Entry/traps use the
// asserted Context layout, User bank transfer and exception-specific PC offsets.
global_asm!(include_str!("arch/tasks_entry.S"), options(raw));
global_asm!(include_str!("arch/task_workloads.S"), options(raw));
const TIMER: usize = 0x40a0_0000;
const PIC: usize = 0x40d0_0000;
const TIMER_IRQ: u32 = 1 << 26;
const INTERVAL: u32 = 36_864; // 10 ms on the synthetic 3,686,400 Hz timer.

#[unsafe(no_mangle)]
static mut CROSSHAIR_TASK_RECORD: [u32; 32] = [0; 32];
#[unsafe(no_mangle)]
static mut TASK_CANARY: [u32; 16] = [0; 16];
unsafe extern "C" {
    fn task_enter(context: *const Context) -> !;
    fn kernel_idle() -> !;
    static task_a_start: u8;
    static task_a_end: u8;
    static task_b_start: u8;
    static task_b_end: u8;
    static __stack_bottom: u8;
    static __stack_top: u8;
    static __irq_stack_bottom: u8;
    static __irq_stack_top: u8;
    static __abort_stack_bottom: u8;
    static __abort_stack_top: u8;
    static __undef_stack_bottom: u8;
    static __undef_stack_top: u8;
}
unsafe fn load(address: usize) -> u32 {
    // SAFETY: private callers supply aligned own synthetic RAM/MMIO only.
    unsafe { read_volatile(address as *const u32) }
}
unsafe fn store(address: usize, value: u32) {
    // SAFETY: single privileged CPU, IRQ masked, exclusive own mapped RAM/MMIO.
    unsafe { write_volatile(address as *mut u32, value) }
}
unsafe fn get(i: usize) -> u32 {
    // SAFETY: all private indices are compile-time <32; no nested writers.
    unsafe { read_volatile(addr_of!(CROSSHAIR_TASK_RECORD).cast::<u32>().add(i)) }
}
unsafe fn put(i: usize, value: u32) {
    // SAFETY: same bounded IRQ-masked record ownership as get.
    unsafe {
        write_volatile(
            addr_of_mut!(CROSSHAIR_TASK_RECORD).cast::<u32>().add(i),
            value,
        )
    }
}
unsafe fn inc(i: usize) {
    unsafe { put(i, get(i) + 1) }
}
fn code_len(index: usize) -> u32 {
    if index == 0 {
        addr_of!(task_a_end) as u32 - addr_of!(task_a_start) as u32
    } else {
        addr_of!(task_b_end) as u32 - addr_of!(task_b_start) as u32
    }
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
    // SAFETY: all addresses kernel-owned and AP1; no User mapping/alias grants RW.
    unsafe {
        for i in 0..16 {
            assert!(
                read_volatile(addr_of!(TASK_CANARY).cast::<u32>().add(i)) == 0xcafe_6000 ^ i as u32
            );
        }
        for (bottom, _) in stacks() {
            for i in 0..4 {
                assert!(load(bottom + i * 4) == 0xface_6000 ^ i as u32);
            }
        }
        let (control, ttbr, domain, pid) = memory::cp15();
        assert!(control == 0x79 && domain == 1 && pid == 0);
        assert!(
            ttbr == addr_of!(memory::TASK_L1) as u32
                || ttbr == addr_of!(memory::TASK_L1) as u32 + 16384
        );
        put(9, control);
        put(10, ttbr);
        put(11, domain);
        put(12, pid);
        put(24, 1);
    }
}
unsafe fn stop(reason: u32) -> *const Context {
    // SAFETY: called in a masked exception, no borrowed User buffers or DMA.
    // This is a bounded diagnostic stop, not a scheduling decision to starve a
    // runnable application. reason2 is the actual no-runnable Idle transition.
    unsafe {
        store(PIC + 4, 0);
        store(TIMER + 0x1c, 0);
        store(TIMER + 0x14, 0xf);
        put(13, load(PIC + 4));
        put(14, load(TIMER + 0x1c));
        put(15, load(TIMER + 0x14));
        integrity();
        put(7, u32::MAX);
        put(25, reason);
        let mut uart = pxa_uart::ReferenceUart::init();
        assert!(
            uart.send("CROSSHAIR TASKS — PREEMPTION COMPLETE\r\n")
                .is_ok()
        );
        put(2, 3);
        core::ptr::null()
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn rust_task_trap(pointer: *const Context) -> *const Context {
    // SAFETY: assembly saves a complete 80 B frame in a privileged banked
    // stack before calling. IRQ/FIQ remain masked throughout Rust, including
    // copy validation/read and TTBR change. No nested contexts or heap/DMA.
    unsafe {
        let frame = read_volatile(pointer);
        let cpsr: u32;
        asm!("mrs {r},cpsr", r=out(reg)cpsr, options(nostack,nomem));
        // T is User-controlled through BX. Unsupported Thumb origins are task
        // failures, not kernel invariants; preserve this distinction on IRQ too.
        assert!(cpsr & 0xc0 == 0xc0 && frame.psr & 0xdf == 0x50);
        let stack_index = match frame.kind {
            0 => 1,
            1 => 3,
            2 => 0,
            3 | 4 => 2,
            _ => panic!(),
        };
        let (bottom, top) = stacks()[stack_index];
        assert!(
            pointer as usize >= bottom + 16
                && pointer as usize + 80 <= top
                && pointer as usize & 7 == 0
        );
        let cur = get(7) as usize;
        assert!(cur < 2);
        integrity();
        let tasks = &mut *addr_of_mut!(TASKS);
        assert!(tasks[cur].state == RUNNING);
        tasks[cur].context = frame;
        let schedule = match frame.kind {
            0 => {
                assert!(
                    cpsr & 0x1f == 0x12 && load(PIC) == TIMER_IRQ && load(TIMER + 0x14) & 1 == 1
                );
                // Acknowledge the source before a new compare/exception return.
                store(TIMER + 0x14, 1);
                store(TIMER, load(TIMER + 0x10).wrapping_add(INTERVAL));
                inc(5);
                inc(26 + cur);
                put(16, pointer as u32);
                put(17, cpsr);
                if get(29 + cur) == 0 {
                    put(29 + cur, frame.pc);
                }
                tasks[cur].preemptions += 1;
                tasks[cur].state = READY;
                // Test command becomes visible only after A has demonstrably
                // returned from an earlier timer preemption. Memory is retained
                // forever, including after fault/exit; no task slot reuse.
                if cur == 0 && tasks[0].preemptions >= 2 && get(4) != 0 {
                    store(memory::data(0) + 0x30, get(4));
                }
                true
            }
            2 => {
                assert!(cpsr & 0x1f == 0x13);
                put(18, pointer as u32);
                put(19, cpsr);
                match syscall::dispatch(&mut tasks[cur], cur, code_len(cur)) {
                    Ok(schedule) => schedule,
                    Err(()) => {
                        mark_fault(&mut tasks[cur], frame, cpsr);
                        true
                    }
                }
            }
            _ => {
                if frame.kind == 1 {
                    put(21, pointer as u32);
                } else {
                    put(20, pointer as u32);
                }
                mark_fault(&mut tasks[cur], frame, cpsr);
                true
            }
        };
        if !schedule {
            return addr_of!(tasks[cur].context);
        }
        if get(4) == 0 && get(5) >= 12 && tasks.iter().all(|t| t.preemptions >= 4) {
            return stop(1);
        }
        if ((1..=5).contains(&get(4)) || get(4) == 7)
            && tasks[0].state == FAULTED
            && get(5) >= get(22) + 8
            && tasks[1].preemptions >= 4
        {
            return stop(1);
        }
        match scheduler::next(tasks, cur) {
            None => stop(2),
            Some(next) => {
                tasks[next].state = RUNNING;
                tasks[next].dispatches += 1;
                if next != cur {
                    inc(6);
                }
                memory::activate(next);
                inc(23);
                put(7, next as u32);
                addr_of!(tasks[next].context)
            }
        }
    }
}
unsafe fn mark_fault(task: &mut task_runtime::Task, frame: Context, cpsr: u32) {
    // SAFETY: a fault never resumes or frees this task. Unknown PC is recorded,
    // never read. Only a bounded installed-code alias is inspected for evidence.
    unsafe {
        task.state = FAULTED;
        task.fault_kind = frame.kind;
        task.fault_lr = frame.raw_lr;
        task.fault_psr = frame.psr;
        asm!("mrc p15,0,{r},c5,c0,0",r=out(reg)task.dfsr,options(nostack,nomem));
        asm!("mrc p15,0,{r},c6,c0,0",r=out(reg)task.dfar,options(nostack,nomem));
        asm!("mrc p15,0,{r},c5,c0,1",r=out(reg)task.ifsr,options(nostack,nomem));
        task.fault_pc = if frame.kind == 2 {
            frame
                .pc
                .wrapping_sub(if frame.psr & 0x20 != 0 { 2 } else { 4 })
        } else {
            frame.pc
        };
        let index = (task.id - 1) as usize;
        if let Some(offset) = task.fault_pc.checked_sub(memory::USER_CODE) {
            let thumb = frame.psr & 0x20 != 0;
            let size = if thumb { 2 } else { 4 };
            // Bounds of installed mapped pages precede every diagnostic read.
            if offset % size == 0
                && matches!(offset / 4096, 0 | 1 | 3)
                && offset % 4096 <= 4096 - size
            {
                let physical = memory::base(index) + offset as usize;
                task.fault_opcode = if thumb {
                    read_volatile(physical as *const u16) as u32
                } else {
                    load(physical)
                };
            }
        }
        put(22, get(5));
        put(28, cpsr);
        put(31, load(memory::data(1))); // Compare actual survivor RAM after fault.
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn rust_main() -> ! {
    // SAFETY: boot owns all initialized state, banked stacks and static tables;
    // ELF payload is our immutable code, not extracted firmware or a loader.
    unsafe {
        put(0, 0x5441_534b);
        put(1, 1);
        put(2, 1);
        let scenario = load(0xa000_0100);
        assert!(scenario <= 7);
        put(4, scenario);
        let midr: u32;
        asm!("mrc p15,0,{r},c0,c0,0",r=out(reg)midr,options(nostack,nomem));
        assert!(midr == 0x6905_2903);
        put(8, midr);
        for i in 0..16 {
            write_volatile(
                addr_of_mut!(TASK_CANARY).cast::<u32>().add(i),
                0xcafe_6000 ^ i as u32,
            );
        }
        for (bottom, _) in stacks() {
            for i in 0..4 {
                store(bottom + i * 4, 0xface_6000 ^ i as u32);
            }
        }
        for index in 0..2 {
            assert!(code_len(index) > 0 && code_len(index) <= 4096);
            for offset in code_len(index) as usize..4096 {
                write_volatile((memory::base(index) + offset) as *mut u8, 0);
            }
            for offset in (0..4096).step_by(4) {
                store(memory::data(index) + offset, 0);
                store(memory::stack(index) + offset, 0);
            }
            for (offset, byte) in b"CROSSHAIR USER\n".iter().enumerate() {
                write_volatile((memory::data(index) + 0x80 + offset) as *mut u8, *byte);
            }
            store(memory::data(index) + 0x200, 0x6000_0001 + index as u32);
            if index == 0 {
                store(memory::data(index) + 0x240, 0x0000_df00);
            }
            if scenario == 6 && index == 1 {
                store(memory::data(index) + 0x30, 6);
            }
            let task = &mut (*addr_of_mut!(TASKS))[index];
            task.id = index as u32 + 1;
            task.context.pc = memory::USER_CODE;
            task.context.sp = memory::USER_STACK_TOP;
            task.context.psr = 0x50; // ARM User, IRQ enabled, FIQ disabled.
        }
        memory::init();
        put(23, 1);
        store(PIC + 4, 0);
        store(PIC + 8, 0);
        store(TIMER + 0x1c, 0);
        for offset in (0..16).step_by(4) {
            store(TIMER + offset, u32::MAX);
        }
        store(TIMER + 0x10, 0);
        store(TIMER + 0x14, 0xf);
        store(TIMER, load(TIMER + 0x10).wrapping_add(INTERVAL));
        store(TIMER + 0x1c, 1);
        store(PIC + 4, TIMER_IRQ);
        integrity();
        put(7, 0);
        put(2, 2);
        (*addr_of_mut!(TASKS))[0].state = RUNNING;
        (*addr_of_mut!(TASKS))[0].dispatches = 1;
        task_enter(addr_of!((*addr_of!(TASKS))[0].context))
    }
}
#[panic_handler]
fn panic(_: &PanicInfo<'_>) -> ! {
    // SAFETY: kernel retains privileged RAM, stops without resuming User.
    unsafe {
        put(3, 0xdead);
        put(2, 0xff);
        kernel_idle()
    }
}
