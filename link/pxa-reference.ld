/* Synthetic QEMU PXA reference ONLY. This low flash region is populated by
   the host ELF loader, never by guest flash programming and never on a PDA. */
ENTRY(_start)
MEMORY {
    VECTORS (rx) : ORIGIN = 0, LENGTH = 64
    RAM (rwx) : ORIGIN = 0xa0008000, LENGTH = 1M
}
PHDRS {
    vectors PT_LOAD FLAGS(5);
    text PT_LOAD FLAGS(5);
    data PT_LOAD FLAGS(6);
}
SECTIONS {
    .vectors : { KEEP(*(.vectors)) } > VECTORS :vectors
    .text : ALIGN(4) { KEEP(*(.text.boot)) *(.text .text.*) } > RAM :text
    .rodata : ALIGN(4) { *(.rodata .rodata.*) } > RAM :text
    .data : ALIGN(8) { *(.data .data.*) } > RAM :data
    .bss (NOLOAD) : ALIGN(8) {
        __bss_start = .;
        *(.bss .bss.*) *(COMMON)
        . = ALIGN(4);
        __bss_end = .;
    } > RAM :data
    .stack (NOLOAD) : ALIGN(8) {
        __stack_bottom = .; . += 16K; __stack_top = .;
    } > RAM :data
    .irq_stack (NOLOAD) : ALIGN(8) {
        __irq_stack_bottom = .; . += 4K; __irq_stack_top = .;
    } > RAM :data
    __image_end = .;
    /DISCARD/ : { *(.ARM.exidx* .ARM.extab*) *(.eh_frame*) *(.comment) }
}
ASSERT(SIZEOF(.vectors) == 64, "need eight ARM vector entries and literals")
ASSERT(_start == ORIGIN(RAM), "RAM binary must start at the ELF entry")
ASSERT((__stack_top & 7) == 0 && (__irq_stack_top & 7) == 0, "AAPCS alignment")
ASSERT(__image_end <= ORIGIN(RAM) + LENGTH(RAM), "reference RAM budget exceeded")
