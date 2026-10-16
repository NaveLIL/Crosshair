#!/usr/bin/env python3
"""Live Mac frontend adapter for the real ARM Shell on unchanged synthetic QEMU.

The Swift window only blits QMP screendumps and forwards keys to the existing
logical-input FIFO. All Shell state, applications, rendering and scheduling run
in ARM TCG. The adapter implements no Shell screen or simulated OS behavior.
"""
import argparse
from collections import deque
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys
import tempfile
import time

from qemu_control import Qmp, stop_process
from qtest_pxa import QTest, equal
from shell_control import DISPLAY, INPUT, MACHINE, MAILBOX, await_stable, wire, physical, user_record, pointer_coordinates, pointer_wire, pointer_phase_wire, hardware_key_wire, ux_record
from smoke_display import ppm_rgb, sha
from smoke_e2a import qemu_version
from smoke_security import words

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "target/artifacts/shell"


class NativeInput:
    """Bounded binary pipe decoder; no TextIOWrapper read-ahead behind select."""
    def __init__(self):
        self.buffer = bytearray()
        self.pending = deque()
        self.quit = False
        self.window_ready = False
        self.automation_isolation = False
        self.measured_holds_ms = []

    def feed(self, data):
        if len(self.buffer) + len(data) > 8192:
            raise ValueError("native input protocol exceeds its 8192-byte bound")
        self.buffer.extend(data)
        self.parse()

    def parse(self):
        while len(self.pending) < 64 and b"\n" in self.buffer and not self.quit:
            line, _, remaining = self.buffer.partition(b"\n")
            self.buffer = bytearray(remaining)
            if line == b"window-ready 1":
                self.window_ready = True
                continue
            if line == b"automation-isolation 1":
                self.automation_isolation = True
                continue
            if line == b"quit":
                self.quit = True
                return
            fields = line.split()
            if len(line) > 96:
                raise ValueError("native frontend protocol line exceeds96bytes")
            if len(fields) == 3 and fields[0] == b"key":
                value = hardware_key_wire(int(fields[1]), int(fields[2]))
            elif len(fields) == 5 and fields[0] == b"pointer":
                phase, x, y, held_ms = (int(field) for field in fields[1:])
                if phase in (1,2,3) and not (0 <= x < 240 and 0 <= y < 320):
                    raise ValueError("native frontend pointer outside actual guest image")
                if phase == 5:
                    if not 600 <= held_ms <= 0xFFFFFFFF:
                        raise ValueError("native hold lacks measured600ms duration")
                    self.measured_holds_ms.append(held_ms)
                    self.measured_holds_ms = self.measured_holds_ms[-128:]
                value = pointer_phase_wire(phase, x, y, held_ms)
            elif len(fields) == 2 and fields[0] == b"event":
                value = int(fields[1])
            else:
                raise ValueError("invalid native frontend protocol line")
            tag, scalar = value >> 24, value & 0xFFFFFF
            if not ((1 <= tag <= 7 and scalar == 0) or (tag == 8 and scalar <= 0x10FFFF and not 0xD800 <= scalar <= 0xDFFF)):
                raise ValueError("native frontend emitted invalid logical input")
            if tag == 8 and scalar >= 0x90000 and pointer_coordinates(value) is None:
                raise ValueError("native frontend emitted out-of-bounds logical pointer")
            self.pending.append(value)


