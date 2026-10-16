#!/usr/bin/env python3
"""Copy an explicit text-only set of local E2A evidence into the public tree.

Presentation paths are normalized; guest/binary hashes retain actual values.
No binaries, firmware, block devices, credentials, or Git history are read.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("public_export", ROOT / "scripts/export-public.py")
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--qemu-cache", type=Path, default=ROOT / "local/qemu-blueangel")
    args = parser.parse_args()
    output = ROOT / "crosshair-emulator/evidence/e2a"
    copies = {}
    for variant in ("normal", "mmio-test"):
        for name in ("image.json", "elf-report.txt", "disassembly.txt", "size.txt"):
            copies[f"images/{variant}/{name}"] = ROOT / "target/artifacts/e2a" / variant / name
    for scenario in ("boot-reset", "fault-1", "fault-2", "fault-3", "fault-4"):
        for name in ("result.json", "qemu-uart.log", "qemu-stderr.log", "memory-protocol.log"):
            copies[f"execution/{scenario}/{name}"] = ROOT / "target/artifacts/e2a-tests" / scenario / name
    for name in ("result.json", "protocol.log", "qemu-uart.log", "qemu-stderr.log"):
        copies[f"qtest/{name}"] = ROOT / "target/artifacts/e2a-qtest" / name
    for name in ("source.json", "version.txt", "machines.txt", "resolved-devices.mak", "host-tools.txt", "loader.txt"):
        copies[f"build/{name}"] = args.qemu_cache / "evidence" / name
    # Refuse to package a stale/failed run as a successful presentation copy.
    for source in copies.values():
        if source.name == "result.json":
            if json.loads(source.read_text())["result"] != "PASS":
                raise RuntimeError(f"Cannot publish failed evidence: {source}")
    hashes = {}
    for relative, source in copies.items():
        # Decode bytes directly: read_text() would silently convert the
        # guest UART's CRLF to LF before its byte-exact evidence is copied.
        original = source.read_bytes()
        text = export.normalize(original.decode("utf-8"), ROOT)
        if export.PRIVATE_PATH.search(text) or export.SECRET.search(text):
            raise ValueError(f"Private material in {relative}")
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(text.encode("utf-8"))
        if source.name == "qemu-uart.log" and destination.read_bytes() != original:
            raise RuntimeError("UART evidence must remain byte-exact")
        hashes[relative] = hashlib.sha256(destination.read_bytes()).hexdigest()
    (output / "manifest.json").write_text(json.dumps({
        "scope": "presentation copies of executed local E2A tests, not hardware traces",
        "normalization": "host paths/hostnames and temporary socket names only; image/binary hashes retain actual values",
        "uart_logs_byte_exact": True,
        "sha256": hashes,
    }, indent=2) + "\n")
    print(f"Collected {len(copies)} text files of verified E2A evidence")


if __name__ == "__main__":
    main()
