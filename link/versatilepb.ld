/* QEMU VersatilePB SDRAM starts at PA 0; reserve the low 64 KiB. */
MEMORY { RAM (rwx) : ORIGIN = 0x00010000, LENGTH = 16M - 64K }
INCLUDE sections.ld
