#!/usr/bin/env python3
"""Inspect three ARM code ranges in the pinned PXADroid HaRET, without execution.

This is an immutable-artifact reader, not a general PE loader or HaRET validator.
Input must match the recorded SHA-256 before any PE parsing or disassembly.
All instruction addresses are preferred PE VAs, not PDA physical observations.
Install the exact analysis dependencies from tools/requirements-haret.txt.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat


EXPECTED_SHA256 = "00d3da3a7610a634f7ef1509f7e98460aabac812349ce3dc73e798b6be701be0"
EXPECTED_BYTES = 144384
VERSIONS = {"pefile": "2024.8.26", "capstone": "5.0.6"}
RANGES = (
    ("copy_words", 0x15514, 0x15540),
    ("preloader", 0x1559C, 0x157E4),
    ("trampoline", 0x15D44, 0x15DD0),
)
EXPECTED_INSTRUCTIONS = (
    (0x2622C, "add", "sb, r3, #0x100"),
    (0x26250, "add", "sl, r3, #0x8000"),
    (0x263CC, "mov", "r0, #0"),
    (0x263D0, "ldr", "r1, [r7]"),
    (0x263D4, "mov", "r2, sb"),
    (0x263DC, "mov", "pc, sl"),
    (0x26998, "bic", "r0, r0, #5"),
    (0x2699C, "bic", "r0, r0, #0x1000"),
    (0x269A0, "mcr", "p15, #0, r0, c1, c0, #0"),
    (0x269B4, "mcr", "p15, #0, r0, c13, c0, #0"),
    (0x269CC, "mov", "pc, r6"),
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_pinned(binary):
    # Bound memory consumption even for a wrong or concurrently growing input.
    # Read-only mode never maps or executes the PE. Reject FIFOs/devices first.
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(binary, flags), "rb") as source:
        require(stat.S_ISREG(os.fstat(source.fileno()).st_mode),
                "input must be a regular file")
        data = source.read(EXPECTED_BYTES + 1)
    digest = hashlib.sha256(data).hexdigest()
    require(digest == EXPECTED_SHA256,
            f"unexpected input SHA-256: {digest}; require {EXPECTED_SHA256}")
    require(len(data) == EXPECTED_BYTES, "unexpected pinned input length")
    return data


def inspect(data, input_name):
    # Dependencies are imported only after the hash gate in read_pinned().
    import capstone
    import pefile

    for module in (pefile, capstone):
        require(module.__version__ == VERSIONS[module.__name__],
                f"require {module.__name__}=={VERSIONS[module.__name__]}")
    pe = pefile.PE(data=data)
    require(pe.FILE_HEADER.Machine == 0x1C0, "need the pinned ARM PE")
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    report = {
        "input": input_name,
        "sha256": EXPECTED_SHA256,
        "bytes": len(data),
        "image_base": hex(pe.OPTIONAL_HEADER.ImageBase),
        "tools": VERSIONS,
        "address_notice": "Preferred PE VAs are before relocation; none is a PDA physical MMIO/RAM observation.",
        "ranges": [],
    }
    by_va = {}
    for name, start, end in RANGES:
        require(0 <= start < end <= len(data) and start % 4 == end % 4 == 0,
                f"invalid bounded range: {name}")
        va = pe.OPTIONAL_HEADER.ImageBase + pe.get_rva_from_offset(start)
        instructions = list(md.disasm(data[start:end], va))
        require(sum(i.size for i in instructions) == end - start,
                f"undecoded bytes in {name}")
        entries = []
        for instruction in instructions:
            entry = {
                "file_offset": hex(pe.get_offset_from_rva(
                    instruction.address - pe.OPTIONAL_HEADER.ImageBase)),
                "preferred_pe_va": hex(instruction.address),
                "bytes": instruction.bytes.hex(),
                "mnemonic": instruction.mnemonic,
                "operands": instruction.op_str,
            }
            entries.append(entry)
            by_va[instruction.address] = entry
        report["ranges"].append({
            "name": name, "file_start": hex(start),
            "file_end_exclusive": hex(end), "instructions": entries,
        })
    for va, mnemonic, operands in EXPECTED_INSTRUCTIONS:
        instruction = by_va.get(va, {})
        require(instruction.get("mnemonic") == mnemonic
                and instruction.get("operands") == operands,
                f"instruction contract mismatch at preferred PE VA {va:#x}")
    return report, len(by_va)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="pinned HaRET EXE; read only")
    parser.add_argument("output", type=Path, help="new JSON file; parent must exist")
    args = parser.parse_args()
    try:
        data = read_pinned(args.input)
        report, count = inspect(data, args.input.name)
        encoded = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
        # Exclusive creation prevents replacement, including a race after parsing.
        # An output equal to the input also fails here without changing the input.
        with args.output.open("xb") as destination:
            destination.write(encoded)
    except (OSError, ValueError, ImportError) as error:
        parser.exit(1, f"error: {error}\n")
    print(f"Verified {count} ARM instructions in {len(RANGES)} bounded ranges")
    print(f"Evidence: {args.output}")
    print(f"Evidence SHA256: {hashlib.sha256(encoded).hexdigest()}")


if __name__ == "__main__":
    main()
