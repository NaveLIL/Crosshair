//! Bounded task ownership/lifetime; hardware, policy and syscall checks are separate.
pub mod context;
pub mod memory;
pub mod scheduler;
pub mod syscall;
use context::Context;

pub const READY: u32 = 0;
pub const RUNNING: u32 = 1;
pub const EXITED: u32 = 2;
pub const FAULTED: u32 = 3;

#[repr(C)]
#[derive(Clone, Copy)]
pub struct Task {
    pub id: u32,
    pub state: u32,
    pub dispatches: u32,
    pub preemptions: u32,
    pub svc_count: u32,
    pub copies: u32,
    pub yields: u32,
    pub exit_code: u32,
    pub fault_kind: u32,
    pub fault_lr: u32,
    pub fault_psr: u32,
    pub dfsr: u32,
    pub dfar: u32,
    pub ifsr: u32,
    pub fault_pc: u32,
    pub fault_opcode: u32,
    pub context: Context,
}
impl Task {
    pub const EMPTY: Self = Self {
        id: 0,
        state: READY,
        dispatches: 0,
        preemptions: 0,
        svc_count: 0,
        copies: 0,
        yields: 0,
        exit_code: 0,
        fault_kind: 0,
        fault_lr: 0,
        fault_psr: 0,
        dfsr: 0,
        dfar: 0,
        ifsr: 0,
        fault_pc: 0,
        fault_opcode: 0,
        context: Context::ZERO,
    };
}
const _: () = assert!(core::mem::size_of::<Task>() == 144);

#[unsafe(no_mangle)]
pub static mut TASKS: [Task; 2] = [Task::EMPTY; 2];
