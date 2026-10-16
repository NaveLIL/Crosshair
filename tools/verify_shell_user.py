#!/usr/bin/env python3
"""Verify the own statically linked Shell User image before kernel embedding."""
import argparse
import json
from pathlib import Path
import subprocess

from qtest_pxa import equal
from smoke_security import digest, elf_loads

BASE, DATA, GUARD, STACK, END = 0x01000000, 0x01010000, 0x0103F000, 0x01040000, 0x01048000
FB_BYTES = 153600


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("llvm", type=Path)
    args = parser.parse_args()
    out, llvm = args.directory, args.llvm
    elf = out / "crosshair-shell-user.elf"
    flat = out / "crosshair-shell-user.bin"
    entry, loads = elf_loads(elf)
    equal(entry, BASE, "fixed own User ARM image entry VA")
    raw = flat.read_bytes()
    equal(bool(raw), True, "complete nonempty embedded User image")
    equal(len(raw), max(load["pa"] + load["filesz"] for load in loads if load["filesz"]) - BASE,
          "flat User file extent matches actual initialized ELF segments")
    coverage = bytearray(len(raw))
    for load in loads:
        address, filesz, memsz, flags = load["pa"], load["filesz"], load["memsz"], load["flags"]
        equal(BASE <= address <= END and memsz <= END - address, True, "User ELF allocation bounds")
        equal(flags in (5, 6), True, "only RX code or RW data segments")
        if flags == 5:
            equal(BASE <= address and address + memsz <= DATA, True, "all executable ELF bytes fit the RO code allocation")
        else:
            equal(DATA <= address and address + memsz <= END, True, "RW allocation is outside immutable code")
        if filesz:
            start = address - BASE
            equal(start >= 0 and start + filesz <= len(raw), True, "initialized flat segment bounds")
            equal(raw[start:start + filesz], load["bytes"], "flat bytes equal the hashed User ELF segment")
            equal(any(coverage[start:start + filesz]), False, "initialized ELF segments do not overlap")
            coverage[start:start + filesz] = bytes([1]) * filesz
    equal(any(byte for index, byte in enumerate(raw) if not coverage[index]), False,
          "flat alignment gaps contain only zero padding")
    def run(*arguments):
        return subprocess.check_output(arguments, text=True)
    symbols = {}
    for line in run(str(llvm / "llvm-nm"), "--defined-only", "--format=posix", str(elf)).splitlines():
        fields = line.split()
        if len(fields) >= 3:
            symbols[fields[0]] = int(fields[2], 16)
    equal(symbols["SHELL_FRAMEBUFFER"], DATA, "single guarded framebuffer starts at exact User data VA")
    equal(DATA + 128 + FB_BYTES <= symbols["SHELL_USER_RECORD"] <= GUARD - 176, True,
          "complete User observation lies after framebuffer and below unmapped guard")
    equal(run(str(llvm / "llvm-nm"), "--undefined-only", str(elf)).strip(), "", "User image has no unresolved kernel/runtime symbols")
    report = run(str(llvm / "llvm-readobj"), "--file-headers", "--program-headers", "--arch-specific", str(elf))
    equal("ARM v5TE" in report, True, "actual compiler ARMv5TE attributes")
    (out / "elf-report.txt").write_text(report)
    (out / "disassembly.txt").write_text(run(str(llvm / "llvm-objdump"), "-d", str(elf)))
    (out / "size.txt").write_text(run(str(llvm / "llvm-size"), str(elf)))
    manifest = {"entry": entry, "address_type": "User virtual", "physical_embedding_base": 0xA0400000,
                "segments": [{key: value for key, value in load.items() if key != "bytes"} for load in loads],
                "symbols": symbols, "sha256": {path.name: digest(path.read_bytes()) for path in (elf, flat)}}
    (out / "user-image.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Verified Shell User ELF32 ARMv5TE: entry VA={entry:#x}, initialized flat bytes={len(raw)}")


if __name__ == "__main__":
    main()
