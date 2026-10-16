.syntax unified
.arch armv5te
.arm
.section .vectors, "ax", %progbits
.global e2b_vectors
e2b_vectors:
    .rept 8
    ldr pc, [pc, #24]
    .endr
    .word _start, e2b_undefined, e2b_other, e2b_prefetch
    .word e2b_data_abort, e2b_other, e2b_irq, e2b_other

.section .text.boot, "ax", %progbits
.global _start
.type _start, %function
_start:
    /* Experimental QEMU CPU reset: privileged ARM, MMU/cache off, low vectors. */
    msr cpsr_c, #0xd2
    ldr sp, =__irq_stack_top
    msr cpsr_c, #0xd3
    ldr sp, =__stack_top
    mov fp, #0
    ldr r3, =__bss_start
    ldr r4, =__bss_end
    mov r5, #0
1:  cmp r3, r4
    strlo r5, [r3], #4
    blo 1b
    bl rust_main
    b kernel_idle
.size _start, . - _start
.ltorg

.section .text.e2b_irq, "ax", %progbits
.global e2b_irq
.type e2b_irq, %function
e2b_irq:
    sub lr, lr, #4
    stmdb sp!, {r0-r3, r12, lr}
    bl rust_irq
    ldmia sp!, {r0-r3, r12, pc}^
.size e2b_irq, . - e2b_irq

.section .text.e2b_fault, "ax", %progbits
e2b_undefined:
    mov r0, #1
    b e2b_fault
e2b_prefetch:
    mov r0, #2
    b e2b_fault
e2b_data_abort:
    mov r0, #3
    b e2b_fault
e2b_other:
    mov r0, #4
e2b_fault:
    /* Capture banked state before changing mode. Faults are terminal. */
    mov r1, lr
    mrs r2, spsr
    msr cpsr_c, #0xd3
    ldr sp, =__stack_top
    bl rust_fault
    b kernel_idle

.section .text.kernel_idle, "ax", %progbits
.global kernel_idle
.type kernel_idle, %function
kernel_idle:
    b kernel_idle
.size kernel_idle, . - kernel_idle
