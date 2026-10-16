.syntax unified
.arch armv5te
.arm
.section .text.boot, "ax", %progbits
.global _start
.type _start, %function
_start:
    /* Entry contract: privileged ARM state, little endian, MMU and caches off,
       RAM loaded at linked PA. No inherited stack is used. Preserve r0-r2. */
    msr cpsr_c, #0xd3             /* SVC, IRQ and FIQ masked; ARMv5 (no cpsid). */
    ldr sp, =__stack_top
    mov fp, #0
    ldr r3, =__bss_start
    ldr r4, =__bss_end
    mov r5, #0
1:
    cmp r3, r4
    strlo r5, [r3], #4
    blo 1b
    bl rust_main
    b kernel_idle
.size _start, . - _start
.ltorg

.section .text.kernel_idle, "ax", %progbits
.global kernel_idle
.type kernel_idle, %function
kernel_idle:
    /* Controlled terminal state. Busy wait deliberately uses only common
       ARMv5 instructions. This is NOT implemented PXA power management. */
    b kernel_idle
.size kernel_idle, . - kernel_idle
