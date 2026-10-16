#!/usr/bin/env python3
"""Execute a real ARM guest; require UART bytes AND a stopped-CPU idle record."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BANNER = "CROSSHAIR BOOT 0.1 — HELLO FROM RUST\r\n".encode()
PANIC = "CROSSHAIR PANIC — HALTED\r\n".encode()


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--panic-test", action="store_true")
    parser.add_argument("--qemu", default=os.environ.get("QEMU_SYSTEM_ARM", "qemu-system-arm"))
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    out = ROOT / "target/artifacts" / ("versatilepb-panic" if args.panic_test else "versatilepb")
    expected = PANIC if args.panic_test else BANNER
    (out / "smoke-test.json").unlink(missing_ok=True)
    image = json.loads((out / "image.json").read_text())
    actual_hashes = {name: hashlib.sha256((out / name).read_bytes()).hexdigest()
                     for name in ("crosshair-boot.elf", "crosshair-boot.bin")}
    assert image["sha256"] == actual_hashes, "image manifest hashes do not match current binaries"
    symbols = image["symbols"]
    qemu = args.qemu
    if qemu == "qemu-system-arm" and (ROOT / "local/qemu/bin/qemu-system-arm").exists():
        qemu = str(ROOT / "local/qemu/bin/qemu-system-arm")
    with tempfile.TemporaryDirectory(prefix="crosshair-") as temp:
        qmp_path = str(Path(temp) / "qmp.sock")
        command = [qemu, "-machine", "versatilepb,audiodev=audio0", "-cpu", "arm926", "-m", "128M", "-accel", "tcg",
                   "-display", "none", "-monitor", "none", "-serial", "stdio", "-nic", "none",
                   "-audiodev", "none,id=audio0", "-no-reboot", "-qmp", f"unix:{qmp_path},server=on,wait=off",
                   "-kernel", str(out / "crosshair-boot.elf"),
                   # Poison the stage field after ELF loading. Successful boot
                   # requires entry.S to clear BSS, rather than relying on QEMU.
                   "-device", f"loader,addr={symbols['CROSSHAIR_BOOT_RECORD'] + 4:#x},data=0xa5a5a5a5,data-len=4"]
        serial_path, stderr_path = out / "qemu-uart.log", out / "qemu-stderr.log"
        with serial_path.open("wb") as serial, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(command, stdout=serial, stderr=stderr)
            try:
                deadline = time.monotonic() + args.timeout
                while expected not in serial_path.read_bytes() or not Path(qmp_path).exists():
                    if process.poll() is not None:
                        raise RuntimeError(f"QEMU exited {process.returncode}: {stderr_path.read_text()}")
                    if time.monotonic() >= deadline:
                        raise RuntimeError(f"guest UART timeout: {serial_path.read_bytes()!r}")
                    time.sleep(0.02)
                # Allow the guest to finish its record and branch to idle.
                time.sleep(0.1)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as qmp:
                    qmp.settimeout(3)
                    qmp.connect(qmp_path)
                    stream = qmp.makefile("rwb", buffering=0)
                    greeting = json.loads(stream.readline())
                    assert "QMP" in greeting

                    def request(name, arguments=None):
                        msg = {"execute": name}
                        if arguments is not None:
                            msg["arguments"] = arguments
                        stream.write(json.dumps(msg).encode() + b"\n")
                        while True:
                            response = json.loads(stream.readline())
                            if "error" in response:
                                raise RuntimeError(response)
                            if "return" in response:
                                return response["return"]

                    def monitor(command):
                        return request("human-monitor-command", {"command-line": command})

                    request("qmp_capabilities")
                    request("stop")
                    registers = monitor("info registers")
                    memory = monitor(f"xp /6wx {symbols['CROSSHAIR_BOOT_RECORD']:#x}")
                    pc = int(re.search(r"R15=([0-9a-fA-F]+)", registers)[1], 16)
                    sp = int(re.search(r"R13=([0-9a-fA-F]+)", registers)[1], 16)
                    psr = int(re.search(r"PSR=([0-9a-fA-F]+)", registers)[1], 16)
                    assert pc == symbols["kernel_idle"], f"not in idle: {registers}"
                    assert symbols["__stack_bottom"] <= sp <= symbols["__stack_top"] and sp % 8 == 0
                    assert psr & 0xff == 0xd3, f"expected SVC ARM IRQ/FIQ masked: {registers}"
                    # HMP lines also contain an address. Drop that per line.
                    values = []
                    for line in memory.splitlines():
                        if ":" in line:
                            values.extend(int(v, 16) for v in re.findall(r"0x([0-9a-fA-F]+)", line.split(":", 1)[1]))
                    assert values[:2] == [0x43524f53, 3 if args.panic_test else 2], memory
                    assert values[5] == len(expected), memory
                    assert serial_path.read_bytes() == expected, "unexpected/repeated UART output"
                    evidence = dict(result="PASS", command=command,
                                    qemu_version=subprocess.check_output([qemu, "--version"], text=True),
                                    image_sha256=actual_hashes, registers=registers, memory=memory,
                                    expected_utf8=expected.decode(), stage=values[1])
                    (out / "smoke-test.json").write_text(json.dumps(evidence, indent=2) + "\n")
                    request("quit")
                    process.wait(timeout=3)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
    print(expected.decode().strip())
    print("PASS: real ARM926 execution, UART, SVC/stack, boot record and controlled idle")


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Smoke verification requires Python assertions; unset PYTHONOPTIMIZE")
    main()
