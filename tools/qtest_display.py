#!/usr/bin/env python3
"""QTest of synthetic display/input: actual QEMU console pixels, no guest CPU."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time

from qemu_control import Qmp, stop_process
from qtest_pxa import QTest, equal
from smoke_e2a import qemu_version

ROOT = Path(__file__).resolve().parents[1]
MACHINE = "crosshair-blueangel-display-test"
DISPLAY, INPUT = 0x10000000, 0x10001000
RAM, RAM_END = 0xA0000000, 0xA8000000
WIDTH, HEIGHT, STRIDE = 240, 320, 480
FRAME_BYTES = STRIDE * HEIGHT
FRAME = RAM + 0x100000


def screenshot(qmp, path, expected):
    qmp.request("screendump", {"filename": str(path)})
    content = path.read_bytes()
    header = b"P6\n240 320\n255\n"
    if not content.startswith(header):
        raise AssertionError(f"unexpected QEMU PPM header: {content[:32]!r}")
    pixels = content[len(header):]
    equal(len(pixels), WIDTH * HEIGHT * 3, "actual console 240x320 RGB888 size")
    if pixels != expected:
        first = next(i for i, (actual, wanted) in enumerate(zip(pixels, expected)) if actual != wanted)
        raise AssertionError(f"actual QEMU console mismatch at RGB byte {first}: observed {pixels[first]}, expected {expected[first]}")
    return hashlib.sha256(content).hexdigest()


def pattern():
    raw, rgb = bytearray(), bytearray()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            pixel = (y * WIDTH + x) & 0xFFFF  # Covers every RGB565 value.
            r, g, b = pixel >> 11, (pixel >> 5) & 63, pixel & 31
            raw.extend(struct.pack("<H", pixel))
            rgb.extend(((r << 3) | r >> 2, (g << 2) | g >> 4, (b << 3) | b >> 2))
    return bytes(raw), bytes(rgb)


def display_state(q):
    return [q.readl(DISPLAY + offset) for offset in range(0, 0x18, 4)]


def input_state(q):
    return [q.readl(INPUT + offset) for offset in (0, 0x0C, 0x10)]


def write_bytes(q, address, data):
    # The shared unbuffered QTest stream is intended for small transactions;
    # bounded requests avoid partial socket writes for a full-frame hex line.
    for start in range(0, len(data), 1024):
        chunk = data[start:start + 1024]
        q.request(f"write {address + start:#x} {len(chunk)} 0x{chunk.hex()}")


def test_display(q, qmp, out):
    black = bytes(WIDTH * HEIGHT * 3)
    equal(display_state(q), [0, WIDTH, HEIGHT, STRIDE, 0x565, 0], "display reset geometry/base/generation")
    hashes = {"initial_black.ppm": screenshot(qmp, out / "initial_black.ppm", black)}
    # No pointer is read until it passes the complete fixed-size RAM contract.
    q.writel(DISPLAY + 0x14, 1)
    for invalid in (0, RAM - 2, RAM + 1, RAM_END - FRAME_BYTES + 2, RAM_END, 0xFFFFFFFE):
        q.writel(DISPLAY, invalid)
        equal(q.readl(DISPLAY), 0, "invalid framebuffer base preserves reset base")
        equal(q.readl(DISPLAY + 0x14), 0, "invalid base/present preserves generation")
    for valid in (RAM, RAM_END - FRAME_BYTES, FRAME):
        q.writel(DISPLAY, valid)
        equal(q.readl(DISPLAY), valid, "inclusive valid framebuffer boundary")
    raw, rgb = pattern()
    q.request(f"write {FRAME - 4:#x} 4 0xa55a5aa5")
    write_bytes(q, FRAME, raw)
    q.request(f"write {FRAME + FRAME_BYTES:#x} 4 0x5aa5a55a")
    hashes["unpresented_black.ppm"] = screenshot(qmp, out / "unpresented_black.ppm", black)
    q.writel(DISPLAY + 0x14, 1)
    equal(q.readl(DISPLAY + 0x14), 1, "first synchronous presentation generation")
    hashes["pattern.ppm"] = screenshot(qmp, out / "pattern.ppm", rgb)
    # A refresh/screendump must not implicitly reread or publish guest RAM.
    q.request(f"memset {FRAME:#x} {FRAME_BYTES} 0")
    hashes["unpresented_pattern.ppm"] = screenshot(qmp, out / "unpresented_pattern.ppm", rgb)
    equal(q.readl(DISPLAY + 0x14), 1, "refresh leaves presentation generation unchanged")
    q.writel(DISPLAY + 0x14, 1)
    equal(q.readl(DISPLAY + 0x14), 2, "second presentation generation")
    hashes["presented_black.ppm"] = screenshot(qmp, out / "presented_black.ppm", black)
    equal(q.readl(FRAME - 4), 0xA55A5AA5, "leading guest framebuffer guard")
    equal(q.readl(FRAME + FRAME_BYTES), 0x5AA5A55A, "trailing guest framebuffer guard")
    before = display_state(q)
    for address in (DISPLAY + 4, DISPLAY + 8, DISPLAY + 0x18):
        q.writel(address, 1)
    q.writel(DISPLAY + 0x14, 0)
    q.writel(DISPLAY + 0x14, 2)
    q.readl(DISPLAY + 0x18)
    q.readb(DISPLAY)
    q.writeb(DISPLAY, 0xFF)
    # If an incorrect implementation split this into two 32-bit writes, the
    # valid low word would change FB_BASE before failing on read-only width.
    q.request(f"writeq {DISPLAY:#x} {RAM:#x}")
    q.writel(DISPLAY + 1, 0xFFFFFFFF)
    equal(display_state(q), before, "invalid display MMIO has no state effects")
    return {"result": "PASS", "geometry": [WIDTH, HEIGHT],
            "format": "little-endian RGB565 expanded by bit replication",
            "distinct_rgb565_values_compared": 65536,
            "framebuffer_range_checked": True, "guest_guards_unchanged": True,
            "synchronous_publication": True, "unpresented_mutations_invisible": True,
            "qemu_screendump_sha256": hashes}


def test_input(q):
    equal(input_state(q), [0, 8, 0], "input reset count/capacity/rejections")
    equal(q.readl(INPUT + 4), 0, "empty EVENT sentinel")
    events = [(tag << 24) for tag in range(1, 8)] + [(8 << 24) | ord("Щ")]
    for index, value in enumerate(events):
        q.writel(INPUT + 8, value)
        equal(q.readl(INPUT), index + 1, "accepted FIFO count")
    q.writel(INPUT + 8, 1 << 24)
    equal(input_state(q), [8, 8, 1], "full FIFO preserves events and records rejection")
    # Invalid widths on the destructive EVENT register must not pop anything.
    q.readb(INPUT + 4)
    q.request(f"readq {INPUT:#x}")
    q.readl(INPUT + 5)
    equal(q.readl(INPUT), 8, "invalid EVENT access does not pop FIFO")
    equal([q.readl(INPUT + 4) for _ in range(8)], events, "exact FIFO order")
    equal(q.readl(INPUT + 4), 0, "drained EVENT sentinel")
    # Validate payload rejection with an empty queue, independently of full
    # backpressure; a full queue alone could hide a missing scalar/tag check.
    invalid = [0, 9 << 24, (1 << 24) | 1, (8 << 24) | 0xD800,
               (8 << 24) | 0xDFFF, (8 << 24) | 0x110000]
    for index, value in enumerate(invalid):
        q.writel(INPUT + 8, value)
        equal(input_state(q), [0, 8, 2 + index], "invalid payload rejected independently of FIFO-full state")
    # Exercise many nonzero ring heads, including every Unicode boundary.
    text = [0, 0x7F, 0x80, 0x7FF, 0x800, 0xD7FF, 0xE000, 0xFFFF, 0x10000, 0x10FFFF]
    expected = []
    for index in range(160):
        event = (8 << 24) | text[index % len(text)]
        q.writel(INPUT + 8, event)
        expected.append(event)
        if len(expected) == 7 or index == 159:
            equal([q.readl(INPUT + 4) for _ in expected], expected, "FIFO wrap and Unicode scalar boundaries")
            expected.clear()
    before = input_state(q)
    q.writel(INPUT, 0xFFFFFFFF)
    q.writel(INPUT + 4, 0xFFFFFFFF)
    q.writel(INPUT + 0x0C, 0xFFFFFFFF)
    q.writel(INPUT + 0x10, 0xFFFFFFFF)
    q.readl(INPUT + 8)
    q.readl(INPUT + 0x14)
    q.writeb(INPUT + 8, 1)
    q.request(f"writeq {INPUT + 8:#x} 0xffffffffffffffff")
    equal(input_state(q), before, "invalid input MMIO has no state effects")
    return {"result": "PASS", "fifo_capacity": 8, "all_tags_ordered": True,
            "overflow_backpressure": True, "invalid_payloads_rejected": invalid,
            "wrap_scalar_events": 160, "unicode_boundaries": text,
            "destructive_reads_strict_width_alignment": True}


def test_reset(q, qmp, out):
    raw, rgb = pattern()
    write_bytes(q, FRAME, raw)
    q.writel(DISPLAY + 0x14, 1)
    q.writel(INPUT + 8, 5 << 24)
    if q.readl(DISPLAY + 0x14) == 0 or q.readl(INPUT) != 1 or q.readl(INPUT + 0x10) == 0:
        raise AssertionError("reset probe requires dirty display, FIFO and rejection state")
    qmp.request("system_reset")
    deadline = time.monotonic() + 3
    while q.readl(DISPLAY) != 0 or q.readl(INPUT) != 0:
        if time.monotonic() > deadline:
            raise TimeoutError("display/input reset did not complete")
        time.sleep(0.01)
    equal(display_state(q), [0, WIDTH, HEIGHT, STRIDE, 0x565, 0], "display reset contract")
    equal(input_state(q), [0, 8, 0], "input reset contract")
    equal(q.readl(INPUT + 4), 0, "reset clears queued event")
    digest = screenshot(qmp, out / "reset_black.ppm", bytes(WIDTH * HEIGHT * 3))
    equal(q.readl(FRAME - 4), 0xA55A5AA5, "reset leaves guest RAM guard")
    # Rebind/present existing RAM: reset changed controller state, not guest pixels.
    q.writel(DISPLAY, FRAME)
    q.writel(DISPLAY + 0x14, 1)
    equal(q.readl(DISPLAY + 0x14), 1, "post-reset presentation generation restarts")
    republished = screenshot(qmp, out / "reset_republish.ppm", rgb)
    return {"result": "PASS", "reset_black_sha256": digest,
            "reset_republish_sha256": republished,
            "guest_ram_retained": True, "post_reset_presentation_works": True}


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--qemu", default=os.environ.get("QEMU_DISPLAY_TEST", str(ROOT / "local/qemu-display-test/bin/qemu-system-arm")))
    args = parser.parse_args()
    out = ROOT / "target/artifacts/display-qtest"
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").unlink(missing_ok=True)
    result = {"result": "FAIL", "machine": MACHINE, "scope": "synthetic test protocols, QTest dummy CPU, no physical display/input validation",
              "qemu_version": qemu_version(args.qemu),
              "qemu_sha256": hashlib.sha256(Path(shutil.which(args.qemu) or args.qemu).read_bytes()).hexdigest()}
    with tempfile.TemporaryDirectory(prefix="crosshair-display-qtest-") as temp:
        qmp_path, memory_path = Path(temp) / "qmp", Path(temp) / "memory"
        command = [args.qemu, "-machine", MACHINE, "-accel", "qtest", "-S", "-display", "none",
                   "-monitor", "none", "-serial", "null", "-nic", "none", "-d", "guest_errors",
                   "-qmp", f"unix:{qmp_path},server=on,wait=off",
                   "-qtest", f"unix:{memory_path},server=on,wait=off", "-qtest-log", str(out / "qemu-qtest.log")]
        result["command"] = command
        stderr_path = out / "qemu-stderr.log"
        with stderr_path.open("wb") as err, (out / "protocol.log").open("w") as transcript:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=err, stdin=subprocess.DEVNULL)
            qmp = q = None
            try:
                qmp = Qmp(qmp_path, process)
                q = QTest(memory_path, process, transcript)
                qmp.request("cont")
                result["display"] = test_display(q, qmp, out)
                result["input"] = test_input(q)
                result["reset"] = test_reset(q, qmp, out)
                log = stderr_path.read_text()
                for fragment in ("rejected display", "rejected input", "size=1", "size=8"):
                    if fragment not in log:
                        raise AssertionError(f"missing explicit invalid-MMIO diagnostic: {fragment}")
                result["invalid_mmio_scope"] = "QTest hides MemTxResult; verifies state preservation and diagnostic rejection, not CPU exception delivery"
                qmp.request("quit")
                process.wait(timeout=3)
                equal(process.returncode, 0, "QEMU clean exit")
                result["result"] = "PASS"
            except Exception as error:
                result.update(result="FAIL", error=f"{type(error).__name__}: {error}")
                raise
            finally:
                try:
                    if q: q.close()
                    if qmp: qmp.close()
                finally:
                    stop_process(process)
                    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print("PASS display/input QTest: actual QEMU pixels, publication, RAM bounds, FIFO/Unicode/wrap/backpressure, reset, MMIO rejection")


if __name__ == "__main__":
    main()
