/* MIT, negative caller-rights fixture, selected only by test mailbox2. */
.syntax unified
.arch armv5te
.arm
.section .user.a,"ax",%progbits
.global shell_role_probe
shell_role_probe:
    ldr r0,=0xa0008000
    mov r1,#48
    mov r2,#0
    mov r3,#0
    mov r7,#3
    svc #0
    ldr r4,=0x01001100
    str r0,[r4]
    mov r7,#4
    svc #0
    str r0,[r4,#4]
    mov r7,#5
    svc #0
    str r0,[r4,#8]
    b task_a_start
.ltorg
