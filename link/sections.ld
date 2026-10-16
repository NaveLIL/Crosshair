ENTRY(_start)
PHDRS {
    text PT_LOAD FLAGS(5);
    data PT_LOAD FLAGS(6);
}
SECTIONS {
    . = ORIGIN(RAM);
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
        __stack_bottom = .;
        . += 16K;
        __stack_top = .;
    } > RAM :data
    __image_end = .;
    /DISCARD/ : { *(.ARM.exidx* .ARM.extab*) *(.eh_frame*) *(.comment) }
}
ASSERT((_start & 3) == 0, "entry must be ARM word aligned")
ASSERT((__stack_top & 7) == 0, "AAPCS stack alignment")
ASSERT(__image_end <= ORIGIN(RAM) + LENGTH(RAM), "image exceeds BSP RAM budget")
