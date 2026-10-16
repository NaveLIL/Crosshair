.syntax unified
.arch armv5te
.arm
.section .vectors,"ax",%progbits
.rept 8
ldr pc,[pc,#24]
.endr
.word _start, security_undefined, security_svc, security_prefetch
.word security_abort, security_fatal, security_fatal, security_fatal

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

.section .text.security,"ax",%progbits
.global security_run_user
security_run_user:
    /* Preserve the trusted caller on SVC stack; all exception frames are64B. */
    stmdb sp!,{r4-r11,r12,lr}
    ldr r2,=SECURITY_RESUME_SP
    str sp,[r2]
    mov r12,r0
    msr cpsr_c,#0xdf
    ldr sp,=0x01004000
    mov lr,#0
    msr cpsr_c,#0xd3
    mov r2,#0xd0
    msr spsr_cxsf,r2
    mov r0,r1
    mov r1,#0
    mov r2,#0
    mov r3,#0
    mov r4,#0
    mov r5,#0
    mov r6,#0
    mov r7,#0
    mov r8,#0
    mov r9,#0
    mov r10,#0
    mov r11,#0
    movs pc,r12
.ltorg

.macro trap name,kind
.global \name
\name:
    sub sp,sp,#64
    stmia sp,{r0-r12}
    str lr,[sp,#52]
    mrs r1,spsr
    str r1,[sp,#56]
    mov r1,#\kind
    str r1,[sp,#60]
    mov r0,sp
    bl rust_trap
    cmp r0,#0
    bne 2f
    ldr r1,[sp,#56]
    msr spsr_cxsf,r1
    ldr lr,[sp,#52]
    ldmia sp,{r0-r12}
    add sp,sp,#64
    movs pc,lr
2:  add sp,sp,#64
    b security_return_kernel
.endm
trap security_svc,2
trap security_abort,3
trap security_undefined,1
trap security_prefetch,4
security_return_kernel:
    msr cpsr_c,#0xd3
    ldr sp,=SECURITY_RESUME_SP
    ldr sp,[sp]
    ldmia sp!,{r4-r11,r12,lr}
    bx lr
security_fatal:
    b kernel_idle
.global kernel_idle
.type kernel_idle,%function
kernel_idle:
    b kernel_idle
.ltorg

.section .user.text,"ax",%progbits
.global security_user_start
security_user_start:
    cmp r0,#20
    beq user_data_svc
    cmp r0,#21
    beq user_unmapped_branch
    cmp r0,#22
    beq user_thumb_svc
    cmp r0,#23
    beq user_data_undefined
    cmp r0,#1
    beq user_kernel_read
    cmp r0,#2
    beq user_kernel_write
    cmp r0,#3
    beq user_mmio_read
    cmp r0,#4
    beq user_mmio_write
    cmp r0,#12
    beq user_code_write
    cmp r0,#13
    beq user_guard_read
    cmp r0,#15
    beq user_cp15
    mov r6,r0
    ldr r0,=0x01001000
    mov r1,#15
    mov r7,#1
    cmp r6,#5
    ldreq r7,=0xffff
    cmp r6,#6
    moveq r0,#0
    cmp r6,#7
    ldreq r0,=KERNEL_CANARY
    moveq r1,#4
    cmp r6,#8
    ldreq r0,=0x01001ffc
    moveq r1,#8
    cmp r6,#9
    moveq r1,#65
    cmp r6,#10
    ldreq r0,=0xfffffff0
    moveq r1,#32
    cmp r6,#11
    ldreq r0,=0x01002000
    moveq r1,#0
    cmp r6,#17
    ldreq r0,=0x01000000
    moveq r1,#4
    cmp r6,#18
    ldreq r0,=0x01001080
    moveq r1,#64
    cmp r6,#19
    moveq r0,#0
    moveq r1,#0
    cmp r6,#16
    bne 1f
    adr lr,1f
    ldr r2,=0x01001200
    bx r2
1:  cmp r6,#14
    beq user_bad_svc
.global user_copy_svc
user_copy_svc:
    svc #0
    b user_after_svc
.global user_bad_svc
user_bad_svc:
    svc #1
user_after_svc:
    ldr r1,=0x01001100
    str r0,[r1]
    mrs r2,cpsr
    str r2,[r1,#4]
    str r8,[r1,#8]
    mov r0,#0
    mov r7,#0
.global user_exit_svc
user_exit_svc:
    svc #0
    b .

.global user_kernel_read
user_kernel_read:
    ldr r1,=KERNEL_CANARY
.global user_kernel_read_fault
user_kernel_read_fault:
    ldr r2,[r1]
    b user_unexpected
.global user_kernel_write
user_kernel_write:
    ldr r1,=KERNEL_CANARY
    mov r2,#0x77
.global user_kernel_write_fault
user_kernel_write_fault:
    str r2,[r1]
    b user_unexpected
.global user_mmio_read
user_mmio_read:
    ldr r1,=0x40100014
.global user_mmio_read_fault
user_mmio_read_fault:
    ldr r2,[r1]
    b user_unexpected
.global user_mmio_write
user_mmio_write:
    ldr r1,=0x40100000
    mov r2,#0x58
.global user_mmio_write_fault
user_mmio_write_fault:
    str r2,[r1]
    b user_unexpected
.global user_code_write
user_code_write:
    ldr r1,=0x01000000
    mov r2,#0
.global user_code_write_fault
user_code_write_fault:
    str r2,[r1]
    b user_unexpected
.global user_guard_read
user_guard_read:
    ldr r1,=0x01002000
.global user_guard_read_fault
user_guard_read_fault:
    ldr r2,[r1]
    b user_unexpected
.global user_cp15
user_cp15:
    mrc p15,0,r0,c1,c0,0
    b user_unexpected
.global user_data_svc
user_data_svc:
    ldr r1,=0x01001220
    bx r1
.global user_unmapped_branch
user_unmapped_branch:
    ldr r1,=0x02000000
.global user_unmapped_branch_fault
user_unmapped_branch_fault:
    bx r1
.global user_thumb_svc
user_thumb_svc:
    ldr r1,=0x01001241
    bx r1
.global user_data_undefined
user_data_undefined:
    ldr r1,=0x01001260
    bx r1
user_unexpected:
    mov r0,#77
    mov r7,#0
    svc #0
    b .
.ltorg
.global security_user_end
security_user_end:
