#!/usr/bin/env python3
"""Check pinned QEMU PXA register models with QTest; no guest CPU or OEM ROM.

This tests the upstream emulator's behavior, not HTC Blue Angel hardware.
The timer reset omission and OIER semantics are deliberately recorded.
"""
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

from qemu_control import Qmp, connect, stop_process

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "fd1952d814da738ed107e05583b3e02ac11e88ff"
MACHINES = {"connex": 3_686_400, "verdex": 3_250_000, "mainstone": 3_250_000}
UART = 0x40100000
TIMER = 0x40A00000
PIC = 0x40D00000
OSCR, OSSR, OIER = TIMER + 0x10, TIMER + 0x14, TIMER + 0x1C
ICIP, ICMR, ICLR, ICFP, ICPR = (PIC + n for n in (0, 4, 8, 12, 16))
TIMER_IRQ = 1 << 26
MASK32 = 0xFFFFFFFF
SOURCES = {
    "board_wiring": f"https://gitlab.com/qemu-project/qemu/-/blob/{COMMIT}/hw/arm/pxa2xx.c",
    "timer": f"https://gitlab.com/qemu-project/qemu/-/blob/{COMMIT}/hw/timer/pxa2xx_timer.c",
    "pic": f"https://gitlab.com/qemu-project/qemu/-/blob/{COMMIT}/hw/arm/pxa2xx_pic.c",
    "uart": f"https://gitlab.com/qemu-project/qemu/-/blob/{COMMIT}/hw/char/serial.c",
    "qtest_accelerator": f"https://gitlab.com/qemu-project/qemu/-/blob/{COMMIT}/accel/qtest/qtest.c",
    "dummy_cpu_thread": f"https://gitlab.com/qemu-project/qemu/-/blob/{COMMIT}/accel/dummy-cpus.c",
}


def equal(actual, expected, label):
    """Keep assertions active even when Python is invoked with -O."""
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, observed {actual!r}")


class QTest:
    def __init__(self, path, process, transcript):
        self.socket = connect(path, process)
        self.stream = self.socket.makefile("rwb", buffering=0)
        self.transcript = transcript

    def request(self, command):
        self.transcript.write(f"> {command}\n")
        self.transcript.flush()
        self.stream.write(command.encode("ascii") + b"\n")
        while True:
            line = self.stream.readline()
            if not line:
                raise RuntimeError(f"QTest closed while handling {command}")
            response = line.decode("ascii").strip()
            self.transcript.write(f"< {response}\n")
            self.transcript.flush()
            # Intercepted IRQ notifications, if enabled in a future test, are
            # asynchronous. Current checks read PIC registers directly.
            if response.startswith("IRQ "):
                continue
            if not (response == "OK" or response.startswith("OK ")):
                raise RuntimeError(f"QTest {command}: {response}")
            return response.split()[1:]

    def readl(self, address):
        return int(self.request(f"readl {address:#x}")[0], 0)

    def readb(self, address):
        return int(self.request(f"readb {address:#x}")[0], 0)

    def writel(self, address, value):
        self.request(f"writel {address:#x} {value:#x}")

    def writeb(self, address, value):
        self.request(f"writeb {address:#x} {value:#x}")

    def step(self, nanoseconds):
        return int(self.request(f"clock_step {nanoseconds}")[0], 0)

    def close(self):
        self.stream.close()
        self.socket.close()


def prepare_timer(qtest):
    """Put only the emulator's timer 0..3 and PIC bank 0 in known states."""
    qtest.writel(OIER, 0)
    qtest.writel(OSSR, 0xFFF)
    qtest.writel(ICMR, 0)
    qtest.writel(ICLR, 0)
    for timer in range(4):
        qtest.writel(TIMER + 4 * timer, 0x7FFFFFFF)
    qtest.writel(OSCR, 0)
    qtest.writel(OSSR, 0xFFF)


def advance_ticks(qtest, frequency, ticks):
    # Step beyond the match. The model floors timer deadline conversion, so
    # the tests do not mistake its rounding behavior for silicon precision.
    nanoseconds = (ticks * 1_000_000_000 + frequency - 1) // frequency + 1
    qtest.step(nanoseconds)
    return nanoseconds


