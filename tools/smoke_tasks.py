#!/usr/bin/env python3
"""Independently inspect two real User tasks executed by E2B ARM TCG.

QTest is a physical-memory observer, never the accelerator, scheduler or clock
source. Guest task counters, exception contexts, MMU descriptors and immutable
ELF instructions are checked after QMP stops the CPU. No OEM image, host block
device or physical PDA is opened. This is a functional emulator experiment.
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

from qemu_control import Qmp, stop_process
from qtest_pxa import QTest, equal
from smoke_e2a import qemu_version, settle_idle, wait_uart
from smoke_security import digest, elf_loads, image_word, read_bytes, register, words

ROOT = Path(__file__).resolve().parents[1]
MACHINE = "crosshair-blueangel-e2b"
IMAGE = ROOT / "target/artifacts/tasks/image"
OUT = ROOT / "target/artifacts/tasks-tests"
MAILBOX = 0xA0000100
USER_CODE, USER_DATA, USER_GUARD, USER_STACK, USER_TOP = (0x01000000 + n * 4096 for n in range(5))
BASES = (0xA0200000, 0xA0300000)
PAYLOAD = b"CROSSHAIR USER\n"
PASS = "CROSSHAIR TASKS — PREEMPTION COMPLETE\r\n".encode()
CASES = {0: "busy_loop_timer_preemption", 1: "other_task_read", 2: "other_task_write",
         3: "kernel_write", 4: "unmapped_guard", 5: "undefined_instruction",
         6: "yield_exit_lifecycle", 7: "unsupported_thumb_svc"}
FIELDS = """magic version stage error scenario ticks switches current midr sctlr ttbr dacr pid
pic_mask_final timer_oier_final timer_ossr_final last_irq_frame last_irq_handler_cpsr
last_svc_frame last_svc_handler_cpsr last_abort_frame last_undef_frame fault_tick
tlb_switches canary_ok terminal_reason irq_from_a irq_from_b last_fault_handler_cpsr
first_irq_a_pc first_irq_b_pc healthy_counter_at_fault""".split()
TASK_FIELDS = """id state dispatches preemptions svc_count copies yields exit_code fault_kind fault_lr
fault_psr dfsr dfar ifsr fault_pc fault_opcode""".split()
CONTEXT_FIELDS = [f"r{n}" for n in range(13)] + ["sp", "lr", "pc", "cpsr", "kind", "raw_lr", "pad"]
DATA_FIELDS = "counter accumulator copyret copypsr last_syscall_err lifecycle_marker zero_length_ret bad_immediate_ret workload_error".split()
TASK_WORDS = len(TASK_FIELDS) + len(CONTEXT_FIELDS)


def record(memory, address):
    return dict(zip(FIELDS, words(memory, address, len(FIELDS))))


def task_records(memory, address):
    result = []
    for index in range(2):
        raw = words(memory, address + TASK_WORDS * 4 * index, TASK_WORDS)
        result.append(dict(zip(TASK_FIELDS, raw[:len(TASK_FIELDS)]),
                           context=dict(zip(CONTEXT_FIELDS, raw[len(TASK_FIELDS):]))))
    return result


def user_physical(task, virtual, size=4):
    if not USER_CODE <= virtual <= USER_TOP - size:
        raise AssertionError(f"User VA range outside task allocation: {virtual:#x}+{size}")
    return BASES[task] + virtual - USER_CODE


def check_code(memory, loads, symbols):
    evidence = []
    for index, base in enumerate(BASES):
        segments = [load for load in loads if load["pa"] == base]
        equal(len(segments), 1, "one distinct user code ELF segment per task")
        load = segments[0]
        equal(load["flags"], 5, "immutable User code ELF RX permission")
        equal(0 < load["filesz"] <= load["memsz"] <= 4096, True, "bounded User code page")
        actual = read_bytes(memory, base, load["filesz"])
        equal(actual, load["bytes"], "actual User code unchanged from hashed ELF")
        evidence.append({"task": index, "physical": base, "bytes": len(actual), "sha256": digest(actual)})
    begin, end = symbols["task_a_busy"], symbols["task_a_busy_end"]
    equal(BASES[0] <= begin < end <= BASES[0] + 4096 and begin % 4 == end % 4 == 0,
          True, "exact ARM Busy Loop code bounds")
    opcodes = [image_word(loads, physical) for physical in range(begin, end, 4)]
    equal(any((opcode & 0x0F000000) == 0x0F000000 for opcode in opcodes), False,
          "actual Task A Busy Loop contains no ARM SVC instruction")
    equal(any((opcode & 0x0F000000) == 0x0B000000 for opcode in opcodes), False,
          "actual Task A Busy Loop has no branch-with-link to another workload")
    return {"code_pages": evidence, "busy_no_svc": {"physical_start": begin, "physical_end": end,
            "instruction_words": len(opcodes), "sha256": digest(read_bytes(memory, begin, end - begin))}}


def check_tables(memory, symbols, r):
    result = []
    for task, base in enumerate(BASES):
        l1, l2 = symbols["TASK_L1"] + task * 16384, symbols["TASK_L2"] + task * 1024
        equal(l1 & 0x3FFF, 0, "task L1 alignment")
        equal(l2 & 0x3FF, 0, "task coarse L2 alignment")
        first, second = words(memory, l1, 4096), words(memory, l2, 256)
        equal(first[USER_CODE >> 20], l2 | 1, "own coarse L2 in client domain0")
        for index in {0, symbols["_start"] >> 20, BASES[0] >> 20, BASES[1] >> 20,
                      0x401, 0x40A, 0x40D}:
            equal(first[index], index << 20 | 0x402, "required identity mapping privileged AP1")
        for index, descriptor in enumerate(first):
            if descriptor and index != USER_CODE >> 20:
                equal(descriptor, index << 20 | 0x402,
                      f"task{task} section {index:#x}: privileged-only AP1, never user alias")
        expected = [base | 0xAA2, base + 4096 | 0xFF2, 0, base + 12288 | 0xFF2] + [0] * 252
        equal(second, expected, "only own codeRO/dataRW/guard-unmapped/stackRW User pages")
        equal(r["ttbr"] in (symbols["TASK_L1"], symbols["TASK_L1"] + 16384), True,
              "terminal TTBR belongs to one trusted task table")
        result.append({"task": task, "l1_physical": l1, "l2_physical": l2,
                       "user_virtual_base": USER_CODE, "code_descriptor": second[0],
                       "data_descriptor": second[1], "guard_descriptor": second[2],
                       "stack_descriptor": second[3], "physical_base": base,
                       "l1_sha256": digest(struct.pack("<4096I", *first)),
                       "l2_sha256": digest(struct.pack("<256I", *second))})
    return result


def check_frame(pointer, symbols, prefix, label):
    bottom, top = symbols[prefix + "_bottom"], symbols[prefix + "_top"]
    equal(bottom <= pointer <= top - 80 and pointer % 8 == 0, True,
          label + " complete 80-byte context/AAPCS frame within banked stack")


def check_context(memory, loads, index, task):
    context = task["context"]
    unsupported_thumb = task["state"] == 3 and task["fault_kind"] == 2 and bool(context["cpsr"] & 0x20)
    equal(context["cpsr"] & 0xFF, 0x70 if unsupported_thumb else 0x50,
          "saved actual User state, IRQ enabled, FIQ masked")
    if unsupported_thumb:
        equal(context["pc"], USER_DATA + 0x242, "unsupported Thumb SVC saved the next 16-bit instruction VA")
    else:
        equal(USER_CODE <= context["pc"] < USER_CODE + 4096 and context["pc"] % 4 == 0,
              True, "saved/resumed User ARM PC within own code page")
    equal(context["sp"] in (USER_TOP, USER_TOP - 56), True, "User SP stays in explicit workload stack contract")
    seed = 0x10 if index == 0 else 0x80
    expected = [seed + n for n in range(13)] + [seed + 14]
    if context["sp"] == USER_TOP - 56:
        equal(words(memory, user_physical(index, context["sp"], 56), 14), expected,
              "all r0-r12 and User LR actual stack sentinels survive switching")
    else:
        equal([context[f"r{n}"] for n in range(13)] + [context["lr"]], expected,
              "all r0-r12 and User LR saved sentinels survive switching")
    for number in (4, 5, 6, 8, 9, 10, 11, 12):
        equal(context[f"r{number}"], seed + number, f"live User r{number} sentinel")
    equal(context["pad"], 0, "exception context alignment word initialized")
    adjustment = {0: 4, 1: 4, 2: 0, 3: 8, 4: 4}
    equal(context["kind"] in adjustment, True, "saved context came from a defined exception path")
    equal(context["raw_lr"] - adjustment[context["kind"]], context["pc"],
          "banked exception LR converted to exact User resume/fault PC")
    physical = user_physical(index, task["fault_pc"] if unsupported_thumb else context["pc"])
    if unsupported_thumb:
        opcode = struct.unpack("<H", read_bytes(memory, physical, 2))[0]
        equal(opcode, 0xDF00, "explicit own unsupported Thumb SVC fixture in User data")
    else:
        opcode = image_word(loads, physical)
        equal(memory.readl(physical), opcode, "saved/resume PC instruction matches immutable own ELF")
    return {"context_physical_instruction": physical, "context_opcode": hex(opcode),
            "register_sentinels_verified": True, "stack_sentinels_verified": context["sp"] != USER_TOP,
            "saved_cpsr": context["cpsr"]}


def check_fault(memory, loads, symbols, selector, r, task):
    expected_kind = 1 if selector == 5 else 2 if selector == 7 else 3
    equal(task["fault_kind"], expected_kind, "actual selected UNDEF, SVC policy trap or data abort")
    equal(task["fault_psr"] & 0xFF, 0x70 if selector == 7 else 0x50,
          "fault originated in actual User instruction state with IRQ enabled")
    expected_bank = 0xDB if selector == 5 else 0xD3 if selector == 7 else 0xD7
    equal(r["last_fault_handler_cpsr"] & 0xFF, expected_bank, "fault uses correct banked exception mode")
    equal(task["fault_lr"] - (4 if selector == 5 else 2 if selector == 7 else 8), task["fault_pc"],
          "raw banked exception LR converts to exact failing ARM/Thumb PC")
    physical = user_physical(0, task["fault_pc"])
    if selector == 7:
        equal(task["fault_pc"], USER_DATA + 0x240, "unsupported SVC executes explicit own Thumb data fixture")
        opcode = struct.unpack("<H", read_bytes(memory, physical, 2))[0]
        equal(opcode, 0xDF00, "actual 16-bit Thumb SVC instruction, rejected before syscall dispatch")
    else:
        opcode = image_word(loads, physical)
        equal(memory.readl(physical), opcode, "actual fault opcode matches immutable ELF")
        fault_symbol = {1: "task_a_peer_read_fault", 2: "task_a_peer_write_fault",
                        3: "task_a_kernel_write_fault", 4: "task_a_guard_fault",
                        5: "task_a_undefined"}[selector]
        equal(physical, symbols[fault_symbol], "exact selected instruction symbol in hashed ELF")
    equal(task["fault_opcode"], opcode, "kernel captured the actual instruction")
    equal(task["ifsr"], 0, "no substituted prefetch fault")
    if selector in (5, 7):
        equal(opcode, 0xDF00 if selector == 7 else 0xE7F000F0, "own deliberate unsupported instruction encoding")
        equal(task["dfsr"], 0, "UNDEF/SVC policy trap has no data fault status")
    else:
        target = {1: BASES[1] + 4096, 2: BASES[1] + 4096 + 0x200,
                  3: symbols["TASK_CANARY"], 4: USER_GUARD}[selector]
        equal(task["dfar"], target, "exact forbidden VA, not a host-injected fault")
        equal(task["dfsr"] & 0xF, 7 if selector == 4 else 0xD,
              "small-page translation or privileged section permission fault")
        equal(opcode & 0x0C000000, 0x04000000, "faulting ARM single-data-transfer instruction")
        equal(bool(opcode & (1 << 20)), selector in (1, 4), "actual LDR/STR encoding proves access direction")
    return {"kind": expected_kind, "virtual_pc": task["fault_pc"], "physical_pc": physical,
            "opcode": hex(opcode), "dfsr": task["dfsr"], "dfar": task["dfar"]}


def capture_checkpoint(qmp, memory, process, uart_path, symbols, selector):
    """Pause real TCG before completion; sample User RAM independently of PASS.

    For a fault case this occurs after the offending task has been quarantined,
    while the surviving task still has its eight timer slices to execute. QMP
    stops the CPU before multiword reads; qtest never advances virtual time.
    """
    if selector == 6:
        return None
    deadline = time.monotonic() + 10
    while True:
        stage = memory.readl(symbols["CROSSHAIR_TASK_RECORD"] + 2 * 4)
        if selector == 0:
            ready = memory.readl(symbols["CROSSHAIR_TASK_RECORD"] + 5 * 4) >= 2
            ready = ready and all(memory.readl(base + 4096) > 0 for base in BASES)
        else:
            ready = memory.readl(symbols["TASKS"] + 4) == 3
            ready = ready and memory.readl(symbols["CROSSHAIR_TASK_RECORD"] + 22 * 4) > 0
        if stage == 2 and ready:
            qmp.request("stop")
            observed = record(memory, symbols["CROSSHAIR_TASK_RECORD"])
            equal(observed["stage"], 2, "real User progress checkpoint precedes terminal completion")
            sample = {"record": observed, "registers": qmp.monitor("info registers"),
                      "user_counters": [memory.readl(base + 4096) for base in BASES],
                      "tasks": task_records(memory, symbols["TASKS"])}
            equal(all(counter > 0 for counter in sample["user_counters"]), True,
                  "both actual User data counters progressed before checkpoint")
            if selector:
                equal(sample["tasks"][0]["state"], 3, "checkpoint observes faulting task already quarantined")
            qmp.request("cont")
            return sample
        if stage in (3, 0xFF) or process.poll() is not None or b"FAIL" in uart_path.read_bytes():
            raise AssertionError("guest terminated before independent live User progress checkpoint")
        if time.monotonic() >= deadline:
            raise TimeoutError("real TCG failed to reach live User progress checkpoint")
        time.sleep(0.001)


def check_run(memory, loads, image, selector, r, tasks, registers, checkpoint):
    symbols = image["symbols"]
    for field, expected in {"magic": 0x5441534B, "version": 1, "stage": 3, "error": 0,
                            "scenario": selector, "current": 0xFFFFFFFF, "midr": 0x69052903,
                            "sctlr": 0x79, "dacr": 1, "pid": 0, "pic_mask_final": 0,
                            "timer_oier_final": 0, "timer_ossr_final": 0, "canary_ok": 1}.items():
        equal(r[field], expected, field)
    equal(register(registers, "R15"), symbols["kernel_idle"], "actual terminal privileged branch")
    equal(register(registers, "PSR") & 0xFF, 0xD3, "terminal SVC IRQ/FIQ masked")
    sp = register(registers, "R13")
    equal(symbols["__stack_bottom"] <= sp <= symbols["__stack_top"] and sp % 8 == 0,
          True, "terminal trusted SVC stack")
    equal(r["last_irq_handler_cpsr"] & 0xFF, 0xD2, "actual IRQ bank, no nested IRQ")
    equal(r["last_svc_handler_cpsr"] & 0xFF, 0xD3, "actual SVC bank")
    check_frame(r["last_irq_frame"], symbols, "__irq_stack", "IRQ")
    check_frame(r["last_svc_frame"], symbols, "__stack", "SVC")
    for prefix, size in (("__stack", 16384), ("__irq_stack", 4096), ("__abort_stack", 4096), ("__undef_stack", 4096)):
        equal(symbols[prefix + "_top"] - symbols[prefix + "_bottom"], size, "banked stack reserved extent")
        equal(words(memory, symbols[prefix + "_bottom"], 4), [0xFACE6000 ^ n for n in range(4)],
              "actual banked stack lower kernel canary intact")
        equal(read_bytes(memory, symbols[prefix + "_bottom"] + 16, 16), b"\xCD" * 16,
              "banked stack lower poison beyond initialized canary untouched")
    equal(words(memory, symbols["TASK_CANARY"], 16), [0xCAFE6000 ^ n for n in range(16)],
          "actual privileged kernel canary survives User access attempts")
    equal(memory.readl(0x40D00004), 0, "actual PIC ICMR disabled at terminal")
    equal(memory.readl(0x40D00008), 0, "timer remains IRQ, never User-controlled FIQ")
    equal(memory.readl(0x40A0001C), 0, "actual timer OIER disabled at terminal")
    equal(memory.readl(0x40A00014) & 1, 0, "actual timer event acknowledged")
    equal(r["tlb_switches"], sum(task["dispatches"] for task in tasks),
          "initial address-space install and every actual dispatch invalidate the ARMv5 TLB")
    equal(r["ticks"], r["irq_from_a"] + r["irq_from_b"], "every scheduler tick came from actual User IRQ")
    equal([task["id"] for task in tasks], [1, 2], "kernel-owned distinct task identity")
    for index, task in enumerate(tasks):
        minimum = 0 if selector == 6 and index == 1 else 2
        equal(task["dispatches"] >= max(1, minimum) and task["preemptions"] >= minimum, True,
              "actual task dispatch and timer preemption count")
    equal([task["preemptions"] for task in tasks], [r["irq_from_a"], r["irq_from_b"]],
          "task preemptions match independently banked IRQ-origin counters")
    data = [dict(zip(DATA_FIELDS, words(memory, base + 4096, len(DATA_FIELDS)))) for base in BASES]
    if checkpoint is not None:
        for index in (0, 1) if selector == 0 else (1,):
            equal(data[index]["counter"] > checkpoint["user_counters"][index], True,
                  "actual User stores continue after QMP stop/resume checkpoint")
    if selector in (1, 2, 3, 4, 5, 7):
        equal(data[1]["counter"] > r["healthy_counter_at_fault"], True,
              "actual healthy User counter advances after companion fault capture")
    else:
        equal(r["healthy_counter_at_fault"], 0, "no hidden fault-progress snapshot in a healthy scenario")
    for index, observed in enumerate(data):
        equal(observed["counter"] > 0 and observed["accumulator"] > 0, True,
              "actual User data RAM proves both independent workloads progressed")
        counter = observed["counter"]
        triangular = lambda count: count * (count + 1) // 2 & 0xFFFFFFFF
        equal(observed["accumulator"] in (triangular(counter), triangular(counter - 1)), True,
              "actual User accumulator follows the workload computation, allowing one interrupted store")
        equal(observed["workload_error"], 0, "User all-register/NZCV self-check did not fail")
        equal(memory.readl(BASES[index] + 4096 + 0x200), 0x60000001 + index,
              "actual task-specific User data canary survives foreign access attempts")
        equal(read_bytes(memory, BASES[index] + 4096 + 0x80, len(PAYLOAD)), PAYLOAD,
              "own source payload remains intact")
        equal(read_bytes(memory, BASES[index] + 8192, 4096), b"\x6D" * 4096,
              "unmapped physical guard is never initialized or reused")
        equal(read_bytes(memory, symbols["TASK_COPY"] + index * 64, 64),
              (PAYLOAD + bytes(64 - len(PAYLOAD))) if index else bytes(64),
              "per-task diagnostic Copy modifies only the trusted task-specific buffer")
    equal(tasks[0]["copies"], 0, "Busy Loop does not request diagnostic Copy")
    equal(tasks[1]["copies"] > 0, True, "healthy task completed permitted SVC copies")
    equal(data[1]["copyret"], len(PAYLOAD), "actual User store observes diagnostic Copy return value")
    equal(data[1]["copypsr"], 0x60000050, "SVC preserves actual User ARM NZCV=ZC, IRQ enabled, FIQ masked")
    equal(words(memory, BASES[1] + 4096 + 0x100, 7),
          [value & 0xFFFFFFFF for value in (-38, -14, -14, -22, -14, -14, -14)],
          "actual User stores prove ENOSYS, boundary, overflow, length cap, code, null/zero and foreign PA rejection")
    equal(data[1]["zero_length_ret"], 0, "one-past-end zero-length Copy accepted")
    equal(data[1]["bad_immediate_ret"], (-38) & 0xFFFFFFFF, "unsupported SVC immediate returns ENOSYS")
    for index, pc in enumerate((r["first_irq_a_pc"], r["first_irq_b_pc"])):
        if tasks[index]["preemptions"]:
            equal(USER_CODE <= pc < USER_CODE + 4096 and pc % 4 == 0, True,
                  "first actual preemption saved a User workload instruction PC")
        else:
            equal(pc, 0, "task exited before timer preemption; no invented IRQ PC")
    verification = {"contexts": [check_context(memory, loads, index, task) for index, task in enumerate(tasks)],
                    "user_data": data, "page_tables": check_tables(memory, symbols, r),
                    "code": check_code(memory, loads, symbols)}
    if selector in (1, 2, 3, 4, 5, 7):
        equal([task["state"] for task in tasks], [3, 0], "only offending task Faulted, healthy task retained Ready")
        equal(r["fault_tick"] >= 2, True, "fault delayed until Busy Loop was genuinely preempted")
        equal(r["ticks"] >= r["fault_tick"] + 8 and tasks[1]["preemptions"] >= 4, True,
              "healthy User continues receiving timer slices after companion fault")
        equal(tasks[0]["svc_count"], 0, "faulting Busy Loop never yielded using SVC")
        check_frame(r["last_undef_frame"] if selector == 5 else r["last_svc_frame"] if selector == 7 else r["last_abort_frame"], symbols,
                    "__undef_stack" if selector == 5 else "__stack" if selector == 7 else "__abort_stack", "fault")
        verification["fault"] = check_fault(memory, loads, symbols, selector, r, tasks[0])
    elif selector == 0:
        equal([task["state"] for task in tasks], [0, 0], "budget freeze retains both allocated Ready tasks")
        equal(r["ticks"] >= 12 and min(task["preemptions"] for task in tasks) >= 4, True,
              "Busy Loop no-SVC hardware preemption acceptance budget")
        equal(tasks[0]["svc_count"], 0, "Busy Loop has no voluntary Yield or other SVC")
        equal(r["fault_tick"], 0, "positive control has no hidden fault termination")
        equal(r["terminal_reason"], 1, "positive control stops by diagnostic budget")
    else:
        equal([task["state"] for task in tasks], [2, 2], "both tasks use real Exit and remain allocated")
        equal(tasks[0]["yields"], 1, "Task A tested actual Yield SVC once")
        equal([task["exit_code"] for task in tasks], [0x2A, 0x2B], "Exit retains the caller-provided status")
        equal(data[0]["last_syscall_err"], 0, "Yield returns zero into real User task")
        equal(data[0]["lifecycle_marker"], 0x66, "actual User resumed after Yield and stored marker before Exit")
        equal(r["terminal_reason"], 2, "no runnable tasks selects privileged Idle")
    for task in tasks[1:] if selector in (1, 2, 3, 4, 5, 7) else tasks:
        equal(task["fault_kind"], 0, "healthy task has no hidden exception")
    equal(read_bytes(memory, 0xA0700000, 256), b"\xA7" * 256, "remote ordinary RAM sentinel preserved")
    return verification


def memory_accounting(symbols):
    stacks = {name: symbols[name + "_top"] - symbols[name + "_bottom"]
              for name in ("__stack", "__irq_stack", "__abort_stack", "__undef_stack")}
    return {"address_type": "physical", "kernel_start": symbols["_start"],
            "kernel_end": symbols["__image_end"],
            "kernel_reserved_extent_bytes": symbols["__image_end"] - symbols["_start"],
            "vectors_bytes": 64, "banked_stacks_bytes": stacks,
            "page_tables_total_bytes": 2 * (16384 + 1024),
            "task_table_bytes": 2 * TASK_WORDS * 4,
            "per_task": {"context_bytes": len(CONTEXT_FIELDS) * 4,
                         "task_metadata_and_context_bytes": TASK_WORDS * 4,
                         "l1_bytes": 16384, "l2_bytes": 1024,
                         "diagnostic_copy_bytes": 64,
                         "kernel_task_overhead_bytes": 16384 + 1024 + TASK_WORDS * 4 + 64,
                         "user_mapped_bytes": 3 * 4096,
                         "user_reserved_extent_bytes": 4 * 4096,
                         "guard_reserved_unmapped_bytes": 4096},
            "flat_binary_is_not_working_ram": True}


def run_case(qemu, selector, image, loads, hashes):
    directory = OUT / f"case-{selector:02d}"
    directory.mkdir(parents=True, exist_ok=True)
    result = {"result": "FAIL", "selector": selector, "name": CASES[selector],
              "machine": MACHINE, "accelerator": "tcg", "image_sha256": hashes, "boots": []}
    symbols = image["symbols"]
    with tempfile.TemporaryDirectory(prefix="crosshair-tasks-") as temporary:
        qmp_path, memory_path = Path(temporary) / "qmp", Path(temporary) / "memory"
        command = [qemu, "-machine", MACHINE, "-cpu", "pxa260", "-accel", "tcg", "-S",
                   "-display", "none", "-monitor", "none", "-serial", "stdio", "-nic", "none",
                   "-device", f"loader,file={IMAGE / 'crosshair-tasks.elf'},cpu-num=0",
                   "-qmp", f"unix:{qmp_path},server=on,wait=off",
                   "-qtest", f"unix:{memory_path},server=on,wait=off",
                   "-qtest-log", str(directory / "memory-server.log"), "-d", "guest_errors"]
        result["command"] = command
        uart_path = directory / "qemu-uart.log"
        with uart_path.open("wb") as uart, (directory / "qemu-stderr.log").open("wb") as stderr, (directory / "memory-protocol.log").open("w") as transcript:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=uart, stderr=stderr)
            qmp = memory = None
            try:
                qmp, memory = Qmp(qmp_path, process), QTest(memory_path, process, transcript)
                for boot in range(2):
                    deadline = time.monotonic() + 3
                    while register(qmp.monitor("info registers"), "R15") != image["entry"]:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("QMP reset did not restore actual ELF entry")
                        time.sleep(0.001)
                    equal(register(qmp.monitor("info registers"), "PSR") & 0xFF, 0xD3, "reset actual privileged ARM")
                    memory.request(f"memset {symbols['__bss_start']:#x} {symbols['__bss_end'] - symbols['__bss_start']} 0xa5")
                    equal(memory.readl(symbols["CROSSHAIR_TASK_RECORD"]), 0xA5A5A5A5, "record resides in poisoned BSS")
                    for prefix in ("__stack", "__irq_stack", "__abort_stack", "__undef_stack"):
                        memory.request(f"memset {symbols[prefix + '_bottom']:#x} {symbols[prefix + '_top'] - symbols[prefix + '_bottom']} 0xcd")
                    for base in BASES:
                        memory.request(f"memset {base + 8192:#x} 4096 0x6d")
                        memory.request(f"memset {base + 4096:#x} 4096 0x97")
                        memory.request(f"memset {base + 12288:#x} 4096 0x98")
                    memory.request("memset 0xa0700000 256 0xa7")
                    memory.writel(MAILBOX, selector)
                    equal(memory.readl(MAILBOX), selector, "scenario chosen before entry, never synthetic IRQ injection")
                    qmp.request("cont")
                    checkpoint = capture_checkpoint(qmp, memory, process, uart_path, symbols, selector)
                    wait_uart(process, uart_path, PASS * (boot + 1), 12)
                    qmp.request("stop")
                    registers = settle_idle(qmp, symbols["kernel_idle"])
                    r = record(memory, symbols["CROSSHAIR_TASK_RECORD"])
                    tasks = task_records(memory, symbols["TASKS"])
                    verification = check_run(memory, loads, image, selector, r, tasks, registers, checkpoint)
                    result["boots"].append({"boot": boot + 1, "pre_entry_poison": 0xA5A5A5A5,
                                            "record": r, "tasks": tasks, "registers": registers,
                                            "live_checkpoint": checkpoint, "verification": verification})
                    if boot == 0:
                        qmp.request("system_reset")
                equal(uart_path.read_bytes(), PASS * 2, "exact task UART for two real reset boots")
                qmp.request("quit")
                process.wait(timeout=3)
                equal(process.returncode, 0, "clean QEMU exit")
                result.update(result="PASS", uart_utf8=uart_path.read_text())
            except Exception as error:
                result["error"] = f"{type(error).__name__}: {error}"
                if qmp and memory and process.poll() is None:
                    try:
                        qmp.request("stop")
                        result["failure_registers"] = qmp.monitor("info registers")
                        result["failure_record"] = record(memory, symbols["CROSSHAIR_TASK_RECORD"])
                        result["failure_tasks"] = task_records(memory, symbols["TASKS"])
                    except Exception:
                        pass
                raise
            finally:
                try:
                    if memory:
                        memory.close()
                    if qmp:
                        qmp.close()
                    stop_process(process)
                finally:
                    (directory / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--qemu", default=os.environ.get("QEMU_E2B", str(ROOT / "local/qemu-e2b/bin/qemu-system-arm")))
    parser.add_argument("--case", type=int, choices=CASES, help="Run one scenario, always two reset boots")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    result = {"result": "FAIL", "machine": MACHINE, "accelerator": "tcg", "cases": [],
              "scope": "two fixed User tasks on unchanged synthetic E2B/pxa260; not PXA263 hardware security validation"}
    try:
        equal((len(FIELDS), TASK_WORDS), (32, 36), "versioned task observation ABI")
        image = json.loads((IMAGE / "image.json").read_text())
        names = {"crosshair-tasks.elf", "crosshair-tasks.bin", "vectors.bin"}
        equal(set(image["sha256"]), names, "complete task image manifest")
        hashes = {name: digest((IMAGE / name).read_bytes()) for name in names}
        equal(hashes, image["sha256"], "current own image bytes match manifest")
        entry, loads = elf_loads(IMAGE / "crosshair-tasks.elf")
        equal(entry, image["entry"], "actual hashed ELF entry")
        symbols = image["symbols"]
        for name, size in (("CROSSHAIR_TASK_RECORD", len(FIELDS) * 4), ("TASKS", 2 * TASK_WORDS * 4),
                           ("TASK_L1", 32768), ("TASK_L2", 2048), ("TASK_COPY", 128), ("TASK_CANARY", 64)):
            equal(symbols["__bss_start"] <= symbols[name] <= symbols["__bss_end"] - size, True,
                  name + " complete trusted allocation within poisoned BSS")
        result.update(image_sha256=hashes, qemu_version=qemu_version(args.qemu),
                      qemu_sha256=digest(Path(shutil.which(args.qemu) or args.qemu).read_bytes()),
                      memory=memory_accounting(symbols))
        selections = list(CASES) if args.case is None else [args.case]
        for selector in selections:
            observed = run_case(args.qemu, selector, image, loads, hashes)
            result["cases"].append({"selector": selector, "name": CASES[selector], "result": observed["result"],
                                    "boots": len(observed["boots"]), "evidence": f"case-{selector:02d}/result.json"})
            print(f"PASS tasks case{selector:02d}: {CASES[selector]}, two boots via QMP reset")
        result.update(result="PASS", case_count=len(selections), boots=2 * len(selections),
                      complete_suite=args.case is None,
                      source_sha256={str(path.relative_to(ROOT)): digest(path.read_bytes()) for path in
                                     (ROOT / "src/tasks.rs", ROOT / "src/arch/tasks_entry.S", ROOT / "src/arch/task_workloads.S", ROOT / "link/tasks.ld",
                                      ROOT / "tools/smoke_tasks.py", ROOT / "scripts/build-tasks.sh",
                                      ROOT / "scripts/test-tasks.sh", ROOT / "scripts/test-wave006.sh",
                                      ROOT / "src/security_policy.rs", ROOT / "src/drivers/pxa_uart.rs",
                                      ROOT / "build.rs", ROOT / "Cargo.toml", ROOT / "Cargo.lock",
                                      ROOT / ".cargo/config.toml", ROOT / "rust-toolchain.toml",
                                      ROOT / "tools/verify_image.py", ROOT / "tools/qemu_control.py",
                                      ROOT / "tools/qtest_pxa.py", ROOT / "tools/smoke_e2a.py", ROOT / "tools/smoke_security.py",
                                      ROOT / "crosshair-emulator/qemu/crosshair-blueangel-e2a.c",
                                      ROOT / "crosshair-emulator/qemu/crosshair-blueangel-e2b.c") +
                                     tuple(sorted((ROOT / "src/task_runtime").glob("*.rs")))})
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"PASS tasks: {result['case_count']} scenarios, {result['boots']} ARM TCG boots; real Busy Loop IRQ preemption and task fault isolation")


if __name__ == "__main__":
    main()
