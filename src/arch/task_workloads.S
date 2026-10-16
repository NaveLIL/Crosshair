/* Original MIT ARM fixtures. Actual User code, not host scheduler models.
 * Every loop checks NZCV before altering flags, and all r0-r12/User LR.
 * The 56-byte User stack image preserves every sentinel while work/SVC runs.
 */
.syntax unified
.arch armv5te
.arm
.macro seed base
    mov r0,#(\base+0)
    mov r1,#(\base+1)
    mov r2,#(\base+2)
    mov r3,#(\base+3)
    mov r4,#(\base+4)
    mov r5,#(\base+5)
    mov r6,#(\base+6)
    mov r7,#(\base+7)
    mov r8,#(\base+8)
    mov r9,#(\base+9)
    mov r10,#(\base+10)
    mov r11,#(\base+11)
    mov r12,#(\base+12)
    mov lr,#(\base+14)
    cmp r0,r0
.endm
.macro check reg,value,target
    cmp \reg,#\value
    bne \target
.endm
.macro verify base,target
    bne \target
    bcc \target
    bmi \target
    bvs \target
    check r0,(\base+0),\target
    check r1,(\base+1),\target
    check r2,(\base+2),\target
    check r3,(\base+3),\target
    check r4,(\base+4),\target
    check r5,(\base+5),\target
    check r6,(\base+6),\target
    check r7,(\base+7),\target
    check r8,(\base+8),\target
    check r9,(\base+9),\target
    check r10,(\base+10),\target
    check r11,(\base+11),\target
    check r12,(\base+12),\target
    check lr,(\base+14),\target
.endm

.section .user.a,"ax",%progbits
.global task_a_start,task_a_end,task_a_busy,task_a_busy_end
task_a_start:
    seed 0x10
task_a_busy:
    verify 0x10,task_a_failed
    stmdb sp!,{r0-r12,lr}
    ldr r0,=0x01001000
    ldr r1,[r0]
    add r1,r1,#1
    str r1,[r0]
    ldr r2,[r0,#4]
    add r2,r2,r1
    str r2,[r0,#4]
    ldr r3,[r0,#0x30]
    cmp r3,#0
    bne task_a_command
    cmp r0,r0
    ldmia sp!,{r0-r12,lr}
    b task_a_busy
task_a_busy_end:
task_a_command:
    cmp r3,#1
    beq task_a_peer_read
    cmp r3,#2
    beq task_a_peer_write
    cmp r3,#3
    beq task_a_kernel_write
    cmp r3,#4
    beq task_a_guard
    cmp r3,#5
    beq task_a_undefined
    cmp r3,#6
    beq task_a_lifecycle
    cmp r3,#7
    beq task_a_thumb_svc
    b task_a_failed
task_a_peer_read:
    ldr r1,=0xa0301000
.global task_a_peer_read_fault
task_a_peer_read_fault:
    ldr r2,[r1]
    b task_a_failed
task_a_peer_write:
    ldr r1,=0xa0301200
    mov r2,#0x77
.global task_a_peer_write_fault
task_a_peer_write_fault:
    str r2,[r1]
    b task_a_failed
task_a_kernel_write:
    ldr r1,=TASK_CANARY
    mov r2,#0x77
.global task_a_kernel_write_fault
task_a_kernel_write_fault:
    str r2,[r1]
    b task_a_failed
task_a_guard:
    ldr r1,=0x01002000
.global task_a_guard_fault
task_a_guard_fault:
    ldr r2,[r1]
    b task_a_failed
.global task_a_undefined
task_a_undefined:
    .word 0xe7f000f0
    b task_a_failed
task_a_thumb_svc:
    ldr r1,=0x01001241
    bx r1
task_a_lifecycle:
    mov r7,#2
.global task_a_yield_svc
task_a_yield_svc:
    svc #0
    ldr r1,=0x01001000
    str r0,[r1,#16]
    mov r2,#0x66
    str r2,[r1,#20]
    mov r0,#0x2a
    mov r7,#0
.global task_a_exit_svc
task_a_exit_svc:
    svc #0
    b task_a_failed
task_a_failed:
    ldr r0,=0x01001000
    mov r1,#1
    str r1,[r0,#32]
    b task_a_failed
.ltorg
task_a_end:

.section .user.b,"ax",%progbits
.global task_b_start,task_b_end,task_b_healthy
task_b_start:
    seed 0x80
task_b_healthy:
    verify 0x80,task_b_failed
    stmdb sp!,{r0-r12,lr}
    ldr r0,=0x01001000
    ldr r1,[r0]
    add r1,r1,#1
    str r1,[r0]
    ldr r2,[r0,#4]
    add r2,r2,r1
    str r2,[r0,#4]
    ldr r0,=0x01001080
    mov r1,#15
    mov r7,#1
.global task_b_copy_svc
task_b_copy_svc:
    svc #0
    ldr r2,=0x01001000
    str r0,[r2,#8]
    mrs r3,cpsr
    str r3,[r2,#12]
    /* Unknown number, crossing end, overflow, cap, code pointer, null/zero,
       foreign PA, zero at end, and wrong immediate: real SVC returns. */
    mov r7,#99
    svc #0
    str r0,[r2,#0x100]
    mov r7,#1
    ldr r0,=0x01001ffc
    mov r1,#8
    svc #0
    str r0,[r2,#0x104]
    ldr r0,=0xfffffff0
    mov r1,#32
    svc #0
    str r0,[r2,#0x108]
    ldr r0,=0x01001080
    mov r1,#65
    svc #0
    str r0,[r2,#0x10c]
    ldr r0,=0x01000000
    mov r1,#4
    svc #0
    str r0,[r2,#0x110]
    mov r0,#0
    mov r1,#0
    svc #0
    str r0,[r2,#0x114]
    ldr r0,=0xa0201000
    mov r1,#4
    svc #0
    str r0,[r2,#0x118]
    ldr r0,=0x01002000
    mov r1,#0
    svc #0
    str r0,[r2,#24]
    svc #1
    str r0,[r2,#28]
    ldr r3,[r2,#0x30]
    cmp r3,#6
    bne task_b_continue
    ldr r3,[r2]
    cmp r3,#32
    blo task_b_continue
    mov r0,#0x2b
    mov r7,#0
.global task_b_exit_svc
task_b_exit_svc:
    svc #0
    b task_b_failed
task_b_continue:
    cmp r0,r0
    ldmia sp!,{r0-r12,lr}
    b task_b_healthy
task_b_failed:
    ldr r0,=0x01001000
    mov r1,#2
    str r1,[r0,#32]
    b task_b_failed
.ltorg
task_b_end:
