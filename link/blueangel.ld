/* HaRET source contract, NOT yet validated on the owner's PDA2k.
 * Image begins at RAMADDR 0xa0000000 + 0x8000. Self-imposed 1 MiB cap;
 * this does not assert that this range is safe for WM user state. */
MEMORY { RAM (rwx) : ORIGIN = 0xa0008000, LENGTH = 1M }
INCLUDE sections.ld
