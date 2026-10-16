#!/usr/bin/env python3
"""Execute Crosshair on our experimental QEMU board; no physical hardware."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from qemu_control import Qmp, stop_process
from qtest_pxa import QTest, equal

ROOT = Path(__file__).resolve().parents[1]
MACHINE = "crosshair-blueangel-e2a"
PASS = "CROSSHAIR E2A — UART TIMER IRQ PASS\r\n".encode()
ABORT = "CROSSHAIR E2A — DATA ABORT PASS\r\n".encode()
FAULTS = {1: (0x40a00020, "unsupported_timer_register"),
          2: (0x40d00000, "read_only_pic_write"),
          3: (0x40a00010, "unsupported_byte_width"),
          4: (0x50000000, "unmapped_address")}


def words(text):
    return [int(v, 16) for line in text.splitlines() if ":" in line
            for v in re.findall(r"0x([0-9a-fA-F]+)", line.split(":", 1)[1])]


def wait_uart(process, path, expected, timeout):
    deadline = time.monotonic() + timeout
    while path.read_bytes() != expected:
        current = path.read_bytes()
        if process.poll() is not None or b"FAIL" in current or time.monotonic() >= deadline:
            raise RuntimeError(f"E2A guest failed/timed out: rc={process.poll()}, uart={current!r}")
        time.sleep(0.01)


def qemu_version(qemu):
    """Bound version probing even if a host executable stalls before main."""
    process = subprocess.Popen([qemu, "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        output, _ = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass  # An uninterruptible host process has SIGKILL pending.
        raise TimeoutError("QEMU --version stalled; check the local executable/signature") from None
    equal(process.returncode, 0, "QEMU version probe exit")
    version = output.decode("utf-8")
    if not version.startswith("QEMU emulator version 9.2.0\n"):
        raise RuntimeError(f"E2A requires pinned QEMU 9.2.0, observed {version!r}")
    return version


def settle_idle(qmp, idle):
    """Do not confuse UART completion with reaching the terminal branch."""
    deadline = time.monotonic() + 2
    while True:
        registers = qmp.monitor("info registers")
        if int(re.search(r"R15=([0-9a-fA-F]+)", registers)[1], 16) == idle:
            return registers
        if time.monotonic() > deadline:
            raise TimeoutError(f"UART completed but guest failed to reach idle: {registers}")
        qmp.request("cont")
        time.sleep(0.001)
        qmp.request("stop")


def run(qemu, selector=0):
    variant = "mmio-test" if selector else "normal"
    image_dir = ROOT / "target/artifacts/e2a" / variant
    out = ROOT / "target/artifacts/e2a-tests" / (f"fault-{selector}" if selector else "boot-reset")
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").unlink(missing_ok=True)
    image = json.loads((image_dir / "image.json").read_text())
    actual = {name: hashlib.sha256((image_dir / name).read_bytes()).hexdigest()
              for name in image["sha256"]}
    equal(actual, image["sha256"], "guest hashes")
    symbols = image["symbols"]
    result = {"result": "FAIL", "machine": MACHINE, "image_sha256": actual,
              "scope": "experimental QEMU pxa260 proxy, not hardware-validated PXA263",
              "qemu_version": qemu_version(qemu),
              "qemu_sha256": hashlib.sha256(Path(shutil.which(qemu) or qemu).read_bytes()).hexdigest()}
    with tempfile.TemporaryDirectory(prefix="crosshair-e2a-") as temp:
        qmp_path = Path(temp) / "qmp"
        qtest_path = Path(temp) / "memory"
        args = [qemu, "-machine", MACHINE, "-accel", "tcg", "-display", "none",
                "-monitor", "none", "-serial", "stdio", "-nic", "none", "-S",
                "-qtest", f"unix:{qtest_path},server=on,wait=off",
                "-qtest-log", str(out / "memory-server.log"),
                "-qmp", f"unix:{qmp_path},server=on,wait=off", "-d", "guest_errors",
                "-device", f"loader,file={image_dir / 'crosshair-e2a.elf'},cpu-num=0"]
        if selector:
            args += ["-device", f"loader,addr={symbols['CROSSHAIR_E2A_FAULT_SELECTOR']:#x},data={selector},data-len=4"]
        result["command"] = args
        uart_path = out / "qemu-uart.log"
        with uart_path.open("wb") as uart, (out / "qemu-stderr.log").open("wb") as stderr, (out / "memory-protocol.log").open("w") as memory_protocol:
            process = subprocess.Popen(args, stdout=uart, stderr=stderr, stdin=subprocess.DEVNULL)
            qmp = memory_client = None
            try:
                qmp = Qmp(qmp_path, process)
                memory_client = QTest(qtest_path, process, memory_protocol)
                rounds = []
                for boot in range(1 if selector else 2):
                    # Do not depend on loader/reset ordering for this proof.
                    # Poison after reset while TCG is stopped and read it
                    # back; only our entry may clear it before rust_main.
                    deadline = time.monotonic() + 3
                    while int(re.search(r"R15=([0-9a-fA-F]+)", qmp.monitor("info registers"))[1], 16) != symbols["_start"]:
                        if time.monotonic() > deadline:
                            raise TimeoutError("reset did not restore ELF entry while stopped")
                        time.sleep(0.001)
                    stage_address = symbols["CROSSHAIR_PXA_RECORD"] + 4
                    memory_client.writel(stage_address, 0xa5a5a5a5)
                    pre_entry_stage = memory_client.readl(stage_address)
                    equal(pre_entry_stage, 0xa5a5a5a5, "BSS poison survives after ROM reset, before ARM entry")
                    qmp.request("cont")
                    wait_uart(process, uart_path, ABORT if selector else PASS * (boot + 1), 10)
                    if qmp is None:
                        qmp = Qmp(qmp_path, process)
                    qmp.request("stop")
                    registers = settle_idle(qmp, symbols["kernel_idle"])
                    record = words(qmp.monitor(f"xp /12wx {symbols['CROSSHAIR_PXA_RECORD']:#x}"))
                    reg = lambda name: int(re.search(rf"{name}=([0-9a-fA-F]+)", registers)[1], 16)
                    equal(reg("R15"), symbols["kernel_idle"], "terminal PC")
                    equal(reg("PSR") & 0xff, 0xd3, "terminal SVC/ARM/IRQ/FIQ masked")
                    if not (symbols["__stack_bottom"] <= reg("R13") <= symbols["__stack_top"] and reg("R13") % 8 == 0):
                        raise AssertionError("SVC stack out of bounds/alignment")
                    equal(record[0], 0x50584152, "boot record magic")
                    equal(record[5], 0x69052903, "experimental pxa260 MIDR")
                    if selector:
                        equal(record[1:3], [5, 0], "abort stage with no IRQs")
                        equal(record[6], selector, "armed MMIO probe reached abort vector")
                        equal(record[7] & 0xf, 8, "DFSR external abort")
                        equal((record[7] >> 12) & 1, int(selector != 4),
                              "DFSR distinguishes MEMTX_ERROR from unmapped DECODE_ERROR")
                        equal(record[8], FAULTS[selector][0], "DFAR failing address")
                        result["fault_probe"] = FAULTS[selector][1]
                    else:
                        equal(record[1:3], [2, 3], "boot and three real CPU IRQs")
                        equal(record[6], 0, "no guest error")
                        if not (record[3] >= 65535 and ((record[4]-record[3]) & 0xffffffff) >= 131070):
                            raise AssertionError("timer counter spacing")
                        if not (record[7] & (1 << 26) and record[8] & 1):
                            raise AssertionError("handler did not observe pending timer IRQ")
                        equal(record[9], 0, "PIC masked at terminal idle")
                        equal(record[10], 0, "OSSR acknowledged")
                        if not (symbols["__irq_stack_bottom"] <= record[11] < symbols["__irq_stack_top"] and record[11] % 8 == 0):
                            raise AssertionError("IRQ stack out of bounds/alignment")
                    rounds.append({"boot": boot + 1, "pre_entry_stage": pre_entry_stage,
                                   "registers": registers, "record_words": record})
                    if boot == 0 and not selector:
                        # Reset while stopped, then poison after ROM restore
                        # at the start of the next iteration.
                        qmp.request("system_reset")
                equal(uart_path.read_bytes(), ABORT if selector else PASS * 2, "exact guest UART bytes")
                result.update(result="PASS", boots=rounds, uart_utf8=uart_path.read_text())
                qmp.request("quit")
                process.wait(timeout=3)
                equal(process.returncode, 0, "QEMU clean exit")
            except Exception as error:
                result["result"] = "FAIL"
                result["error"] = f"{type(error).__name__}: {error}"
                raise
            finally:
                try:
                    if memory_client:
                        memory_client.close()
                    if qmp:
                        qmp.close()
                    stop_process(process)
                except Exception as error:
                    result["result"] = "FAIL"
                    result["cleanup_error"] = f"{type(error).__name__}: {error}"
                    raise
                finally:
                    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"PASS E2A {FAULTS[selector][1] if selector else 'boot + system_reset reboot'}")


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--qemu", default=os.environ.get("QEMU_BLUEANGEL", str(ROOT / "local/qemu-blueangel/bin/qemu-system-arm")))
    args = parser.parse_args()
    run(args.qemu)
    for selector in FAULTS:
        run(args.qemu, selector)


if __name__ == "__main__":
    main()