def pump_input(qmp, memory, symbols, decoder, limit=4):
    """Pause for an atomic combined queue observation, then admit at most4.

    The native pipe supplies bounded backpressure; normal typing never relies
    on dropping keys into a full hardware or kernel queue. The guest continues
    owning its timer and input polling. No guest state or counter is fabricated.
    """
    decoder.parse()
    if not decoder.pending:
        return 0
    qmp.request("stop")
    try:
        queued = memory.readl(INPUT) + memory.readl(symbols["CROSSHAIR_SHELL_RECORD"] + 10 * 4)
        count = min(max(0, 4 - queued), len(decoder.pending), limit)
        for _ in range(count):
            memory.writel(INPUT + 8, decoder.pending.popleft())
    finally:
        qmp.request("cont")
    return count


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--qemu", default=os.environ.get("QEMU_DISPLAY_TEST", str(ROOT / "local/qemu-display-test/bin/qemu-system-arm")))
    parser.add_argument("--frontend", type=Path, default=ARTIFACTS / "gui/crosshair-gui")
    parser.add_argument("--headless-test", action="store_true", help="Test the actual QEMU frames/input and native PPM decoder, then quit")
    parser.add_argument("--window-test", action="store_true", help="Open the real native window, post four actual key events, verify ARM transitions, and close")
    parser.add_argument("--pointer-window-test", action="store_true", help="Post actual native mouseDowns, keys and Cyrillic text; verify real ARM coordinate delivery")
    parser.add_argument("--adaptive-window-test", action="store_true", help="Real Cocoa drag cancellation, measured hold, key repeats and adaptive modes")
    args = parser.parse_args()
    if sum((args.headless_test, args.window_test, args.pointer_window_test,args.adaptive_window_test)) > 1:
        parser.error("choose one frontend test mode")
    native_test = args.window_test or args.pointer_window_test or args.adaptive_window_test
    mode = "pipeline" if args.headless_test else "adaptive-window-test" if args.adaptive_window_test else "pointer-window-test" if args.pointer_window_test else "window-test" if args.window_test else "live"
    expected_screens = [0,1,0,0,0,2,2,3,3,3,2,0,0] if args.pointer_window_test else [2,2,3,3,2,2,0,0]
    expected_native_wires = ([pointer_phase_wire(1,40,68),pointer_phase_wire(3,40,68),
        hardware_key_wire(0,5),hardware_key_wire(2,5),pointer_phase_wire(1,12,8),pointer_phase_wire(3,12,8),
        0x0800041E,hardware_key_wire(0,4),hardware_key_wire(2,4),
        pointer_phase_wire(1,227,12),pointer_phase_wire(3,227,12),hardware_key_wire(0,7),hardware_key_wire(2,7)]
        if args.pointer_window_test else [hardware_key_wire(edge,key) for key in (11,4,5,7) for edge in (0,2)])
    if args.adaptive_window_test:
        expected_screens = [0]*13+[4]*14+[0]*2
        expected_native_wires = [pointer_phase_wire(1,40,68),pointer_phase_wire(2,130,150),
            pointer_phase_wire(2,40,68),pointer_phase_wire(3,40,68),pointer_phase_wire(1,40,68),None,
            pointer_phase_wire(3,40,68),hardware_key_wire(0,5),hardware_key_wire(2,5),
            hardware_key_wire(0,1),hardware_key_wire(1,1),hardware_key_wire(1,1),hardware_key_wire(2,1),
            hardware_key_wire(0,4),hardware_key_wire(2,4),hardware_key_wire(0,12),hardware_key_wire(2,12),
            pointer_phase_wire(1,30,214),pointer_phase_wire(3,30,214),hardware_key_wire(0,12),hardware_key_wire(2,12),
            pointer_phase_wire(1,30,240),pointer_phase_wire(3,30,240),pointer_phase_wire(1,230,8),pointer_phase_wire(3,230,8),
            pointer_phase_wire(1,30,188),pointer_phase_wire(3,30,188),hardware_key_wire(0,7),hardware_key_wire(2,7)]
    image = json.loads((ARTIFACTS / "image/image.json").read_text())
    user = json.loads((ARTIFACTS / "user-image/user-image.json").read_text())
    for name, expected in image["sha256"].items():
        equal(sha((ARTIFACTS / "image" / name).read_bytes()), expected, "current live guest image hash")
    version = qemu_version(args.qemu)
    sources = [ROOT / name for name in (
        "tools/run_shell.py", "tools/crosshair_gui.swift", "tools/shell_control.py", "tools/qemu_control.py",
        "tools/qtest_pxa.py", "tools/smoke_display.py", "tools/smoke_security.py", "tools/smoke_tasks.py",
        "tools/smoke_e2a.py", "tools/framebuffer_png.py", "scripts/run-crosshair-gui.sh", "scripts/run-shell.sh",
        "scripts/build-shell-gui.sh", "scripts/build-shell.sh", "scripts/shell-env.sh", "scripts/env.sh")]
    sources_before = {str(path.relative_to(ROOT)): sha(path.read_bytes()) for path in sources}
    directory = ARTIFACTS / "gui"
    directory.mkdir(exist_ok=True, parents=True)
    log_directory = directory / mode
    log_directory.mkdir(exist_ok=True, parents=True)
    result = {"result": "FAIL", "mode": "headless-pipeline-test" if args.headless_test else "native-adaptive-window-test" if args.adaptive_window_test else "native-pointer-window-test" if args.pointer_window_test else "native-window-test" if args.window_test else "live-window",
              "scope": "actual ARM TCG Shell; host window only displays QEMU committed console pixels and forwards logical keys/pointers",
              "image_sha256": image["sha256"], "user_image_sha256": user["sha256"],
              "frontend_sha256": sha(args.frontend.read_bytes()), "source_sha256": sources_before,
              "logs": log_directory.name,
              "qemu_version": version, "qemu_sha256": sha(Path(shutil.which(args.qemu) or args.qemu).read_bytes()),
              "swift_version": (directory / "swift-version.txt").read_text() if (directory / "swift-version.txt").exists() else "not recorded",
              "compile_command": (directory / "compile-command.txt").read_text() if (directory / "compile-command.txt").exists() else "not recorded"}
    with tempfile.TemporaryDirectory(prefix="crosshair-gui-") as temporary:
        temp = Path(temporary)
        live_ppm, pending_ppm = temp / "display.ppm", temp / "pending.ppm"
        qmp_path, memory_path = temp / "qmp", temp / "memory"
        command = [args.qemu, "-machine", MACHINE, "-cpu", "pxa260", "-accel", "tcg", "-S",
                   "-display", "none", "-monitor", "none", "-serial", "stdio", "-nic", "none",
                   "-device", f"loader,file={ARTIFACTS / 'image/crosshair-shell.elf'},cpu-num=0",
                   "-qmp", f"unix:{qmp_path},server=on,wait=off",
                   "-qtest", f"unix:{memory_path},server=on,wait=off",
                   "-qtest-log", str(log_directory / "memory-server.log")]
        result["command"] = command
        with (log_directory / "qemu-uart.log").open("wb") as uart, (log_directory / "qemu-stderr.log").open("wb") as stderr, (log_directory / "memory-protocol.log").open("w") as transcript, (log_directory / "frontend-stderr.log").open("wb") as frontend_stderr:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=uart, stderr=stderr)
            qmp = memory = frontend = None
            try:
                qmp, memory = Qmp(qmp_path, process), QTest(memory_path, process, transcript)
                memory.writel(MAILBOX, 0)
                qmp.request("cont")
                await_stable(memory, image["symbols"], user["symbols"], 0, process)
                qmp.request("screendump", {"filename": str(pending_ppm)})
                os.replace(pending_ppm, live_ppm)
                if args.headless_test:
                    result["native_self_test"] = subprocess.check_output([str(args.frontend), "--self-test"], text=True).strip()
                    (directory / "native-self-test.log").write_text(result["native_self_test"] + "\n")
                    inspected = json.loads(subprocess.check_output([str(args.frontend), "--inspect-ppm", str(live_ppm)], text=True))
                    result["native_frame_inspection"] = inspected
                    equal((inspected["width"], inspected["height"]), (240, 320), "native frontend decodes the actual QEMU console geometry")
                    first = ppm_rgb(live_ppm)
                    fnv = 0xCBF29CE484222325
                    for byte in first:
                        fnv = ((fnv ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
                    equal(inspected["rgb_fnv1a64"], f"{fnv:016x}", "native AppKit frame decoder reads exactly the actual QEMU console RGB bytes")
                    for count, action in enumerate((8, 8, 7), 1):
                        memory.writel(INPUT + 8, wire(action))
                        await_stable(memory, image["symbols"], user["symbols"], count, process)
                        qmp.request("screendump", {"filename": str(pending_ppm)})
                        os.replace(pending_ppm, live_ppm)
                        actual = ppm_rgb(live_ppm)
                        if count == 1:
                            equal(actual != first, True, "real keyboard FIFO action changes the actual ARM/QEMU screen")
                    # Regression: one atomic OS pipe write contains three keys.
                    # The same binary decoder/pacer must consume all without a
                    # later write making a buffered line visible to select.
                    values = [wire(action) for action in (8, 8, 7)]
                    payload = b"".join(f"event {value}\n".encode("ascii") for value in values)
                    fixture = subprocess.Popen([sys.executable, "-c", "import os,sys;os.write(1,bytes.fromhex(sys.argv[1]))", payload.hex()],
                                               stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, bufsize=0)
                    decoder = NativeInput()
                    decoder.feed(os.read(fixture.stdout.fileno(), 4096))
                    fixture.wait(timeout=3)
                    fixture.stdout.close()
                    equal(list(decoder.pending), values, "all three native event lines from one OS write decoded immediately")
                    equal(pump_input(qmp, memory, image["symbols"], decoder), 3, "single native batch admitted without another keypress")
                    await_stable(memory, image["symbols"], user["symbols"], 6, process)
                    journal = physical(user["symbols"]["SHELL_TRACE"])
                    equal([words(memory, journal + index * 128, 32)[4] for index in (4,5,6)], [2,3,0],
                          "actual ARM processed every rapid native key in order")
                    equal(memory.readl(INPUT + 0x10), 0, "paced native typing does not overflow hardware FIFO")
                    equal(memory.readl(image["symbols"]["CROSSHAIR_SHELL_RECORD"] + 11 * 4), 0,
                          "paced native typing does not overflow kernel queue")
                    qmp.request("screendump", {"filename": str(pending_ppm)})
                    os.replace(pending_ppm, live_ppm)
                    actual = ppm_rgb(live_ppm)
                    result.update(result="PASS", events=6, single_write_events=3,
                                  final_console_rgb_sha256=sha(actual))
                    shutil.copyfile(live_ppm, directory / "pipeline-final.ppm")
                else:
                    frontend_command = [str(args.frontend)] + (["--adaptive-window-test"] if args.adaptive_window_test else ["--pointer-window-test"] if args.pointer_window_test else ["--window-test"] if args.window_test else []) + [str(live_ppm)]
                    frontend = subprocess.Popen(frontend_command, stdin=subprocess.DEVNULL,
                                                stdout=subprocess.PIPE, stderr=frontend_stderr, bufsize=0)
                    selector = selectors.DefaultSelector()
                    selector.register(frontend.stdout, selectors.EVENT_READ)
                    decoder = NativeInput()
                    generation = memory.readl(DISPLAY + 0x14)
                    window_events = []
                    if native_test:
                        result["events"] = window_events
                    window_delivered = 0
                    print("Crosshair ARM window is live. Close the window to stop QEMU. Click/release guest controls; arrows, Enter, Escape, F1 Start, F2 context, F3 switch, F4 Home, F10 system panel.", flush=True)
                    while frontend.poll() is None:
                        if process.poll() is not None:
                            raise RuntimeError(f"QEMU closed unexpectedly: {process.returncode}")
                        if len(decoder.pending) < 64:
                            for key, _ in selector.select(timeout=0.02):
                                data = os.read(key.fileobj.fileno(), 4096)
                                if not data:
                                    frontend.wait(timeout=3)
                                    break
                                decoder.feed(data)
                        else:
                            time.sleep(0.02)
                        if decoder.quit:
                            result["aborted_pending_on_window_close"] = len(decoder.pending)
                            frontend.wait(timeout=3)
                            break
                        admitted = pump_input(qmp, memory, image["symbols"], decoder, limit=1 if native_test else 4)
                        if native_test and admitted:
                            window_delivered += admitted
                            observed, user_state, _ = await_stable(memory, image["symbols"], user["symbols"], window_delivered, process)
                            equal(admitted, 1, "native posted key events are independently delivered")
                            result["last_native_observation"] = {"event":window_delivered,"wire":user_state["last_event"],
                                "screen":user_state["snapshot"]["screen"],"generation":observed["frames"]}
                            equal(window_delivered <= len(expected_screens), True, "native test produced only the scheduled events")
                            expected_wire = expected_native_wires[window_delivered-1]
                            if expected_wire is None:
                                equal(len(decoder.measured_holds_ms),1,"Cocoa source measured exactly one stationary hold")
                                expected_wire = pointer_phase_wire(5,held_ms=decoder.measured_holds_ms[0])
                            equal(user_state["last_event"], expected_wire,
                                  "actual ARM native test wire matches the registered scheduled NSEvent")
                            equal(user_state["snapshot"]["screen"], expected_screens[window_delivered-1],
                                  "actual NSWindow input route changes real ARM Shell state")
                            if args.pointer_window_test:
                                expected_wires = {1: (40,68), 2: (40,68), 5: (12,8), 6: (12,8), 10: (227,12), 11: (227,12)}
                                if window_delivered in expected_wires:
                                    equal(pointer_coordinates(user_state["last_event"]), expected_wires[window_delivered],
                                          "actual ARM observed the exact logical mouse coordinates")
                                if window_delivered == 7:
                                    equal(user_state["last_event"], 0x0800041E, "actual ARM received native Cyrillic Unicode")
                            ux = ux_record(memory,user["symbols"])
                            if args.adaptive_window_test:
                                if window_delivered == 1:
                                    equal((ux["pointer_active"],ux["actions_invoked"]),(1,0),"native Press captures without activating")
                                if window_delivered == 4:
                                    equal((ux["pointer_active"],ux["actions_invoked"]),(0,0),"native drag outside and back never taps")
                                if window_delivered == 6:
                                    equal((ux["panel"],ux["pointer_active"]),(4,0),"measured native hold opens Shell panel and suppresses later release")
                                if window_delivered in (10,11,12):
                                    equal(user_state["snapshot"]["desktop_selected"],{10:1,11:2,12:2}[window_delivered],"native repeated Down moves bounded focus")
                                if window_delivered == 13:
                                    equal(ux["held_keys"],0,"native keyUp clears held state")
                                if window_delivered in (19,23,27):
                                    mode_value = {19:1,23:2,27:0}[window_delivered]
                                    equal((ux["chrome_mode"],ux["content_y"],ux["content_height"]),
                                          (mode_value,{0:24,1:16,2:0}[mode_value],{0:296,1:304,2:320}[mode_value]),"native pointer selects actual adaptive content policy")
                            shot = directory / f"{'adaptive-window' if args.adaptive_window_test else 'pointer-window' if args.pointer_window_test else 'window'}-step-{window_delivered}.ppm"
                            qmp.request("screendump", {"filename": str(shot)})
                            window_events.append({"event":window_delivered,"screen":user_state["snapshot"]["screen"],
                                                  "generation":observed["frames"],"wire":user_state["last_event"],
                                                  "pointer":pointer_coordinates(user_state["last_event"]),
                                                  "snapshot":user_state["snapshot"],
                                                  "ux":ux,
                                                  "console_rgb_sha256":sha(ppm_rgb(shot))})
                        current = memory.readl(DISPLAY + 0x14)
                        if current != generation:
                            qmp.request("screendump", {"filename": str(pending_ppm)})
                            os.replace(pending_ppm, live_ppm)
                            generation = current
                    selector.close()
                    equal(frontend.returncode, 0, "native window closed cleanly")
                    if native_test:
                        equal(decoder.window_ready, True, "actual native NSWindow reported visible")
                        equal(decoder.automation_isolation, True, "unregistered AppKit text was ignored only in explicit automation mode")
                        equal(len(window_events), len(expected_screens), "all scheduled native input events reached ARM before test window closed")
                        equal(memory.readl(INPUT + 0x10), 0, "native window test input has no hardware overflow")
                        result.update(window_ready=True, automation_isolation=True, events=window_events,
                                      measured_holds_ms=decoder.measured_holds_ms)
                    result.update(result="PASS", last_generation=generation)
                equal({str(path.relative_to(ROOT)): sha(path.read_bytes()) for path in sources}, sources_before,
                      "live adapter source bytes unchanged throughout execution")
                qmp.request("quit")
                process.wait(timeout=3)
                equal(process.returncode, 0, "live QEMU exited cleanly")
            except Exception as error:
                result["error"] = f"{type(error).__name__}: {error}"
                raise
            finally:
                if frontend and frontend.poll() is None:
                    stop_process(frontend)
                if memory:
                    memory.close()
                if qmp:
                    qmp.close()
                stop_process(process)
                (directory / ("pipeline-result.json" if args.headless_test else "adaptive-window-test-result.json" if args.adaptive_window_test else "pointer-window-test-result.json" if args.pointer_window_test else "window-test-result.json" if args.window_test else "session-result.json")).write_text(json.dumps(result, indent=2) + "\n")
    if args.headless_test:
        print("PASS live frontend pipeline: real ARM User input and QEMU console frames; native keymap/PPM decoder")
    if args.adaptive_window_test:
        print("PASS native adaptive window: actual Cocoa press/move/release, measured hold, key repeats and Standard/Compact/Immersive reached ARM")
    if args.pointer_window_test:
        print("PASS native pointer window: actual NSWindow mouseDown coordinates, keys and Cyrillic text reached ARM with QEMU frames")
    if args.window_test:
        print("PASS native window: actual NSWindow key press/release reached ARM Launcher/About/Back/Home with QEMU frame publication")


if __name__ == "__main__":
    main()
