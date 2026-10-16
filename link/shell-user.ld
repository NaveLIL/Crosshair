/* Original MIT static User application; kernel maps VA to separate PA. */
ENTRY(user_start)
MEMORY {
    CODE (rx) : ORIGIN = 0x01000000, LENGTH = 64K
    DATA (rw) : ORIGIN = 0x01010000, LENGTH = 188K
    STACK (rw) : ORIGIN = 0x01040000, LENGTH = 32K
}
PHDRS { code PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); stack PT_LOAD FLAGS(6); }
SECTIONS {
    .text : { KEEP(*(.text.user_entry)) *(.text .text.*) } > CODE :code
    .rodata : ALIGN(4) { *(.rodata .rodata.*) } > CODE :code
    .data : ALIGN(8) { *(.data .data.*) } > DATA :data
    .framebuffer (NOLOAD) : ALIGN(8) {
        __user_bss_start = .; KEEP(*(.user.framebuffer))
    } > DATA :data
    .bss (NOLOAD) : ALIGN(8) { *(.bss .bss.*) *(COMMON) . = ALIGN(8); __user_bss_end = .; } > DATA :data
    .stack (NOLOAD) : { __user_stack_bottom = .; . += 32K; __user_stack_top = .; } > STACK :stack
    /DISCARD/ : { *(.ARM.exidx* .ARM.extab*) *(.eh_frame*) *(.comment) }
}
ASSERT(user_start == 0x01000000, "User entry contract")
ASSERT(SHELL_FRAMEBUFFER == 0x01010000, "one guarded framebuffer at fixed User allocation")
ASSERT(__user_bss_end <= 0x0103f000, "User data must not touch guard")
