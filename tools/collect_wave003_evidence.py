#!/usr/bin/env python3
"""Collect explicit text-only Wave003 evidence; never copy images or firmware.

Run after scripts/test-wave003.sh; paths are presentation-normalized, UART
bytes and image hashes remain exact. Old accepted evidence is not overwritten.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = "01973b66ce76ad6b5089b67b57be33d80b2c8f27"
spec = importlib.util.spec_from_file_location("public_export", ROOT / "scripts/export-public.py")
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--qemu-cache", type=Path, default=ROOT / "local/qemu-e2b")
    args = parser.parse_args()
    artifacts = ROOT / "target/artifacts"
    copies = {}
    e2b = "crosshair-emulator/evidence/e2b"
    report = "reports/wave003"
    results = {}

    def add(destination, source):
        copies[destination] = source
        if source.name in ("result.json", "smoke-test.json", "qtest-result.json", "validation.json"):
            status = json.loads(source.read_text())["result"]
            permitted = ("PASS", "PASS_WITH_RECORDED_MODEL_LIMITATIONS")
            if status not in permitted:
                raise ValueError(f"Failed test: {source.name}: {status}")
            results[destination] = status

    for variant in ("normal", "negative-test"):
        for name in ("image.json", "elf-report.txt", "disassembly.txt", "size.txt"):
            add(f"{e2b}/images/{variant}/{name}", artifacts / "e2b" / variant / name)
    for scenario in ("gpio-boot-reset", "fault-1", "fault-2", "fault-3", "fault-4", "fault-5"):
        for name in ("result.json", "qemu-uart.log", "qemu-stderr.log", "memory-protocol.log"):
            add(f"{e2b}/execution/{scenario}/{name}", artifacts / "e2b-tests" / scenario / name)
    add(f"{e2b}/qtest/result.json", artifacts / "e2b-qtest/result.json")
    for scenario in ("registers", "gpio-out", "gpio-oe"):
        for name in ("protocol.log", "qemu-stderr.log"):
            add(f"{e2b}/qtest/{scenario}/{name}", artifacts / "e2b-qtest" / scenario / name)
    for name in ("source.json", "version.txt", "machines.txt", "resolved-devices.mak", "host-tools.txt", "loader.txt"):
        add(f"{e2b}/build/{name}", args.qemu_cache / "evidence" / name)
    for name in ("validation.json", "memory-layout.json", "ui02-input-trace.json", "tests.log", "arm-build.log", "arm-lib-report.txt", "layout-host.txt", "layout-arm.txt", "font-generator-check.json", "encoder-generator-checks.json"):
        add(f"{report}/ui/{name}", artifacts / "ui" / name)
    for board in ("versatilepb", "versatilepb-panic"):
        add(f"{report}/regressions/{board}.json", artifacts / board / "smoke-test.json")
    for board in ("connex", "verdex", "mainstone"):
        add(f"{report}/regressions/e1-{board}-tcg.json", artifacts / "pxa-reference" / board / "smoke-test.json")
        add(f"{report}/regressions/e1-{board}-qtest.json", artifacts / "pxa-qtest" / board / "qtest-result.json")
    for scenario in ("boot-reset", "fault-1", "fault-2", "fault-3", "fault-4"):
        add(f"{report}/regressions/e2a-{scenario}.json", artifacts / "e2a-tests" / scenario / "result.json")
    add(f"{report}/regressions/e2a-qtest.json", artifacts / "e2a-qtest/result.json")
    add(f"{report}/all-tests.log", artifacts / "wave003/all-tests.log")

    # Require source/image provenance to match the run, not merely a PASS label.
    ui = json.loads((artifacts / "ui/validation.json").read_text())
    for name, expected in ui["source_sha256"].items():
        assert digest((ROOT / name).read_bytes()) == expected, name
    for name, expected in ui["artifacts_sha256"].items():
        assert digest((artifacts / "ui" / name).read_bytes()) == expected, name
    build = json.loads((args.qemu_cache / "evidence/source.json").read_text())
    overlay = ROOT / "crosshair-emulator/qemu/crosshair-blueangel-e2b.c"
    assert digest(overlay.read_bytes()) == build["overlay_sha256"]
    assert digest((args.qemu_cache / "bin/qemu-system-arm").read_bytes()) == build["qemu_sha256"]
    for scenario in ("gpio-boot-reset", "fault-1", "fault-2", "fault-3", "fault-4", "fault-5"):
        run = json.loads((artifacts / "e2b-tests" / scenario / "result.json").read_text())
        variant = "normal" if scenario == "gpio-boot-reset" else "negative-test"
        image = json.loads((artifacts / "e2b" / variant / "image.json").read_text())
        assert run["image_sha256"] == image["sha256"]
        assert run["qemu_sha256"] == build["qemu_sha256"]
    assert json.loads((artifacts / "e2b-qtest/result.json").read_text())["qemu_sha256"] == build["qemu_sha256"]
    old_paths = ("crosshair-emulator/qemu/crosshair-blueangel-e2a.c", "src/pxa_reference.rs", "src/arch/pxa_entry.S", "tools/qtest_pxa.py", "tools/smoke_pxa.py", "tools/qtest_e2a.py", "tools/smoke_e2a.py", "ui/tests/surface.rs", "ui/examples/primitives.rs", "ui/src/font.rs", "ui/tools/subset_font.py", "ui/third_party/cozette/LICENSE", "ui/third_party/cozette/PROVENANCE.json", "tools/framebuffer_png.py")
    unchanged = {}
    for name in old_paths:
        original = subprocess.run(["/usr/bin/git", "-C", str(ROOT), "show", f"{BASE}:{name}"], check=True, capture_output=True).stdout
        assert (ROOT / name).read_bytes() == original, name
        unchanged[name] = digest(original)
    binary_regressions = {}
    for old, new in (
        ("crosshair-emulator/evidence/pxa-reference/image.json", "pxa-reference/image.json"),
        ("crosshair-emulator/evidence/e2a/images/normal/image.json", "e2a/normal/image.json"),
    ):
        original = json.loads(subprocess.run(["/usr/bin/git", "-C", str(ROOT), "show", f"{BASE}:{old}"], check=True, capture_output=True).stdout)
        current = json.loads((artifacts / new).read_text())
        for name, expected in original["sha256"].items():
            if not name.endswith(".elf"):
                assert current["sha256"][name] == expected, name
                binary_regressions[f"{new}:{name}"] = expected
    execution_sources = ("src/e2b.rs", "src/arch/e2b_entry.S", "link/e2b.ld", "tools/smoke_e2b.py", "tools/qtest_e2b.py", "scripts/build-e2b.sh", "scripts/test-e2b.sh", "scripts/test-wave003.sh")

    hashes = {}
    for relative, source in copies.items():
        original = source.read_bytes()
        payload = export.normalize(original.decode("utf-8"), ROOT).encode("utf-8")
        if source.name == "qemu-uart.log":
            assert payload == original, "UART evidence changed"
        if export.PRIVATE_PATH.search(payload.decode()) or export.SECRET.search(payload.decode()):
            raise ValueError(f"Private material in {relative}")
        destination = ROOT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        hashes[relative] = digest(payload)
    (ROOT / report / "validation.json").write_text(json.dumps({
        "result": "PASS", "accepted_base": BASE,
        "scope": "executed host/QEMU regressions; ARM UI compile-only; no physical hardware",
        "normalization": "host paths/hostnames/socket names only; UART bytes exact",
        "results": results, "unchanged_baseline_source_sha256": unchanged,
        "unchanged_baseline_flat_image_sha256": binary_regressions,
        "execution_source_sha256": {name: digest((ROOT / name).read_bytes()) for name in execution_sources},
        "copied_evidence_sha256": hashes,
    }, indent=2) + "\n")
    print(f"Collected {len(copies)} text files; {len(results)} successful test records; old evidence preserved")


if __name__ == "__main__":
    main()
