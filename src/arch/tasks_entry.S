.syntax unified
.arch armv5te
.arm
.section .vectors,"ax",%progbits
.rept 8
ldr pc,[pc,#24]
.endr
.word _start, task_undefined, task_svc, task_prefetch
.word task_abort, task_fatal, task_irq, task_fatal

.section .text.boot,"ax",%progbits
.global _start
_start:
    msr cpsr_c,#0xd2
    ldr sp,=__irq_stack_top
    msr cpsr_c,#0xd7
    ldr sp,=__abort_stack_top
    msr cpsr_c,#0xdb
    ldr sp,=__undef_stack_top
    msr cpsr_c,#0xd3
    ldr sp,=__stack_top
    ldr r0,=__bss_start
    ldr r1,=__bss_end
    mov r2,#0
1:  cmp r0,r1
    strlo r2,[r0],#4
    blo 1b
    bl rust_main
    b kernel_idle
.ltorg

.section .text.context,"ax",%progbits
/* 80 B, 8-byte aligned Context: r0-r12, User SP/LR, resume PC, SPSR,
 * kind, raw exception LR, pad. Never use exception LR as User LR.
 * Single CPU, no nested IRQ; each path masks IRQ/FIQ before the first store.
 * Rust may select another kernel-owned Context only after copying this frame.
 */
.macro trap name,kind,mode,adjust
.global \name
\name:
    msr cpsr_c,#\mode
    sub sp,sp,#80
    stmia sp,{r0-r12}
    add r0,sp,#52
    stmia r0,{sp,lr}^
    nop
    str lr,[sp,#72]
    sub r1,lr,#\adjust
    str r1,[sp,#60]
    mrs r1,spsr
    str r1,[sp,#64]
.if \kind == 1
    /* UNDEF's sequential address is +2 in Thumb, +4 in ARM. */
    tst r1,#0x20
    subne r2,lr,#2
    strne r2,[sp,#60]
.endif
    mov r1,#\kind
    str r1,[sp,#68]
    mov r1,#0
    str r1,[sp,#76]
    mov r0,sp
    bl rust_task_trap
    add sp,sp,#80
    cmp r0,#0
    beq task_terminal
    b task_restore
.endm
trap task_irq,0,0xd2,4
trap task_undefined,1,0xdb,4
trap task_svc,2,0xd3,0
trap task_abort,3,0xd7,8
trap task_prefetch,4,0xd7,4

.global task_enter
task_enter:
    /* Called once in SVC, never returns to a Rust frame. */
task_restore:
    ldr r1,[r0,#64]
    msr spsr_cxsf,r1
    add r1,r0,#52
    ldmia r1,{sp,lr}^
    nop
    ldr lr,[r0,#60]
    ldmia r0,{r0-r12}
    movs pc,lr
task_fatal:
    b task_fatal
task_terminal:
    msr cpsr_c,#0xd3
    b kernel_idle
.global kernel_idle
kernel_idle:
    /* Terminal diagnostic Idle: no runnable task, or bounded host test stop. */
    b kernel_idle
.ltorg
