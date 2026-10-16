#!/usr/bin/env python3
"""Wave007.1 taps and update costs on the real ARM Shell and unchanged QEMU.

The test injects logical coordinates, observes User RAM after WaitEvent, and
compares committed QEMU pixels with the same inputs rendered by the host crate.
No Shell state or hit-testing runs in the native frontend.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from qemu_control import Qmp, stop_process
from qtest_pxa import QTest, equal
from shell_control import (DISPLAY, INPUT, MACHINE, MAILBOX, METRICS, SNAPSHOT, await_stable,
                           physical, pointer_coordinates, pointer_wire, record, user_record, wire)
from smoke_display import sha
from smoke_e2a import qemu_version
from smoke_security import read_bytes, register, words
from smoke_shell import (ARTIFACTS, IMAGE, USER_IMAGE, capture, check_state, check_tables,
                         idle_progress, read_trace, verify_reference)
from smoke_tasks import task_records

ROOT = Path(__file__).resolve().parents[1]
OUT = ARTIFACTS / "pointer"
COST_FIELDS = "packets_decoded pixels_decoded pixels_written runs_written dirty_rects dirty_pixels full rendered".split()


def tap(x, y):
    return pointer_wire(x, y)


# Screen/overlay/theme expectations are independent of the host renderer. A tap
# is an activation, while arrows only move focus. Modals consume the whole tap.
POINTER = [
    ("blank-workspace", tap(130,50), 0,0,0),
    ("settings-shortcut", tap(40,120), 5,0,0),
    ("theme", tap(30,80), 5,0,1),
    ("reset-dialog", tap(30,138), 5,3,1),
    ("outside-dialog", tap(239,150), 5,3,1),
    ("cancel-dialog", tap(150,208), 5,0,1),
    ("reset-again", tap(30,138), 5,3,1),
    ("confirm-reset", tap(40,208), 5,0,0),
    ("app-back", tap(228,12), 0,0,0),
    ("keyboard-focus-down", wire(1), 0,0,0),
    ("keyboard-focus-up", wire(0), 0,0,0),
    ("start", tap(12,8), 2,0,0),
    ("about-row", tap(30,70), 3,0,0),
    ("about-blank", tap(130,270), 3,0,0),
    ("about-back", tap(228,12), 2,0,0),
    ("cyrillic-query", 0x0800041E, 2,0,0),
    ("query-keyboard-select", wire(4), 3,0,0),
    ("keyboard-home", wire(7), 0,0,0),
    ("today-shortcut", tap(40,68), 1,0,0),
    ("today-diagnostics", tap(30,280), 4,0,0),
    ("diagnostics-soft-back", wire(5), 1,0,0),
    ("today-launcher", tap(30,255), 2,0,0),
    ("home-again", wire(7), 0,0,0),
    ("system-menu", wire(6), 0,1,0),
    ("menu-today", tap(30,96), 1,0,0),
    ("home-menu", wire(7), 0,0,0),
    ("menu-open", wire(6), 0,1,0),
    ("outside-menu-no-fallthrough", tap(230,150), 0,0,0),
    ("last-pixel", tap(239,319), 0,0,0),
    ("menu-keyboard-back", wire(5), 0,0,0),
    ("top-right-boundary", tap(239,0), 0,0,0),
    ("start-top-left-boundary", tap(0,0), 2,0,0),
    ("launcher-keyboard-back", wire(5), 2,0,0),  # Clears the retained query first.
    ("launcher-back-home", wire(5), 0,0,0),
]
INVALID = [("invalid-x240", 0x08000000 | (0xF0000 + 240)),
           ("invalid-x255-y319", 0x08000000 | (0xF0000 + (319 << 8) + 255)),
           ("invalid-y320", 0x08000000 | (0xF0000 + (320 << 8))),
           ("invalid-reserved-upper", 0x0810FFFF)]
KEYBOARD = [("focus-settings",wire(1),0,0,0), ("open-settings",wire(4),5,0,0),
            ("keyboard-theme",wire(4),5,0,1), ("focus-reset",wire(1),5,0,1),
            ("keyboard-dialog",wire(4),5,3,1), ("focus-cancel",wire(3),5,3,1),
            ("keyboard-cancel",wire(4),5,0,1), ("focus-theme",wire(0),5,0,1),
            ("keyboard-theme-reset",wire(4),5,0,0), ("back-desktop",wire(5),0,0,0),
            ("focus-today",wire(0),0,0,0), ("keyboard-today",wire(4),1,0,0),
            ("today-focus-diag",wire(3),1,0,0), ("keyboard-diag",wire(4),4,0,0)]
KEYFRAMES = {0,2,3,4,6,8,9,10,12,13,19,20,24,25,28,29,34}


def observe(qmp, memory, process, image, user, delivered, handled, last_event=None):
    await_stable(memory, image["symbols"], user["symbols"], delivered, process, shell_events=handled)
    qmp.request("stop")
    r = record(memory, image["symbols"]["CROSSHAIR_SHELL_RECORD"])
    u = user_record(memory, user["symbols"])
    tasks = task_records(memory, image["symbols"]["TASKS"])
    check_state(memory, image, user, r, u, tasks, delivered, 0, shell_events=handled)
    if last_event is not None:
        equal(u["last_event"], last_event, "exact logical wire consumed by actual ARM User Shell")
    stats = words(memory, physical(user["symbols"]["SHELL_RENDER_METRICS"]), 8)
    return {"record":r,"user":u,"tasks":tasks,"render_metrics":stats,
            "registers":qmp.monitor("info registers")}


def trace_item(state):
    u = state["user"]
    return {"last_event":u["last_event"],"snapshot":u["snapshot"],"metrics":u["metrics"],
            "render_metrics":state["render_metrics"]}


def prepare(qmp, memory, image):
    symbols = image["symbols"]
    equal(register(qmp.monitor("info registers"), "R15"), image["entry"], "reset enters current guest ELF")
    equal((memory.readl(DISPLAY),memory.readl(DISPLAY+0x14),memory.readl(INPUT)),(0,0,0),"actual display/FIFO reset")
    memory.request(f"memset {symbols['__bss_start']:#x} {symbols['__bss_end']-symbols['__bss_start']} 0xa5")
    for prefix in ("__stack","__irq_stack","__abort_stack","__undef_stack"):
        memory.request(f"memset {symbols[prefix+'_bottom']:#x} {symbols[prefix+'_top']-symbols[prefix+'_bottom']} 0xcd")
    for address in (0xA0202000,0xA043F000):
        memory.request(f"memset {address:#x} 4096 0x6d")
    memory.request("memset 0xa0700000 256 0xa7")
    memory.writel(MAILBOX,0)
    qmp.request("cont")


def run(qemu, image, user, exporter):
    result = {"result":"FAIL","boots":[],"machine":MACHINE,"accelerator":"tcg",
              "scope":"actual ARM logical pointer/hit-testing and keyboard; no physical stylus driver or PDA timing"}
    sources = [ROOT/name for name in ("tools/smoke_shell_pointer.py","tools/smoke_shell.py","tools/shell_control.py",
               "tools/run_shell.py","tools/crosshair_gui.swift","tools/test_shell_input.py",
               "scripts/test-shell-pointer.sh","scripts/test-wave007-1.sh")]
    sources += [path for path in (ROOT/"shell").rglob("*") if path.is_file() and
                (path.suffix in (".rs",".svg",".json",".py",".toml",".lock") or path.name in ("LICENSE","Cargo.lock"))
                and "__pycache__" not in path.parts]
    sources += [path for path in (ROOT/"shell/assets").rglob("*") if path.is_file() and path.name != ".DS_Store"]
    sources += [ROOT/name for name in (
        "Cargo.toml","Cargo.lock","build.rs","rust-toolchain.toml",".cargo/config.toml",
        "src/shell_user.rs","src/shell.rs","src/security_policy.rs","src/drivers/pxa_uart.rs",
        "src/arch/tasks_entry.S","src/arch/task_workloads.S","src/arch/shell_probe.S",
        "link/shell.ld","link/shell-user.ld","tools/qemu_control.py","tools/qtest_pxa.py",
        "tools/smoke_security.py","tools/smoke_tasks.py","tools/smoke_e2a.py","tools/smoke_display.py",
        "tools/framebuffer_png.py","tools/verify_shell_user.py","tools/verify_image.py",
        "scripts/build-shell.sh","scripts/test-shell-ui.sh","scripts/shell-env.sh","scripts/env.sh",
        "crosshair-emulator/qemu/crosshair-blueangel-display-test.c",
        "crosshair-emulator/qemu/crosshair-blueangel-e2b.c","crosshair-emulator/qemu/crosshair-blueangel-e2a.c")]
    sources += list((ROOT/"src/shell_runtime").glob("*.rs")) + list((ROOT/"src/task_runtime").glob("*.rs"))
    sources += list((ROOT/"ui/src").rglob("*.rs")) + [ROOT/"ui/Cargo.toml",ROOT/"ui/Cargo.lock"]
    bindings = {str(path.relative_to(ROOT)):sha(path.read_bytes()) for path in sorted(set(sources))}
    result["source_sha256"] = bindings
    with tempfile.TemporaryDirectory(prefix="crosshair-pointer-") as temporary:
        qmp_path, memory_path = Path(temporary)/"qmp",Path(temporary)/"memory"
        command = [qemu,"-machine",MACHINE,"-cpu","pxa260","-accel","tcg","-S","-display","none",
                   "-monitor","none","-serial","stdio","-nic","none","-device",f"loader,file={IMAGE/'crosshair-shell.elf'},cpu-num=0",
                   "-qmp",f"unix:{qmp_path},server=on,wait=off","-qtest",f"unix:{memory_path},server=on,wait=off",
                   "-qtest-log",str(OUT/"memory-server.log")]
        result["command"] = command
        with (OUT/"qemu-uart.log").open("wb") as uart,(OUT/"qemu-stderr.log").open("wb") as stderr,(OUT/"memory-protocol.log").open("w") as transcript:
            process = subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=uart,stderr=stderr)
            qmp = memory = None
            try:
                qmp,memory = Qmp(qmp_path,process),QTest(memory_path,process,transcript)
                for boot,name in enumerate(("pointer","keyboard-reset","pointer-burst-reset")):
                    directory = OUT/name; directory.mkdir(parents=True,exist_ok=True)
                    prepare(qmp,memory,image)
                    initial = observe(qmp,memory,process,image,user,0,0)
                    equal((initial["user"]["snapshot"]["screen"],initial["user"]["snapshot"]["theme"]),(0,0),"fresh Desktop/defaulttheme")
                    states = [dict(initial,name="initial",event=0)]
                    trace = [trace_item(initial)]
                    captures = {0:capture(qmp,initial["record"],directory/"step-00")}
                    delivered = handled = 0
                    if name == "pointer-burst-reset":
                        sequence = [tap(40,68),tap(30,255),tap(30,70),tap(228,12)]
                        for value in sequence: memory.writel(INPUT+8,value)
                        equal(memory.readl(INPUT),4,"four coordinate taps admitted as a bounded burst")
                        qmp.request("cont")
                        final = observe(qmp,memory,process,image,user,4,4,sequence[-1])
                        journal = read_trace(memory,user["symbols"],4)
                        equal([item["last_event"] for item in journal[1:]],sequence,"ARM preserves pointer burst order")
                        equal([item["snapshot"]["screen"] for item in journal],[0,1,2,3,2],"every burst tap hit-tests in its own actual guest state")
                        trace = journal
                        states.append(dict(final,name="burst-final",event=4))
                        captures[4] = capture(qmp,final["record"],directory/"step-04")
                        delivered = handled = 4
                    else:
                        sequence = POINTER if name == "pointer" else KEYBOARD
                        for index,(label,value,screen,overlay,theme) in enumerate(sequence,1):
                            memory.writel(INPUT+8,value); qmp.request("cont")
                            delivered += 1; handled += 1
                            state = observe(qmp,memory,process,image,user,delivered,handled,value)
                            snapshot = state["user"]["snapshot"]
                            equal((snapshot["screen"],snapshot["overlay"],snapshot["theme"]),(screen,overlay,theme),f"independent tap/key effect: {label}")
                            state.update(name=label,event=delivered,pointer=pointer_coordinates(value))
                            states.append(state); trace.append(trace_item(state))
                            if name == "keyboard-reset" or index in KEYFRAMES:
                                captures[index] = capture(qmp,state["record"],directory/f"step-{index:02d}")
                        if name == "pointer":
                            for label,value in INVALID:
                                before = states[-1]["user"]["snapshot"]
                                memory.writel(INPUT+8,value); qmp.request("cont"); delivered += 1
                                state = observe(qmp,memory,process,image,user,delivered,handled,value)
                                # Runtime words can advance; invalid coordinates cannot
                                # mutate UI state/revision/render/event counters.
                                for field in SNAPSHOT[:13]:
                                    equal(state["user"]["snapshot"][field],before[field],f"{label} ignored before UI counters: {field}")
                                equal(state["render_metrics"],[0]*8,"invalidcoordinate has zero composition/updatework")
                                state.update(name=label,event=delivered,pointer=None)
                                states.append(state);trace.append(trace_item(state))
                            rejected_before = memory.readl(INPUT+0x10)
                            for malformed in (0x09000000,0x0800D800,0x01000001): memory.writel(INPUT+8,malformed)
                            equal(memory.readl(INPUT),0,"malformed tag/Unicode/control never enters unchanged model FIFO")
                            equal(memory.readl(INPUT+0x10),rejected_before+3,"each malformed wire explicitly rejected by unchanged model")
                    parity = verify_reference(exporter,directory,trace,states,captures)
                    host_frames = json.loads((directory/"host/frames.json").read_text())["frames"]
                    for state,frame in zip(states,host_frames):
                        if name != "pointer-burst-reset":
                            equal(frame["render_stats"],state["render_metrics"],"all eight actual ARM updatecost words equal independent host execution")
                    if name == "pointer-burst-reset":
                        equal(host_frames[-1]["render_stats"],states[-1]["render_metrics"],
                              "final actual ARM burst updatecost words equal host execution")
                    if name == "pointer":
                        named = {state["name"]:state for state in states}
                        for label in ("blank-workspace","outside-dialog","about-blank","top-right-boundary"):
                            equal(named[label]["render_metrics"],[0]*8,f"{label}: no unnecessary render or wallpaper decode")
                        for label in ("keyboard-focus-down","keyboard-focus-up"):
                            cost = named[label]["render_metrics"]
                            equal((cost[6],cost[7]),(0,1),"Desktop focus uses partial composition")
                            equal(0 < cost[5] < 240*320,True,"Desktopfocus dirty pixels below fullframe")
                            equal(cost[2] < 240*320,True,"Desktopfocus wallpaper restoration below fullframe")
                        for label in ("system-menu","menu-open"):
                            equal(named[label]["render_metrics"][:4],[0]*4,"opening Desktop menu reuses wallpaper without decoding")
                    final = states[-1]
                    equal(final["record"]["queue_dropped"],0,"newpointer/keysession has no kerneloverflow")
                    equal(memory.readl(INPUT),0,"all admitted pointer events drained")
                    equal(memory.readl(INPUT+0x10),3 if name == "pointer" else 0,"only explicit malformed wire probes rejected")
                    idle = idle_progress(qmp,memory,process,image,user,delivered,0) if delivered == handled else None
                    result["boots"].append({"name":name,"events":delivered,"ui_events":handled,"states":states,"trace":trace,
                                            "captures":captures,"parity":parity,"page_tables":check_tables(memory,image["symbols"],final["record"]),
                                            "idle_progress":idle,"input_device_rejections":memory.readl(INPUT+0x10)})
                    if boot < 2: qmp.request("system_reset")
                # Settings before interaction has identical pixels regardless
                # of pointer shortcut or keyboard focus+Select activation.
                equal((OUT/"pointer/step-02.raw565").read_bytes() == (OUT/"keyboard-reset/step-02.raw565").read_bytes(),True,"stylus and keyboard open pixel-identical Settings")
                current_bindings = {str(path.relative_to(ROOT)):sha(path.read_bytes()) for path in sorted(set(sources))}
                equal([name for name in bindings if bindings[name] != current_bindings[name]], [],
                      "tested pointer source bytes unchanged during execution")
                qmp.request("quit");process.wait(timeout=3);equal(process.returncode,0,"cleanpointerQEMUexit")
                result.update(result="PASS",boots_completed=3,events=sum(boot["events"] for boot in result["boots"]),
                              pixel_comparisons=sum(boot["parity"]["pixel_comparisons"] for boot in result["boots"]),
                              image_sha256=image["sha256"],user_image_sha256=user["sha256"],qemu_version=qemu_version(qemu),
                              qemu_sha256=sha(Path(shutil.which(qemu) or qemu).read_bytes()))
            except Exception as error:
                result["error"] = f"{type(error).__name__}: {error}"
                if qmp and memory and process.poll() is None:
                    try:
                        qmp.request("stop");result["failure_user"] = user_record(memory,user["symbols"])
                        result["failure_record"] = record(memory,image["symbols"]["CROSSHAIR_SHELL_RECORD"])
                        result["failure_registers"] = qmp.monitor("info registers")
                    except Exception: pass
                raise
            finally:
                if memory: memory.close()
                if qmp: qmp.close()
                stop_process(process)
                (OUT/"result.json").write_text(json.dumps(result,indent=2)+"\n")
    return result


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--qemu",default=os.environ.get("QEMU_DISPLAY_TEST",str(ROOT/"local/qemu-display-test/bin/qemu-system-arm")))
    args = parser.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    image = json.loads((IMAGE/"image.json").read_text());user = json.loads((USER_IMAGE/"user-image.json").read_text())
    for directory,manifest in ((IMAGE,image),(USER_IMAGE,user)):
        equal({name:sha((directory/name).read_bytes()) for name in manifest["sha256"]},manifest["sha256"],"current hashed guest images")
    exporter = Path((ARTIFACTS/"host/exporter-path.txt").read_text().strip())
    result = run(args.qemu,image,user,exporter)
    print(f"PASS User pointer: {result['boots_completed']} real ARM boots, {result['events']} delivered events, {result['pixel_comparisons']} host/ARM/QEMU pixels; coordinate bounds/malformed/keyboard/updatecost checks")


if __name__ == "__main__": main()
