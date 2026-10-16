#!/usr/bin/env python3
"""Run real ARM User Shell sessions; verify input, scheduling and QEMU pixels.

The emulator, display/input model and accepted Wave006 tests stay independent.
QTest only injects logical events and observes physical RAM/MMIO; ARM TCG runs
all Shell state, graphics composition, applications, syscalls and task switches.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time

from framebuffer_png import encode
from qemu_control import Qmp, stop_process
from qtest_pxa import QTest, equal
from shell_control import (DISPLAY, INPUT, MAILBOX, MACHINE, FB_BYTES, FIELDS, SNAPSHOT, METRICS,
                           PROBE_RETURNS, physical, record, user_record, await_stable, wire)
from smoke_display import png_rgb, ppm_rgb, sha
from smoke_e2a import qemu_version, settle_idle
from smoke_security import elf_loads, image_word, read_bytes, register, words
from smoke_tasks import task_records

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "target/artifacts/shell"
IMAGE, USER_IMAGE, OUT = ARTIFACTS / "image", ARTIFACTS / "user-image", ARTIFACTS / "execution"
# First24: the shared meaningful session. Remaining actions exercise every key,
# clamped focus, launcher context cancellation, selection restoration and text.
CANONICAL = [8,8,5,7,1,4,8,1,8,9,7,3,4,5,6,8,1,8,10,5,7,6,1,8,
             0,2,1,3,4,5,6,5,7,0,2,8,(8<<24)|0x041E,4,7,8,(8<<24)|8,3,2,7]
EXPECTED_SCREENS = [2,3,2,0,0,5,5,5,5,5,0,0,4,0,0,1,1,4,5,4,0,0,0,2,
                    2,2,2,2,5,2,2,2,0,0,0,2,2,3,0,2,2,2,2,0]
KEYFRAMES = {0,1,2,4,6,7,9,10,13,15,16,18,19,24,29,33,37,38,44}
TRACE_WORDS, TRACE_CAPACITY = 32, 64


def as_wire(action):
    return wire(action) if action <= 10 else action


def read_trace(memory, user_symbols, count):
    equal(count < TRACE_CAPACITY, True, "bounded Shell observation journal retains this session")
    start = physical(user_symbols["SHELL_TRACE"])
    result = []
    for step in range(count + 1):
        values = words(memory, start + step * TRACE_WORDS * 4, TRACE_WORDS)
        equal(values[:3], [0x5553484C, 1, 2], "complete stable User journal entry")
        snapshot = dict(zip(SNAPSHOT, values[4:20]))
        equal(snapshot["events_processed"], step, "journal event order contains no overwrite or skipped entry")
        result.append({"last_event": values[3], "snapshot": snapshot,
                       "metrics": dict(zip(METRICS, values[20:32]))})
    return result


def check_guards(memory, symbols, user_symbols, r):
    base = physical(user_symbols["SHELL_FRAMEBUFFER"])
    equal(r["fb_pa"], base + 64, "one User framebuffer; backend uses trusted physical alias")
    equal(words(memory, base, 16), [0xFACE7000 ^ n for n in range(16)], "actual framebuffer prefix guard")
    equal(words(memory, base + 64 + FB_BYTES, 16), [0xBEEF7000 ^ n for n in range(16)], "actual framebuffer suffix guard")
    equal(words(memory, symbols["TASK_CANARY"], 16), [0xCAFE7000 ^ n for n in range(16)], "actual privileged kernel canary")
    for prefix, size in (("__stack", 16384), ("__irq_stack", 4096), ("__abort_stack", 4096), ("__undef_stack", 4096)):
        equal(symbols[prefix + "_top"] - symbols[prefix + "_bottom"], size, "banked kernel stack allocation")
        equal(words(memory, symbols[prefix + "_bottom"], 4), [0xFACE6000 ^ n for n in range(4)], "actual kernel stack lower canary")
    equal(words(memory, symbols["SHELL_IDLE_STACK"], 4), [0x1D1E7000 ^ n for n in range(4)], "actual privileged Idle private stack canary")
    equal(read_bytes(memory, 0xA0202000, 4096), b"\x6D" * 4096, "Busy User guard remains unmapped and untouched")
    equal(read_bytes(memory, 0xA043F000, 4096), b"\x6D" * 4096, "Shell User guard remains unmapped and untouched")
    equal(read_bytes(memory, 0xA0700000, 256), b"\xA7" * 256, "remote RAM sentinel intact")


def check_tables(memory, symbols, r):
    evidence = []
    for task, base in enumerate((0xA0200000, 0xA0400000)):
        l1, l2 = symbols["SHELL_L1"] + task * 16384, symbols["SHELL_L2"] + task * 1024
        equal((l1 & 0x3FFF, l2 & 0x3FF), (0, 0), "task L1/L2 alignment")
        first, second = words(memory, l1, 4096), words(memory, l2, 256)
        equal(first[0x10], l2 | 1, "own User coarse table in client domain0")
        for index in (0, 0x100, 0x401, 0x40A, 0x40D, 0xA00, 0xA02, 0xA04):
            equal(first[index], index << 20 | 0x402, "required common identity section privileged AP1")
        for index, descriptor in enumerate(first):
            if descriptor and index != 0x10:
                equal(descriptor, index << 20 | 0x402, "all other mapped aliases are privileged AP1")
        expected = [0] * 256
        if task == 0:
            expected[:4] = [base | 0xAA2, base + 4096 | 0xFF2, 0, base + 12288 | 0xFF2]
        else:
            for index in range(16):
                expected[index] = base + index * 4096 | 0xAA2
            for index in list(range(16, 63)) + list(range(64, 72)):
                expected[index] = base + index * 4096 | 0xFF2
        equal(second, expected, "only own RO code, RW data/stack, guard hole; no foreign User mappings")
        evidence.append({"task": task, "l1_physical": l1, "l2_physical": l2,
                         "l1_sha256": sha(struct.pack("<4096I", *first)),
                         "l2_sha256": sha(struct.pack("<256I", *second)),
                         "user_mapped_pages": sum(bool(value) for value in second)})
    equal(r["ttbr"] in (symbols["SHELL_L1"], symbols["SHELL_L1"] + 16384), True, "CPU retains a trusted task TTBR")
    return evidence


def check_state(memory, image, user, r, u, tasks, events, scenario, shell_events=None):
    symbols, user_symbols = image["symbols"], user["symbols"]
    for key, value in {"magic": 0x53484C4C, "version": 1, "stage": 2, "error": 0,
                       "events_delivered": events, "queue_len": 0, "queue_capacity": 4,
                       "fb_bytes": FB_BYTES, "sctlr": 0x79, "dacr": 1, "pid": 0,
                       "last_present_ptr": 0x01010040, "last_present_len": FB_BYTES}.items():
        equal(r[key], value, key)
    equal([task["id"] for task in tasks], [1, 2], "kernel owns Busy and Shell identities")
    equal(tasks[1]["state"], 4, "Shell blocks in real WaitEvent instead of spinning")
    equal(tasks[1]["context"]["cpsr"] & 0xFF, 0x50, "Shell actually enters User ARM with timer IRQ enabled")
    context = tasks[1]["context"]
    equal(context["kind"], 2, "waiting Shell saved a real SVC context")
    equal(context["raw_lr"], context["pc"], "SVC preserves the exact following instruction PC")
    equal(0x01000000 <= context["pc"] < 0x01010000 and context["pc"] % 4 == 0, True, "User Shell resume PC stays in RO code")
    equal(0x01040000 <= context["sp"] <= 0x01048000 and context["sp"] % 8 == 0, True, "Shell User stack is bounded and AAPCS aligned")
    equal(memory.readl(physical(context["pc"] - 4)), 0xEF000000, "actual waiting instruction was ARM SVC0")
    equal((u["magic"], u["version"], u["state"]), (0x5553484C, 1, 2), "stable unprivileged observation ABI")
    equal(u["snapshot"]["events_processed"], events if shell_events is None else shell_events, "actual User Shell consumed each admitted logical event")
    equal(u["snapshot"]["renders"], r["frames"], "each completed User render is one privileged presentation")
    equal(u["probe_returns"], [value & 0xFFFFFFFF for value in PROBE_RETURNS], "actual User negative API return stores")
    equal(u["metrics"]["version"], 1, "versioned kernel diagnostics snapshot")
    equal(u["metrics"]["valid"], 15, "timer/task/memory/input are real available metric groups")
    equal(u["metrics"]["task_count"], 2, "actual fixed task table size")
    equal(u["metrics"]["reserved"], 0, "no undefined diagnostic ABI fields")
    equal(u["metrics"]["working_ram_bytes"], symbols["__image_end"] - symbols["_start"] + 64 + 74 * 4096,
          "reported working RAM matches actual kernel extent and mapped User pages")
    equal(r["api_rejections"], 14 if scenario == 2 else 11, "all eleven actual invalid API calls rejected once")
    equal(r["last_svc_psr"] & 0xFF, 0xD3, "privileged SVC broker executes IRQ/FIQ masked")
    equal(r["last_user_psr"] & 0xFF, 0x50, "system call originated in actual User ARM")
    equal(memory.readl(DISPLAY), r["fb_pa"], "actual synthetic device framebuffer address")
    equal(memory.readl(DISPLAY + 0x14), r["frames"], "actual QEMU console publication generation")
    equal(memory.readl(INPUT), 0, "hardware FIFO drained into the bounded event service")
    equal(r["waits"] >= events + 1, True, "one blocking/event-wait operation per completed User iteration")
    check_guards(memory, symbols, user_symbols, r)
    return {"page_tables": check_tables(memory, symbols, r), "scenario": scenario}


def capture(qmp, r, destination):
    raw, png, ppm = (destination.with_suffix(suffix) for suffix in (".raw565", ".png", ".ppm"))
    qmp.request("pmemsave", {"val": r["fb_pa"], "size": FB_BYTES, "filename": str(raw)})
    encode(raw, png)
    qmp.request("screendump", {"filename": str(ppm)})
    equal(png_rgb(png), ppm_rgb(ppm), "actual guest framebuffer equals the QEMU committed console pixels")
    return {"name": destination.name, "raw565": raw.name, "png": png.name, "ppm": ppm.name,
            "raw565_sha256": sha(raw.read_bytes()), "png_sha256": sha(png.read_bytes()),
            "console_rgb_sha256": sha(ppm_rgb(ppm)), "generation": r["frames"]}


def await_ticks(memory, symbols, count, process):
    deadline = time.monotonic() + 10
    while memory.readl(symbols["CROSSHAIR_SHELL_RECORD"] + 16) < count:
        if process.poll() is not None or time.monotonic() >= deadline:
            raise TimeoutError("real hardware timer did not continue while Shell was waiting")
        time.sleep(0.002)


def idle_progress(qmp, memory, process, image, user, events, scenario):
    symbols = image["symbols"]
    before, u, tasks = await_stable(memory, symbols, user["symbols"], events, process)
    qmp.request("stop")
    before = record(memory, symbols["CROSSHAIR_SHELL_RECORD"])
    counter = memory.readl(0xA0201000)
    registers = qmp.monitor("info registers")
    frames = before["frames"]
    qmp.request("cont")
    await_ticks(memory, symbols, before["ticks"] + 3, process)
    qmp.request("stop")
    after = record(memory, symbols["CROSSHAIR_SHELL_RECORD"])
    final_tasks = task_records(memory, symbols["TASKS"])
    equal((after["events_delivered"], after["frames"]), (events, frames), "no background redraw or synthetic input while Shell waits")
    equal(final_tasks[1]["state"], 4, "waiting Shell stays non-runnable without input")
    if scenario != 1:
        equal(memory.readl(0xA0201000) > counter, True, "real independent Busy User stores continue while Shell is blocked")
        equal(after["busy_preemptions"] > before["busy_preemptions"], True, "hardware timer preempts the Busy User workload")
        equal(final_tasks[0]["svc_count"], 3 if scenario == 2 else 0,
              "Busy User has only the explicit role probes or no voluntary syscalls")
    return {"before": before, "after": after, "busy_counter_before": counter,
            "busy_counter_after": memory.readl(0xA0201000), "registers_before": registers,
            "registers_after": qmp.monitor("info registers")}


def verify_reference(exporter, directory, trace, snapshots, captures):
    replay = directory / "host-replay.txt"
    rows = []
    for index, item in enumerate(trace):
        metrics = " ".join(str(item["metrics"][name]) for name in METRICS)
        event = "-1" if index == 0 else f"wire:{item['last_event']:08x}"
        rows.append(f"step-{index:02d} {event} {metrics}")
    replay.write_text("\n".join(rows) + "\n")
    host = directory / "host"
    subprocess.run([str(exporter), str(host), "--replay", str(replay)], check=True, stdout=subprocess.DEVNULL)
    manifest = json.loads((host / "frames.json").read_text())
    frames = manifest["frames"] if isinstance(manifest, dict) else manifest
    equal(len(frames), len(trace), "host replays every actual User event and frozen metrics snapshot")
    for index, frame in enumerate(frames):
        expected = frame["snapshot"]
        equal(expected, trace[index]["snapshot"], "all16 host/ARM Shell state words agree for the same input and actual metrics")
    for index, observed in captures.items():
        frame = frames[index]
        host_raw = host / frame["file"]
        guest_raw = directory / observed["raw565"]
        equal(guest_raw.read_bytes(), host_raw.read_bytes(), "byte-exact actual ARM vs host Shell RGB565")
        equal(ppm_rgb(directory / observed["ppm"]), png_rgb(host_raw.with_suffix(".png")), "QEMU console vs host Shell pixel parity")
        observed["host_raw565_sha256"] = sha(host_raw.read_bytes())
        observed["host_png_sha256"] = sha(host_raw.with_suffix(".png").read_bytes())
    return {"frames": len(frames), "pixel_comparisons": len(captures), "host_replay_sha256": sha(replay.read_bytes())}


def run(qemu, image, user, exporter):
    symbols, user_symbols = image["symbols"], user["symbols"]
    result = {"result": "FAIL", "machine": MACHINE, "accelerator": "tcg", "boots": []}
    with tempfile.TemporaryDirectory(prefix="crosshair-shell-") as temporary:
        qmp_path, memory_path = Path(temporary) / "qmp", Path(temporary) / "memory"
        command = [qemu, "-machine", MACHINE, "-cpu", "pxa260", "-accel", "tcg", "-S", "-display", "none",
                   "-monitor", "none", "-serial", "stdio", "-nic", "none",
                   "-device", f"loader,file={IMAGE / 'crosshair-shell.elf'},cpu-num=0",
                   "-qmp", f"unix:{qmp_path},server=on,wait=off",
                   "-qtest", f"unix:{memory_path},server=on,wait=off", "-qtest-log", str(OUT / "memory-server.log")]
        result["command"] = command
        with (OUT / "qemu-uart.log").open("wb") as uart, (OUT / "qemu-stderr.log").open("wb") as stderr, (OUT / "memory-protocol.log").open("w") as transcript:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=uart, stderr=stderr)
            qmp = memory = None
            try:
                qmp, memory = Qmp(qmp_path, process), QTest(memory_path, process, transcript)
                for boot, (name, batch, scenario) in enumerate((("canonical",1,0),("burst-reset",4,0),("fault-reset",1,1),("role-reset",1,2))):
                    directory = OUT / name
                    directory.mkdir(parents=True, exist_ok=True)
                    equal(register(qmp.monitor("info registers"), "R15"), image["entry"], "real ELF reset entry")
                    equal((memory.readl(DISPLAY), memory.readl(DISPLAY + 0x14), memory.readl(INPUT)), (0,0,0), "display/input device reset independently from guest BSS")
                    memory.request(f"memset {symbols['__bss_start']:#x} {symbols['__bss_end']-symbols['__bss_start']} 0xa5")
                    equal(memory.readl(symbols["CROSSHAIR_SHELL_RECORD"]),0xA5A5A5A5,"kernel observation BSS poisoned before entry")
                    for prefix in ("__stack","__irq_stack","__abort_stack","__undef_stack"):
                        memory.request(f"memset {symbols[prefix+'_bottom']:#x} {symbols[prefix+'_top']-symbols[prefix+'_bottom']} 0xcd")
                    for address in (0xA0202000,0xA043F000):
                        memory.request(f"memset {address:#x} 4096 0x6d")
                    memory.request("memset 0xa0700000 256 0xa7")
                    memory.writel(MAILBOX,scenario)
                    qmp.request("cont")
                    r,u,tasks=await_stable(memory,symbols,user_symbols,0,process)
                    qmp.request("stop")
                    r,u,tasks=record(memory,symbols["CROSSHAIR_SHELL_RECORD"]),user_record(memory,user_symbols),task_records(memory,symbols["TASKS"])
                    check_state(memory,image,user,r,u,tasks,0,scenario)
                    equal((u["snapshot"]["screen"],u["snapshot"]["theme"]),(0,0),"real Desktop and default volatile theme after reset")
                    captures={0:capture(qmp,r,directory/"step-00")}
                    states=[{"event":0,"record":r,"user":u,"tasks":tasks,"registers":qmp.monitor("info registers")}]
                    qmp.request("cont")
                    idle=idle_progress(qmp,memory,process,image,user,0,scenario)
                    # Burst boot additionally overflows both independent queues:
                    # hardware8 admits8/rejects ninth, kernel4 delivers4/drops4.
                    sequence=[]
                    if batch>1:
                        for _ in range(8): memory.writel(INPUT+8,wire(5))
                        memory.writel(INPUT+8,wire(6))
                        memory.writel(INPUT+8,(8<<24)|0xD800)
                        equal(memory.readl(INPUT),8,"hardware FIFO bounds before guest execution")
                        equal(memory.readl(INPUT+0x10),2,"full FIFO and invalid Unicode rejected independently")
                        qmp.request("cont")
                        await_stable(memory,symbols,user_symbols,4,process)
                        qmp.request("stop")
                        r=record(memory,symbols["CROSSHAIR_SHELL_RECORD"])
                        equal((r["input_drained"],r["queue_dropped"]),(8,4),"bounded kernel queue rejects overflow without corrupting admitted ordering")
                        sequence += [5]*4
                    completed=len(sequence)
                    pending=CANONICAL[:4] if scenario == 2 else CANONICAL[:]
                    while pending:
                        group,pending=pending[:batch],pending[batch:]
                        for action in group: memory.writel(INPUT+8,as_wire(action))
                        equal(memory.readl(INPUT),len(group),"actual injected logical events queued while ARM stopped")
                        qmp.request("cont")
                        completed+=len(group); sequence+=group
                        await_stable(memory,symbols,user_symbols,completed,process)
                        qmp.request("stop")
                        r,u,tasks=record(memory,symbols["CROSSHAIR_SHELL_RECORD"]),user_record(memory,user_symbols),task_records(memory,symbols["TASKS"])
                        check_state(memory,image,user,r,u,tasks,completed,scenario)
                        canonical_step=len(sequence)-(4 if batch>1 else 0)
                        equal(u["snapshot"]["screen"],EXPECTED_SCREENS[canonical_step-1],"independently specified functional navigation screen")
                        states.append({"event":completed,"record":r,"user":u,"tasks":tasks,"registers":qmp.monitor("info registers")})
                        if canonical_step in KEYFRAMES or not pending:
                            captures[completed]=capture(qmp,r,directory/f"step-{completed:02d}")
                    trace=read_trace(memory,user_symbols,completed)
                    equal([item["last_event"] for item in trace[1:]],[as_wire(action) for action in sequence],"exact logical input order seen by actual User Shell")
                    parity=verify_reference(exporter,directory,trace,states,captures)
                    if scenario == 1:
                        equal(tasks[0]["state"],3,"faulting Busy User quarantined while Shell remains usable")
                        equal(tasks[0]["fault_kind"],1,"actual Busy UNDEF exception, not a host-state flag")
                        equal(u["metrics"]["faulted_tasks"],1,"real faulted task appears in Shell diagnostics snapshot")
                        fault_physical = 0xA0200000 + tasks[0]["fault_pc"] - 0x01000000
                        equal(fault_physical, symbols["task_a_undefined"], "actual Busy fault is the exact immutable UNDEF fixture")
                        equal(memory.readl(fault_physical), 0xE7F000F0, "actual faulting ARM opcode in RAM")
                        fault_idle_registers = settle_idle(qmp, symbols["shell_idle_loop"])
                        equal(register(fault_idle_registers, "PSR") & 0xFF, 0x5F, "with Busy faulted and Shell waiting CPU executes real privileged System Idle with IRQ enabled")
                        equal(register(fault_idle_registers, "R13"), symbols["SHELL_IDLE_STACK"] + 4096, "System Idle uses its own bounded private stack")
                    if scenario == 2:
                        equal(words(memory, 0xA0201100, 3), [0xFFFFFFFF] * 3,
                              "actual unprivileged Busy callers receive EPERM for Present, Metrics and WaitEvent")
                        equal(tasks[0]["svc_count"], 3, "exactly three real caller-rights SVC probes")
                    user_raw=(USER_IMAGE/"crosshair-shell-user.bin").read_bytes()
                    equal(read_bytes(memory,0xA0400000,len(user_raw)),user_raw,"User Shell code unchanged from current hashed embedded image")
                    result["boots"].append({"name":name,"scenario":scenario,"batch_size":batch,"events":completed,
                                            "states":states,"captures":captures,"trace":trace,"parity":parity,
                                            "idle_progress":idle,"final_record":r,"final_user":u,
                                            "input_device_rejections":memory.readl(INPUT+0x10),
                                            "page_tables":check_tables(memory,symbols,r),
                                            "role_probe_returns":words(memory,0xA0201100,3) if scenario == 2 else None,
                                            "fault_idle_registers":fault_idle_registers if scenario == 1 else None})
                    if boot<3: qmp.request("system_reset")
                qmp.request("quit"); process.wait(timeout=3)
                equal(process.returncode,0,"clean QEMU exit")
                result.update(result="PASS",boots_completed=len(result["boots"]),
                              pixel_comparisons=sum(boot["parity"]["pixel_comparisons"] for boot in result["boots"]))
            except Exception as error:
                result["error"]=f"{type(error).__name__}: {error}"
                if qmp and memory and process.poll() is None:
                    try:
                        qmp.request("stop")
                        result["failure_registers"]=qmp.monitor("info registers")
                        result["failure_record"]=record(memory,symbols["CROSSHAIR_SHELL_RECORD"])
                        result["failure_user"]=user_record(memory,user_symbols)
                        result["failure_tasks"]=task_records(memory,symbols["TASKS"])
                    except Exception: pass
                raise
            finally:
                if memory: memory.close()
                if qmp: qmp.close()
                stop_process(process)
                (OUT/"result.json").write_text(json.dumps(result,indent=2)+"\n")
    return result


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument("--qemu",default=os.environ.get("QEMU_DISPLAY_TEST",str(ROOT/"local/qemu-display-test/bin/qemu-system-arm")))
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"result.json").write_text(json.dumps({"result":"FAIL","error":"test not completed"})+"\n")
    image=json.loads((IMAGE/"image.json").read_text())
    user=json.loads((USER_IMAGE/"user-image.json").read_text())
    for directory,manifest in ((IMAGE,image),(USER_IMAGE,user)):
        equal({name:sha((directory/name).read_bytes()) for name in manifest["sha256"]},manifest["sha256"],"fresh current image files")
    elf_loads(IMAGE/"crosshair-shell.elf");elf_loads(USER_IMAGE/"crosshair-shell-user.elf")
    exporter=Path((ARTIFACTS/"host/exporter-path.txt").read_text().strip())
    result=run(args.qemu,image,user,exporter)
    result.update(scope="User Shell and isolated Busy task on synthetic display-test ARM TCG; no physical PDA graphics/input/performance validation",
                  qemu_version=qemu_version(args.qemu),qemu_sha256=sha(Path(shutil.which(args.qemu)or args.qemu).read_bytes()),
                  image_sha256=image["sha256"],user_image_sha256=user["sha256"])
    sources=[ROOT/"Cargo.toml",ROOT/"Cargo.lock",ROOT/"build.rs",ROOT/"rust-toolchain.toml",ROOT/".cargo/config.toml"]
    sources+=list((ROOT/"shell").rglob("*.rs"))+[ROOT/"shell/Cargo.toml",ROOT/"shell/Cargo.lock"]
    sources += [path for path in (ROOT / "shell/assets").rglob("*")
                if path.is_file() and path.name != ".DS_Store" and "__pycache__" not in path.parts]
    sources += list((ROOT / "shell/tools").rglob("*.py"))
    sources+=list((ROOT/"src/shell_runtime").glob("*.rs"))+list((ROOT/"src/task_runtime").glob("*.rs"))
    sources+=list((ROOT/"ui/src").rglob("*.rs"))+[ROOT/"ui/Cargo.toml",ROOT/"ui/Cargo.lock"]
    sources+=[ROOT/"src/arch/tasks_entry.S",ROOT/"src/arch/task_workloads.S",ROOT/"src/arch/shell_probe.S",ROOT/"src/security_policy.rs",ROOT/"src/drivers/pxa_uart.rs"]
    sources+=[ROOT/name for name in ("src/shell.rs","src/shell_user.rs","link/shell.ld","link/shell-user.ld",
                                   "tools/smoke_shell.py","tools/shell_control.py","tools/verify_shell_user.py",
                                   "tools/qemu_control.py","tools/qtest_pxa.py","tools/smoke_display.py","tools/smoke_security.py",
                                   "tools/framebuffer_png.py","tools/smoke_tasks.py","tools/smoke_e2a.py","tools/verify_image.py",
                                   "scripts/env.sh","scripts/shell-env.sh",
                                   "scripts/build-shell.sh","scripts/test-shell.sh","scripts/test-shell-ui.sh","scripts/test-wave007.sh",
                                   "scripts/test-shell-pointer.sh","scripts/test-wave007-1.sh","tools/smoke_shell_pointer.py",
                                   "tools/run_shell.py","tools/crosshair_gui.swift","tools/test_shell_input.py",
                                   "crosshair-emulator/qemu/crosshair-blueangel-display-test.c",
                                   "crosshair-emulator/qemu/crosshair-blueangel-e2b.c","crosshair-emulator/qemu/crosshair-blueangel-e2a.c")]
    result["source_sha256"]={str(path.relative_to(ROOT)):sha(path.read_bytes())for path in sorted(set(sources))if path.is_file()}
    (OUT/"result.json").write_text(json.dumps(result,indent=2)+"\n")
    print(f"PASS User Shell: {result['boots_completed']} real ARM boots, reset/burst/queue overflow/API checks, {result['pixel_comparisons']} host/ARM/QEMU pixel comparisons")


if __name__=="__main__":main()