def test_uart(qtest, serial):
    # pxa2xx.c creates generic serial_mm with reg_shift=2. Byte writes here
    # exercise that model, including register spacing and DLAB selection.
    qtest.writeb(UART + 3 * 4, 0x80)
    qtest.writeb(UART, 8)
    qtest.writeb(UART + 4, 0)
    qtest.writeb(UART + 3 * 4, 3)
    qtest.writeb(UART + 4, 0)
    equal(qtest.readb(UART + 5 * 4) & 0x60, 0x60, "UART initial THRE/TEMT")
    qtest.writeb(UART, ord("Q"))
    equal(serial.read_bytes(), b"Q", "UART transmitted byte")
    equal(qtest.readb(UART + 5 * 4) & 0x60, 0x60, "UART final THRE/TEMT")
    return {"result": "PASS", "base": UART, "register_shift": 2, "transmitted_hex": "51"}


def test_frequency(qtest, frequency):
    prepare_timer(qtest)
    start = qtest.step(0)
    equal(qtest.readl(OSCR), 0, "OSCR initial value")
    equal(qtest.step(1), start + 1, "QTest first nanosecond")
    equal(qtest.readl(OSCR), 0, "OSCR fractional tick truncation")
    end = qtest.step(999_999_999)
    equal(end - start, 1_000_000_000, "QTest exact virtual interval")
    observed = qtest.readl(OSCR)
    equal(observed, frequency, "OSCR ticks in exactly one virtual second")
    return {"result": "PASS", "virtual_interval_ns": end - start,
            "expected_hz": frequency, "observed_ticks": observed}


def test_oier_and_pic(qtest, frequency):
    prepare_timer(qtest)
    qtest.writel(TIMER, 4096)
    advance_ticks(qtest, frequency, 4097)
    equal(qtest.readl(OSSR) & 1, 0, "disabled OIER suppresses model event")
    equal(qtest.readl(ICPR) & TIMER_IRQ, 0, "disabled timer has no raw PIC pending")
    qtest.writel(OIER, 1)
    equal(qtest.readl(OSSR) & 1, 0, "enabling OIER does not latch missed match")
    # Schedule a fresh match after enabling the timer source.
    qtest.writel(TIMER, (qtest.readl(OSCR) + 4096) & MASK32)
    advance_ticks(qtest, frequency, 4097)
    equal(qtest.readl(OSSR) & 1, 1, "enabled timer latches event")
    equal(qtest.readl(ICPR) & TIMER_IRQ, TIMER_IRQ, "PIC raw pending before mask")
    equal(qtest.readl(ICIP) & TIMER_IRQ, 0, "ICMR masks IRQ pending")
    equal(qtest.readl(ICFP) & TIMER_IRQ, 0, "ICMR masks FIQ pending")
    qtest.writel(ICMR, TIMER_IRQ)
    equal(qtest.readl(ICIP) & TIMER_IRQ, TIMER_IRQ, "unmasked IRQ pending")
    equal(qtest.readl(ICFP) & TIMER_IRQ, 0, "source initially routed to IRQ")
    qtest.writel(ICLR, TIMER_IRQ)
    equal(qtest.readl(ICIP) & TIMER_IRQ, 0, "ICLR removes source from IRQ")
    equal(qtest.readl(ICFP) & TIMER_IRQ, TIMER_IRQ, "ICLR routes source to FIQ")
    qtest.writel(ICLR, 0)
    equal(qtest.readl(ICIP) & TIMER_IRQ, TIMER_IRQ, "ICLR routes source back to IRQ")
    equal(qtest.readl(ICFP) & TIMER_IRQ, 0, "ICLR removes source from FIQ")
    qtest.writel(ICLR, TIMER_IRQ)
    qtest.writel(ICMR, 0)
    equal(qtest.readl(ICPR) & TIMER_IRQ, TIMER_IRQ, "mask retains raw source")
    equal(qtest.readl(ICFP) & TIMER_IRQ, 0, "mask suppresses routed FIQ")
    qtest.writel(ICMR, TIMER_IRQ)
    qtest.writel(OIER, 0)
    equal(qtest.readl(OSSR) & 1, 1, "OIER disable retains latched model event")
    equal(qtest.readl(ICFP) & TIMER_IRQ, TIMER_IRQ, "OIER write does not lower existing model IRQ")
    qtest.writel(OSSR, 0)
    equal(qtest.readl(OSSR) & 1, 1, "OSSR write zero preserves event")
    qtest.writel(OSSR, 2)
    equal(qtest.readl(OSSR) & 1, 1, "OSSR unrelated W1C preserves event")
    qtest.writel(OSSR, 1)
    equal(qtest.readl(OSSR) & 1, 0, "OSSR W1C clears event")
    equal(qtest.readl(ICPR) & TIMER_IRQ, 0, "OSSR W1C lowers PIC raw source")
    equal(qtest.readl(ICFP) & TIMER_IRQ, 0, "OSSR W1C clears routed FIQ")
    return {"result": "PASS", "timer0_pic_bit": 26,
            "properties": ["OIER match gating", "raw pending versus ICMR", "ICLR IRQ/FIQ routing", "OSSR W1C"],
            "model_specific_observations": [
                "A match while OIER is disabled does not set OSSR; enabling OIER later does not recreate it.",
                "Disabling OIER after a match does not clear OSSR or lower its already asserted IRQ; W1C does."]}


