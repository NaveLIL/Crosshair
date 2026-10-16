#!/usr/bin/env python3
"""Collect verified Wave005 text evidence after the complete test run.

This does not execute guests, rebuild images, publish binaries or replace prior
accepted reports. Host paths are normalized using the publication exporter;
UART logs remain byte-exact. Detailed memory protocols stay under target/.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE_REF = "a509d2e"
PASS_UART = "CROSSHAIR SECURITY — USER ISOLATION PASS\r\n".encode()
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
    return subprocess.check_output(["/usr/bin/git", "-C", str(ROOT), "show", revision + ":" + name])


def checked_hash(path, expected):
    require(sha(path.read_bytes()) == expected, "Hash mismatch: " + str(path.relative_to(ROOT)))


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--qemu-cache", type=Path, default=ROOT / "local/qemu-e2b")
    parser.add_argument("--crypto-evidence", type=Path, required=True,
                        help="Directory containing the six proof_text logs declared in research/crypto-candidates.json")
    args = parser.parse_args()
    base = subprocess.check_output(["/usr/bin/git", "-C", str(ROOT), "rev-parse", BASE_REF], text=True).strip()
    artifacts, output = ROOT / "target/artifacts", ROOT / "reports/wave005"
    copies, statuses = {}, {}

    def add(relative, source):
        require(relative not in copies, "Duplicate evidence name: " + relative)
        require(source.is_file(), "Missing required evidence: " + str(source))
        copies[relative] = source
        report = read_json(source) if source.suffix == ".json" else {}
        if "result" in report:
            status = report["result"]
            require(status in ("PASS", "PASS_WITH_RECORDED_MODEL_LIMITATIONS"),
                    f"Cannot collect failed evidence: {relative}: {status}")
            statuses[relative] = status

    # Validate the complete latest security suite before selecting any files.
    summary = read_json(artifacts / "security-tests/result.json")
    require((summary["result"], summary["complete_suite"], summary["case_count"], summary["boots"])
            == ("PASS", True, 24, 48), "Need a complete fresh 24-case/48-boot PASS")
    require([case["selector"] for case in summary["cases"]] == list(range(24)), "Incomplete/duplicate case selectors")
    for name, expected in summary["source_sha256"].items():
        checked_hash(ROOT / name, expected)
    image_dir = artifacts / "security/image"
    image = read_json(image_dir / "image.json")
    require(summary["image_sha256"] == image["sha256"], "Suite/image manifest mismatch")
    require(set(image["sha256"]) == {"crosshair-security.elf", "crosshair-security.bin", "vectors.bin"},
            "Unexpected image manifest contents")
    for name, expected in image["sha256"].items():
        checked_hash(image_dir / name, expected)
    runtime = args.qemu_cache / "bin/qemu-system-arm"
    build = read_json(args.qemu_cache / "evidence/source.json")
    runtime_hash = sha(runtime.read_bytes())
    accepted_build = json.loads(git_bytes(base, "crosshair-emulator/evidence/e2b/build/source.json"))
    require(summary["qemu_sha256"] == build["qemu_sha256"] == accepted_build["qemu_sha256"] == runtime_hash,
            "Security tests must use the unchanged accepted E2B runtime")
    checked_hash(ROOT / "crosshair-emulator/qemu/crosshair-blueangel-e2b.c", build["overlay_sha256"])
    checked_hash(ROOT / "crosshair-emulator/qemu/crosshair-blueangel-e2a.c", build["included_e2a_sha256"])
    add("security/result.json", artifacts / "security-tests/result.json")
    local_protocols = {}
    for entry in summary["cases"]:
        selector = entry["selector"]
        relative = f"case-{selector:02d}"
        require(entry["evidence"] == relative + "/result.json", "Unexpected case result path")
        directory = artifacts / "security-tests" / relative
        case = read_json(directory / "result.json")
        require((entry["result"], entry["boots"], case["result"], case["selector"])
                == ("PASS", 2, "PASS", selector), "Case/suite status mismatch")
        require(case["name"] == entry["name"] and case["image_sha256"] == image["sha256"], "Case identity/image mismatch")
        require(Path(case["command"][0]).resolve() == runtime.resolve(), "Case used a different QEMU runtime")
        require(len(case["boots"]) == 2 and [b["boot"] for b in case["boots"]] == [1, 2], "Need actual reset/reboot evidence")
        for boot in case["boots"]:
            record = boot["record"]
            require((boot["pre_entry_stage"], record["magic"], record["stage"], record["error"], record["selector"])
                    == (0xA5A5A5A5, 0x53454355, 5, 0, selector), "Invalid BSS/terminal record")
            require((record["recovery_ok"], record["kernel_resumes"], record["recovery_return"], record["recovery_user_return"])
                    == (1, 2, 15, 15), "Missing actual healthy-context recovery")
            require(record["case_count"] == 24 and boot["verification"]["result"] == "PASS", "Incomplete case verification")
        require((directory / "qemu-uart.log").read_bytes() == PASS_UART * 2, "Unexpected security UART bytes")
        for name in ("result.json", "qemu-uart.log", "qemu-stderr.log"):
            add("security/" + relative + "/" + name, directory / name)
        for name in ("memory-protocol.log", "memory-server.log"):
            path = directory / name
            require(path.is_file(), "Missing local protocol: " + relative + "/" + name)
            local_protocols[str(path.relative_to(ROOT))] = {"bytes": path.stat().st_size, "sha256": sha(path.read_bytes())}

    for name in ("image.json", "size.txt", "elf-report.txt", "disassembly.txt", "policy-host-tests.log"):
        add("image/" + name, image_dir / name)
    policy_log = (image_dir / "policy-host-tests.log").read_text()
    require("test result: ok. 2 passed; 0 failed" in policy_log, "Host copy-policy tests did not pass")
    for name in ("source.json", "version.txt", "machines.txt", "cpus.txt", "host-tools.txt", "resolved-devices.mak", "loader.txt"):
        add("build/" + name, args.qemu_cache / "evidence" / name)
    add("all-tests.log", artifacts / "wave005/all-tests.log")
    all_tests = (artifacts / "wave005/all-tests.log").read_text()
    require(all_tests.rstrip().endswith("PASS security: 24 cases, 48 boots, precise exceptions/policy rejections, actual healthy User SVC recovery"),
            "Full-run log lacks terminal complete-suite success")
    require(len(re.findall(r"^PASS security case\d\d:", all_tests, re.M)) == 24, "Full-run log must contain each fresh security case once")

    # Current full-run regressions, without replacing their accepted reports.
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
    add("regressions/display-execution.json", artifacts / "display-test/execution/result.json")
    add("regressions/display-qtest.json", artifacts / "display-qtest/result.json")
    add("regressions/missing-reference-check.json", artifacts / "wave004/missing-reference-check.json")
    add("regressions/ui-validation.json", artifacts / "ui/validation.json")
    add("regressions/ui-tests.log", artifacts / "ui/tests.log")
    add("regressions/ui-memory-layout.json", artifacts / "ui/memory-layout.json")

    accepted = json.loads(git_bytes(base, "reports/wave004/validation.json"))
    require(read_json(ROOT / "reports/wave004/validation.json") == accepted, "Accepted Wave004 evidence was modified")
    baseline = dict(accepted["unchanged_baseline_source_sha256"])
    baseline.update({name: expected for name, expected in accepted["source_sha256"].items()
                     if name not in ("Cargo.toml", "build.rs")})
    accepted_ui = json.loads(git_bytes(base, "reports/wave004/ui/validation.json"))
    baseline.update(accepted_ui["source_sha256"])
    for name, expected in baseline.items():
        require(sha(git_bytes(base, name)) == expected, "Accepted source manifest mismatch: " + name)
        checked_hash(ROOT / name, expected)
    # Also prove all current host UI references belong to the unchanged sources.
    ui = read_json(artifacts / "ui/validation.json")
    for name, expected in ui["source_sha256"].items():
        checked_hash(ROOT / name, expected)
        require(expected == accepted_ui["source_sha256"][name], "UI004 source changed: " + name)
    for name, expected in ui["artifacts_sha256"].items():
        checked_hash(artifacts / "ui" / name, expected)
    display = read_json(artifacts / "display-test/execution/result.json")
    require(display["pixel_comparisons"] == 23 and sum(b["events"] for b in display["boots"]) == 101,
            "Display regression is incomplete")

    flat_hashes = {}
    old_manifests = (
        ("reports/versatilepb/image.json", "versatilepb/image.json"),
        ("reports/versatilepb-panic/image.json", "versatilepb-panic/image.json"),
        ("reports/blueangel/image.json", "blueangel/image.json"),
        ("crosshair-emulator/evidence/pxa-reference/image.json", "pxa-reference/image.json"),
        ("crosshair-emulator/evidence/e2a/images/normal/image.json", "e2a/normal/image.json"),
        ("crosshair-emulator/evidence/e2a/images/mmio-test/image.json", "e2a/mmio-test/image.json"),
        ("crosshair-emulator/evidence/e2b/images/normal/image.json", "e2b/normal/image.json"),
        ("crosshair-emulator/evidence/e2b/images/negative-test/image.json", "e2b/negative-test/image.json"),
        ("reports/wave004/image/image.json", "display-test/image/image.json"),
    )
    for old_name, current in old_manifests:
        old = json.loads(git_bytes(base, old_name))
        now_path = artifacts / current
        now = read_json(now_path)
        for name, expected in old["sha256"].items():
            if not name.endswith(".elf"):
                require(now["sha256"][name] == expected, "Baseline flat manifest changed: " + current + ":" + name)
                checked_hash(now_path.parent / name, expected)
                flat_hashes[current + ":" + name] = expected
    for key, expected in accepted["unchanged_baseline_flat_image_sha256"].items():
        require(flat_hashes[key] == expected, "Wave004 baseline flat hash mismatch: " + key)

    crypto = read_json(ROOT / "research/crypto-candidates.json")
    require(len(crypto["proof_text"]) == 6, "Need all six declared crypto proof logs")
    crypto_checks = {}
    for proof in crypto["proof_text"]:
        name = proof["name"]
        require(Path(name).name == name and name.endswith((".txt", ".log")), "Unexpected crypto proof filename")
        source = args.crypto_evidence / name
        data = source.read_bytes()
        require((len(data), sha(data)) == (proof["bytes"], proof["sha256"]), "Crypto proof mismatch: " + name)
        add("crypto/" + name, source)
        crypto_checks[name] = {"bytes": len(data), "sha256": sha(data)}

    # Account for allocations, not the large sparse flat file's zero-filled gap.
    symbols = image["symbols"]
    kernel_bytes = symbols["__image_end"] - image["entry"]
    require(kernel_bytes == 78848, "Unexpected actual kernel RAM extent")
    require(symbols["security_user_start"] == 0xA0200000 and symbols["security_user_end"] <= 0xA0201000,
            "User payload does not fit its physical code page")
    require(any(s["pa"] == 0 and s["filesz"] == s["memsz"] == 64 for s in image["segments"]), "Need exactly 64 vector bytes")
    memory = {"kernel_ram_extent_bytes": kernel_bytes, "user_code_page_bytes": 4096,
              "user_data_page_bytes": 4096, "user_stack_page_bytes": 4096,
              "user_mapped_pages_bytes": 12288, "vectors_bytes": 64,
              "total_allocated_ram_bytes": kernel_bytes + 12288 + 64,
              "user_guard_page_mapped": False,
              "flat_file_bytes": (image_dir / "crosshair-security.bin").stat().st_size,
              "elf_file_bytes": (image_dir / "crosshair-security.elf").stat().st_size,
              "flat_gap_is_not_allocated_ram": True}
    require(memory["total_allocated_ram_bytes"] == 91200, "RAM accounting mismatch")

    payloads, copied = {}, {}
    for relative, source in copies.items():
        export.safe_name("reports/wave005/" + relative)
        original = source.read_bytes()
        text = export.normalize(original.decode("utf8"), ROOT)
        require(not (export.PRIVATE_PATH.search(text) or export.LOCAL_HOST.search(text) or export.SECRET.search(text)),
                "Private material in evidence: " + relative)
        payload = text.encode("utf8")
        if source.name == "qemu-uart.log":
            require(payload == original, "UART normalization would alter guest bytes")
        payloads[relative] = payload
        copied[relative] = sha(payload)
    sources = tuple(summary["source_sha256"]) + (
        "scripts/build-security.sh", "scripts/test-wave005.sh", "Cargo.toml", "Cargo.lock", "build.rs",
        "research/crypto-candidates.json", "tools/collect_wave005_evidence.py")
    validation = {"result": "PASS", "accepted_base": base,
                  "scope": "24 User/SVC/MMU cases, 48 boots on unchanged E2B; fixed healthy recovery fixture, no physical security certification",
                  "normalization": "host paths/hostnames/sockets only; UART byte-exact",
                  "security": {"result": "PASS", "complete_suite": True, "cases": 24, "boots": 48,
                               "image_sha256": image["sha256"], "qemu_sha256": runtime_hash},
                  "memory": memory, "results": statuses,
                  "crypto": {"status": "compile-only positive ARM object and expected unsupported-entropy compile failure; no crypto execution or entropy backend",
                             "proof_text_verified": crypto_checks},
                  "source_sha256": {name: sha((ROOT / name).read_bytes()) for name in sources},
                  "intentional_baseline_source_changes": ["Cargo.toml", "build.rs"],
                  "unchanged_baseline_source_sha256": baseline,
                  "unchanged_baseline_flat_image_sha256": flat_hashes,
                  "copied_evidence_sha256": copied, "local_protocols": local_protocols}
    payloads["validation.json"] = (json.dumps(validation, indent=2) + "\n").encode()
    if output.exists():
        existing = {str(path.relative_to(output)) for path in output.rglob("*") if path.is_file()}
        require(existing <= set(payloads), "Refusing to overwrite an evidence directory with unexpected files")
    for relative, payload in payloads.items():
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    total_bytes = sum(len(payload) for payload in payloads.values())
    print(f"Collected {len(payloads)} Wave005 text files, {total_bytes} bytes, {len(statuses)} PASS/status records")
    print(f"Verified 24 cases / 48 boots; {len(baseline)} unchanged sources, {len(flat_hashes)} unchanged flat outputs; RAM=91200 bytes")
    print(f"Preserved {len(local_protocols)} detailed local protocols by size/hash; six crypto proof logs verified")


if __name__ == "__main__":
    main()
