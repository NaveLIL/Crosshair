#!/usr/bin/env python3
"""Execute User/SVC isolation cases on the unchanged synthetic E2B machine.

These are functional ARMv5/TCG proofs, not a complete security certification or
physical PXA263 validation. No host block device or manufacturer image is used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import time

from qemu_control import Qmp, stop_process
from qtest_pxa import QTest, equal
from smoke_e2a import qemu_version, settle_idle, wait_uart

ROOT = Path(__file__).resolve().parents[1]
MACHINE = "crosshair-blueangel-e2b"
MAILBOX = 0xA0000100
USER_CODE, USER_CODE_PA = 0x01000000, 0xA0200000
USER_DATA, USER_DATA_PA = 0x01001000, 0xA0201000
USER_GUARD = 0x01002000
USER_STACK, USER_STACK_PA = 0x01003000, 0xA0203000
PASS = "CROSSHAIR SECURITY — USER ISOLATION PASS\r\n".encode()
PAYLOAD = b"CROSSHAIR USER\n"

# Independent host expectations; never derive these from guest result flags.
CASES = {
    0: {"name": "valid_copy", "return": 15},
    1: {"name": "kernel_read", "fault": "data", "dfsr": 0xD},
    2: {"name": "kernel_write", "fault": "data", "dfsr": 0xD},
    3: {"name": "mmio_read", "fault": "data", "dfsr": 0xD, "dfar": 0x40100014},
    4: {"name": "mmio_write", "fault": "data", "dfsr": 0xD, "dfar": 0x40100000},
    5: {"name": "unknown_syscall", "return": -38},
    6: {"name": "null_pointer", "return": -14},
    7: {"name": "kernel_pointer", "return": -14},
    8: {"name": "cross_data_boundary", "return": -14},
    9: {"name": "oversized_copy", "return": -22},
    10: {"name": "pointer_add_overflow", "return": -14},
    11: {"name": "one_past_zero_length", "return": 0},
    12: {"name": "user_code_write", "fault": "data", "dfsr": 0xF, "dfar": USER_CODE},
    13: {"name": "unmapped_user_guard", "fault": "data", "dfsr": 7, "dfar": USER_GUARD},
    14: {"name": "wrong_svc_immediate", "return": -38},
    15: {"name": "privileged_cp15", "fault": "undefined"},
    16: {"name": "armv5_no_xn_control", "return": 15},
    17: {"name": "code_pointer_copy_policy", "return": -14},
    18: {"name": "maximum_valid_copy", "return": 64},
    19: {"name": "null_zero_length", "return": -14},
    20: {"name": "svc_from_user_rw_data", "fault": "svc_policy"},
    21: {"name": "unmapped_user_instruction_fetch", "fault": "prefetch"},
    22: {"name": "unsupported_thumb_svc", "fault": "svc_policy"},
    23: {"name": "undefined_from_user_rw_data", "fault": "undefined"},
}
FIELDS = """magic stage error selector outcome primary_attempts primary_return
primary_exit_code fault_kind fault_lr fault_psr dfsr dfar fault_opcode
primary_svc_lr primary_svc_psr primary_svc_opcode primary_number primary_pointer
primary_length primary_copy_length primary_copy_hash canary_ok copy_guards_ok
recovery_ok recovery_return recovery_svc_psr recovery_user_psr midr sctlr ttbr
dacr l1_user l2_code l2_data l2_guard l2_stack primary_user_return primary_user_psr
primary_marker user_entry kernel_resumes recovery_copy_hash successful_copies
fault_handler_psr primary_handler_psr recovery_attempts primary_exits
recovery_exits bad_immediates unknown_numbers policy_rejections primary_frame
abort_frame undef_frame resume_sp case_count maximum_copy data_end user_code_bytes
recovery_user_return recovery_stored_psr pid opcode_available recovery_svc_lr
recovery_svc_opcode recovery_number total_svc ifsr recovery_handler_psr
user_code_hash_before user_code_hash_after""".split()
FAULT_SYMBOLS = {1: "user_kernel_read_fault", 2: "user_kernel_write_fault",
                 3: "user_mmio_read_fault", 4: "user_mmio_write_fault",
                 12: "user_code_write_fault", 13: "user_guard_read_fault",
                 15: "user_cp15"}
COPY_REJECTS = {6, 7, 8, 9, 10, 17, 19}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fnv32(data):
    value = 0x811C9DC5
    for byte in data:
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return value


def read_bytes(memory, address, size):
    response = memory.request(f"read {address:#x} {size:#x}")
    data = bytes.fromhex(response[0].removeprefix("0x"))
    equal(len(data), size, "complete physical memory observation")
    return data


def words(memory, address, count):
    return list(struct.unpack(f"<{count}I", read_bytes(memory, address, count * 4)))


def register(text, name):
    match = re.search(rf"\b{name}=([0-9a-fA-F]+)", text)
    if match is None:
        raise AssertionError(f"missing CPU register {name}")
    return int(match[1], 16)


def elf_loads(path):
    """Bounded ELF32 program-header reader for our hashed own image."""
    data = path.read_bytes()
    if len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("need a complete ELF32 little-endian image")
    header = struct.unpack_from("<HHIIIIIHHHHHH", data, 16)
    kind, machine, _, entry, phoff, _, flags, _, phsize, phnum, *_ = header
    equal((kind, machine), (2, 40), "static ARM ELF")
    equal(flags >> 24, 5, "ARM EABI5")
    equal(bool(flags & 0x400), False, "no hard-float ABI")
    if phsize != 32 or phoff > len(data) or phnum > (len(data) - phoff) // phsize:
        raise ValueError("invalid ELF program-header bounds")
    loads = []
    for index in range(phnum):
        ptype, offset, va, pa, filesz, memsz, permission, alignment = struct.unpack_from(
            "<8I", data, phoff + index * phsize)
        if ptype in (2, 3):
            raise ValueError("dynamic runtime is forbidden")
        if ptype == 1:
            if (filesz > memsz or offset > len(data) or filesz > len(data) - offset
                    or pa + memsz > 1 << 32 or va + memsz > 1 << 32 or va != pa):
                raise ValueError("invalid ELF load segment")
            loads.append({"pa": pa, "va": va, "filesz": filesz, "memsz": memsz,
                          "flags": permission, "bytes": data[offset:offset + filesz]})
    return entry, loads


def image_word(loads, physical):
    matches = [load for load in loads if load["pa"] <= physical and physical + 4 <= load["pa"] + load["filesz"]]
    equal(len(matches), 1, "instruction belongs to one hashed ELF load segment")
    load = matches[0]
    equal(bool(load["flags"] & 1), True, "instruction lies in executable ELF segment")
    return struct.unpack_from("<I", load["bytes"], physical - load["pa"])[0]


def check_page_tables(memory, symbols, entry):
    l1, l2 = symbols["SECURITY_L1"], symbols["SECURITY_L2"]
    equal(l1 & 0x3FFF, 0, "L1 table alignment")
    equal(l2 & 0x3FF, 0, "coarse L2 table alignment")
    first, second = words(memory, l1, 4096), words(memory, l2, 256)
    equal(first[USER_CODE >> 20], l2 | 1, "user coarse table in client domain0")
    required = {0, entry >> 20, USER_CODE_PA >> 20, 0x401}
    for index in required:
        equal(first[index], index << 20 | 0x402, "required privileged identity section/AP1")
    for index, descriptor in enumerate(first):
        if descriptor and index != USER_CODE >> 20:
            equal(descriptor, index << 20 | 0x402,
                  f"other mapped section {index:#x} is identity and privileged AP1")
    expected = [USER_CODE_PA | 0xAA2, USER_DATA_PA | 0xFF2, 0,
                USER_STACK_PA | 0xFF2] + [0] * 252
    equal(second, expected, "user codeRO/dataRW/guard-unmapped/stackRW, all subpage AP fields")
    return {"l1": l1, "l2": l2, "domain": 0, "dacr_required": 1,
            "code_descriptor": second[0], "data_descriptor": second[1],
            "guard_descriptor": second[2], "stack_descriptor": second[3],
            "other_sections_privileged_only": True}


def check_user_code(memory, loads):
    segments = [load for load in loads if load["pa"] == USER_CODE_PA]
    equal(len(segments), 1, "separate physical user-code ELF segment")
    segment = segments[0]
    if segment["filesz"] > 4096 or segment["memsz"] > 4096:
        raise AssertionError("user-code segment exceeds its page")
    equal(segment["flags"], 5, "user-code segment RX in ELF")
    observed = read_bytes(memory, USER_CODE_PA, segment["filesz"])
    equal(observed, segment["bytes"], "user code unchanged from hashed ELF")
    return digest(observed)


def user_virtual(physical):
    if not USER_CODE_PA <= physical < USER_CODE_PA + 4096:
        raise AssertionError(f"user instruction symbol outside code page: {physical:#x}")
    return USER_CODE + physical - USER_CODE_PA


def check_instruction(memory, loads, virtual, symbol_physical, expected_opcode=None):
    equal(virtual, user_virtual(symbol_physical), "exact fault/SVC instruction virtual PC")
    opcode = image_word(loads, symbol_physical)
    equal(memory.readl(symbol_physical), opcode, "executed physical opcode matches hashed ELF")
    if expected_opcode is not None:
        equal(opcode, expected_opcode, "expected ARM instruction encoding")
    return {"virtual_pc": virtual, "physical_pc": symbol_physical, "opcode": hex(opcode)}


def check_stack(address, symbols, prefix, size, label):
    bottom, top = symbols[prefix + "_bottom"], symbols[prefix + "_top"]
    equal(top - bottom, size, label + " allocated bytes")
    equal(bottom <= address and address + 64 <= top and address % 8 == 0,
          True, label + " frame bounds/AAPCS alignment")


def check_case(memory, loads, symbols, selector, r, registers):
    case = CASES[selector]
    hardware_fault = selector in FAULT_SYMBOLS or selector in (21, 23)
    terminated = hardware_fault or selector in (20, 22)
    basic = {"magic": 0x53454355, "stage": 5, "error": 0, "selector": selector,
             "primary_exit_code": 0, "canary_ok": 1, "copy_guards_ok": 1,
             "recovery_ok": 1, "recovery_return": 15, "midr": 0x69052903,
             "sctlr": 0x79, "ttbr": symbols["SECURITY_L1"], "dacr": 1,
             "l1_user": symbols["SECURITY_L2"] | 1,
             "l2_code": USER_CODE_PA | 0xAA2, "l2_data": USER_DATA_PA | 0xFF2,
             "l2_guard": 0, "l2_stack": USER_STACK_PA | 0xFF2,
             "user_entry": USER_CODE, "kernel_resumes": 2,
             "recovery_copy_hash": fnv32(PAYLOAD), "recovery_attempts": 1,
             "primary_exits": int(not terminated), "recovery_exits": 1,
             "bad_immediates": int(selector == 14), "unknown_numbers": int(selector == 5),
             "policy_rejections": int(selector in COPY_REJECTS),
             "case_count": 24, "maximum_copy": 64, "data_end": USER_GUARD,
             "user_code_bytes": symbols["security_user_end"] - USER_CODE_PA,
             "recovery_user_return": 15, "pid": 0,
             "opcode_available": int(terminated and selector != 21),
             "recovery_svc_opcode": 0xEF000000, "recovery_number": 1,
             "total_svc": 2 if hardware_fault else 3 if selector in (20, 22) else 4,
             "ifsr": 5 if selector == 21 else 0}
    primary_success = selector in (0, 11, 16, 18)
    basic["successful_copies"] = 1 + int(primary_success)
    for name, expected in basic.items():
        equal(r[name], expected, name)
    for name in ("recovery_svc_psr", "recovery_user_psr", "recovery_stored_psr"):
        equal(r[name] & 0xFF, 0xD0, name + " proves actual User ARM with IRQ/FIQ masked")
    equal(r["recovery_handler_psr"] & 0xFF, 0xD3, "recovery handler executes SVC")
    equal(register(registers, "PSR") & 0xFF, 0xD3, "terminal privileged ARM SVC")
    sp = register(registers, "R13")
    equal(symbols["__stack_bottom"] <= sp <= symbols["__stack_top"] and sp % 8 == 0,
          True, "terminal SVC stack")
    equal(symbols["__stack_bottom"] <= r["resume_sp"] <= symbols["__stack_top"] - 40
          and r["resume_sp"] % 8 == 0, True, "trusted caller resume frame")
    recovery_instruction = check_instruction(memory, loads, r["recovery_svc_lr"] - 4,
                                               symbols["user_copy_svc"], 0xEF000000)
    user_segment = next(load for load in loads if load["pa"] == USER_CODE_PA)
    code_hash = fnv32(user_segment["bytes"])
    equal((r["user_code_hash_before"], r["user_code_hash_after"]), (code_hash, code_hash),
          "privileged/user code hashing matches own immutable ELF")
    equal(words(memory, symbols["KERNEL_CANARY"], 16),
          [0xCAFE5100 ^ i for i in range(16)], "actual kernel canary RAM intact")
    copy = symbols["SECURITY_COPY"]
    equal(words(memory, copy, 4), [0xACE00000 ^ i for i in range(4)], "copy prefix guard")
    equal(read_bytes(memory, copy + 16, 64), PAYLOAD + b"\xCC" * (64 - len(PAYLOAD)),
          "recovery copied exactly its allowed bytes")
    equal(words(memory, copy + 80, 4), [0xACE10000 ^ i for i in range(4)], "copy suffix guard")
    equal(words(memory, USER_DATA_PA + 0x100, 3), [15, r["recovery_stored_psr"], 0],
          "actual recovery user stores return/CPSR/marker")
    equal(words(memory, USER_DATA_PA + 0x200, 2), [0xE3A0805A, 0xE12FFF1E],
          "own benign ARM data-execution control instructions")
    if selector >= 20:
        kind = 2 if selector in (20, 22) else 4 if selector == 21 else 1
        equal((r["outcome"], r["fault_kind"]),
              (5 if kind == 2 else 4 if kind == 4 else 3, kind), "unsupported User behavior terminates context")
        thumb = selector == 22
        equal(r["fault_psr"] & 0xFF, 0xF0 if thumb else 0xD0, "actual User instruction state captured")
        equal(r["fault_handler_psr"] & 0xFF, 0xD3 if kind == 2 else 0xD7 if kind == 4 else 0xDB,
              "unsupported User trap uses correct privileged exception bank")
        equal((r["dfsr"], r["dfar"]), (0, 0), "these traps are not data-abort substitutes")
        equal((r["primary_return"], r["primary_copy_length"], r["primary_copy_hash"]),
              (0, 0, 0), "terminated User did not return or copy")
        equal((r["primary_user_return"], r["primary_user_psr"], r["primary_marker"]),
              (0xFFFFFFFF,) * 3, "terminated before user post-SVC stores")
        if selector == 21:
            equal(r["fault_lr"], 0x02000004, "prefetch LR is unreadable destination+4")
            equal(r["fault_opcode"], 0, "unmapped instruction is not speculatively read")
            primary_instruction = {"virtual_pc": 0x02000000, "opcode_available": False,
                                   "ifsr": 5, "branch_instruction": check_instruction(
                                       memory, loads, user_virtual(symbols["user_unmapped_branch_fault"]),
                                       symbols["user_unmapped_branch_fault"], 0xE12FFF11)}
            check_stack(r["abort_frame"], symbols, "__abort_stack", 4096, "prefetch ABT")
            equal(r["undef_frame"], 0, "no UNDEF in prefetch case")
        else:
            offset = 0x224 if selector == 20 else 0x240 if selector == 22 else 0x260
            opcode = 0xEF000000 if selector == 20 else 0xDF00 if selector == 22 else 0xE7F000F0
            pc = USER_DATA + offset
            equal(r["fault_lr"], pc + (2 if thumb else 4), "exact data-page trap LR")
            equal(r["fault_opcode"], opcode, "actual own data-page instruction")
            raw = read_bytes(memory, USER_DATA_PA + offset, 2 if thumb else 4)
            equal(int.from_bytes(raw, "little"), opcode, "data-page instruction retained in actual RAM")
            primary_instruction = {"virtual_pc": pc, "physical_pc": USER_DATA_PA + offset,
                                   "opcode": hex(opcode), "source": "own runtime-initialized data-page words"}
            if selector == 23:
                check_stack(r["undef_frame"], symbols, "__undef_stack", 4096, "data-page UND")
                equal(r["abort_frame"], 0, "no data ABT for undefined instruction")
            else:
                equal(r["primary_attempts"], 1, "actual unsupported-origin SVC trap counted")
                equal(r["primary_svc_lr"], r["fault_lr"], "SVC LR retained before termination")
                equal(r["primary_svc_psr"] & 0xFF, 0xF0 if thumb else 0xD0, "SVC saved actual User/Thumb state")
                equal(r["primary_svc_opcode"], opcode, "unsupported-origin SVC opcode retained")
                equal(r["primary_handler_psr"] & 0xFF, 0xD3, "policy termination in SVC")
                equal((r["primary_number"], r["primary_pointer"], r["primary_length"]),
                      (1, 20, USER_DATA + 0x220) if selector == 20 else (0, 22, USER_DATA + 0x241),
                      "unsupported-origin actual user registers")
                check_stack(r["primary_frame"], symbols, "__stack", 16384, "unsupported-origin SVC")
                equal((r["abort_frame"], r["undef_frame"]), (0, 0), "SVC policy termination is not hardware ABT/UND")
        if hardware_fault:
            for field in ("primary_attempts", "primary_svc_lr", "primary_svc_psr", "primary_svc_opcode",
                          "primary_number", "primary_pointer", "primary_length", "primary_handler_psr", "primary_frame"):
                equal(r[field], 0, field + " absent before hardware context termination")
    elif hardware_fault:
        kind = 1 if selector == 15 else 3
        equal(r["outcome"], 3 if kind == 1 else 2, "primary terminated by actual expected exception")
        equal(r["fault_kind"], kind, "exact exception vector class")
        equal(r["fault_psr"] & 0xFF, 0xD0, "hardware captured faulting User CPSR")
        equal(r["fault_handler_psr"] & 0xFF, 0xDB if kind == 1 else 0xD7,
              "handler executes in correct privileged bank")
        pc = r["fault_lr"] - (4 if kind == 1 else 8)
        opcode = 0xEE110F10 if kind == 1 else 0xE5812000 if selector in (2, 4, 12) else 0xE5912000
        fault_instruction = check_instruction(memory, loads, pc, symbols[FAULT_SYMBOLS[selector]], opcode)
        equal(r["fault_opcode"], opcode, "handler retained actual failed instruction")
        if kind == 3:
            equal(r["dfsr"], case["dfsr"], "ARMv5 precise permission/translation status (no V6 WnR)")
            equal(r["dfar"], symbols["KERNEL_CANARY"] if selector in (1, 2) else case["dfar"],
                  "exact virtual address denied")
            check_stack(r["abort_frame"], symbols, "__abort_stack", 4096, "ABT")
            equal(r["undef_frame"], 0, "no unexpected UNDEF")
        else:
            equal((r["dfsr"], r["dfar"], r["abort_frame"]), (0, 0, 0), "UNDEF is not a fabricated data abort")
            check_stack(r["undef_frame"], symbols, "__undef_stack", 4096, "UND")
        for field in ("primary_attempts", "primary_return", "primary_svc_lr", "primary_svc_psr",
                      "primary_svc_opcode", "primary_number", "primary_pointer", "primary_length",
                      "primary_copy_length", "primary_copy_hash", "primary_handler_psr", "primary_frame"):
            equal(r[field], 0, field + " absent before hardware fault")
        equal((r["primary_user_return"], r["primary_user_psr"], r["primary_marker"]),
              (0xFFFFFFFF,) * 3, "fault terminated before user post-SVC stores")
        primary_instruction = fault_instruction
    else:
        expected_return = case["return"] & 0xFFFFFFFF
        equal(r["outcome"], 1, "primary returned through real user EXIT SVC")
        equal(r["primary_attempts"], 1, "one primary copy/policy attempt")
        equal((r["primary_return"], r["primary_user_return"]), (expected_return,) * 2,
              "kernel syscall result actually returned to User")
        equal(r["primary_user_psr"] & 0xFF, 0xD0, "User resumed after syscall")
        equal(r["primary_svc_psr"] & 0xFF, 0xD0, "primary SVC captured User mode")
        equal(r["primary_handler_psr"] & 0xFF, 0xD3, "primary SVC handler is privileged")
        check_stack(r["primary_frame"], symbols, "__stack", 16384, "SVC")
        equal(r["primary_marker"], 90 if selector == 16 else 0,
              "explicit ARMv5 no-XN control marker")
        pointer, length = {
            6: (0, 15), 7: (symbols["KERNEL_CANARY"], 4),
            8: (USER_GUARD - 4, 8), 9: (USER_DATA, 65),
            10: (0xFFFFFFF0, 32), 11: (USER_GUARD, 0),
            17: (USER_CODE, 4), 18: (USER_DATA + 0x80, 64), 19: (0, 0),
        }.get(selector, (USER_DATA, 15))
        equal((r["primary_pointer"], r["primary_length"]), (pointer, length), "actual untrusted syscall arguments")
        equal(r["primary_number"], 0xFFFF if selector == 5 else 1, "actual untrusted syscall number")
        syscall_opcode = 0xEF000001 if selector == 14 else 0xEF000000
        symbol = "user_bad_svc" if selector == 14 else "user_copy_svc"
        primary_instruction = check_instruction(memory, loads, r["primary_svc_lr"] - 4,
                                                 symbols[symbol], syscall_opcode)
        equal(r["primary_svc_opcode"], syscall_opcode, "actual SVC immediate")
        data = bytes(range(64)) if selector == 18 else b"" if selector == 11 else PAYLOAD
        equal((r["primary_copy_length"], r["primary_copy_hash"]),
              (len(data), fnv32(data)) if primary_success else (0, 0),
              "copy length/hash; rejected arguments never copied")
        for field in ("fault_kind", "fault_lr", "fault_psr", "dfsr", "dfar", "fault_opcode",
                      "fault_handler_psr", "abort_frame", "undef_frame"):
            equal(r[field], 0, field + " no unexpected CPU fault")
    return {"result": "PASS", "primary_instruction": primary_instruction,
            "recovery_instruction": recovery_instruction,
            "kernel_canary_ram_verified": True, "copy_guard_ram_verified": True,
            "recovery_user_resumed_after_copy": True,
            "code_sha256": check_user_code(memory, loads),
            "page_tables": check_page_tables(memory, symbols, symbols["_start"])}


def run_case(qemu, selector, image, loads, image_hashes, out):
    directory = out / f"case-{selector:02d}"
    directory.mkdir(parents=True, exist_ok=True)
    result_path = directory / "result.json"
    result_path.write_text(json.dumps({"result": "FAIL", "error": "case not completed"}) + "\n")
    symbols = image["symbols"]
    result = {"result": "FAIL", "selector": selector, "name": CASES[selector]["name"],
              "machine": MACHINE, "image_sha256": image_hashes, "boots": []}
    image_dir = ROOT / "target/artifacts/security/image"
    with tempfile.TemporaryDirectory(prefix="crosshair-security-") as temp:
        qmp_path, memory_path = Path(temp) / "qmp", Path(temp) / "memory"
        command = [qemu, "-machine", MACHINE, "-cpu", "pxa260", "-accel", "tcg", "-S",
                   "-display", "none", "-monitor", "none", "-serial", "stdio", "-nic", "none",
                   "-device", f"loader,file={image_dir / 'crosshair-security.elf'},cpu-num=0",
                   "-qmp", f"unix:{qmp_path},server=on,wait=off",
                   "-qtest", f"unix:{memory_path},server=on,wait=off", "-qtest-log", str(directory / "memory-server.log"),
                   "-d", "guest_errors"]
        result["command"] = command
        uart_path = directory / "qemu-uart.log"
        with uart_path.open("wb") as uart, (directory / "qemu-stderr.log").open("wb") as stderr, (directory / "memory-protocol.log").open("w") as transcript:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=uart, stderr=stderr)
            qmp = memory = None
            try:
                qmp = Qmp(qmp_path, process)
                memory = QTest(memory_path, process, transcript)
                for boot in range(2):
                    deadline = time.monotonic() + 3
                    while register(qmp.monitor("info registers"), "R15") != image["entry"]:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("reset did not restore the actual ELF entry")
                        time.sleep(0.001)
                    equal(register(qmp.monitor("info registers"), "PSR") & 0xFF, 0xD3, "reset privileged ARM")
                    bss_size = symbols["__bss_end"] - symbols["__bss_start"]
                    memory.request(f"memset {symbols['__bss_start']:#x} {bss_size} 0xa5")
                    record_address = symbols["CROSSHAIR_SECURITY_RECORD"]
                    equal(memory.readl(record_address + 4), 0xA5A5A5A5, "BSS stage poison after loader/reset")
                    for prefix, size in (("__stack", 16384), ("__irq_stack", 4096), ("__abort_stack", 4096), ("__undef_stack", 4096)):
                        equal(symbols[prefix + "_top"] - symbols[prefix + "_bottom"], size, "banked stack allocation")
                        memory.request(f"memset {symbols[prefix + '_bottom']:#x} {size} 0xcd")
                    memory.request("memset 0xa0700000 256 0xa7")
                    memory.request("memset 0xa0202000 4096 0x6d")
                    memory.writel(MAILBOX, selector)
                    equal(memory.readl(MAILBOX), selector, "own host case mailbox")
                    qmp.request("cont")
                    wait_uart(process, uart_path, PASS * (boot + 1), 8)
                    qmp.request("stop")
                    registers = settle_idle(qmp, symbols["kernel_idle"])
                    equal(register(registers, "R15"), symbols["kernel_idle"], "actual terminal branch")
                    values = words(memory, record_address, len(FIELDS))
                    r = dict(zip(FIELDS, values))
                    verification = check_case(memory, loads, symbols, selector, r, registers)
                    equal(read_bytes(memory, 0xA0700000, 256), b"\xA7" * 256, "remote ordinary RAM sentinel")
                    equal(read_bytes(memory, 0xA0202000, 4096), b"\x6D" * 4096, "unmapped physical user guard page untouched")
                    result["boots"].append({"boot": boot + 1, "pre_entry_stage": 0xA5A5A5A5,
                                             "record": r, "registers": registers, "verification": verification})
                    if boot == 0:
                        qmp.request("system_reset")
                equal(uart_path.read_bytes(), PASS * 2, "exact guest UART, no leaked MMIO byte")
                qmp.request("quit")
                process.wait(timeout=3)
                equal(process.returncode, 0, "QEMU clean exit")
                result["uart_utf8"] = uart_path.read_text()
                result["result"] = "PASS"
            except Exception as error:
                result.update(result="FAIL", error=f"{type(error).__name__}: {error}")
                if qmp and memory and process.poll() is None:
                    try:
                        qmp.request("stop")
                        result["failure_registers"] = qmp.monitor("info registers")
                        result["failure_record"] = dict(zip(FIELDS, words(memory, symbols["CROSSHAIR_SECURITY_RECORD"], len(FIELDS))))
                    except Exception:
                        pass
                raise
            finally:
                try:
                    if memory: memory.close()
                    if qmp: qmp.close()
                    stop_process(process)
                finally:
                    result_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--qemu", default=os.environ.get("QEMU_E2B", str(ROOT / "local/qemu-e2b/bin/qemu-system-arm")))
    parser.add_argument("--case", type=int, choices=range(24), help="Run one independently verified case (two boots)")
    args = parser.parse_args()
    out = ROOT / "target/artifacts/security-tests"
    out.mkdir(parents=True, exist_ok=True)
    result_path = out / "result.json"
    result_path.write_text(json.dumps({"result": "FAIL", "error": "test not completed"}) + "\n")
    result = {"result": "FAIL", "machine": MACHINE,
              "scope": "functional ARMv5 User/SVC and MMU isolation on synthetic E2B; no physical security certification",
              "cases": []}
    try:
        equal(len(FIELDS), 72, "fixed record ABI")
        image_dir = ROOT / "target/artifacts/security/image"
        image = json.loads((image_dir / "image.json").read_text())
        names = {"crosshair-security.elf", "crosshair-security.bin", "vectors.bin"}
        equal(set(image["sha256"]), names, "complete security image manifest")
        hashes = {name: digest((image_dir / name).read_bytes()) for name in names}
        equal(hashes, image["sha256"], "current image files match manifest")
        entry, loads = elf_loads(image_dir / "crosshair-security.elf")
        equal(entry, image["entry"], "actual ELF entry")
        equal(image["symbols"]["security_user_start"], USER_CODE_PA, "user ELF physical start")
        record_address = image["symbols"]["CROSSHAIR_SECURITY_RECORD"]
        equal(image["symbols"]["__bss_start"] <= record_address and record_address + 72 * 4 <= image["symbols"]["__bss_end"],
              True, "complete record resides in poisoned BSS")
        result.update(image_sha256=hashes, qemu_version=qemu_version(args.qemu),
                      qemu_sha256=digest(Path(shutil.which(args.qemu) or args.qemu).read_bytes()))
        selections = list(CASES) if args.case is None else [args.case]
        for selector in selections:
            observed = run_case(args.qemu, selector, image, loads, hashes, out)
            result["cases"].append({"selector": selector, "name": observed["name"], "result": observed["result"],
                                    "boots": len(observed["boots"]), "evidence": f"case-{selector:02d}/result.json"})
            print(f"PASS security case{selector:02d}: {CASES[selector]['name']} + healthy User recovery, reset/reboot")
        equal(len(result["cases"]), len(selections), "all selected cases freshly completed")
        result.update(result="PASS", case_count=len(selections), boots=sum(c["boots"] for c in result["cases"]),
                      complete_suite=args.case is None,
                      armv5_limitations=["No XN/W^X guarantee; case16 executes own benign code from RW data",
                                         "DFSR.WnR absent on this ARMv5 CPU; LDR/STR proved from actual opcode"],
                      source_sha256={str(path.relative_to(ROOT)): digest(path.read_bytes()) for path in
                                     (ROOT / "src/security.rs", ROOT / "src/security_policy.rs", ROOT / "src/arch/security_entry.S",
                                      ROOT / "link/security.ld", ROOT / "tools/smoke_security.py", ROOT / "scripts/test-security.sh")})
    except Exception as error:
        result.update(result="FAIL", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        result_path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"PASS security: {result['case_count']} cases, {result['boots']} boots, precise exceptions/policy rejections, actual healthy User SVC recovery")


if __name__ == "__main__":
    main()
