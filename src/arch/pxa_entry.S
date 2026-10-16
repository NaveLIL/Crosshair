.syntax unified
.arch armv5te
.arm
.section .vectors, "ax", %progbits
.global reference_vectors
reference_vectors:
    /* Low vectors in a synthetic QEMU flash segment. Branches cannot span
       from PA 0 to SDRAM A0008000, so use absolute literals. No OEM ROM. */
    .rept 8
    ldr pc, [pc, #24]
    .endr
    .word _start, reference_fault, reference_fault, reference_fault
    .word reference_fault, reference_fault, reference_irq, reference_fault

.section .text.boot, "ax", %progbits
.global _start
.type _start, %function
_start:
    /* QEMU reset contract only: privileged ARM, MMU/cache off, low vectors. */
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

.section .text.reference_irq, "ax", %progbits
.global reference_irq
.type reference_irq, %function
reference_irq:
    sub lr, lr, #4
    /* Six registers preserve 8-byte stack alignment for the C ABI. IRQ/FIQ
       remain masked in this handler; no nested interrupts are supported. */
    stmdb sp!, {r0-r3, r12, lr}
    bl rust_irq
    ldmia sp!, {r0-r3, r12, pc}^
.size reference_irq, . - reference_irq

.section .text.reference_fault, "ax", %progbits
reference_fault:
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
