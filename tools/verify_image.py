#!/usr/bin/env python3
"""Validate our linked ELF and save the actual machine-code evidence (stdlib only)."""
import hashlib
import argparse
import json
from pathlib import Path
import struct
import subprocess
import sys


def run(*args):
    return subprocess.check_output(args, text=True)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("llvm", type=Path)
    parser.add_argument("--name", default="crosshair-boot")
    parser.add_argument("--split-vectors", action="store_true")
    args = parser.parse_args()
    out, llvm, name = args.output, args.llvm, args.name
    elf = out / f"{name}.elf"
    data = elf.read_bytes()
    assert data[:7] == b"\x7fELF\x01\x01\x01", "need ELF32 little endian"
    fields = struct.unpack_from("<HHIIIIIHHHHHH", data, 16)
    kind, machine, _, entry, phoff, _, flags, _, phsize, phnum, *_ = fields
    assert (kind, machine) == (2, 40), "need static ARM executable"
    assert flags >> 24 == 5 and not flags & 0x400, "need EABI5, no hard float"
    headers = []
    flat = (out / f"{name}.bin").read_bytes()
    vector_seen = False
    for i in range(phnum):
        ptype, offset, va, pa, filesz, memsz, perm, align = struct.unpack_from(
            "<IIIIIIII", data, phoff + i * phsize)
        assert ptype not in (2, 3), "dynamic loader/runtime is forbidden"
        if ptype == 1:
            assert va == pa and filesz <= memsz and offset + filesz <= len(data)
            if args.split_vectors and pa == 0:
                assert filesz == memsz == 64 and perm == 5
                assert (out / "vectors.bin").read_bytes() == data[offset:offset + filesz]
                vector_seen = True
            elif filesz:
                assert pa >= entry and flat[pa - entry:pa - entry + filesz] == data[offset:offset + filesz]
            headers.append(dict(pa=pa, filesz=filesz, memsz=memsz, flags=perm))
    assert any(h["pa"] <= entry < h["pa"] + h["filesz"] and h["flags"] & 1 for h in headers)
    assert len(flat) == max(h["pa"] + h["filesz"] for h in headers if h["filesz"] and h["pa"] >= entry) - entry
    assert vector_seen == args.split_vectors
    symbols = {}
    for line in run(str(llvm / "llvm-nm"), "--defined-only", "--format=posix", str(elf)).splitlines():
        fields = line.split()
        if len(fields) >= 3:
            symbols[fields[0]] = int(fields[2], 16)
    assert symbols["_start"] == entry
    assert symbols["__stack_top"] % 8 == 0
    assert symbols["__stack_top"] - symbols["__stack_bottom"] == 16384
    record = "CROSSHAIR_PXA_RECORD" if args.split_vectors else "CROSSHAIR_BOOT_RECORD"
    assert symbols["__bss_start"] <= symbols[record] < symbols["__bss_end"]
    if args.split_vectors:
        assert symbols["__irq_stack_top"] % 8 == 0
        assert symbols["__irq_stack_top"] - symbols["__irq_stack_bottom"] == 4096
    assert not run(str(llvm / "llvm-nm"), "--undefined-only", str(elf)).strip()
    report = run(str(llvm / "llvm-readobj"), "--file-headers", "--program-headers", "--arch-specific", str(elf))
    assert "ARM v5TE" in report, "unexpected ISA attributes"
    (out / "elf-report.txt").write_text(report)
    (out / "disassembly.txt").write_text(run(str(llvm / "llvm-objdump"), "-d", str(elf)))
    (out / "size.txt").write_text(run(str(llvm / "llvm-size"), str(elf)))
    binaries = [elf, out / f"{name}.bin"]
    if args.split_vectors:
        binaries.append(out / "vectors.bin")
    if out.name == "blueangel":
        padded = out / "crosshair-haret.bin"
        raw = binaries[1].read_bytes()
        assert padded.read_bytes() == raw + bytes((-len(raw)) % 4096)
        binaries.append(padded)
    manifest = dict(entry=entry, flags=flags, segments=headers, symbols=symbols,
                    sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in binaries})
    (out / "image.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Verified ELF32 ARM EABI5 v5TE: entry={entry:#x}, image RAM={symbols['__image_end']-entry} bytes")


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Image verification requires Python assertions; unset PYTHONOPTIMIZE")
    main()
