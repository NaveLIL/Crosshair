#!/usr/bin/env python3
"""Execute our ARMv5 guest on three upstream PXA boards; never use OEM ROM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from qemu_control import Qmp, stop_process

ROOT = Path(__file__).resolve().parents[1]
PASS = "CROSSHAIR PXA REFERENCE — UART TIMER IRQ PASS\r\n".encode()
MACHINES = {"connex": (16, 0x69052d00), "verdex": (32, 0x69054114), "mainstone": (None, 0x69054117)}


def run(qemu, machine, timeout):
    image_dir = ROOT / "target/artifacts/pxa-reference"
    image = json.loads((image_dir / "image.json").read_text())
    actual = {name: hashlib.sha256((image_dir / name).read_bytes()).hexdigest() for name in image["sha256"]}
    if image["sha256"] != actual:
        raise RuntimeError("PXA guest hashes do not match manifest")
    out = image_dir / machine
    out.mkdir(exist_ok=True)
    (out / "smoke-test.json").unlink(missing_ok=True)
    symbols = image["symbols"]
    flash_mib, cpuid = MACHINES[machine]
    with tempfile.TemporaryDirectory(prefix="crosshair-pxa-") as temp:
        temp = Path(temp)
        qmp_path = temp / "qmp"
        args = [qemu, "-machine", machine, "-accel", "tcg", "-display", "none", "-monitor", "none",
                "-serial", "stdio", "-nic", "none", "-no-reboot", "-qmp", f"unix:{qmp_path},server=on,wait=off"]
        if flash_mib:
            # Sparse zero-filled synthetic backing. Snapshot changes are
            # temporary, and no host block-device path can enter this command.
            flash = temp / "synthetic-flash.raw"
            with flash.open("xb") as stream:
                stream.truncate(flash_mib * 1024 * 1024)
            args += ["-drive", f"if=pflash,format=raw,file={flash},snapshot=on"]
            args += ["-device", f"loader,file={image_dir / 'crosshair-pxa-reference.elf'},cpu-num=0"]
        else:
            args += ["-kernel", str(image_dir / "crosshair-pxa-reference.elf")]
        # Ensure BSS is cleared by our entry, rather than inherited zero RAM.
        args += ["-device", f"loader,addr={symbols['CROSSHAIR_PXA_RECORD'] + 4:#x},data=0xa5a5a5a5,data-len=4"]
        with (out / "qemu-uart.log").open("wb") as uart, (out / "qemu-stderr.log").open("wb") as stderr:
            process = subprocess.Popen(args, stdout=uart, stderr=stderr, stdin=subprocess.DEVNULL)
            qmp = None
            try:
                deadline = time.monotonic() + timeout
                log = out / "qemu-uart.log"
                while PASS not in log.read_bytes():
                    if process.poll() is not None:
                        raise RuntimeError(f"{machine}: exit {process.returncode}: {(out/'qemu-stderr.log').read_text()}")
                    if b"FAIL" in log.read_bytes() or time.monotonic() >= deadline:
                        raise RuntimeError(f"{machine}: guest failed or timed out: {log.read_bytes()!r}")
                    time.sleep(0.02)
                time.sleep(0.03)
                qmp = Qmp(qmp_path, process)
                qmp.request("stop")
                registers = qmp.monitor("info registers")
                memory = qmp.monitor(f"xp /12wx {symbols['CROSSHAIR_PXA_RECORD']:#x}")
                values = [int(v, 16) for line in memory.splitlines() if ":" in line
                          for v in re.findall(r"0x([0-9a-fA-F]+)", line.split(":", 1)[1])]
                register = lambda name: int(re.search(rf"{name}=([0-9a-fA-F]+)", registers)[1], 16)
                assert register("R15") == symbols["kernel_idle"], registers
                assert register("PSR") & 0xff == 0xd3, registers
                assert symbols["__stack_bottom"] <= register("R13") <= symbols["__stack_top"]
                assert register("R13") % 8 == 0
                assert values[:3] == [0x50584152, 2, 3], memory
                assert values[3] >= 65_535 and ((values[4] - values[3]) & 0xffffffff) >= 131_070, memory
                assert values[5] == cpuid and values[6] == 0, memory
                assert values[7] & (1 << 26) and values[8] & 1, memory
                assert values[9] == 0 and values[10] & 1 == 0, memory
                assert symbols["__irq_stack_bottom"] <= values[11] < symbols["__irq_stack_top"] and values[11] % 8 == 0, memory
                assert log.read_bytes() == PASS
                (out / "smoke-test.json").write_text(json.dumps({
                    "result": "PASS", "machine": machine, "image_sha256": actual,
                    "qemu_version": subprocess.check_output([qemu, "--version"], text=True),
                    "registers": registers, "memory": memory, "record_words": values,
                    "uart_utf8": PASS.decode(), "command": args,
                    "scope": "synthetic upstream PXA board, not Blue Angel hardware",
                }, indent=2) + "\n")
                qmp.request("quit")
                process.wait(timeout=3)
            finally:
                if qmp:
                    qmp.close()
                stop_process(process)
    print(f"PASS {machine}: UART, three real timer IRQs, exception return to SVC, two stacks, terminal idle")


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--qemu", default=os.environ.get("QEMU_PXA", str(ROOT / "local/qemu-pxa/bin/qemu-system-arm")))
    parser.add_argument("--machine", choices=MACHINES)
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    for machine in [args.machine] if args.machine else MACHINES:
        run(args.qemu, machine, args.timeout)


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Smoke verification requires Python assertions; unset PYTHONOPTIMIZE")
    main()
