/* Same E2B/display synthetic board, complete Wave006 context entry. */
ENTRY(_start)
MEMORY {
    VECTORS (rx) : ORIGIN = 0, LENGTH = 64
    RAM (rwx) : ORIGIN = 0xa0008000, LENGTH = 1M
    BUSY (rx) : ORIGIN = 0xa0200000, LENGTH = 4K
    SHELL (rx) : ORIGIN = 0xa0400000, LENGTH = 256K
}
PHDRS { vectors PT_LOAD FLAGS(5); text PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); busy PT_LOAD FLAGS(5); shell PT_LOAD FLAGS(5); }
SECTIONS {
    .vectors : { KEEP(*(.vectors)) } > VECTORS :vectors
    .text : ALIGN(4) { KEEP(*(.text.boot)) *(.text .text.*) } > RAM :text
    .rodata : ALIGN(4) { *(.rodata .rodata.*) } > RAM :text
    .data : ALIGN(8) { *(.data .data.*) } > RAM :data
    .bss (NOLOAD) : ALIGN(16384) { __bss_start = .; *(.bss .bss.*) *(COMMON) . = ALIGN(8); __bss_end = .; } > RAM :data
    .stack (NOLOAD) : ALIGN(8) { __stack_bottom = .; . += 16K; __stack_top = .; } > RAM :data
    .irq_stack (NOLOAD) : ALIGN(8) { __irq_stack_bottom = .; . += 4K; __irq_stack_top = .; } > RAM :data
    .abort_stack (NOLOAD) : ALIGN(8) { __abort_stack_bottom = .; . += 4K; __abort_stack_top = .; } > RAM :data
    .undef_stack (NOLOAD) : ALIGN(8) { __undef_stack_bottom = .; . += 4K; __undef_stack_top = .; } > RAM :data
    __image_end = .;
    .user_a : { KEEP(*(.user.a)) } > BUSY :busy
    .shell_user : { KEEP(*(.shell.user)) } > SHELL :shell
    /DISCARD/ : { *(.user.b) *(.ARM.exidx* .ARM.extab*) *(.eh_frame*) *(.comment) }
}
ASSERT(_start == ORIGIN(RAM) && SIZEOF(.vectors) == 64, "entry/vector contract")
ASSERT((SHELL_L1 & 0x3fff) == 0 && (SHELL_L2 & 0x3ff) == 0, "MMU alignment")
ASSERT(__image_end <= ORIGIN(RAM) + LENGTH(RAM), "kernel RAM budget")
ASSERT(SIZEOF(.user_a) <= 4096 && SIZEOF(.shell_user) <= 256K, "payload budgets")
