#!/usr/bin/env python3
"""Exercise the explicit E2B GPIO90 model; no guest CPU or physical pad claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from qemu_control import Qmp, stop_process
from qtest_pxa import QTest, equal, ICIP, ICMR, ICLR, ICFP, ICPR
from smoke_e2a import qemu_version

ROOT = Path(__file__).resolve().parents[1]
MACHINE = "crosshair-blueangel-e2b"
GPIO = 0x40E00000
GPLR, GPDR, GPSR, GPCR, GRER, GFER, GEDR, GAFR = (
    GPIO + offset for offset in (0, 0x0C, 0x18, 0x24, 0x30, 0x3C, 0x48, 0x54))
MASKS = [0xFFFFFFFF, 0xFFFFFFFF, 0x03FFFFFF]
SPECIAL = 0x03C00000  # GPDR2 pins86..89 have inverted direction.
ALL_SPECIAL_GPIO = 0x55000  # GAFR2_U: AF1 for four special pins.
PIC_GPIO = (1 << 8) | (1 << 9) | (1 << 10)


class ObservedQTest(QTest):
    def __init__(self, *args):
        super().__init__(*args)
        self.events = []
        self.levels = [0] * 90

    def request(self, command):
        self.transcript.write(f"> {command}\n")
        self.transcript.flush()
        self.stream.write(command.encode("ascii") + b"\n")
        while True:
            raw = self.stream.readline()
            if not raw:
                raise RuntimeError(f"QTest closed: {command}")
            response = raw.decode("ascii").strip()
            self.transcript.write(f"< {response}\n")
            self.transcript.flush()
            if response.startswith("IRQ "):
                _, action, number = response.split()
                pin = int(number)
                if not 0 <= pin < 90 or action not in ("raise", "lower"):
                    raise AssertionError(f"unexpected IRQ event: {response}")
                self.levels[pin] = int(action == "raise")
                self.events.append([action, pin])
                continue
            if not (response == "OK" or response.startswith("OK ")):
                raise RuntimeError(f"QTest {command}: {response}")
            return response.split()[1:]

    def inject(self, pin, level):
        self.request(f"set_irq_in /machine/gpio unnamed-gpio-in {pin} {level}")

    def lines(self, expected, label):
        self.readl(ICMR)  # Drain asynchronous output notifications.
        equal(self.levels[:len(expected)], expected, label)


def bit_for(pin):
    return 1 << (pin % 32)


def direction(q, pin, output):
    address = GPDR + 4 * (pin // 32)
    value = q.readl(address)
    encoded = not output if pin >= 86 else output
    q.writel(address, (value | bit_for(pin)) if encoded else (value & ~bit_for(pin)))


def function(q, pin, alternate):
    address, shift = GAFR + 4 * (pin // 16), 2 * (pin % 16)
    q.writel(address, (q.readl(address) & ~(3 << shift)) | alternate << shift)


def sample(q, pin):
    return int(bool(q.readl(GPLR + 4 * (pin // 32)) & bit_for(pin)))


def all_inputs(q):
    for bank in range(3):
        q.writel(GPDR + bank * 4, SPECIAL if bank == 2 else 0)
        q.writel(GRER + bank * 4, MASKS[bank])
        q.writel(GFER + bank * 4, MASKS[bank])
        q.writel(GEDR + bank * 4, MASKS[bank])
    for word in range(6):
        q.writel(GAFR + word * 4, ALL_SPECIAL_GPIO if word == 5 else 0)


def snapshot(q):
    return {hex(offset): q.readl(GPIO + offset)
            for offset in list(range(0, 0x18, 4)) + list(range(0x30, 0x6C, 4))}


def test_masks_and_directions(q):
    for group in (GPDR, GRER, GFER):
        for bank, mask in enumerate(MASKS):
            q.writel(group + bank * 4, 0xFFFFFFFF)
            equal(q.readl(group + bank * 4), mask, "implemented bank mask")
    for word in range(6):
        q.writel(GAFR + word * 4, 0xFFFFFFFF)
        equal(q.readl(GAFR + word * 4), 0xFFFFF if word == 5 else 0xFFFFFFFF,
              "implemented AF mask")
    all_inputs(q)
    for pin in range(90):
        q.inject(pin, 0)
        q.writel(GEDR + 4 * (pin // 32), bit_for(pin))
        q.writel(GPSR + 4 * (pin // 32), bit_for(pin))
        equal(sample(q, pin), 0, f"pin{pin} input ignores preloaded high latch")
        direction(q, pin, True)
        equal(sample(q, pin), 1, f"pin{pin} output reveals preloaded high latch")
        q.writel(GPSR + 4 * (pin // 32), 0)
        q.writel(GPCR + 4 * (pin // 32), 0)
        equal(sample(q, pin), 1, f"pin{pin} zero set/clear commands preserve latch")
        q.writel(GPCR + 4 * (pin // 32), bit_for(pin))
        equal(sample(q, pin), 0, f"pin{pin} GPCR clears output")
        q.writel(GPSR + 4 * (pin // 32), bit_for(pin))
        direction(q, pin, False)
        equal(sample(q, pin), 0, f"pin{pin} input disconnects latched output")
        equal(q.readl(GEDR + 4 * (pin // 32)), 0,
              f"pin{pin} direction/output writes do not synthesize edges")
    return {"result": "PASS", "pins_tested": list(range(90)),
            "inverted_direction_pins": [86, 87, 88, 89],
            "preload_while_input": True, "masked_bank2_bits": 26}


def test_edges_and_routing(q):
    all_inputs(q)
    q.writel(ICMR, 0)
    q.writel(ICLR, 0)
    for pin in range(90):
        bank, bit = pin // 32, bit_for(pin)
        expected = 1 << (8 if pin == 0 else 9 if pin == 1 else 10)
        q.inject(pin, 1)
        equal(q.readl(GEDR + 4 * bank), bit, f"pin{pin} rising edge")
        equal(q.readl(ICPR), expected, f"pin{pin} correct raw PIC source")
        equal(q.readl(ICIP), 0, f"pin{pin} PIC mask suppresses CPU pending")
        q.writel(GEDR + 4 * bank, 0)
        equal(q.readl(GEDR + 4 * bank), bit, "W1C zero preserves event")
        q.writel(GEDR + 4 * bank, bit ^ MASKS[bank])
        equal(q.readl(GEDR + 4 * bank), bit, "unrelated W1C preserves event")
        q.writel(GEDR + 4 * bank, bit)
        q.inject(pin, 1)
        equal(q.readl(GEDR + 4 * bank), 0, "same external level is not an edge")
        q.inject(pin, 0)
        equal(q.readl(GEDR + 4 * bank), bit, f"pin{pin} falling edge")
        q.writel(GEDR + 4 * bank, bit)
        equal(q.readl(ICPR), 0, "last W1C lowers raw source")
    # Two shared sources: clearing one must retain the shared line.
    q.inject(2, 1)
    q.inject(89, 1)
    q.writel(GEDR, 1 << 2)
    equal(q.readl(ICPR), 1 << 10, "other bank retains shared line")
    q.writel(GRER + 8, 0)
    q.writel(GFER + 8, 0)
    equal(q.readl(ICPR), 1 << 10, "disabling edges preserves latched status")
    q.writel(GEDR + 8, 1 << 25)
    equal(q.readl(ICPR), 0, "all shared sources cleared")
    return {"result": "PASS", "rising_and_falling_pins": list(range(90)),
            "irq_map": {"0": 8, "1": 9, "2..89": 10},
            "shared_w1c_isolation": True}


def test_af_and_input_gate(q):
    all_inputs(q)
    for pin in range(90):
        bank, bit = pin // 32, bit_for(pin)
        q.inject(pin, 0)
        q.writel(GEDR + bank * 4, bit)
        # AF modes other than normal0 / special1 disconnect GPIO edges.
        for alternate in (0, 1, 2, 3):
            function(q, pin, alternate)
            q.inject(pin, 1)
            enabled = alternate == (1 if pin >= 86 else 0)
            equal(bool(q.readl(GEDR + bank * 4) & bit), enabled,
                  f"pin{pin} AF{alternate} edge gating")
            q.writel(GEDR + bank * 4, bit)
            q.inject(pin, 0)
            q.writel(GEDR + bank * 4, bit)
        function(q, pin, 1 if pin >= 86 else 0)
        direction(q, pin, True)
        q.inject(pin, 1)
        q.inject(pin, 0)
        equal(q.readl(GEDR + bank * 4) & bit, 0, f"pin{pin} output suppresses edges")
        # External line high before reconfiguration: no new physical edge.
        q.inject(pin, 1)
        function(q, pin, 0 if pin >= 86 else 1)
        direction(q, pin, False)
        function(q, pin, 1 if pin >= 86 else 0)
        equal(q.readl(GEDR + bank * 4) & bit, 0,
              f"pin{pin} AF/direction reconfiguration does not invent edge")
        q.inject(pin, 0)
        equal(q.readl(GEDR + bank * 4) & bit, bit,
              f"pin{pin} new input edge works after reconfiguration")
        q.writel(GEDR + bank * 4, bit)
    return {"result": "PASS", "all_af_encodings_all_90_pins": True,
            "edge_gate_status": "explicit subset interpretation: GPIO mode AND effective input",
            "reconfiguration_synthesizes_no_edges": True}


def test_irq_transitions(q):
    all_inputs(q)
    q.request("irq_intercept_out /machine/e2a sysbus-irq")
    q.lines([0, 0], "initial IRQ/FIQ low")
    q.inject(0, 1)
    q.lines([0, 0], "PIC mask holds IRQ low")
    q.writel(ICMR, PIC_GPIO)
    q.lines([1, 0], "unmask raises IRQ")
    q.writel(ICLR, 1 << 8)
    q.lines([0, 1], "GPIO0 route raises FIQ")
    q.inject(1, 1)
    q.lines([1, 1], "GPIO1 raises independent IRQ")
    equal(q.readl(ICIP), 1 << 9, "GPIO1 IRQ pending")
    equal(q.readl(ICFP), 1 << 8, "GPIO0 FIQ pending")
    q.writel(GEDR, 1)
    q.lines([1, 0], "GPIO0 W1C lowers only FIQ")
    q.writel(GEDR, 2)
    q.lines([0, 0], "GPIO1 W1C lowers IRQ")
    q.inject(89, 1)
    q.lines([1, 0], "GPIO89 raises shared IRQ")
    q.writel(GEDR + 8, 1 << 25)
    q.lines([0, 0], "GPIO89 W1C lowers shared IRQ")
    expected = [["raise", 0], ["lower", 0], ["raise", 1], ["raise", 0],
                ["lower", 1], ["lower", 0], ["raise", 0], ["lower", 0]]
    equal(q.events, expected, "exact GPIO IRQ/FIQ transitions")
    return {"result": "PASS", "events": q.events.copy()}


def test_reset(q, qmp):
    all_inputs(q)
    for pin in range(90):
        q.inject(pin, pin % 2)
    for bank in range(3):
        q.writel(GPSR + bank * 4, MASKS[bank])
    q.writel(ICMR, PIC_GPIO)
    q.writel(ICLR, PIC_GPIO)
    before = snapshot(q)
    qmp.request("system_reset")
    deadline = time.monotonic() + 3
    while q.readl(GAFR + 20) != 0:
        if time.monotonic() > deadline:
            raise TimeoutError("E2B GPIO reset did not complete")
        time.sleep(0.01)
    after = snapshot(q)
    expected = {hex(offset): 0 for offset in range(0x0C, 0x18, 4)}
    expected.update({hex(offset): 0 for offset in range(0x30, 0x6C, 4)})
    expected.update({hex(bank * 4): 0xAAAAAAAA & mask for bank, mask in enumerate(MASKS)})
    equal(after, expected, "reset registers; external wire samples persist")
    equal(q.readl(ICPR), 0, "reset clears GPIO raw PIC pending")
    q.lines([0, 0], "reset lowers both physical CPU lines")
    # Latches must be reset as well, despite being write-only command state.
    for bank in range(3):
        q.writel(GPDR + bank * 4, MASKS[bank] & (~SPECIAL if bank == 2 else 0xFFFFFFFF))
    q.writel(GAFR + 20, ALL_SPECIAL_GPIO)
    equal([q.readl(GPLR + bank * 4) for bank in range(3)], [0, 0, 0],
          "synthetic latch0 after reset is visible when all pins drive output")
    return {"result": "PASS", "before": before, "after": after,
            "external_wires_persist": True, "latch0_is_synthetic_choice": True}


def test_invalid(q, stderr):
    before = snapshot(q)
    q.readl(GPIO + 0x6C)
    q.readl(GPSR)
    q.readl(GPCR)
    q.writel(GPLR, 0xFFFFFFFF)
    q.readb(GPDR)
    q.writeb(GPDR, 0xFF)
    q.request(f"readw {GPDR:#x}")
    q.request(f"writew {GPDR:#x} 0xffff")
    q.request(f"readq {GPDR:#x}")
    q.request(f"writeq {GPDR:#x} 0xffffffffffffffff")
    q.readl(GPDR + 1)
    q.writel(GPDR + 1, 0xFFFFFFFF)
    equal(snapshot(q), before, "invalid widths/alignment/directions have no side effects")
    log = stderr.read_text()
    for fragment in ("offset=0x6c", "offset=0x18", "offset=0x24", "size=1", "size=2", "size=8", "offset=0xd"):
        if fragment not in log:
            raise AssertionError(f"missing invalid GPIO diagnostic: {fragment}")
    return {"result": "PASS", "state_unchanged": True,
            "scope": "QTest hides MemTxResult; validates rejection diagnostics and side effects, not CPU data abort delivery"}


def test_output_signals(q, group):
    q.request(f"irq_intercept_out /machine/gpio {group}")
    all_inputs(q)
    q.events.clear()
    # OE must describe driver connection independently of its low/high latch.
    # Probe an ordinary pin and inverted-direction special pin in each session.
    for pin in (2, 89):
        q.writel(GPCR + 4 * (pin // 32), bit_for(pin))
        direction(q, pin, True)
        expected = [0] * 90
        expected[pin] = int(group == "gpio-oe")
        q.lines(expected, f"{group} pin{pin} low latch: OE=1, OUT=0")
        equal(sample(q, pin), 0, f"pin{pin} drives low latch")
        direction(q, pin, False)
        q.lines([0] * 90, f"{group} pin{pin} low-latch driver disconnects")
    low_events = q.events.copy()
    equal(low_events, [[action, pin] for pin in (2, 89) for action in ("raise", "lower")]
          if group == "gpio-oe" else [], f"{group} low-latch transitions")
    q.events.clear()
    for pin in range(90):
        bank, bit = pin // 32, bit_for(pin)
        q.writel(GPSR + bank * 4, bit)
        direction(q, pin, True)
        q.lines([0] * pin + [1], f"{group} pin{pin} rises when output enabled")
        function(q, pin, 0 if pin >= 86 else 1)
        q.lines([0] * (pin + 1), f"{group} pin{pin} disconnects in AF mode")
        function(q, pin, 1 if pin >= 86 else 0)
        q.lines([0] * pin + [1], f"{group} pin{pin} reconnects in GPIO mode")
        direction(q, pin, False)
        q.lines([0] * (pin + 1), f"{group} pin{pin} disconnects as input")
    expected = [[action, pin] for pin in range(90) for action in ("raise", "lower", "raise", "lower")]
    equal(q.events, expected, f"exact {group} transitions for every pin")
    return {"result": "PASS", "group": group, "pins_tested": 90, "events": q.events.copy(),
            "low_latch_pins": [2, 89], "low_latch_events": low_events,
            "oe_independent_of_latch": True}


def session(args, out, name, run):
    directory = out / name
    directory.mkdir(parents=True, exist_ok=True)
    stderr = directory / "qemu-stderr.log"
    with tempfile.TemporaryDirectory(prefix="crosshair-e2b-") as temp:
        qmp_path, qtest_path = Path(temp) / "qmp", Path(temp) / "qtest"
        command = [args.qemu, "-machine", MACHINE, "-accel", "qtest", "-S", "-display", "none",
                   "-monitor", "none", "-serial", "null", "-nic", "none", "-d", "guest_errors",
                   "-qmp", f"unix:{qmp_path},server=on,wait=off",
                   "-qtest", f"unix:{qtest_path},server=on,wait=off", "-qtest-log", str(directory / "qemu-qtest.log")]
        with stderr.open("wb") as err, (directory / "protocol.log").open("w") as transcript:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=err, stdin=subprocess.DEVNULL)
            qmp = q = None
            try:
                qmp = Qmp(qmp_path, process)
                q = ObservedQTest(qtest_path, process, transcript)
                qmp.request("cont")  # Dummy CPU; permits reset/callback dispatch.
                result = run(q, qmp, stderr)
                qmp.request("quit")
                process.wait(timeout=3)
                equal(process.returncode, 0, "QEMU clean exit")
                return {"command": command, **result}
            finally:
                try:
                    if q:
                        q.close()
                    if qmp:
                        qmp.close()
                finally:
                    stop_process(process)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--qemu", default=os.environ.get("QEMU_E2B", str(ROOT / "local/qemu-e2b/bin/qemu-system-arm")))
    args = parser.parse_args()
    out = ROOT / "target/artifacts/e2b-qtest"
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").unlink(missing_ok=True)
    result = {"result": "FAIL", "machine": MACHINE,
              "scope": "synthetic register subset; no guest instructions or physical HTC/pad observations",
              "qemu_version": qemu_version(args.qemu),
              "qemu_sha256": hashlib.sha256(Path(shutil.which(args.qemu) or args.qemu).read_bytes()).hexdigest()}
    try:
        def registers(q, qmp, stderr):
            return {"directions": test_masks_and_directions(q),
                    "edges": test_edges_and_routing(q),
                    "alternate_functions": test_af_and_input_gate(q),
                    "irq_transitions": test_irq_transitions(q),
                    "reset": test_reset(q, qmp),
                    "invalid_mmio": test_invalid(q, stderr)}
        result["registers"] = session(args, out, "registers", registers)
        for group in ("gpio-out", "gpio-oe"):
            result[group] = session(args, out, group,
                                    lambda q, qmp, err, group=group: test_output_signals(q, group))
        result["result"] = "PASS"
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print("PASS E2B QTest: GPIO90 direction, AF, preload, edges/W1C, PIC IRQ/FIQ, reset, strict MMIO side effects, outputs/OE")


if __name__ == "__main__":
    main()