def test_w1c_isolation(qtest, frequency):
    prepare_timer(qtest)
    qtest.writel(TIMER, 4096)
    qtest.writel(TIMER + 4, 4096)
    qtest.writel(OIER, 3)
    advance_ticks(qtest, frequency, 4097)
    both = TIMER_IRQ | (TIMER_IRQ << 1)
    equal(qtest.readl(OSSR) & 3, 3, "both timer matches latch")
    equal(qtest.readl(ICPR) & both, both, "both timer sources reach PIC")
    qtest.writel(OSSR, 1)
    equal(qtest.readl(OSSR) & 3, 2, "W1C clears only requested timer event")
    equal(qtest.readl(ICPR) & both, TIMER_IRQ << 1, "W1C lowers only requested PIC input")
    qtest.writel(OSSR, 2)
    equal(qtest.readl(OSSR) & 3, 0, "second W1C clears other timer event")
    equal(qtest.readl(ICPR) & both, 0, "both PIC inputs cleared")
    return {"result": "PASS", "timer_channels": [0, 1], "pic_bits": [26, 27]}


def test_rollover(qtest, frequency):
    prepare_timer(qtest)
    initial = 0xFFFFFFF0
    qtest.writel(OSCR, initial)
    qtest.writel(TIMER, 0x10)
    qtest.writel(OIER, 1)
    qtest.writel(ICMR, TIMER_IRQ)
    start = qtest.step(0)
    end = qtest.step(1_000_000_000)
    expected = (initial + frequency) & MASK32
    observed = qtest.readl(OSCR)
    equal(end - start, 1_000_000_000, "rollover virtual interval")
    equal(observed, expected, "OSCR wraps modulo 2^32")
    equal(qtest.readl(OSSR) & 1, 1, "match across rollover latches")
    equal(qtest.readl(ICIP) & TIMER_IRQ, TIMER_IRQ, "match across rollover reaches IRQ pending")
    qtest.writel(OSSR, 1)
    return {"result": "PASS", "initial_counter": initial, "match": 0x10,
            "virtual_interval_ns": end - start, "expected_counter": expected,
            "observed_counter": observed}


def snapshot(qtest):
    return {name: qtest.readl(address) for name, address in {
        "OSMR0": TIMER, "OSCR": OSCR, "OIER": OIER, "OSSR": OSSR,
        "ICMR": ICMR, "ICLR": ICLR, "ICPR": ICPR,
    }.items()}


def observe_reset_limitation(qtest, qmp, frequency):
    prepare_timer(qtest)
    qtest.writel(TIMER, 0x1234)
    qtest.writel(OIER, 1)
    qtest.writel(ICMR, TIMER_IRQ)
    qtest.writel(ICLR, TIMER_IRQ)
    advance_ticks(qtest, frequency, 0x1235)
    before = snapshot(qtest)
    equal(before["OSSR"] & 1, 1, "reset probe starts with latched timer event")
    virtual_before = qtest.step(0)
    qmp.request("system_reset")
    # QMP reset requests are asynchronous. A cleared PIC mask is a reset
    # completion marker; polling does not advance QTest virtual time.
    deadline = time.monotonic() + 3
    while qtest.readl(ICMR) != 0:
        if time.monotonic() >= deadline:
            raise TimeoutError("QMP system_reset did not reset PIC mask")
        time.sleep(0.01)
    after = snapshot(qtest)
    equal(qtest.step(0), virtual_before, "system_reset probe does not advance virtual time")
    for name in ("OSMR0", "OSCR", "OIER", "OSSR"):
        equal(after[name], before[name], f"pinned model retains {name} across system_reset")
    for name in ("ICMR", "ICLR", "ICPR"):
        equal(after[name], 0, f"PIC resets {name}")
    return {"status": "LIMITATION_TIMER_STATE_PERSISTS", "before": before, "after": after,
            "retained_timer_registers": ["OSMR0", "OSCR", "OIER", "OSSR"],
            "explanation": "QEMU 9.1 pxa2xx-timer has init/realize but no reset callback. PIC resets separately; this is not evidence of correct PXA silicon reset."}


