//! Syscalls run to completion with IRQ masked. No scheduling during checked copy.
use super::memory::{self, USER_CODE};
use super::{EXITED, READY, Task};
use crate::security_policy::{ENOSYS, checked_copy};
use core::ptr::{addr_of_mut, read_volatile, write_volatile};

#[unsafe(no_mangle)]
pub static mut TASK_COPY: [[u8; 64]; 2] = [[0; 64]; 2];

/// Returns true when a lifecycle operation requests scheduling. Invalid SVC
/// origin is handled before this function, never dereferenced speculatively.
/// SAFETY: task is exclusively owned by the IRQ-masked handler; its index and
/// code extent belong to the installed immutable task. AP tables stay unchanged
/// until return; PA aliases are privileged, no DMA/cache alias exists in E2B.
pub unsafe fn dispatch(task: &mut Task, index: usize, code_len: u32) -> Result<bool, ()> {
    const _: () = assert!(memory::USER_END == crate::security_policy::USER_END);
    let f = &mut task.context;
    let pc = f.pc.checked_sub(4).ok_or(())?;
    if f.psr & 0x20 != 0 || pc & 3 != 0 || pc < USER_CODE || pc >= USER_CODE + code_len {
        return Err(());
    }
    // SAFETY: aligned instruction inside linker-bounded RO code page.
    let opcode =
        unsafe { read_volatile((memory::base(index) + (pc - USER_CODE) as usize) as *const u32) };
    task.svc_count += 1;
    if opcode != 0xef00_0000 {
        f.regs[0] = ENOSYS;
        return Ok(false);
    }
    match f.regs[7] {
        0 => {
            task.exit_code = f.regs[0];
            task.state = EXITED;
            Ok(true)
        }
        2 => {
            task.yields += 1;
            f.regs[0] = 0;
            task.state = READY;
            Ok(true)
        }
        1 => {
            f.regs[0] = match checked_copy(f.regs[0], f.regs[1]) {
                Err(error) => error,
                Ok(len) => {
                    // Full pointer+length policy precedes every byte read.
                    // Translate to the caller's fixed PA; shared VA cannot select
                    // the other task's backing or race a TTBR switch here.
                    let physical = memory::data(index) + (f.regs[0] - memory::USER_DATA) as usize;
                    for offset in 0..len {
                        unsafe {
                            let byte = read_volatile((physical + offset) as *const u8);
                            write_volatile(
                                addr_of_mut!(TASK_COPY)
                                    .cast::<u8>()
                                    .add(index * 64 + offset),
                                byte,
                            );
                        }
                    }
                    task.copies += 1;
                    len as u32
                }
            };
            Ok(false)
        }
        _ => {
            f.regs[0] = ENOSYS;
            Ok(false)
        }
    }
}
