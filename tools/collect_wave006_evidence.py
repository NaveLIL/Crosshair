#!/usr/bin/env python3
"""Verify complete Wave006 execution and collect normalized text evidence.

No guests are executed, images rebuilt, binaries published, or accepted Wave005
reports replaced. Source/image/runtime hashes and independently captured TCG
case records are required before any output is written. Detailed local memory
protocols are retained by byte count/hash rather than copied into reports.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE_REF = "d7f39d7968bd5163e908abe8911ca05e960eefd2"
PASS_UART = "CROSSHAIR TASKS — PREEMPTION COMPLETE\r\n".encode()
TASK_SENTINEL = ("PASS tasks: 8 scenarios, 16 ARM TCG boots; real Busy Loop IRQ "
                 "preemption and task fault isolation")
SECURITY_SENTINEL = ("PASS security: 24 cases, 48 boots, precise exceptions/policy "
                     "rejections, actual healthy User SVC recovery")
# All executable, compiler/linker configuration and observer dependencies used by
# the task suite must be recorded by its harness, not added after execution.
TESTED_SOURCES = (
    "Cargo.toml", "Cargo.lock", "build.rs", ".cargo/config.toml", "rust-toolchain.toml",
    "src/tasks.rs", "src/arch/tasks_entry.S", "src/arch/task_workloads.S",
    "src/task_runtime/mod.rs", "src/task_runtime/context.rs", "src/task_runtime/memory.rs",
    "src/task_runtime/scheduler.rs", "src/task_runtime/syscall.rs", "src/security_policy.rs",
    "src/drivers/pxa_uart.rs", "link/tasks.ld",
    "scripts/build-tasks.sh", "scripts/test-tasks.sh", "scripts/test-wave006.sh",
    "tools/smoke_tasks.py", "tools/verify_image.py", "tools/qemu_control.py",
    "tools/qtest_pxa.py", "tools/smoke_e2a.py", "tools/smoke_security.py",
)
spec = importlib.util.spec_from_file_location("public_export", ROOT / "scripts/export-public.py")
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, label):
    if not condition:
        raise ValueError(label)


def read_json(path):
    return json.loads(path.read_text())


def git_bytes(revision, name):
    return subprocess.check_output(["git", "-C", str(ROOT), "show", revision + ":" + name])


def checked_hash(path, expected):
    require(path.is_file(), "Missing required file: " + str(path))
    require(sha(path.read_bytes()) == expected, "Hash mismatch: " + str(path))


def check_image(directory, image):
    """Bind the manifest's segments and flat payload to actual bounded ELF32."""
    require(set(image["sha256"]) == {"crosshair-tasks.elf", "crosshair-tasks.bin", "vectors.bin"},
            "Unexpected task image manifest contents")
    for name, expected in image["sha256"].items():
        checked_hash(directory / name, expected)
    data = (directory / "crosshair-tasks.elf").read_bytes()
    require(len(data) >= 52 and data[:7] == b"\x7fELF\x01\x01\x01", "Need bounded ELF32 little-endian image")
    fields = struct.unpack_from("<HHIIIIIHHHHHH", data, 16)
    kind, machine, _, entry, phoff, _, flags, _, phsize, phnum, *_ = fields
    require((kind, machine, entry, flags) == (2, 40, image["entry"], image["flags"]), "ELF header/manifest mismatch")
    require(flags >> 24 == 5 and not flags & 0x400, "Need ARM EABI5 without hard-float ABI")
    require(phsize == 32 and phoff + phsize * phnum <= len(data), "ELF program headers out of bounds")
    flat, vectors = (directory / "crosshair-tasks.bin").read_bytes(), (directory / "vectors.bin").read_bytes()
    segments, payloads = [], {}
    for index in range(phnum):
        ptype, offset, va, pa, filesz, memsz, perm, _ = struct.unpack_from("<IIIIIIII", data, phoff + index * phsize)
        require(ptype not in (2, 3), "No dynamic ELF interpreter/runtime permitted")
        if ptype != 1:
            continue
        require(va == pa and filesz <= memsz and offset + filesz <= len(data) and pa + memsz <= 2**32,
                "ELF load segment out of bounds")
        payload = data[offset:offset + filesz]
        if pa == 0:
            require((filesz, memsz, perm, payload) == (64, 64, 5, vectors), "Vector payload mismatch")
        elif filesz:
            require(pa >= entry and flat[pa - entry:pa - entry + filesz] == payload, "Flat/ELF load mismatch")
        segments.append(dict(pa=pa, filesz=filesz, memsz=memsz, flags=perm))
        payloads[pa] = payload
    require(segments == image["segments"], "ELF segment manifest is stale")
    require(len(flat) == max(s["pa"] + s["filesz"] for s in segments if s["pa"] >= entry and s["filesz"]) - entry,
            "Flat extent mismatch")
    for base in (0xA0200000, 0xA0300000):
        matches = [s for s in segments if s["pa"] == base]
        require(len(matches) == 1 and matches[0]["flags"] == 5 and 0 < matches[0]["memsz"] <= 4096,
                "Need distinct bounded RX User code segments")
    return payloads


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--artifacts", type=Path, default=ROOT / "target/artifacts")
    parser.add_argument("--qemu-cache", type=Path, default=ROOT / "local/qemu-e2b")
    parser.add_argument("--llvm", type=Path, required=True, help="Pinned toolchain directory containing llvm-nm/readobj/objdump/size")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/wave006")
    parser.add_argument("--check-only", action="store_true", help="Validate every input without writing reports")
    args = parser.parse_args()
    artifacts, output = args.artifacts.resolve(), args.output.resolve()
    base = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", BASE_REF + "^{commit}"], text=True).strip()
    require(base == BASE_REF, "Expected accepted Wave005 base is unavailable")
    subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", base, "HEAD"], check=True)
    require(output == ROOT / "reports/wave006" or not output.is_relative_to(ROOT / "reports/wave005"),
            "Cannot replace accepted Wave005 evidence")
    copies, statuses, local_protocols = {}, {}, {}

    def add(relative, source):
        export.safe_name("reports/wave006/" + relative)
        require(relative not in copies and source.is_file(), "Duplicate or missing evidence: " + relative)
        copies[relative] = source
        report = read_json(source) if source.suffix == ".json" else {}
        if "result" in report:
            require(report["result"] in ("PASS", "PASS_WITH_RECORDED_MODEL_LIMITATIONS"),
                    "Cannot collect failed evidence: " + relative)
            statuses[relative] = report["result"]

    accepted = json.loads(git_bytes(base, "reports/wave005/validation.json"))
    require(read_json(ROOT / "reports/wave005/validation.json") == accepted, "Accepted Wave005 validation changed")
    for name, expected in accepted["copied_evidence_sha256"].items():
        checked_hash(ROOT / "reports/wave005" / name, expected)
    baseline = dict(accepted["unchanged_baseline_source_sha256"])
    baseline.update({name: expected for name, expected in accepted["source_sha256"].items()
                     if name not in ("Cargo.toml", "build.rs")})
    # Include inherited boot guest/linker inputs not enumerated by the previous
    # collector; their flat outputs are checked independently below as well.
    for name in ("src/main.rs", "src/arch/entry.S", "src/bsp/blueangel.rs", "src/bsp/versatilepb.rs",
                 "src/drivers/mod.rs", "src/drivers/pl011.rs", "src/drivers/pxa_uart.rs",
                 "scripts/env.sh", "link/sections.ld", "link/blueangel.ld", "link/versatilepb.ld", "link/pxa-reference.ld", "link/e2b.ld"):
        baseline[name] = sha(git_bytes(base, name))
    for name, expected in baseline.items():
        require(sha(git_bytes(base, name)) == expected, "Accepted source manifest mismatch: " + name)
        checked_hash(ROOT / name, expected)

    summary_path = artifacts / "tasks-tests/result.json"
    summary = read_json(summary_path)
    require((summary["result"], summary["complete_suite"], summary["case_count"], summary["boots"])
            == ("PASS", True, 8, 16), "Need complete fresh 8-case/16-boot task PASS")
    require((summary["machine"], summary["accelerator"]) == ("crosshair-blueangel-e2b", "tcg"), "Wrong task execution platform")
    require([case["selector"] for case in summary["cases"]] == list(range(8)), "Incomplete/duplicate task selectors")
    require(set(TESTED_SOURCES) <= set(summary["source_sha256"]), "Task suite did not bind all executable/build/observer sources")
    for name, expected in summary["source_sha256"].items():
        require(not Path(name).is_absolute() and ".." not in Path(name).parts, "Invalid source hash path")
        checked_hash(ROOT / name, expected)
    image_dir = artifacts / "tasks/image"
    image = read_json(image_dir / "image.json")
    symbols = image["symbols"]
    require(summary["image_sha256"] == image["sha256"], "Task suite/image manifest mismatch")
    code_payloads = check_image(image_dir, image)
    # Regenerate the three text reports read-only from the hashed ELF. This
    # rejects stale disassembly/size/header evidence without rebuilding it.
    commands = {
        "disassembly.txt": ("llvm-objdump", "-d"),
        "elf-report.txt": ("llvm-readobj", "--file-headers", "--program-headers", "--arch-specific"),
        "size.txt": ("llvm-size",),
    }
    for name, command in commands.items():
        fresh = subprocess.check_output([str(args.llvm / command[0]), *command[1:], str(image_dir / "crosshair-tasks.elf")])
        require((image_dir / name).read_bytes() == fresh, "Stale image text report: " + name)
    actual_symbols = {}
    nm = subprocess.check_output([str(args.llvm / "llvm-nm"), "--defined-only", "--format=posix", str(image_dir / "crosshair-tasks.elf")], text=True)
    for line in nm.splitlines():
        fields = line.split()
        if len(fields) >= 3:
            actual_symbols[fields[0]] = int(fields[2], 16)
    require(actual_symbols == image["symbols"], "ELF symbol manifest is stale")
    runtime = (args.qemu_cache / "bin/qemu-system-arm").resolve()
    build = read_json(args.qemu_cache / "evidence/source.json")
    accepted_build = json.loads(git_bytes(base, "crosshair-emulator/evidence/e2b/build/source.json"))
    runtime_hash = sha(runtime.read_bytes())
    require(build == accepted_build and runtime_hash == summary["qemu_sha256"] == accepted["security"]["qemu_sha256"] == build["qemu_sha256"],
            "Task suite must use unchanged accepted E2B runtime/build")
    checked_hash(ROOT / "crosshair-emulator/qemu/crosshair-blueangel-e2b.c", build["overlay_sha256"])
    checked_hash(ROOT / "crosshair-emulator/qemu/crosshair-blueangel-e2a.c", build["included_e2a_sha256"])
    add("tasks/result.json", summary_path)
    for entry in summary["cases"]:
        selector = entry["selector"]
        relative = f"case-{selector:02d}"
        require(entry["evidence"] == relative + "/result.json", "Unexpected task case path")
        directory = artifacts / "tasks-tests" / relative
        case = read_json(directory / "result.json")
        require((entry["result"], entry["boots"], case["result"], case["selector"])
                == ("PASS", 2, "PASS", selector), "Task case/suite status mismatch")
        require(case["name"] == entry["name"] and case["image_sha256"] == image["sha256"], "Task case identity/image mismatch")
        require((case["machine"], case["accelerator"]) == ("crosshair-blueangel-e2b", "tcg"), "Case platform mismatch")
        require(Path(case["command"][0]).resolve() == runtime, "Case used another QEMU runtime")
        require(len(case["boots"]) == 2 and [boot["boot"] for boot in case["boots"]] == [1, 2], "Missing actual reset/reboot records")
        for boot in case["boots"]:
            r, tasks, verified = boot["record"], boot["tasks"], boot["verification"]
            require((boot["pre_entry_poison"], r["magic"], r["version"], r["stage"], r["error"], r["scenario"])
                    == (0xA5A5A5A5, 0x5441534B, 1, 3, 0, selector), "Invalid task BSS/terminal record")
            require((r["sctlr"], r["dacr"], r["pid"], r["canary_ok"], r["current"], r["pic_mask_final"], r["timer_oier_final"], r["timer_ossr_final"])
                    == (0x79, 1, 0, 1, 0xFFFFFFFF, 0, 0, 0), "Kernel MMU/timer/control invariant failed")
            require(len(tasks) == 2 and [task["id"] for task in tasks] == [1, 2] and all(task["dispatches"] > 0 for task in tasks), "Tasks did not both execute")
            require(r["tlb_switches"] == sum(task["dispatches"] for task in tasks), "Missing address-space switch evidence")
            require(r["ticks"] == r["irq_from_a"] + r["irq_from_b"] and tasks[0]["preemptions"] >= 2, "Missing real Busy Loop IRQ preemption")
            require(all(context["register_sentinels_verified"] for context in verified["contexts"]) and len(verified["contexts"]) == 2,
                    "Missing context/register verification")
            require(all(data["counter"] > 0 and data["workload_error"] == 0 for data in verified["user_data"]) and len(verified["user_data"]) == 2,
                    "Missing both actual User workloads' progress")
            require(tasks[1]["copies"] > 0, "Healthy User SVC did not run")
            busy = verified["code"]["busy_no_svc"]
            begin, end = symbols["task_a_busy"], symbols["task_a_busy_end"]
            require(0xA0200000 <= begin < end <= 0xA0200000 + len(code_payloads[0xA0200000])
                    and begin % 4 == end % 4 == 0, "Busy Loop ELF instruction bounds invalid")
            busy_bytes = code_payloads[0xA0200000][begin - 0xA0200000:end - 0xA0200000]
            require((busy["physical_start"], busy["physical_end"], busy["instruction_words"], busy["sha256"])
                    == (begin, end, len(busy_bytes) // 4, sha(busy_bytes)), "Busy Loop inspection differs from immutable ELF")
            require(all(word & 0x0F000000 not in (0x0F000000, 0x0B000000)
                        for (word,) in struct.iter_unpack("<I", busy_bytes)), "Busy Loop contains SVC or branch-with-link")
            for index, base_pa in enumerate((0xA0200000, 0xA0300000)):
                code = verified["code"]["code_pages"][index]
                require((code["task"], code["physical"], code["bytes"], code["sha256"])
                        == (index, base_pa, len(code_payloads[base_pa]), sha(code_payloads[base_pa])), "Executed User code differs from hashed ELF")
            if selector in (1, 2, 3, 4, 5, 7):
                require([task["state"] for task in tasks] == [3, 0] and "fault" in verified
                        and r["ticks"] >= r["fault_tick"] + 8, "Missing healthy progress after task fault")
                require(verified["user_data"][1]["counter"] > r["healthy_counter_at_fault"],
                        "Healthy User did not advance beyond the actual fault snapshot")
            elif selector == 6:
                require([task["state"] for task in tasks] == [2, 2] and r["terminal_reason"] == 2, "Missing actual Exit/Idle lifecycle")
            else:
                require([task["state"] for task in tasks] == [0, 0] and tasks[0]["svc_count"] == 0 and r["ticks"] >= 12,
                        "Missing noncooperative Busy Loop acceptance control")
            checkpoint = boot["live_checkpoint"]
            if selector == 6:
                require(checkpoint is None, "Exited lifecycle case has an unexpected live checkpoint")
            else:
                require(checkpoint["record"]["stage"] == 2 and checkpoint["record"]["ticks"] < r["ticks"]
                        and checkpoint["record"]["scenario"] == selector
                        and len(checkpoint["user_counters"]) == 2,
                        "Missing independent live QMP midpoint before terminal completion")
                require(verified["user_data"][1]["counter"] > checkpoint["user_counters"][1],
                        "Healthy task did not advance after the independent live midpoint")
                if selector == 0:
                    require(verified["user_data"][0]["counter"] > checkpoint["user_counters"][0],
                            "Busy Loop did not advance after the independent live midpoint")
                else:
                    require(checkpoint["tasks"][0]["state"] == 3
                            and checkpoint["user_counters"][1] > r["healthy_counter_at_fault"],
                            "Live midpoint did not observe healthy execution after companion fault")
        require((directory / "qemu-uart.log").read_bytes() == PASS_UART * 2, "Unexpected actual task UART bytes")
        for name in ("result.json", "qemu-uart.log", "qemu-stderr.log"):
            add("tasks/" + relative + "/" + name, directory / name)
        for name in ("memory-protocol.log", "memory-server.log"):
            path = directory / name
            require(path.is_file() and path.stat().st_size > 0, "Missing actual local observer protocol: " + relative)
            local_protocols["tasks-tests/" + relative + "/" + name] = {"bytes": path.stat().st_size, "sha256": sha(path.read_bytes())}
    for name in ("image.json", "size.txt", "elf-report.txt", "disassembly.txt"):
        add("image/" + name, image_dir / name)
    for name in ("source.json", "version.txt", "machines.txt", "cpus.txt", "host-tools.txt", "resolved-devices.mak", "loader.txt"):
        add("build/" + name, args.qemu_cache / "evidence" / name)

    log_path = artifacts / "wave006/all-tests.log"
    log = log_path.read_text()
    require(log.rstrip().endswith(TASK_SENTINEL) and SECURITY_SENTINEL in log, "Full-suite log lacks terminal security/tasks success")
    require(sorted(re.findall(r"^PASS tasks case(\d\d):", log, re.M)) == [f"{i:02d}" for i in range(8)], "Full-suite log must contain each task case exactly once")
    require(sorted(re.findall(r"^PASS security case(\d\d):", log, re.M)) == [f"{i:02d}" for i in range(24)], "Full-suite log must contain each security case exactly once")
    add("all-tests.log", log_path)
    for board in ("versatilepb", "versatilepb-panic"):
        add("regressions/" + board + ".json", artifacts / board / "smoke-test.json")
    for board in ("connex", "verdex", "mainstone"):
        add(f"regressions/e1-{board}-tcg.json", artifacts / "pxa-reference" / board / "smoke-test.json")
        add(f"regressions/e1-{board}-qtest.json", artifacts / "pxa-qtest" / board / "qtest-result.json")
    for wave, scenarios in (("e2a", ("boot-reset", "fault-1", "fault-2", "fault-3", "fault-4")),
                            ("e2b", ("gpio-boot-reset", "fault-1", "fault-2", "fault-3", "fault-4", "fault-5"))):
        for scenario in scenarios:
            add(f"regressions/{wave}-{scenario}.json", artifacts / (wave + "-tests") / scenario / "result.json")
        add(f"regressions/{wave}-qtest.json", artifacts / (wave + "-qtest") / "result.json")
    for relative, local in (("display-execution.json", "display-test/execution/result.json"),
                            ("display-qtest.json", "display-qtest/result.json"),
                            ("missing-reference-check.json", "wave004/missing-reference-check.json"),
                            ("ui-validation.json", "ui/validation.json"), ("ui-tests.log", "ui/tests.log"),
                            ("ui-memory-layout.json", "ui/memory-layout.json")):
        add("regressions/" + relative, artifacts / local)
    security = read_json(artifacts / "security-tests/result.json")
    require((security["result"], security["complete_suite"], security["case_count"], security["boots"])
            == ("PASS", True, 24, 48), "Incomplete current Security regression")
    require([case["selector"] for case in security["cases"]] == list(range(24)), "Incomplete current Security case selectors")
    require(security["qemu_sha256"] == runtime_hash and security["image_sha256"] == read_json(artifacts / "security/image/image.json")["sha256"], "Security runtime/image mismatch")
    for name, expected in security["source_sha256"].items():
        checked_hash(ROOT / name, expected)
    add("regressions/security-result.json", artifacts / "security-tests/result.json")
    for entry in security["cases"]:
        path = artifacts / "security-tests" / entry["evidence"]
        case = read_json(path)
        require(entry["result"] == case["result"] == "PASS" and entry["boots"] == len(case["boots"]) == 2
                and case["image_sha256"] == security["image_sha256"], "Incomplete current Security case")
        add(f"regressions/security-case-{entry['selector']:02d}.json", path)
    ui = read_json(artifacts / "ui/validation.json")
    for name, expected in ui["source_sha256"].items():
        checked_hash(ROOT / name, expected)
    for name, expected in ui["artifacts_sha256"].items():
        checked_hash(artifacts / "ui" / name, expected)
    display = read_json(artifacts / "display-test/execution/result.json")
    require(display["pixel_comparisons"] == 23 and sum(boot["events"] for boot in display["boots"]) == 101, "Incomplete display regression")
    flat_hashes = dict(accepted["unchanged_baseline_flat_image_sha256"])
    for name, expected in accepted["security"]["image_sha256"].items():
        if not name.endswith(".elf"):
            flat_hashes["security/image/image.json:" + name] = expected
    for key, expected in flat_hashes.items():
        manifest_name, filename = key.split(":", 1)
        manifest = read_json(artifacts / manifest_name)
        require(manifest["sha256"][filename] == expected, "Baseline flat manifest changed: " + key)
        checked_hash((artifacts / manifest_name).parent / filename, expected)

    memory = dict(summary["memory"])
    symbols = image["symbols"]
    kernel = symbols["__image_end"] - image["entry"]
    require(memory["kernel_start"] == image["entry"] and memory["kernel_end"] == symbols["__image_end"]
            and memory["kernel_reserved_extent_bytes"] == kernel and memory["vectors_bytes"] == 64
            and memory["page_tables_total_bytes"] == 34816 and memory["task_table_bytes"] == 288, "Task RAM accounting differs from linked allocation")
    for prefix, size in memory["banked_stacks_bytes"].items():
        require(size == symbols[prefix + "_top"] - symbols[prefix + "_bottom"], "Stack RAM accounting mismatch")
    per_task = memory["per_task"]
    require((per_task["context_bytes"], per_task["task_metadata_and_context_bytes"], per_task["l1_bytes"], per_task["l2_bytes"],
             per_task["diagnostic_copy_bytes"], per_task["kernel_task_overhead_bytes"], per_task["user_mapped_bytes"],
             per_task["user_reserved_extent_bytes"], per_task["guard_reserved_unmapped_bytes"])
            == (80, 144, 16384, 1024, 64, 17616, 12288, 16384, 4096), "Per-task RAM accounting mismatch")
    memory.update(total_mapped_working_ram_bytes=kernel + 2 * 12288 + 64,
                  total_reserved_extent_bytes=kernel + 2 * 16384 + 64,
                  flat_file_bytes=(image_dir / "crosshair-tasks.bin").stat().st_size,
                  elf_file_bytes=(image_dir / "crosshair-tasks.elf").stat().st_size)
    payloads, copied, original_hashes = {}, {}, {}
    for relative, source in copies.items():
        original = source.read_bytes()
        # Normalize explicit cache/artifact paths first, then source/parent
        # paths and generic host paths. UART must remain byte-exact.
        text = original.decode("utf8")
        for path, replacement in ((args.qemu_cache.resolve(), "<qemu-cache>"), (artifacts, "<artifacts>"), (ROOT, "<workspace>")):
            text = text.replace(str(path), replacement)
        text = export.normalize(text, ROOT.parent.parent)
        require(not (export.PRIVATE_PATH.search(text) or export.LOCAL_HOST.search(text) or export.SECRET.search(text)), "Private material in evidence: " + relative)
        payload = text.encode("utf8")
        if source.name == "qemu-uart.log":
            require(payload == original, "UART normalization would change actual guest bytes")
        payloads[relative], copied[relative] = payload, sha(payload)
        original_hashes[relative] = {"bytes": len(original), "sha256": sha(original)}
    validation = {
        "result": "PASS", "accepted_base": base,
        "scope": "8 scenarios / 16 ARM TCG boots; two fixed isolated User tasks and hardware timer preemption on unchanged synthetic E2B; no PXA263 hardware validation",
        "normalization": "host/cache/workspace/socket paths and hostnames only; UART byte-exact",
        "tasks": {"result": "PASS", "complete_suite": True, "cases": 8, "boots": 16,
                  "image_sha256": image["sha256"], "qemu_sha256": runtime_hash},
        "memory": memory, "results": statuses,
        "source_sha256": summary["source_sha256"],
        "collector_source_sha256": {"tools/collect_wave006_evidence.py": sha(Path(__file__).read_bytes()), "scripts/export-public.py": sha((ROOT / "scripts/export-public.py").read_bytes())},
        "intentional_baseline_source_changes": ["Cargo.toml", "build.rs"],
        "unchanged_baseline_source_sha256": baseline,
        "unchanged_baseline_flat_image_sha256": flat_hashes,
        "accepted_wave005_validation_sha256": sha(git_bytes(base, "reports/wave005/validation.json")),
        "copied_evidence_sha256": copied, "original_evidence": original_hashes,
        "local_protocols": local_protocols,
    }
    payloads["validation.json"] = (json.dumps(validation, indent=2) + "\n").encode()
    if output.exists():
        existing = {str(path.relative_to(output)) for path in output.rglob("*") if path.is_file()}
        require(existing <= set(payloads), "Refusing evidence directory with unexpected files")
        if args.check_only:
            require(existing == set(payloads), "Collected evidence directory is incomplete")
            for relative, payload in payloads.items():
                require((output / relative).read_bytes() == payload, "Collected evidence differs from verified inputs: " + relative)
    if not args.check_only:
        for relative, payload in payloads.items():
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
    print(f"Verified 8 cases / 16 boots; {len(baseline)} unchanged baseline sources, {len(flat_hashes)} unchanged flat outputs")
    print(f"RAM: mapped={memory['total_mapped_working_ram_bytes']}, reserved={memory['total_reserved_extent_bytes']} bytes; flat gap excluded")
    print(f"{'Validated' if args.check_only else 'Collected'} {len(payloads)} Wave006 text files, {sum(map(len, payloads.values()))} bytes; {len(local_protocols)} local protocols retained by hash")


if __name__ == "__main__":
    main()