def run(qemu, machine):
    out = ROOT / "target/artifacts/pxa-qtest" / machine
    out.mkdir(parents=True, exist_ok=True)
    result_path = out / "qtest-result.json"
    result_path.unlink(missing_ok=True)
    serial = out / "qemu-uart.log"
    serial.unlink(missing_ok=True)
    frequency = MACHINES[machine]
    result = {"result": "FAIL", "machine": machine, "sources": SOURCES,
              "scope": "QEMU 9.1 PXA register models only; no guest instructions or OEM firmware; not Blue Angel hardware"}
    executable = Path(shutil.which(qemu) or qemu).resolve()
    result["qemu_sha256"] = hashlib.sha256(executable.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="crosshair-qtest-") as temporary:
        temporary = Path(temporary)
        qmp_path, qtest_path = temporary / "qmp", temporary / "qtest"
        args = [qemu, "-machine", machine, "-accel", "qtest", "-S", "-display", "none",
                "-monitor", "none", "-serial", f"file:{serial}", "-nic", "none",
                "-qmp", f"unix:{qmp_path},server=on,wait=off",
                "-qtest", f"unix:{qtest_path},server=on,wait=off",
                "-qtest-log", str(out / "qemu-qtest.log")]
        result["command"] = args
        result["qemu_version"] = subprocess.check_output([qemu, "--version"], text=True)
        if not result["qemu_version"].startswith("QEMU emulator version 9.1.0\n"):
            raise RuntimeError("These model-specific assertions require pinned QEMU 9.1.0")
        with (out / "qemu-stderr.log").open("wb") as stderr, (out / "protocol.log").open("w") as transcript:
            process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=stderr, stdin=subprocess.DEVNULL)
            qmp = qtest = None
            try:
                qmp = Qmp(qmp_path, process)
                qtest = QTest(qtest_path, process, transcript)
                result["prelaunch_run_status"] = qmp.request("query-status")
                equal(result["prelaunch_run_status"]["running"], False, "start in prelaunch")
                # QEMU disables virtual timer callback dispatch while paused.
                # cont enables device time, while the QTest accelerator still
                # uses dummy_start_vcpu_thread: no guest CPU interpreter runs.
                qmp.request("cont")
                result["initial_run_status"] = qmp.request("query-status")
                equal(result["initial_run_status"]["running"], True, "device clock callback dispatch enabled")
                before_registers = qmp.monitor("info registers")
                result["uart"] = test_uart(qtest, serial)
                result["frequency"] = test_frequency(qtest, frequency)
                result["timer_and_pic"] = test_oier_and_pic(qtest, frequency)
                result["w1c_isolation"] = test_w1c_isolation(qtest, frequency)
                result["counter_rollover"] = test_rollover(qtest, frequency)
                after_registers = qmp.monitor("info registers")
                register = lambda text: re.search(r"R15=([0-9a-fA-F]+)", text)[1]
                equal(register(after_registers), register(before_registers), "no guest PC movement during register tests")
                result["cpu_registers_before"] = before_registers
                result["cpu_registers_after"] = after_registers
                result["reset_observation"] = observe_reset_limitation(qtest, qmp, frequency)
                result["final_run_status"] = qmp.request("query-status")
                equal(result["final_run_status"]["running"], True, "QTest device clock dispatch remains enabled after reset")
                result["result"] = "PASS_WITH_RECORDED_MODEL_LIMITATIONS"
                qmp.request("quit")
                process.wait(timeout=3)
                equal(process.returncode, 0, "QEMU clean exit")
            except Exception as error:
                result["result"] = "FAIL"
                result["error"] = f"{type(error).__name__}: {error}"
                raise
            finally:
                if qtest:
                    qtest.close()
                if qmp:
                    qmp.close()
                stop_process(process)
                result_path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"PASS {machine}: QTest UART, {frequency} Hz, OIER/W1C, PIC mask/routing, 32-bit rollover; "
          "LIMITATION: timer state survives system_reset; guest CPU never executed")


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--qemu", default=os.environ.get("QEMU_PXA", str(ROOT / "local/qemu-pxa/bin/qemu-system-arm")))
    parser.add_argument("--machine", choices=MACHINES)
    args = parser.parse_args()
    for machine in [args.machine] if args.machine else MACHINES:
        run(args.qemu, machine)


if __name__ == "__main__":
    main()
