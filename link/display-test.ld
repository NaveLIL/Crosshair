/* Test-only display guest, not ATI/HaRET. All writable storage is ordinary RAM. */
ENTRY(_start)
MEMORY {
    VECTORS (rx) : ORIGIN = 0, LENGTH = 64
    RAM (rwx) : ORIGIN = 0xa0008000, LENGTH = 1M
}
PHDRS { vectors PT_LOAD FLAGS(5); text PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }
SECTIONS {
    .vectors : { KEEP(*(.vectors)) } > VECTORS :vectors
    .text : ALIGN(4) { KEEP(*(.text.boot)) *(.text .text.*) } > RAM :text
    .rodata : ALIGN(4) { *(.rodata .rodata.*) } > RAM :text
    .data : ALIGN(8) { *(.data .data.*) } > RAM :data
    .bss (NOLOAD) : ALIGN(8) {
        __bss_start = .; *(.bss .bss.*) *(COMMON)
        . = ALIGN(8); __bss_end = .;
    } > RAM :data
    .stack_guard (NOLOAD) : ALIGN(8) {
        __stack_guard = .; . += 64;
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
ASSERT(SIZEOF(.vectors) == 64, "need ARM vectors")
ASSERT(_start == ORIGIN(RAM), "flat image starts at entry")
ASSERT((__stack_top & 7) == 0 && (__irq_stack_top & 7) == 0, "AAPCS alignment")
ASSERT(__image_end <= ORIGIN(RAM) + LENGTH(RAM), "display guest RAM budget exceeded")
