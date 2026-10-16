#!/usr/bin/env python3
"""Verify the complete Wave007.2 run and collect public text/frame evidence.

This collector does not execute guests, rebuild images, alter older reports or
publish anything. Only generated Shell framebuffer PNG/raw565 pairs are copied
as binary evidence; guest executables and detailed memory protocols stay local.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

from collect_wave006_evidence import ROOT, checked_hash, export, git_bytes, read_json, require, sha
from smoke_display import png_rgb, ppm_rgb
from smoke_security import elf_loads, image_word, register
from shell_control import UX_FIELDS, hardware_key_wire, pointer_coordinates, pointer_phase_wire

BASE = "4cbb78509ca1188e7ae4bf7703702128184b16f6"
MACHINE = "crosshair-blueangel-display-test"
START_UART = "CROSSHAIR SHELL — USER SESSION START\r\n".encode()
GUI_SENTINEL = "PASS live frontend pipeline: real ARM User input and QEMU console frames; native keymap/PPM decoder"
WINDOW_SENTINEL = "PASS native window: actual NSWindow key press/release reached ARM Launcher/About/Back/Home with QEMU frame publication"
POINTER_WINDOW_SENTINEL = "PASS native pointer window: actual NSWindow mouseDown coordinates, keys and Cyrillic text reached ARM with QEMU frames"
ADAPTIVE_WINDOW_SENTINEL = "PASS native adaptive window: actual Cocoa press/move/release, measured hold, key repeats and Standard/Compact/Immersive reached ARM"
OLD_TASK_SENTINEL = "PASS tasks: 8 scenarios, 16 ARM TCG boots; real Busy Loop IRQ preemption and task fault isolation"
FB_BYTES = 240 * 320 * 2
METRIC_NAMES = "version valid ticks switches task_count ready_tasks running_tasks faulted_tasks working_ram_bytes events_delivered input_overflows reserved".split()
REQUIRED_SOURCES = {
    "Cargo.toml", "Cargo.lock", "build.rs", "rust-toolchain.toml", ".cargo/config.toml",
    "src/shell.rs", "src/shell_user.rs", "src/shell_runtime/memory.rs",
    "src/arch/tasks_entry.S", "src/arch/task_workloads.S", "src/arch/shell_probe.S", "src/security_policy.rs", "src/drivers/pxa_uart.rs",
    "src/task_runtime/mod.rs", "src/task_runtime/context.rs", "src/task_runtime/memory.rs",
    "src/task_runtime/scheduler.rs", "src/task_runtime/syscall.rs",
    "shell/Cargo.toml", "shell/Cargo.lock", "shell/src/lib.rs", "shell/src/render.rs", "shell/src/icons.rs",
    "shell/src/fixtures.rs", "shell/src/tests.rs", "shell/examples/export.rs",
    "ui/Cargo.toml", "ui/Cargo.lock", "ui/src/lib.rs", "ui/src/components.rs", "ui/src/font.rs", "ui/src/theme.rs",
    "link/shell.ld", "link/shell-user.ld", "scripts/env.sh", "scripts/shell-env.sh",
    "scripts/build-shell.sh", "scripts/test-shell.sh", "scripts/test-shell-ui.sh", "scripts/test-wave007.sh",
    "tools/smoke_shell.py", "tools/shell_control.py", "tools/verify_shell_user.py", "tools/verify_image.py",
    "tools/framebuffer_png.py", "tools/qemu_control.py", "tools/qtest_pxa.py", "tools/smoke_display.py",
    "tools/smoke_security.py", "tools/smoke_tasks.py", "tools/smoke_e2a.py",
    "crosshair-emulator/qemu/crosshair-blueangel-display-test.c",
    "crosshair-emulator/qemu/crosshair-blueangel-e2a.c", "crosshair-emulator/qemu/crosshair-blueangel-e2b.c",
    "shell/src/geometry.rs", "shell/src/wallpaper.rs",
    "scripts/test-wave007-1.sh", "scripts/test-shell-pointer.sh", "tools/smoke_shell_pointer.py",
    "tools/test_shell_input.py",
    "shell/src/adaptive.rs", "ui/src/pda.rs",
}
ADAPTIVE_SOURCES = REQUIRED_SOURCES | {"scripts/test-wave007-2.sh", "scripts/test-shell-adaptive.sh", "tools/smoke_shell_adaptive.py"}
GUI_SOURCES = {"tools/run_shell.py", "tools/crosshair_gui.swift", "tools/shell_control.py",
               "scripts/run-crosshair-gui.sh", "scripts/run-shell.sh", "scripts/build-shell-gui.sh", "scripts/shell-env.sh"}

# Intentional presentation/input/test changes. Everything else already bound
# by Wave007 remains immutable, including the UI renderer, kernel, scheduling,
# MMU, toolchain, old workloads and the synthetic board models.
MUTABLE_BASELINE = {
    "shell/src/lib.rs", "shell/src/render.rs", "shell/src/fixtures.rs", "shell/src/tests.rs",
    "shell/examples/export.rs", "src/shell_user.rs", "tools/smoke_shell.py",
    "tools/shell_control.py", "tools/run_shell.py", "tools/crosshair_gui.swift",
    "scripts/build-shell.sh", "scripts/test-shell-ui.sh",
    "tools/pack_repomix.py", "shell/src/geometry.rs", "tools/test_shell_input.py", "tools/smoke_shell_pointer.py",
}
VERSION_METADATA = {"Cargo.lock", "shell/Cargo.lock", "shell/Cargo.toml"}
UI_MODULE_EXPORT = "ui/src/lib.rs"

# Derived from the complete accepted ELF recorded by Wave007.1.
# Its User PT_LOAD at a0400000 is deliberately omitted: the kernel embeds the
# new User binary, so its whole-file hash must change despite unchanged kernel.
ACCEPTED_KERNEL_LOADS = [
    {"pa": 0, "va": 0, "filesz": 64, "memsz": 64, "flags": 5,
     "sha256": "01d24cc9d926bff09df0f1785ce577ec1029e8cccdaa84797cf43b7e20d32d63"},
    {"pa": 0xA0008000, "va": 0xA0008000, "filesz": 5180, "memsz": 5180, "flags": 5,
     "sha256": "a01a2aaceadfceb4d0a04ddfa3e670e96a8efc08a6fa68a9768a748882d296ba"},
    {"pa": 0xA000C000, "va": 0xA000C000, "filesz": 0, "memsz": 68168, "flags": 6,
     "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
    {"pa": 0xA0200000, "va": 0xA0200000, "filesz": 524, "memsz": 524, "flags": 5,
     "sha256": "61dc5c57972c7fc64c865c12d7f133736a38c87f6c186a1b5fb38f05f7bcd23e"},
]


def check_kernel_loads(loads):
    actual = [{key: value for key, value in load.items() if key != "bytes"}
              | {"sha256": sha(load["bytes"])} for load in loads if load["pa"] != 0xA0400000]
    require(actual == ACCEPTED_KERNEL_LOADS,
            "Wave007 kernel/vector/Busy code or allocated kernel RAM changed")
    return actual


def preserve_accepted_reports():
    names = subprocess.check_output(["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", "-z", BASE,
                                     "--", "reports", "crosshair-emulator/evidence"]).decode().rstrip("\0").split("\0")
    require(names and all("\n" not in name and "\r" not in name for name in names), "Invalid accepted report path")
    request = "".join(BASE + ":" + name + "\n" for name in names).encode()
    blobs = subprocess.check_output(["git", "-C", str(ROOT), "cat-file", "--batch"], input=request)
    result, position = {}, 0
    for name in names:
        end = blobs.index(b"\n", position)
        header = blobs[position:end].split()
        require(len(header) == 3 and header[1] == b"blob", "Accepted report is not a Git blob")
        size = int(header[2])
        position = end + 1
        original = blobs[position:position + size]
        require(len(original) == size and blobs[position + size:position + size + 1] == b"\n", "Incomplete accepted Git blob")
        expected = sha(original)
        checked_hash(ROOT / name, expected)
        result[name] = expected
        position += size + 1
    require(position == len(blobs), "Unexpected accepted report batch bytes")
    return result


def check_baseline(artifacts, output, accepted_kernel=None):
    require(subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", BASE + "^{commit}"], text=True).strip() == BASE,
            "Accepted Wave007.1 base is unavailable")
    subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", BASE, "HEAD"], check=True)
    require(output == ROOT / "reports/wave007-2" or not output.is_relative_to(ROOT / "reports"),
            "Only the new Wave007.2 report directory may be written inside reports")
    accepted = json.loads(git_bytes(BASE, "reports/wave007-1/validation.json"))
    require(read_json(ROOT / "reports/wave007-1/validation.json") == accepted,
            "Accepted Wave007.1 validation changed")
    preserved = preserve_accepted_reports()
    baseline = dict(accepted["unchanged_baseline_source_sha256"])
    baseline.update(accepted["source_sha256"])
    baseline.update(accepted["native_source_sha256"])
    baseline.update(accepted["desktop_pointer"]["source_sha256"])
    baseline.update(accepted["collector_publication_source_sha256"])
    for name in VERSION_METADATA:
        old = git_bytes(BASE, name)
        before = b'name = "crosshair-shell"\nversion = "0.1.1"'
        after = b'name = "crosshair-shell"\nversion = "0.1.2"'
        require(old.count(before) == 1 and (ROOT / name).read_bytes() == old.replace(before, after),
                "Only the Shell 0.1.1-to-0.1.2 metadata update is accepted: " + name)
    old_ui = git_bytes(BASE, UI_MODULE_EXPORT)
    require(old_ui.count(b"pub mod font;\n") == 1 and (ROOT / UI_MODULE_EXPORT).read_bytes()
            == old_ui.replace(b"pub mod font;\n", b"pub mod font;\npub mod pda;\n"),
            "Only the exact public pda module export may extend the accepted UI renderer file")
    for name in MUTABLE_BASELINE | VERSION_METADATA | {UI_MODULE_EXPORT}:
        baseline.pop(name, None)
    for name, expected in baseline.items():
        require(sha(git_bytes(BASE, name)) == expected, "Accepted source manifest mismatch: " + name)
        checked_hash(ROOT / name, expected)
    flats = dict(accepted["unchanged_baseline_flat_image_sha256"])
    for key, expected in flats.items():
        manifest_name, filename = key.split(":", 1)
        require(read_json(artifacts / manifest_name)["sha256"][filename] == expected,
                "Earlier flat manifest changed: " + key)
        checked_hash((artifacts / manifest_name).parent / filename, expected)
    cached_elf = accepted_kernel or artifacts / "wave007-2/baseline/accepted-crosshair-shell.elf"
    require(cached_elf.is_file(),
            "Accepted Wave007.1 ELF is needed for independent segment comparison; rebuild 4cbb785 with the pinned toolchain and pass --accepted-kernel")
    checked_hash(cached_elf, accepted["shell"]["image_sha256"]["crosshair-shell.elf"])
    check_kernel_loads(elf_loads(cached_elf)[1])
    return accepted, baseline, flats, preserved


def check_wallpaper(user_flat, user_loads, user):
    directory = ROOT / "shell/assets/wallpaper"
    manifest = read_json(directory / "PROVENANCE.json")
    require((manifest["schema"], manifest["width"], manifest["height"], manifest["colors"],
             manifest["mutable_decode_scratch_bytes"]) == ("crosshair-wallpaper-v1", 240, 320, 16, 0),
            "Wallpaper format/budget changed")
    require(manifest["generated_path"] == "shell/src/wallpaper_assets.rs", "Unexpected generated wallpaper path")
    reference = manifest["reference"]
    require(reference["path"] == "docs/design/crosshair-ui-reference-2026-10-16.png"
            and reference["sha256"] == sha(git_bytes(BASE, reference["path"])),
            "Wallpaper provenance does not bind the accepted visual reference")
    checked_hash(ROOT / reference["path"], reference["sha256"])
    check = subprocess.check_output([sys.executable, str(ROOT / "shell/tools/generate_wallpaper.py"), "--check"], text=True).strip()
    require(check.startswith("Wallpaper PASS:"), "Offline wallpaper source/format/output validation failed")
    spec = importlib.util.spec_from_file_location("crosshair_wallpaper_generator", ROOT / "shell/tools/generate_wallpaper.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    palette, offsets, encoded = generator.parse_generated((ROOT / manifest["generated_path"]).read_bytes())
    parts = {"palette": struct.pack("<32H", *palette), "row_table": struct.pack("<321H", *offsets), "rle": encoded}
    require(sha(b"".join(parts.values())) == manifest["payload_sha256"]
            and sum(map(len, parts.values())) == manifest["payload_bytes"], "Wallpaper payload manifest mismatch")
    locations = {}
    for name, data in parts.items():
        offset = user_flat.find(data)
        require(offset >= 0 and user_flat.find(data, offset + 1) < 0,
                "Need exactly one actual wallpaper " + name + " in tested User image")
        virtual = user["entry"] + offset
        require(any(load["flags"] == 5 and load["pa"] <= virtual
                    and virtual + len(data) <= load["pa"] + load["filesz"] for load in user_loads),
                "Wallpaper part is not in the existing read-only User allocation")
        locations[name] = {"bytes": len(data), "sha256": sha(data), "user_va": virtual,
                           "physical": 0xA0400000 + offset, "allocation": "single initialized User RO ELF segment"}
    return {"provenance": manifest, "runtime_parts": locations, "collector_offline_binding_check": check,
            "persistent_decode_buffer_bytes": 0, "expanded_framebuffers": 0,
            "scratch_scope": "No persistent row/pixel buffer; scalar automatic call state and Shell RenderStats remain separately accounted"}


def check_render_stats(values):
    require(isinstance(values, list) and len(values) == 8
            and all(isinstance(value, int) and 0 <= value <= 0xFFFFFFFF for value in values),
            "Invalid actual render cost observation")
    packets, decoded, written, runs, rectangles, dirty_pixels, full, rendered = values
    require(full in (0, 1) and rendered in (0, 1) and full <= rendered
            and written <= decoded <= 240 * 320 and runs <= packets <= decoded
            and written <= dirty_pixels <= 240 * 320 and rectangles <= 16,
            "Unbounded or inconsistent software render cost")
    require(rendered == 1 or values == [0] * 8, "No-op render must perform zero recorded work")
    return dict(zip(("wallpaper_packets_decoded", "wallpaper_pixels_decoded", "wallpaper_pixels_written",
                     "wallpaper_runs_written", "dirty_rectangles", "dirty_pixels", "full_composition", "rendered"), values))


def check_ux(values, snapshot=None):
    require(isinstance(values, dict) and set(values) == set(UX_FIELDS)
            and all(isinstance(value, int) and 0 <= value <= 0xFFFFFFFF for value in values.values()),
            "Invalid complete ARM UX observation")
    mode = values["chrome_mode"]
    require(mode in (0, 1, 2) and values["version"] == 1
            and (values["content_y"], values["content_height"]) == ((24, 296), (16, 304), (0, 320))[mode]
            and values["pointer_active"] in (0, 1) and values["pointer_cancelled"] in (0, 1)
            and values["pointer_target"] <= 121 and values["last_phase"] <= 5
            and values["scroll_offset"] <= values["scroll_max"] <= 25
            and values["held_keys"] < (1 << 13) and values["last_key_phase"] <= 2 and values["last_key"] <= 12,
            "Unbounded or inconsistent ARM capture/chrome/key state")
    if snapshot is not None:
        require(values["panel"] == snapshot["overlay"], "UX overlay differs from actual Shell state")
    return [values[name] for name in UX_FIELDS]


def check_replay(folder, boot, working_ram, require_ux=False):
    """Validate the immutable host input journal against actual ARM observations."""
    replay = folder / "host-replay.txt"
    checked_hash(replay, boot["parity"]["host_replay_sha256"])
    manifest = read_json(folder / "host/frames.json")
    require(manifest["schema"] == "crosshair-shell-frames-v1" and manifest["pixel_format"] == "RGB565_LE"
            and manifest["runtime_bytes"] == 48 and manifest["snapshot_bytes"] == 64 and manifest["ux_bytes"] == 80,
            "Wrong host snapshot/runtime/UX replay schema")
    frames, trace, lines = manifest["frames"], boot["trace"], replay.read_text().splitlines()
    require(len(frames) == len(trace) == len(lines) == boot["parity"]["frames"], "Replay omitted actual observations")
    for index, (entry, frame, line) in enumerate(zip(trace, frames, lines)):
        action = "-1" if index == 0 else f"wire:{entry['last_event']:08x}"
        require(line.split() == [f"step-{index:02d}", action] + [str(entry["metrics"][key]) for key in METRIC_NAMES],
                "Replay differs from actual wire/kernel metrics")
        require(frame["snapshot"] == entry["snapshot"]
                and frame["runtime_words"] == [entry["metrics"][key] for key in METRIC_NAMES],
                "Actual ARM and host replay state/metrics differ")
        require((entry["metrics"]["version"], entry["metrics"]["valid"], entry["metrics"]["reserved"],
                 entry["metrics"]["working_ram_bytes"]) == (1, 15, 0, working_ram), "Invalid actual runtime metrics")
        stats = check_render_stats(frame["render_stats"])
        require(frame["rendered"] == bool(stats["rendered"]), "Host render declaration differs from measured work")
        if "render_metrics" in entry:
            require(entry["render_metrics"] == frame["render_stats"], "ARM/host journal render work differs")
        else:
            require(not require_ux, "Adaptive journal omitted actual render work")
        if "ux" in entry:
            require(check_ux(entry["ux"], entry["snapshot"]) == frame["ux_words"], "ARM/host UX journal differs")
        else:
            require(not require_ux, "Adaptive journal omitted actual UX state")
    return frames


def processing_cost(accepted, legacy, adaptive):
    """Counts are observed work; source bounds are deliberately not timings."""
    old = read_json(ROOT / "reports/wave007-1/pointer/result.json")
    before = {state["name"]: state for state in old["boots"][0]["states"]}
    after = {state["name"]: state for state in legacy["boots"][0]["states"]}
    comparisons = {}
    for name in ("settings-shortcut", "today-shortcut", "about-row", "keyboard-focus-down", "keyboard-focus-up",
                 "system-menu", "outside-menu-no-fallthrough"):
        require(name in before and name in after, "Missing accepted/current comparable logical action: " + name)
        old_state, new_state = before[name], after[name]
        require(tuple(old_state["user"]["snapshot"][key] for key in ("screen", "overlay", "theme"))
                == tuple(new_state["user"]["snapshot"][key] for key in ("screen", "overlay", "theme")),
                "Cannot compare actions ending in different logical views")
        comparisons[name] = {"accepted_wave007_1": check_render_stats(old_state["render_metrics"]),
                             "wave007_2": check_render_stats(new_state["render_metrics"]),
                             "input_wire_records": {"accepted": 1, "current_legacy_action": 1}}
    return {"accepted_validation_sha256": sha(git_bytes(BASE, "reports/wave007-1/validation.json")),
            "same_legacy_action_render_work": comparisons,
            "input_transport": {"legacy_tap_wire_records": 1, "physical_press_release_wire_records": 2,
                                "scope": "Additional Move/Cancel/Hold and key edges are counted separately in complete actual traces"},
            "bounded_hit_testing": {"overlay_candidates_max": 8, "launcher_app_candidates_max": 4,
                                     "desktop_shortcuts_max": 3,
                                     "status": "SOURCE BOUNDS in shell/src/adaptive.rs and geometry.rs; no dynamic scan counter"},
            "actual_adaptive_observations": adaptive["event_processing"],
            "presentation_bytes_per_render": FB_BYTES,
            "unmeasured": ["guest CPU cycles", "guest instruction counts", "physical PDA latency", "display bus cost"],
            "scope": "Actual ARM/host software counters and render/no-render observations; host wall time is not a performance estimate"}


def collect_native_window(shell_dir, mode, screens, wires, image, user, summary, pipeline, runtime, protocols, add):
    directory = shell_dir / "gui"
    path = directory / (mode + "-result.json")
    result = read_json(path)
    require((result["result"], result["mode"], result["window_ready"], result["logs"])
            == ("PASS", "native-" + mode, True, mode), "Actual native window event-path test did not complete: " + mode)
    require(result["automation_isolation"] is True and result["aborted_pending_on_window_close"] == 0,
            "Native automation admitted unscheduled input or discarded pending events")
    require(result["image_sha256"] == image["sha256"] and result["user_image_sha256"] == user["sha256"]
            and result["qemu_sha256"] == summary["qemu_sha256"]
            and result["frontend_sha256"] == pipeline["frontend_sha256"]
            and Path(result["command"][0]).resolve() == runtime, "Native window tested other guest/runtime/frontend bytes")
    bindings(result["source_sha256"], GUI_SOURCES, "Native " + mode)
    events = result["events"]
    require(len(screens) == len(wires) == len(events) and [event["event"] for event in events] == list(range(1, len(events) + 1))
            and [event["screen"] for event in events] == screens, "Incomplete native input/state trace: " + mode)
    previous_generation = 0
    for number, (event, wire) in enumerate(zip(events, wires), 1):
        if wire is None:
            holds = result["measured_holds_ms"]
            require(len(holds) == 1 and isinstance(holds[0], int) and 600 <= holds[0] <= 0xFFFFFFFF,
                    "Native long press lacks one measured monotonic 600ms hold")
            wire = pointer_phase_wire(5, held_ms=holds[0])
        require(event["wire"] == wire and event["pointer"] == (list(pointer_coordinates(wire)) if pointer_coordinates(wire) else None),
                "Actual native coordinate/key/text wire differs from scheduled input")
        require(event["generation"] >= previous_generation and event["snapshot"]["renders"] == event["generation"]
                and event["snapshot"]["events_processed"] == number and event["snapshot"]["screen"] == event["screen"],
                "Native frame generation/state differs from actual ARM input order")
        previous_generation = event["generation"]
        check_ux(event["ux"], event["snapshot"])
        path = directory / f"{mode.removesuffix('-test')}-step-{number}.ppm"
        require(sha(ppm_rgb(path)) == event["console_rgb_sha256"], "Native window QEMU frame differs from observed pixels")
        protocols["gui/" + path.name] = {"bytes": path.stat().st_size, "sha256": sha(path.read_bytes())}
    add("gui/" + mode + "-result.json", directory / (mode + "-result.json"))
    return result


def check_user_static_layout(directory, user, llvm):
    expected = {"SHELL_FRAMEBUFFER": 153728, "SHELL_USER_RECORD": 176, "SHELL_METRICS": 48,
                "SHELL_TRACE": 8192, "SHELL_RENDER_METRICS": 32, "SHELL_UX_METRICS": 80,
                "SHELL_UX_TRACE": 5120, "SHELL_RENDER_TRACE": 2048}
    actual = {}
    for line in subprocess.check_output([str(llvm / "llvm-nm"), "-S", "--defined-only", "--format=posix",
                                         str(directory / "crosshair-shell-user.elf")], text=True).splitlines():
        fields = line.split()
        if fields and fields[0] in expected:
            require(len(fields) == 4 and fields[1] == "B", "User observation is not an exact BSS symbol")
            name, address, size = fields[0], int(fields[2], 16), int(fields[3], 16)
            require(size == expected[name] and address == user["symbols"][name], "Unexpected User static symbol extent: " + name)
            actual[name] = {"user_va": address, "physical": 0xA0400000 + address - 0x01000000, "bytes": size}
    require(set(actual) == set(expected), "Missing actual User framebuffer/observation symbol sizes")
    end = user["symbols"]["__user_bss_start"]
    for value in sorted(actual.values(), key=lambda value: value["user_va"]):
        require(value["user_va"] == end, "Unexpected hidden BSS buffer, gap or overlapping observation")
        end += value["bytes"]
    require(end == user["symbols"]["__user_bss_end"] <= 0x0103F000, "Actual User data crosses the existing guard")
    return actual


def collect_adaptive(shell_dir, image, user, user_loads, runtime, working_ram, reference_tables, add):
    directory = shell_dir / "adaptive"
    result = read_json(directory / "result.json")
    require((result["result"], result["machine"], result["accelerator"], result["boots_completed"],
             result["events"], result["pixel_comparisons"]) == ("PASS", MACHINE, "tcg", 2, 75, 24),
            "Need complete two-boot/75-delivery/24-pixel adaptive evidence")
    require(result["image_sha256"] == image["sha256"] and result["user_image_sha256"] == user["sha256"]
            and result["qemu_sha256"] == sha(runtime.read_bytes()) and Path(result["command"][0]).resolve() == runtime,
            "Adaptive execution used another image or runtime")
    bindings(result["source_sha256"], ADAPTIVE_SOURCES, "Adaptive execution")
    contracts = {"phases": (43, 41, {0, 1, 4, 7, 9, 14, 21, 26, 30, 32, 37, 39, 41}),
                 "adaptive-reset": (32, 32, {0, 2, 3, 4, 5, 7, 9, 11, 23, 27, 32})}
    require([boot["name"] for boot in result["boots"]] == list(contracts), "Adaptive reset cases missing or reordered")
    observations, named, statistics, capture_count = {}, {}, {}, 0
    for boot in result["boots"]:
        name = boot["name"]
        count, handled, captures = contracts[name]
        trace, states, folder = boot["trace"], boot["states"], directory / name
        require((boot["events"], boot["ui_events"], len(trace)) == (count, handled, count + 1), "Incomplete adaptive input trace")
        require(len(states) == (44 if name == "phases" else 30), "Incomplete stable adaptive observations")
        expected_ui = [index - int(index >= 21) - int(index >= 29) for index in range(44)] if name == "phases" else list(range(33))
        require([entry["snapshot"]["events_processed"] for entry in trace] == expected_ui,
                "Cancel/invalid events changed UI counters or admitted input was lost")
        frames = check_replay(folder, boot, working_ram, True)
        named[name] = {state["name"]: state for state in states}
        require(len(named[name]) == len(states) and "initial" in named[name], "Duplicated/missing adaptive state labels")
        for index, entry in enumerate(trace):
            observations[f"{name}/step-{index:02d}"] = {"wire": entry["last_event"], "ui_events": expected_ui[index],
                "ux": entry["ux"], "render_work": check_render_stats(entry["render_metrics"])}
            require(entry["metrics"]["events_delivered"] == index, "Adaptive kernel input metric differs from delivered order")
        for state in states:
            r, u = state["record"], state["user"]
            index = r["events_delivered"]
            require(0 <= index <= count and u["snapshot"] == trace[index]["snapshot"]
                    and u["metrics"] == trace[index]["metrics"] and u["last_event"] == trace[index]["last_event"]
                    and state["ux"] == trace[index]["ux"] and state["render_metrics"] == trace[index]["render_metrics"],
                    "Stable adaptive observation differs from complete actual journal")
            require((r["magic"], r["version"], r["stage"], r["error"], r["sctlr"], r["dacr"], r["pid"],
                     r["queue_len"], r["api_rejections"], r["queue_capacity"], r["fb_bytes"], r["last_present_ptr"], r["last_present_len"])
                    == (0x53484C4C, 1, 2, 0, 0x79, 1, 0, 0, 11, 4, FB_BYTES, 0x01010040, FB_BYTES),
                    "Adaptive kernel/API/framebuffer invariant failed")
            require((u["magic"], u["version"], u["state"]) == (0x5553484C, 1, 2)
                    and u["snapshot"]["renders"] == r["frames"] and state["tasks"][1]["state"] == 4,
                    "Adaptive Shell did not block after actual User presentation")
            context = state["tasks"][1]["context"]
            require(context["cpsr"] & 0xFF == 0x50 and context["kind"] == 2 and context["raw_lr"] == context["pc"]
                    and 0x01000000 <= context["pc"] < 0x01010000 and context["pc"] % 4 == 0
                    and 0x01040000 <= context["sp"] <= 0x01048000 and context["sp"] % 8 == 0
                    and image_word(user_loads, context["pc"] - 4) == 0xEF000000,
                    "Adaptive Waiting context is not a bounded IRQ-enabled User SVC")
            expected_dropped = 4 if name == "adaptive-reset" and index >= 27 else 0
            require(r["queue_dropped"] == expected_dropped and u["metrics"]["input_overflows"] == expected_dropped,
                    "Adaptive actual overflow/recovery metrics mismatch")
        require(boot["page_tables"] == reference_tables, "Adaptive page tables differ from unchanged isolation contract")
        progress = boot["waiting_progress"]
        require(progress["after"]["ticks"] >= progress["before"]["ticks"] + 3
                and progress["after"]["frames"] == progress["before"]["frames"]
                and progress["after"]["events_delivered"] == count
                and progress["busy_counter_after"] > progress["busy_counter_before"],
                "Adaptive waiting session lacks actual timer and independent Busy progress")
        require(set(map(int, boot["captures"])) == captures and boot["parity"]["pixel_comparisons"] == len(captures),
                "Required gesture/mode/recovery captures missing")
        for key, capture in boot["captures"].items():
            index = int(key)
            require(capture["name"] == f"step-{index:02d}" and capture["generation"] == trace[index]["snapshot"]["renders"],
                    "Unsafe or stale adaptive capture")
            for field, suffix in (("raw565", ".raw565"), ("png", ".png"), ("ppm", ".ppm")):
                require(capture[field] == capture["name"] + suffix, "Unsafe adaptive capture filename")
            raw, png, ppm = (folder / capture[field] for field in ("raw565", "png", "ppm"))
            checked_hash(raw, capture["raw565_sha256"]); checked_hash(png, capture["png_sha256"])
            pixels = rgb565(raw.read_bytes())
            require(pixels == png_rgb(png) == ppm_rgb(ppm) and sha(pixels) == capture["console_rgb_sha256"],
                    "Actual adaptive guest/PNG/QEMU pixels differ")
            host_raw = folder / "host" / frames[index]["file"]
            require(host_raw.parent == folder / "host", "Adaptive host frame escapes replay directory")
            checked_hash(host_raw, capture["host_raw565_sha256"]); checked_hash(host_raw.with_suffix(".png"), capture["host_png_sha256"])
            require(raw.read_bytes() == host_raw.read_bytes() and pixels == png_rgb(host_raw.with_suffix(".png")),
                    "Actual adaptive ARM/host framebuffer parity failed")
            add("frames/" + name + "/" + raw.name, raw, True); add("frames/" + name + "/" + png.name, png, True)
        capture_count += len(captures)
        statistics[name] = {"input_records": count, "ui_events": handled,
            "rendered_observations": sum(entry["render_metrics"][7] for entry in trace[1:]),
            "no_render_observations": sum(entry["render_metrics"][7] == 0 for entry in trace[1:]),
            "actions_invoked": trace[-1]["ux"]["actions_invoked"], "key_actions": trace[-1]["ux"]["key_actions"],
            "initial_render_counted_separately": True,
            "total_wallpaper_pixels_written": sum(entry["render_metrics"][2] for entry in trace)}
        add("adaptive/" + name + "/host-replay.txt", folder / "host-replay.txt")
        add("adaptive/" + name + "/host-frames.json", folder / "host/frames.json")
    require(len(observations) == 77 and capture_count == 24, "Incomplete adaptive work/capture observations")
    phases, modes = named["phases"], named["adaptive-reset"]
    for label in ("press-no-activation", "move-within-target", "moved-hold-rejected", "drag-out",
                  "drag-back-still-cancelled", "drag-release-no-tap", "orphan-release", "orphan-hold",
                  "hold599-no-context", "post-hold-release-suppressed", "source-failure", "invalid-move-cancels-input",
                  "launcher-measured-context", "context-release-suppressed", "outside-panel-press",
                  "outside-panel-release-dismisses", "outside-dialog-press", "outside-dialog-release-inert"):
        before = next(index for index, state in enumerate(result["boots"][0]["states"]) if state["name"] == label) - 1
        require(phases[label]["ux"]["actions_invoked"] == result["boots"][0]["states"][before]["ux"]["actions_invoked"],
                "Ineligible phase invoked an action: " + label)
    require(phases["release-one-tap"]["user"]["snapshot"]["screen"] == 1
            and phases["release-one-tap"]["ux"]["actions_invoked"] == 1
            and phases["hold600-context"]["ux"]["panel"] == 4
            and phases["hold600-context"]["ux"]["pointer_active"] == 0,
            "Matching Release or trusted 600ms hold semantics missing")
    require(phases["launcher-measured-context"]["ux"]["panel"] == 2
            and phases["context-release-suppressed"]["ux"]["panel"] == 2
            and phases["outside-panel-release-dismisses"]["ux"]["panel"] == 0
            and phases["outside-panel-release-dismisses"]["user"]["snapshot"]["screen"] == 2
            and phases["outside-panel-release-dismisses"]["user"]["last_event"] == pointer_phase_wire(3, 10, 140)
            and phases["outside-dialog-release-inert"]["ux"]["panel"] == 3
            and phases["outside-dialog-release-inert"]["user"]["snapshot"]["screen"] == 5
            and phases["outside-dialog-release-inert"]["user"]["snapshot"]["theme"] == 0
            and phases["outside-dialog-release-inert"]["user"]["last_event"] == pointer_phase_wire(3, 10, 80),
            "Native-style outside Release, modal consumption or Launcher context hold coverage missing")
    for label in ("orphan-release", "orphan-hold", "hold599-no-context", "home-release"):
        require(phases[label]["render_metrics"] == [0] * 8, "Ignored phase unexpectedly rendered: " + label)
    for label in ("down-repeat-clamped", "down-release"):
        require(modes[label]["render_metrics"] == [0] * 8, "Ignored bounded key edge unexpectedly rendered: " + label)
    physical_pair = [phases[label] for label in ("fresh-press", "fresh-release-recovers")]
    statistics["physical_activation_pair"] = {
        "labels": [state["name"] for state in physical_pair], "input_records": 2,
        "actions_invoked_delta": physical_pair[-1]["ux"]["actions_invoked"] - phases["home-release"]["ux"]["actions_invoked"],
        "renders": sum(state["render_metrics"][7] for state in physical_pair),
        "render_work_words_summed": [sum(state["render_metrics"][index] for state in physical_pair) for index in range(8)],
        "scope": "Actual adjacent Press/Release opens Today; summed full/rendered fields are counts"}
    require(statistics["physical_activation_pair"]["actions_invoked_delta"] == 1,
            "Two-record matching physical activation did not invoke exactly once")
    statistics["ignored_key_observations"] = {}
    mode_states = result["boots"][1]["states"]
    for label in ("down-release", "select-repeat-no-reinvoke", "select-release"):
        index = next(index for index, state in enumerate(mode_states) if state["name"] == label)
        state, previous = mode_states[index], mode_states[index - 1]
        counters = {field: state["ux"][field] - previous["ux"][field] for field in ("actions_invoked", "key_actions")}
        require(counters == {"actions_invoked": 0, "key_actions": 0}, "Ignored Repeat/Release reinvoked a command")
        statistics["ignored_key_observations"][label] = counters | {"rendered": state["render_metrics"][7],
            "scope": "Diagnostics may redraw independently when a real runtime metrics snapshot changes"}
    for label, mode in (("open-about-standard", 0), ("enter-compact", 1), ("enter-immersive", 2), ("return-standard", 0)):
        require(modes[label]["ux"]["chrome_mode"] == mode and modes[label]["user"]["snapshot"]["screen"] == 3,
                "Missing actual shared-framebuffer adaptive mode: " + label)
    require(modes["enter-immersive"]["ux"]["scroll_offset"] == modes["return-standard"]["ux"]["scroll_offset"] == 1
            and modes["back-preserves-history"]["user"]["snapshot"]["history_depth"] == 1
            and modes["actual-queue-overflow"]["ux"]["held_keys"] == modes["actual-queue-overflow"]["ux"]["pointer_active"] == 0
            and modes["fresh-release-after-loss"]["user"]["snapshot"]["screen"] == 1,
            "Mode/history preservation or actual source-loss recovery missing")
    add("adaptive/result.json", directory / "result.json")
    return {"result": "PASS", "boots": 2, "delivered_events": 75, "handled_ui_events": 73,
        "pixel_comparisons": capture_count, "source_sha256": result["source_sha256"],
        "observed_work": observations, "event_processing": statistics,
        "functional_keyframes": {"standard": "frames/adaptive-reset/step-02.png", "panel": "frames/adaptive-reset/step-03.png",
            "compact": "frames/adaptive-reset/step-04.png", "immersive": "frames/adaptive-reset/step-07.png",
            "edge_recovery": "frames/adaptive-reset/step-09.png", "hold_panel": "frames/phases/step-14.png",
            "launcher_context": "frames/phases/step-32.png", "outside_panel_dismissal": "frames/phases/step-37.png",
            "dialog_outside_release": "frames/phases/step-41.png"},
        "cost_scope": "All 77 actual ARM initial/input journal observations independently matched to host UX20/render8; software counters, no CPU timing"}


def collect_pointer(shell_dir, image, user, user_loads, runtime, working_ram, reference_tables, add):
    directory = shell_dir / "pointer"
    result = read_json(directory / "result.json")
    require((result["result"], result["machine"], result["accelerator"], result["boots_completed"],
             result["events"], result["pixel_comparisons"]) == ("PASS", MACHINE, "tcg", 3, 56, 34),
            "Need complete three-boot/56-delivery/34-pixel pointer and keyboard evidence")
    require(result["image_sha256"] == image["sha256"] and result["user_image_sha256"] == user["sha256"]
            and result["qemu_sha256"] == sha(runtime.read_bytes()) and Path(result["command"][0]).resolve() == runtime,
            "Pointer execution used another image or runtime")
    required = {"tools/smoke_shell_pointer.py", "tools/smoke_shell.py", "tools/shell_control.py",
                "tools/run_shell.py", "tools/crosshair_gui.swift", "tools/test_shell_input.py",
                "scripts/test-shell-pointer.sh", "scripts/test-wave007-1.sh", "src/shell_user.rs", "src/shell.rs"}
    required |= {str(path.relative_to(ROOT)) for path in (ROOT / "shell/src").glob("*.rs")}
    required |= {str(path.relative_to(ROOT)) for path in (ROOT / "shell/assets").rglob("*")
                 if path.is_file() and path.name != ".DS_Store" and "__pycache__" not in path.parts}
    bindings(result["source_sha256"], required, "Pointer execution")
    contract = {"pointer": (38, 34, set([0, 2, 3, 4, 6, 8, 9, 10, 12, 13, 19, 20, 24, 25, 28, 29, 34])),
                "keyboard-reset": (14, 14, set(range(15))), "pointer-burst-reset": (4, 4, {0, 4})}
    require([boot["name"] for boot in result["boots"]] == list(contract), "Pointer reset/burst boot order incomplete")
    costs, captures_total = {}, 0
    for boot in result["boots"]:
        name = boot["name"]
        count, handled, expected_captures = contract[name]
        require((boot["events"], boot["ui_events"], len(boot["trace"])) == (count, handled, count + 1),
                "Incomplete delivered/handled pointer trace")
        trace, states = boot["trace"], boot["states"]
        require([state["event"] for state in states] == ([0, 4] if name == "pointer-burst-reset" else list(range(count + 1))),
                "Missing stable pointer observations")
        require(trace[0]["snapshot"]["screen"] == trace[0]["snapshot"]["theme"] == 0
                and trace[-1]["snapshot"]["events_processed"] == handled, "Pointer reset/handled count mismatch")
        expected_ui_counts = list(range(35)) + [34] * 4 if name == "pointer" else list(range(count + 1))
        require([entry["snapshot"]["events_processed"] for entry in trace] == expected_ui_counts,
                "Invalid coordinates changed UI counters or an accepted event was lost")
        folder = directory / name
        replay = folder / "host-replay.txt"
        checked_hash(replay, boot["parity"]["host_replay_sha256"])
        frames = read_json(folder / "host/frames.json")["frames"]
        lines = replay.read_text().splitlines()
        require(len(frames) == len(lines) == boot["parity"]["frames"] == count + 1, "Pointer replay omitted observations")
        for index, (entry, frame, line) in enumerate(zip(trace, frames, lines)):
            action = "-1" if index == 0 else f"wire:{entry['last_event']:08x}"
            require(line.split() == [f"step-{index:02d}", action] + [str(entry["metrics"][key]) for key in METRIC_NAMES],
                    "Pointer replay differs from actual wire/kernel metrics")
            require(frame["snapshot"] == entry["snapshot"]
                    and frame["runtime_words"] == [entry["metrics"][key] for key in METRIC_NAMES],
                    "Pointer ARM/host state or kernel metrics differ")
            require((entry["metrics"]["version"], entry["metrics"]["valid"], entry["metrics"]["reserved"],
                     entry["metrics"]["working_ram_bytes"]) == (1, 15, 0, working_ram), "Pointer diagnostics allocation mismatch")
            require(entry["metrics"]["events_delivered"] == index, "Pointer kernel metric delivery order mismatch")
            check_render_stats(frame["render_stats"])
        for state in states:
            index, r, u = state["event"], state["record"], state["user"]
            require(u["snapshot"] == trace[index]["snapshot"] and u["metrics"] == trace[index]["metrics"]
                    and u["last_event"] == trace[index]["last_event"], "Stable pointer state does not match full trace")
            require(state["render_metrics"] == frames[index]["render_stats"], "Actual ARM/host update costs differ")
            costs[name + "/" + state["name"]] = check_render_stats(state["render_metrics"])
            require((r["magic"], r["stage"], r["error"], r["sctlr"], r["dacr"], r["pid"], r["queue_len"],
                     r["queue_dropped"], r["api_rejections"], r["events_delivered"])
                    == (0x53484C4C, 2, 0, 0x79, 1, 0, 0, 0, 11, index), "Pointer kernel/control invariant failed")
            require(u["snapshot"]["renders"] == r["frames"] and state["tasks"][1]["state"] == 4,
                    "Pointer Shell did not block after one actual presentation per render")
            context = state["tasks"][1]["context"]
            require(context["cpsr"] & 0xFF == 0x50 and context["kind"] == 2 and context["raw_lr"] == context["pc"]
                    and 0x01000000 <= context["pc"] < 0x01010000 and context["pc"] % 4 == 0
                    and 0x01040000 <= context["sp"] <= 0x01048000 and context["sp"] % 8 == 0
                    and image_word(user_loads, context["pc"] - 4) == 0xEF000000,
                    "Pointer Waiting context is not an actual bounded IRQ-enabled User SVC")
            expected_pointer = None
            wire = u["last_event"]
            if wire >> 24 == 8 and 0xF0000 <= (wire & 0xFFFFFF) <= 0x10FFFF:
                point = (wire & 0xFFFFFF) - 0xF0000
                x, y = point & 255, point >> 8
                if x < 240 and y < 320:
                    expected_pointer = [x, y]
            if "pointer" in state:
                require(state["pointer"] == expected_pointer, "Observed logical pointer does not match actual wire bits")
        require(boot["input_device_rejections"] == (3 if name == "pointer" else 0), "Malformed FIFO coverage missing")
        require(boot["page_tables"] == reference_tables, "Pointer live page tables differ from unchanged isolation contract")
        idle = boot["idle_progress"]
        if count == handled:
            require(idle is not None and idle["after"]["ticks"] >= idle["before"]["ticks"] + 3
                    and idle["after"]["frames"] == idle["before"]["frames"]
                    and idle["busy_counter_after"] > idle["busy_counter_before"]
                    and idle["after"]["busy_preemptions"] > idle["before"]["busy_preemptions"],
                    "Pointer/key reset did not retain idle timer/Busy preemption without redraw")
        else:
            require(idle is None, "Invalid-coordinate session has an unexpected event-count idle observation")
        require(set(map(int, boot["captures"])) == expected_captures
                and boot["parity"]["pixel_comparisons"] == len(expected_captures), "Required Desktop/Today/app/menu pointer captures missing")
        for key, capture in boot["captures"].items():
            index = int(key)
            require(capture["name"] == f"step-{index:02d}", "Unsafe pointer capture name")
            require(capture["generation"] == trace[index]["snapshot"]["renders"], "Pointer capture generation mismatch")
            for field, suffix in (("raw565", ".raw565"), ("png", ".png"), ("ppm", ".ppm")):
                require(capture[field] == capture["name"] + suffix, "Unsafe pointer capture filename")
            raw, png, ppm = (folder / capture[field] for field in ("raw565", "png", "ppm"))
            checked_hash(raw, capture["raw565_sha256"])
            checked_hash(png, capture["png_sha256"])
            pixels = rgb565(raw.read_bytes())
            require(pixels == png_rgb(png) == ppm_rgb(ppm) and sha(pixels) == capture["console_rgb_sha256"],
                    "Pointer actual guest/PNG/QEMU pixels differ")
            host_raw = folder / "host" / frames[index]["file"]
            require(host_raw.parent == folder / "host", "Pointer host frame escapes directory")
            checked_hash(host_raw, capture["host_raw565_sha256"])
            checked_hash(host_raw.with_suffix(".png"), capture["host_png_sha256"])
            require(raw.read_bytes() == host_raw.read_bytes() and pixels == png_rgb(host_raw.with_suffix(".png")),
                    "Pointer actual ARM/host pixels differ")
            add("frames/" + name + "/" + raw.name, raw, True)
            add("frames/" + name + "/" + png.name, png, True)
        captures_total += len(expected_captures)
        add("pointer/" + name + "/host-replay.txt", replay)
        add("pointer/" + name + "/host-frames.json", folder / "host/frames.json")
    require(captures_total == 34, "Pointer comparison count differs from complete suite")
    require(len(costs) == 56, "Stable ARM cost observations contain duplicate or missing labels")
    named = {state["name"]: state for state in result["boots"][0]["states"]}
    expected_views = {"initial": (0, 0, 0), "settings-shortcut": (5, 0, 0), "theme": (5, 0, 1),
        "reset-dialog": (5, 3, 1), "start": (2, 0, 0), "about-row": (3, 0, 0),
        "today-shortcut": (1, 0, 0), "today-diagnostics": (4, 0, 0), "system-menu": (0, 1, 0),
        "menu-today": (1, 0, 0), "outside-menu-no-fallthrough": (0, 0, 0)}
    for label, expected in expected_views.items():
        snapshot = named[label]["user"]["snapshot"]
        require(tuple(snapshot[key] for key in ("screen", "overlay", "theme")) == expected,
                "Missing functional Desktop/Today/Launcher/app/menu/dialog state: " + label)
    for label in ("blank-workspace", "outside-dialog", "about-blank", "top-right-boundary",
                  "invalid-x240", "invalid-x255-y319", "invalid-y320", "invalid-reserved-upper"):
        require(named[label]["render_metrics"] == [0] * 8, "No-op/invalid pointer unexpectedly composed pixels")
    for label in ("keyboard-focus-down", "keyboard-focus-up"):
        value = named[label]["render_metrics"]
        require(value[2] == value[5] == 8352 and value[4] == 2 and value[6:] == [0, 1],
                "Desktop focus did not restore exactly two 72x58 shortcut regions")
    for label in ("system-menu", "menu-open"):
        require(named[label]["render_metrics"][:4] == [0] * 4, "Desktop menu unnecessarily decoded wallpaper")
    for label in ("outside-menu-no-fallthrough",):
        value = named[label]["render_metrics"]
        require(value[2] == 53240 and value[6:] == [0, 1], "Desktop menu dismissal did not restore its bounded covered union")
    for label in ("last-pixel", "menu-keyboard-back"):
        require(named[label]["render_metrics"] == [0] * 8, "Removed bottom bar left a hidden Desktop action")
    for label in ("initial", "app-back", "keyboard-home", "home-again", "home-menu", "launcher-back-home"):
        value = named[label]["render_metrics"]
        require(value[2] == 71040 and value[6:] == [1, 1], "Desktop full entry did not compose its expanded 240x296 content wallpaper")
    require((directory / "pointer/step-02.raw565").read_bytes() == (directory / "keyboard-reset/step-02.raw565").read_bytes(),
            "Stylus and keyboard activation do not open pixel-identical Settings")
    add("pointer/result.json", directory / "result.json")
    return {"result": "PASS", "boots": 3, "delivered_events": 56, "handled_ui_events": 52,
            "pixel_comparisons": 34, "source_sha256": result["source_sha256"], "observed_render_costs": costs,
            "functional_keyframes": {label: f"frames/pointer/step-{index:02d}.png" for label, index in (
                ("desktop", 0), ("desktop_focus", 10), ("today", 19), ("launcher", 12),
                ("open_app", 13), ("system_menu", 24), ("theme", 3), ("dialog", 4))},
            "cost_observations": {"actual_arm_stable_states": len(costs), "host_replayed_states": 59,
                "burst_scope": "Initial/final actual ARM render costs only; intermediate burst state journal has no render-cost fields"},
            "cost_scope": "Software composition and Surface dirty bounds; each rendered frame still publishes 153600 bytes. No CPU-cycle, bus or physical display-latency measurement"}


def bindings(values, required, label):
    require(required <= set(values), label + " did not bind all required source files")
    for name, expected in values.items():
        require(not Path(name).is_absolute() and ".." not in Path(name).parts, "Invalid source binding path")
        checked_hash(ROOT / name, expected)


def check_image(directory, manifest, name, llvm, user=False):
    expected_names = {name + ".elf", name + ".bin"} | (set() if user else {"vectors.bin"})
    require(set(manifest["sha256"]) == expected_names, "Incomplete image manifest: " + name)
    for filename, expected in manifest["sha256"].items():
        checked_hash(directory / filename, expected)
    entry, loads = elf_loads(directory / (name + ".elf"))
    require(entry == manifest["entry"], "ELF entry/manifest mismatch")
    segments = [{k: value for k, value in load.items() if k != "bytes"} for load in loads]
    if not user:
        segments = [{k: value for k, value in segment.items() if k != "va"} for segment in segments]
    require(segments == manifest["segments"], "ELF segments/manifest mismatch")
    raw = (directory / (name + ".bin")).read_bytes()
    for load in loads:
        if not user and load["pa"] == 0:
            require(load["filesz"] == load["memsz"] == 64 and load["bytes"] == (directory / "vectors.bin").read_bytes(), "Vector payload mismatch")
        elif load["filesz"]:
            offset = load["pa"] - entry
            require(offset >= 0 and raw[offset:offset + load["filesz"]] == load["bytes"], "ELF/flat payload mismatch")
    symbols = {}
    for line in subprocess.check_output([str(llvm / "llvm-nm"), "--defined-only", "--format=posix", str(directory / (name + ".elf"))], text=True).splitlines():
        fields = line.split()
        if len(fields) >= 3:
            symbols[fields[0]] = int(fields[2], 16)
    require(symbols == manifest["symbols"], "Stale image symbol manifest")
    for filename, args in (("disassembly.txt", ("llvm-objdump", "-d")),
                           ("size.txt", ("llvm-size",)),
                           ("elf-report.txt", ("llvm-readobj", "--file-headers", "--program-headers", "--arch-specific"))):
        actual = subprocess.check_output([str(llvm / args[0]), *args[1:], str(directory / (name + ".elf"))])
        require((directory / filename).read_bytes() == actual, "Stale machine-code text evidence: " + filename)
    return loads


def rgb565(raw):
    require(len(raw) == FB_BYTES, "Framebuffer must be exactly 153600 bytes")
    rgb = bytearray()
    for (pixel,) in struct.iter_unpack("<H", raw):
        red, green, blue = pixel >> 11, pixel >> 5 & 63, pixel & 31
        rgb.extend(((red << 3) | (red >> 2), (green << 2) | (green >> 4), (blue << 3) | (blue >> 2)))
    return bytes(rgb)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=ROOT / "target/artifacts")
    parser.add_argument("--qemu-cache", type=Path, default=ROOT / "local/qemu-display-test")
    parser.add_argument("--llvm", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/wave007-2")
    parser.add_argument("--accepted-kernel", type=Path,
                        help="Original accepted Wave007.1 ELF, default artifacts/wave007-2/baseline/accepted-crosshair-shell.elf")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    artifacts, output = args.artifacts.resolve(), args.output.resolve()
    accepted, baseline, flats, preserved_reports = check_baseline(artifacts, output, args.accepted_kernel)

    shell_dir = artifacts / "shell"
    summary = read_json(shell_dir / "execution/result.json")
    require(summary["result"] == "PASS" and summary["boots_completed"] == 4 and len(summary["boots"]) == 4,
            "Need complete four-boot Shell execution PASS")
    require((summary["machine"], summary["accelerator"]) == (MACHINE, "tcg"), "Wrong Shell execution platform")
    asset_sources = {str(path.relative_to(ROOT)) for path in (ROOT / "shell/assets").rglob("*")
                     if path.is_file() and path.name != ".DS_Store" and "__pycache__" not in path.parts}
    asset_sources |= {str(path.relative_to(ROOT)) for path in (ROOT / "shell/tools").glob("*.py")}
    asset_sources |= {str(path.relative_to(ROOT)) for path in (ROOT / "shell/src").glob("*.rs")}
    bindings(summary["source_sha256"], REQUIRED_SOURCES | asset_sources, "Shell execution")
    icons = read_json(ROOT / "shell/assets/tabler/PROVENANCE.json")
    require(icons["schema"] == "crosshair-tabler-assets-v1" and len(icons["icons"]) == 18
            and icons["sizes"] == [12, 16, 24] and icons["mask_bytes"] == 2196 and icons["mutable_bytes"] == 0
            and icons["license"]["spdx"] == "MIT", "Incomplete pinned Tabler catalog/rights/budget")
    icon_check = subprocess.check_output([sys.executable, str(ROOT / "shell/tools/generate_icons.py"), "--check"], text=True).strip()
    require(icon_check.startswith("Tabler icons PASS:"), "Offline pinned SVG/license/generator/output check failed")
    image = read_json(shell_dir / "image/image.json")
    user = read_json(shell_dir / "user-image/user-image.json")
    require(summary["image_sha256"] == image["sha256"] and summary["user_image_sha256"] == user["sha256"], "Execution/image identity mismatch")
    loads = check_image(shell_dir / "image", image, "crosshair-shell", args.llvm)
    user_loads = check_image(shell_dir / "user-image", user, "crosshair-shell-user", args.llvm, True)
    user_flat = (shell_dir / "user-image/crosshair-shell-user.bin").read_bytes()
    require([load["bytes"] for load in loads if load["pa"] == 0xA0400000] == [user_flat], "Kernel does not embed the exact tested User image")
    generated = (ROOT / "shell/src/icon_assets.rs").read_bytes()
    array = generated.split(b"pub static ICON_MASK_DATA: [u8; MASK_BYTES] = [\n", 1)[1].split(b"];", 1)[0]
    mask_data = bytes(int(value, 16) for value in re.findall(rb"0x([0-9a-f]{2})", array))
    require(len(mask_data) == 2196 and sha(mask_data) == icons["mask_sha256"], "Generated Tabler mask pool mismatch")
    mask_offset = user_flat.find(mask_data)
    require(mask_offset >= 0 and user_flat.find(mask_data, mask_offset + 1) == -1, "Need exactly one complete Tabler mask pool in actual User image")
    mask_va = user["entry"] + mask_offset
    require(any(load["flags"] == 5 and load["pa"] <= mask_va and mask_va + 2196 <= load["pa"] + load["filesz"] for load in user_loads),
            "Actual Tabler masks must reside in the Shell RO code/constant allocation")
    wallpaper = check_wallpaper(user_flat, user_loads, user)
    build = read_json(args.qemu_cache / "evidence/source.json")
    accepted_build = json.loads(git_bytes(BASE, "reports/wave004/build/source.json"))
    runtime = (args.qemu_cache / "bin/qemu-system-arm").resolve()
    require(build == accepted_build and sha(runtime.read_bytes()) == summary["qemu_sha256"] == build["qemu_sha256"], "Shell must use unchanged accepted display runtime")
    for name, field in (("crosshair-blueangel-display-test.c", "overlay_sha256"), ("crosshair-blueangel-e2a.c", "included_e2a_sha256"), ("crosshair-blueangel-e2b.c", "included_e2b_sha256")):
        checked_hash(ROOT / "crosshair-emulator/qemu" / name, build[field])
    require(Path(summary["command"][0]).resolve() == runtime, "Shell command used another runtime")
    symbols, user_symbols = image["symbols"], user["symbols"]
    kernel = symbols["__image_end"] - symbols["_start"]
    working_ram = kernel + 64 + 74 * 4096
    memory = {
        "address_type": "guest physical except explicitly marked User VA",
        "kernel_start": symbols["_start"], "kernel_end": symbols["__image_end"],
        "kernel_reserved_extent_bytes": kernel,
        "kernel_bss_bytes": symbols["__bss_end"] - symbols["__bss_start"],
        "banked_stacks_bytes": {prefix: symbols[prefix + "_top"] - symbols[prefix + "_bottom"] for prefix in ("__stack", "__irq_stack", "__abort_stack", "__undef_stack")},
        "idle_stack_bytes": 4096, "idle_context_bytes": 80,
        "l1_total_bytes": 32768, "l2_total_bytes": 2048,
        "task_table_bytes": 288, "kernel_event_queue_bytes": 16,
        "vectors_bytes": 64, "busy_user_mapped_bytes": 12288,
        "shell_user_code_reserved_bytes": 65536, "shell_user_data_reserved_bytes": 192512,
        "shell_user_stack_reserved_bytes": 32768, "shell_user_mapped_bytes": 71 * 4096,
        "guard_holes_reserved_unmapped_bytes": 8192,
        "mapped_working_ram_bytes": working_ram,
        "reserved_extent_including_guards_bytes": working_ram + 8192,
        "shell_user_bss_bytes": user_symbols["__user_bss_end"] - user_symbols["__user_bss_start"],
        "framebuffers_in_guest": 1, "framebuffer_pixel_bytes": FB_BYTES, "framebuffer_guard_bytes": 128,
        "user_record_bytes": 176, "user_metrics_bytes": 48, "user_trace_capacity": 64, "user_trace_entry_bytes": 128,
        "user_trace_bytes": 8192, "user_render_metrics_bytes": 32,
        "user_ux_metrics_bytes": 80, "user_ux_trace_bytes": 5120, "user_render_trace_bytes": 2048,
        "kernel_flat_file_bytes": (shell_dir / "image/crosshair-shell.bin").stat().st_size,
        "kernel_elf_file_bytes": (shell_dir / "image/crosshair-shell.elf").stat().st_size,
        "user_flat_file_bytes": len(user_flat), "user_elf_file_bytes": (shell_dir / "user-image/crosshair-shell-user.elf").stat().st_size,
        "sparse_flat_gaps_are_not_working_ram": True,
    }
    require(memory["shell_user_bss_bytes"] == FB_BYTES + 128 + 176 + 48 + 8192 + 32 + 80 + 5120 + 2048,
            "User BSS no longer equals one guarded framebuffer plus declared record/metrics/journal/render stats/UX observations")
    memory["user_static_allocations"] = check_user_static_layout(shell_dir / "user-image", user, args.llvm)
    memory["shell_user_data_reservation_unused_bytes"] = 192512 - memory["shell_user_bss_bytes"]
    require(user_symbols["SHELL_FRAMEBUFFER"] == 0x01010000 and user_symbols["SHELL_TRACE"] + 8192 <= 0x0103F000,
            "User framebuffer/journal allocation exceeds data/guard boundary")
    require(symbols["__bss_start"] <= symbols["SHELL_L1"] <= symbols["__bss_end"] - 32768
            and symbols["__bss_start"] <= symbols["SHELL_L2"] <= symbols["__bss_end"] - 2048, "Page tables outside own kernel BSS")
    type_path = shell_dir / "user-image/type-sizes.txt"
    type_text = type_path.read_text()
    checked_hash(ROOT / "target/armv5te-none-eabi/release/crosshair-shell-user", user["sha256"]["crosshair-shell-user.elf"])
    type_sizes = {}
    for name, expected in (("crosshair_shell::Shell", (296, 4)), ("crosshair_ui::Surface<'_>", (88, 4)),
                           ("crosshair_shell::Snapshot", (64, 4)), ("crosshair_shell::RuntimeInfo", (48, 4)),
                           ("crosshair_shell::RenderStats", (32, 4)), ("crosshair_shell::wallpaper::DrawStats", (16, 4)),
                           ("crosshair_shell::UxSnapshot", (80, 4)), ("Framebuffer", (153728, 8))):
        match = re.search(r"print-type-size type: `" + re.escape(name) + r"`: (\d+) bytes, alignment: (\d+) bytes", type_text)
        require(match is not None, "Missing actual ARM type layout: " + name)
        observed = tuple(map(int, match.groups()))
        require(observed == expected, "Unexpected actual ARM type layout: " + name)
        type_sizes[name] = {"bytes": observed[0], "alignment": observed[1]}
    memory["arm_type_sizes"] = type_sizes
    memory["delta_from_wave007_1"] = {key: memory[key] - accepted["memory"][key] for key in (
        "kernel_reserved_extent_bytes", "kernel_bss_bytes", "mapped_working_ram_bytes", "shell_user_bss_bytes",
        "kernel_flat_file_bytes", "kernel_elf_file_bytes", "user_flat_file_bytes", "user_elf_file_bytes")}
    memory["user_ro_code_window_remaining_bytes"] = 65536 - len(user_flat)
    memory["wallpaper_ro_payload_bytes"] = wallpaper["provenance"]["payload_bytes"]
    memory["wallpaper_persistent_decode_buffer_bytes"] = 0
    require(memory["user_ro_code_window_remaining_bytes"] >= 0, "Shell exceeds existing 64KiB RO code allocation")
    check_kernel_loads(loads)
    copies, statuses, protocols = {}, {}, {}

    def add(relative, source, binary=False):
        require(relative not in copies and source.is_file(), "Duplicate or missing evidence: " + relative)
        if binary:
            require(re.fullmatch(r"frames/(?:canonical|burst-reset|fault-reset|role-reset|pointer|keyboard-reset|pointer-burst-reset|phases|adaptive-reset)/step-\d{2}\.(?:png|raw565)", relative) is not None,
                    "Only validated own Shell framebuffer assets may be copied")
        else:
            export.safe_name("reports/wave007-2/" + relative)
        copies[relative] = (source, binary)
        if source.suffix == ".json":
            data = read_json(source)
            if "result" in data:
                require(data["result"] in ("PASS", "PASS_WITH_RECORDED_MODEL_LIMITATIONS"), "Cannot collect failed evidence: " + relative)
                statuses[relative] = data["result"]

    add("shell/result.json", shell_dir / "execution/result.json")
    total_captures = 0
    require([boot["name"] for boot in summary["boots"]] == ["canonical", "burst-reset", "fault-reset", "role-reset"], "Missing reset/burst/fault Shell boots")
    for boot_index, boot in enumerate(summary["boots"]):
        name = boot["name"]
        require((boot["scenario"], boot["batch_size"]) == ((1, 1) if name == "fault-reset" else (2, 1) if name == "role-reset" else (0, 4) if name == "burst-reset" else (0, 1)), "Wrong scenario/batch contract")
        directory = shell_dir / "execution" / name
        trace, count = boot["trace"], boot["events"]
        require(count == (48 if name == "burst-reset" else 4 if name == "role-reset" else 44) and len(trace) == count + 1 and count < 64,
                "Incomplete Shell navigation or journal")
        require(trace[0]["snapshot"]["screen"] == trace[0]["snapshot"]["theme"] == 0, "Boot did not start on default Desktop")
        require([entry["snapshot"]["events_processed"] for entry in trace] == list(range(count + 1)), "Missing or reordered User journal entries")
        require(boot["parity"]["frames"] == count + 1, "Host replay omitted User journal states")
        replay = directory / "host-replay.txt"
        checked_hash(replay, boot["parity"]["host_replay_sha256"])
        replay_lines = replay.read_text().splitlines()
        require(len(replay_lines) == len(trace), "Replay trace length mismatch")
        host_manifest = read_json(directory / "host/frames.json")
        require(host_manifest["schema"] == "crosshair-shell-frames-v1" and host_manifest["pixel_format"] == "RGB565_LE", "Wrong host replay schema")
        frames = host_manifest["frames"]
        require(len(frames) == len(trace), "Missing host replay states")
        for index, (entry, host, line) in enumerate(zip(trace, frames, replay_lines)):
            fields = line.split()
            expected_action = "-1" if index == 0 else f"wire:{entry['last_event']:08x}"
            require(fields == [f"step-{index:02d}", expected_action] + [str(entry["metrics"][key]) for key in METRIC_NAMES], "Replay input/metrics differs from actual User journal")
            require(host["snapshot"] == entry["snapshot"] and host["runtime_words"] == [entry["metrics"][key] for key in METRIC_NAMES], "Host/ARM state or metrics mismatch")
            require(entry["metrics"]["working_ram_bytes"] == working_ram and entry["metrics"]["valid"] == 15
                    and entry["metrics"]["version"] == 1 and entry["metrics"]["reserved"] == 0, "User diagnostics not bound to actual allocation")
        idle = boot["idle_progress"]
        require(idle["after"]["ticks"] >= idle["before"]["ticks"] + 3 and idle["after"]["frames"] == idle["before"]["frames"], "Waiting Shell has no real timer progress or redraws without input")
        if name != "fault-reset":
            require(idle["busy_counter_after"] > idle["busy_counter_before"] and idle["after"]["busy_preemptions"] > idle["before"]["busy_preemptions"], "Independent Busy loop did not progress/preempt while Shell waited")
        else:
            require(boot["final_user"]["metrics"]["faulted_tasks"] == 1 and boot["final_record"]["last_fault_kind"] == 1, "No actual companion UNDEF isolation")
            idle_registers = boot["fault_idle_registers"]
            require(register(idle_registers, "PSR") & 0xFF == 0x5F
                    and register(idle_registers, "R15") == symbols["shell_idle_loop"]
                    and register(idle_registers, "R13") == symbols["SHELL_IDLE_STACK"] + 4096
                    and image_word(loads, symbols["shell_idle_loop"]) == 0xEAFFFFFE,
                    "Fault recovery did not enter the actual IRQ-enabled System Idle loop/private stack")
        if name == "role-reset":
            require(boot["role_probe_returns"] == [0xFFFFFFFF] * 3
                    and boot["states"][-1]["tasks"][0]["svc_count"] == 3,
                    "Missing actual Busy caller-rights EPERM return evidence")
        require(len(boot["page_tables"]) == 2, "Missing complete live page-table observations")
        for task, observed in enumerate(boot["page_tables"]):
            l1_pa, l2_pa = symbols["SHELL_L1"] + task * 16384, symbols["SHELL_L2"] + task * 1024
            first, second = [0] * 4096, [0] * 256
            for section in [0, 0x100, *range(0x400, 0x410), *range(0xA00, 0xA80)]:
                first[section] = section << 20 | 0x402
            first[16] = l2_pa | 1
            if task == 0:
                second[:4] = [0xA0200AA2, 0xA0201FF2, 0, 0xA0203FF2]
            else:
                for page in range(16):
                    second[page] = 0xA0400000 + page * 4096 | 0xAA2
                for page in [*range(16, 63), *range(64, 72)]:
                    second[page] = 0xA0400000 + page * 4096 | 0xFF2
            require((observed["task"], observed["l1_physical"], observed["l2_physical"], observed["l1_sha256"], observed["l2_sha256"], observed["user_mapped_pages"])
                    == (task, l1_pa, l2_pa, sha(struct.pack("<4096I", *first)), sha(struct.pack("<256I", *second)), 3 if task == 0 else 71),
                    "Observed full page tables differ from the allocated isolation contract")
        final = boot["final_record"]
        require((final["magic"], final["stage"], final["error"], final["sctlr"], final["dacr"], final["pid"], final["queue_len"], final["api_rejections"])
                == (0x53484C4C, 2, 0, 0x79, 1, 0, 0, 14 if name == "role-reset" else 11), "Final kernel/API control invariant failed")
        require(final["events_delivered"] == count and boot["final_user"]["snapshot"]["events_processed"] == count, "Kernel/User event counts differ")
        require((final["queue_dropped"], boot["input_device_rejections"]) == ((4, 2) if name == "burst-reset" else (0, 0)), "Missing independent queue overflow coverage")
        captures = boot["captures"]
        require(len(captures) == boot["parity"]["pixel_comparisons"] and "0" in captures, "Missing capture/parity evidence")
        expected_captures = {0, 8, 20, 28, 48} if name == "burst-reset" else {0, 1, 2, 4} if name == "role-reset" else {
            0, 1, 2, 4, 6, 7, 9, 10, 13, 15, 16, 18, 19, 24, 29, 33, 37, 38, 44}
        require(set(map(int, captures)) == expected_captures, "Required functional Shell keyframes are incomplete")
        for key, capture in captures.items():
            index = int(key)
            require(0 <= index <= count and capture["name"] == f"step-{index:02d}", "Unsafe capture name")
            for field, suffix in (("raw565", ".raw565"), ("png", ".png"), ("ppm", ".ppm")):
                require(capture[field] == capture["name"] + suffix, "Unexpected capture filename")
            raw, png, ppm = (directory / capture[field] for field in ("raw565", "png", "ppm"))
            checked_hash(raw, capture["raw565_sha256"])
            checked_hash(png, capture["png_sha256"])
            rgb = rgb565(raw.read_bytes())
            require(rgb == png_rgb(png) == ppm_rgb(ppm) and sha(rgb) == capture["console_rgb_sha256"], "Actual guest/PNG/QEMU console pixels differ")
            host_raw = directory / "host" / frames[index]["file"]
            require(host_raw.parent == directory / "host", "Host frame path escapes replay directory")
            checked_hash(host_raw, capture["host_raw565_sha256"])
            checked_hash(host_raw.with_suffix(".png"), capture["host_png_sha256"])
            require(raw.read_bytes() == host_raw.read_bytes() and rgb == png_rgb(host_raw.with_suffix(".png")), "Actual ARM/host framebuffer parity failed")
            add("frames/" + name + "/" + raw.name, raw, True)
            add("frames/" + name + "/" + png.name, png, True)
        total_captures += len(captures)
        add("shell/" + name + "/host-replay.txt", replay)
        add("shell/" + name + "/host-frames.json", directory / "host/frames.json")
    require(summary["pixel_comparisons"] == total_captures == 47, "Shell total pixel comparison count mismatch")
    pointer = collect_pointer(shell_dir, image, user, user_loads, runtime, working_ram, summary["boots"][0]["page_tables"], add)
    adaptive = collect_adaptive(shell_dir, image, user, user_loads, runtime, working_ram, summary["boots"][0]["page_tables"], add)
    costs = processing_cost(accepted, read_json(shell_dir / "pointer/result.json"), adaptive)
    require((shell_dir / "execution/qemu-uart.log").read_bytes() == START_UART * 4, "Unexpected Shell reset UART bytes")
    for label, directory in (("shell", shell_dir / "execution"),
                             ("pointer", shell_dir / "pointer"),
                             ("adaptive", shell_dir / "adaptive"),
                             ("gui/pipeline", shell_dir / "gui/pipeline"),
                             ("gui/window-test", shell_dir / "gui/window-test"),
                             ("gui/pointer-window-test", shell_dir / "gui/pointer-window-test"),
                             ("gui/adaptive-window-test", shell_dir / "gui/adaptive-window-test")):
        require((directory / "qemu-uart.log").read_bytes() == START_UART * (4 if label == "shell" else 3 if label == "pointer" else 2 if label == "adaptive" else 1),
                "Unexpected automated guest UART bytes: " + label)
        for filename in ("qemu-uart.log", "qemu-stderr.log"):
            add(label + "/" + filename, directory / filename)
        if label.startswith("gui/"):
            add(label + "/frontend-stderr.log", directory / "frontend-stderr.log")
        for filename in ("memory-protocol.log", "memory-server.log"):
            path = directory / filename
            require(path.is_file() and path.stat().st_size > 0, "Missing actual observer protocol")
            protocols[label + "/" + filename] = {"bytes": path.stat().st_size, "sha256": sha(path.read_bytes())}
    for label, directory, manifest in (("image", shell_dir / "image", "image.json"), ("user-image", shell_dir / "user-image", "user-image.json")):
        for filename in (manifest, "size.txt", "elf-report.txt", "disassembly.txt"):
            add(label + "/" + filename, directory / filename)
    add("user-image/type-sizes.txt", type_path)
    add("host/tests.log", shell_dir / "host/tests.log")
    for filename in ("icon-check.log", "icon-tests.log", "icon-regenerate.log",
                     "wallpaper-check.log", "wallpaper-tests.log", "wallpaper-regenerate.log"):
        add("host/" + filename, shell_dir / "host" / filename)
    require("Tabler icons PASS:" in (shell_dir / "host/icon-check.log").read_text()
            and "regenerated" in (shell_dir / "host/icon-regenerate.log").read_text(), "Missing exact source/output and pinned raster regeneration checks")
    icon_tests = (shell_dir / "host/icon-tests.log").read_text()
    require("Ran 6 tests" in icon_tests and icon_tests.rstrip().endswith("OK"), "SVG corruption/source-binding tests did not pass")
    require("Wallpaper PASS:" in (shell_dir / "host/wallpaper-check.log").read_text()
            and "pinned regeneration" in (shell_dir / "host/wallpaper-regenerate.log").read_text(),
            "Missing source-bound and pinned wallpaper raster regeneration checks")
    wallpaper_tests = (shell_dir / "host/wallpaper-tests.log").read_text()
    require(re.search(r"Ran [1-9]\d* tests", wallpaper_tests) and wallpaper_tests.rstrip().endswith("OK"),
            "Wallpaper corruption/format tests did not pass")
    for filename in ("PROVENANCE.json", "LICENSE", "requirements.txt", "requirements.lock.json"):
        add("icons/" + filename, ROOT / "shell/assets/tabler" / filename)
    for filename in ("PROVENANCE.json", "PROMPT.txt"):
        add("wallpaper/" + filename, ROOT / "shell/assets/wallpaper" / filename)
    host_log = (shell_dir / "host/tests.log").read_text()
    require(re.search(r"test result: ok\. [1-9]\d* passed; 0 failed", host_log) is not None, "Shell host tests did not pass")

    pipeline = read_json(shell_dir / "gui/pipeline-result.json")
    require((pipeline["result"], pipeline["mode"], pipeline["events"]) == ("PASS", "headless-pipeline-test", 6), "Native frontend pipeline did not complete")
    require(pipeline["logs"] == "pipeline", "Native pipeline logs must be separate from manual input")
    require(pipeline["single_write_events"] == 3, "Native input batch/read-ahead regression was not exercised")
    require(pipeline["image_sha256"] == image["sha256"] and pipeline["user_image_sha256"] == user["sha256"], "Native pipeline used another image")
    require(pipeline["qemu_sha256"] == summary["qemu_sha256"] and Path(pipeline["command"][0]).resolve() == runtime, "Native pipeline runtime mismatch")
    bindings(pipeline["source_sha256"], GUI_SOURCES, "Native frontend pipeline")
    checked_hash(shell_dir / "gui/crosshair-gui", pipeline["frontend_sha256"])
    require(pipeline["native_self_test"].startswith("PASS Crosshair GUI:"), "Native keymap/PPM self-test missing")
    require("pointer scale/letterbox/bounds" in pipeline["native_self_test"], "Native pointer coordinate self-test missing")
    require((pipeline["native_frame_inspection"]["width"], pipeline["native_frame_inspection"]["height"], pipeline["native_frame_inspection"]["rgb_bytes"]) == (240, 320, 230400), "Native frontend frame geometry mismatch")
    require(sha(ppm_rgb(shell_dir / "gui/pipeline-final.ppm")) == pipeline["final_console_rgb_sha256"], "Native pipeline final QEMU frame mismatch")
    add("gui/pipeline-result.json", shell_dir / "gui/pipeline-result.json")
    for filename in ("swift-version.txt", "compile-command.txt", "compile.log", "native-self-test.log", "source-sha256.txt"):
        add("gui/" + filename, shell_dir / "gui" / filename)
    require(pipeline["swift_version"] == (shell_dir / "gui/swift-version.txt").read_text()
            and pipeline["compile_command"] == (shell_dir / "gui/compile-command.txt").read_text()
            and pipeline["native_self_test"] == (shell_dir / "gui/native-self-test.log").read_text().strip(),
            "Native build/self-test logs differ from pipeline evidence")
    require((shell_dir / "gui/source-sha256.txt").read_text().strip() == sha((ROOT / "tools/crosshair_gui.swift").read_bytes()),
            "Compiled native frontend source binding is stale")
    window_wires = [hardware_key_wire(edge, key) for key in (11, 4, 5, 7) for edge in (0, 2)]
    window = collect_native_window(shell_dir, "window-test", [2, 2, 3, 3, 2, 2, 0, 0], window_wires,
        image, user, summary, pipeline, runtime, protocols, add)
    pointer_wires = [pointer_phase_wire(1,40,68), pointer_phase_wire(3,40,68),
        hardware_key_wire(0,5), hardware_key_wire(2,5), pointer_phase_wire(1,12,8), pointer_phase_wire(3,12,8),
        0x0800041E, hardware_key_wire(0,4), hardware_key_wire(2,4), pointer_phase_wire(1,227,12),
        pointer_phase_wire(3,227,12), hardware_key_wire(0,7), hardware_key_wire(2,7)]
    native_pointer = collect_native_window(shell_dir, "pointer-window-test", [0,1,0,0,0,2,2,3,3,3,2,0,0], pointer_wires,
        image, user, summary, pipeline, runtime, protocols, add)
    adaptive_wires = [pointer_phase_wire(1,40,68), pointer_phase_wire(2,130,150), pointer_phase_wire(2,40,68),
        pointer_phase_wire(3,40,68), pointer_phase_wire(1,40,68), None, pointer_phase_wire(3,40,68),
        hardware_key_wire(0,5), hardware_key_wire(2,5), hardware_key_wire(0,1), hardware_key_wire(1,1),
        hardware_key_wire(1,1), hardware_key_wire(2,1), hardware_key_wire(0,4), hardware_key_wire(2,4),
        hardware_key_wire(0,12), hardware_key_wire(2,12), pointer_phase_wire(1,30,214), pointer_phase_wire(3,30,214),
        hardware_key_wire(0,12), hardware_key_wire(2,12), pointer_phase_wire(1,30,240), pointer_phase_wire(3,30,240),
        pointer_phase_wire(1,230,8), pointer_phase_wire(3,230,8), pointer_phase_wire(1,30,188), pointer_phase_wire(3,30,188),
        hardware_key_wire(0,7), hardware_key_wire(2,7)]
    native_adaptive = collect_native_window(shell_dir, "adaptive-window-test", [0]*13 + [4]*14 + [0]*2, adaptive_wires,
        image, user, summary, pipeline, runtime, protocols, add)
    native_events = native_adaptive["events"]
    require(native_events[0]["ux"]["pointer_active"] == 1 and native_events[0]["ux"]["actions_invoked"] == 0
        and native_events[3]["ux"]["pointer_active"] == native_events[3]["ux"]["actions_invoked"] == 0
        and native_events[5]["ux"]["panel"] == 4 and native_events[5]["ux"]["pointer_active"] == 0
        and [native_events[index-1]["snapshot"]["desktop_selected"] for index in (10,11,12)] == [1,2,2]
        and native_events[12]["ux"]["held_keys"] == 0
        and [native_events[index-1]["ux"]["chrome_mode"] for index in (19,23,27)] == [1,2,0],
        "Native source-measured hold/cancel/repeat/adaptive modes were not observed in actual ARM")

    log_path = artifacts / "wave007-2/all-tests.log"
    full_log = log_path.read_text()
    require(full_log.rstrip().endswith(ADAPTIVE_WINDOW_SENTINEL) and POINTER_WINDOW_SENTINEL in full_log and WINDOW_SENTINEL in full_log
            and GUI_SENTINEL in full_log and OLD_TASK_SENTINEL in full_log,
            "Full Wave007.2 log lacks final adaptive/native pointer/window/pipeline and prior task success")
    require("PASS adaptive Shell: 2 real ARM boots, 75 input records, 24 host/ARM/QEMU pixels; phases/keys/chrome/loss recovery and Busy progress" in full_log,
            "Full run omitted complete adaptive ARM input/modes/recovery checks")
    require("PASS User pointer: 3 real ARM boots, 56 delivered events, 34 host/ARM/QEMU pixels; coordinate bounds/malformed/keyboard/updatecost checks" in full_log,
            "Full run omitted complete ARM pointer/keyboard/updatecost checks")
    require("Ran 7 tests" in full_log and "test_coordinate_bits_and_bounds" in full_log
            and "test_malformed_or_untrusted_frontend_lines" in full_log
            and "test_atomic_phases_and_hardware_edges_do_not_alias" in full_log
            and "test_physical_source_lines_and_measured_hold_validation" in full_log,
            "Full run omitted native transport/coordinate corruption tests")
    require(len(re.findall(r"^PASS security case\d\d:", full_log, re.M)) == 24
            and len(re.findall(r"^PASS tasks case\d\d:", full_log, re.M)) == 8, "Full run lacks fresh complete Security/task regressions")
    require(f"PASS User Shell: 4 real ARM boots, reset/burst/queue overflow/API checks, {total_captures} host/ARM/QEMU pixel comparisons" in full_log,
            "Full log does not bind complete Shell execution")
    add("all-tests.log", log_path)
    prior = read_json(artifacts / "tasks-tests/result.json")
    require((prior["result"], prior["complete_suite"], prior["case_count"], prior["boots"]) == ("PASS", True, 8, 16), "Current Wave006 regression incomplete")
    # Cargo/build changed intentionally, but the task sources recorded by this
    # fresh full run must still match their current bytes.
    bindings(prior["source_sha256"], set(), "Wave006 regression")
    require(prior["image_sha256"] == read_json(artifacts / "tasks/image/image.json")["sha256"], "Current task image mismatch")
    add("regressions/tasks-result.json", artifacts / "tasks-tests/result.json")
    for entry in prior["cases"]:
        require(entry["result"] == "PASS" and entry["boots"] == 2, "Current task case incomplete")
        add(f"regressions/tasks-case-{entry['selector']:02d}.json", artifacts / "tasks-tests" / entry["evidence"])
    regression_files = [
        ("versatilepb.json", "versatilepb/smoke-test.json"), ("versatilepb-panic.json", "versatilepb-panic/smoke-test.json"),
        ("security-result.json", "security-tests/result.json"), ("display-execution.json", "display-test/execution/result.json"),
        ("display-qtest.json", "display-qtest/result.json"), ("ui-validation.json", "ui/validation.json"),
        ("ui-tests.log", "ui/tests.log"), ("missing-reference-check.json", "wave004/missing-reference-check.json"),
    ]
    for board in ("connex", "verdex", "mainstone"):
        regression_files += [(f"e1-{board}-tcg.json", f"pxa-reference/{board}/smoke-test.json"), (f"e1-{board}-qtest.json", f"pxa-qtest/{board}/qtest-result.json")]
    for wave, scenarios in (("e2a", ("boot-reset", "fault-1", "fault-2", "fault-3", "fault-4")), ("e2b", ("gpio-boot-reset", "fault-1", "fault-2", "fault-3", "fault-4", "fault-5"))):
        regression_files += [(f"{wave}-{scenario}.json", f"{wave}-tests/{scenario}/result.json") for scenario in scenarios]
        regression_files.append((wave + "-qtest.json", wave + "-qtest/result.json"))
    for relative, source in regression_files:
        add("regressions/" + relative, artifacts / source)
    for filename in ("source.json", "version.txt", "machines.txt", "cpus.txt", "host-tools.txt", "resolved-devices.mak", "loader.txt"):
        add("build/" + filename, args.qemu_cache / "evidence" / filename)

    payloads, copied, originals = {}, {}, {}
    for relative, (source, binary) in copies.items():
        original = source.read_bytes()
        if binary:
            payload = original
        else:
            text = original.decode("utf8")
            for path, replacement in ((args.qemu_cache.resolve(), "<qemu-cache>"), (artifacts, "<artifacts>"), (ROOT, "<workspace>")):
                text = text.replace(str(path), replacement)
            text = export.normalize(text, ROOT.parent.parent)
            require(not (export.PRIVATE_PATH.search(text) or export.LOCAL_HOST.search(text) or export.SECRET.search(text)), "Private material in evidence: " + relative)
            payload = text.encode()
            if source.name == "qemu-uart.log":
                require(payload == original, "Normalization changed actual UART bytes")
        payloads[relative], copied[relative] = payload, sha(payload)
        originals[relative] = {"bytes": len(original), "sha256": sha(original)}
    extra_sources = ("tools/collect_wave007_2_evidence.py", "tools/collect_wave007_1_evidence.py", "tools/collect_wave007_evidence.py", "tools/collect_wave006_evidence.py", "scripts/export-public.py",
                     "tools/pack_repomix.py", "scripts/pack-repomix.sh", "repomix.config.json")
    validation = {
        "result": "PASS", "accepted_base": BASE,
        "scope": "Complete prior safety chain plus 3 legacy tap/key and 2 adaptive capture/key/mode/recovery ARM boots on unchanged kernel/display model; native NSWindow key/pointer/hold adapters, real state/pixels/software work counts; no physical PDA validation",
        "normalization": "host/workspace/cache/socket paths and hostnames only; UART and validated framebuffer PNG/raw565 byte-exact",
        "shell": {"result": "PASS", "boots": 4, "events": sum(boot["events"] for boot in summary["boots"]),
                  "pixel_comparisons": total_captures, "image_sha256": image["sha256"], "user_image_sha256": user["sha256"], "qemu_sha256": summary["qemu_sha256"]},
        "native_frontend": {"status": "Headless pipeline and actual NSWindow/NSApp-posted key/pointer/move/measured-hold paths PASS; extended manual use remains separate evidence",
            "frontend_sha256": pipeline["frontend_sha256"], "pipeline_input_records": pipeline["events"],
            "window_key_records": len(window["events"]), "window_pointer_key_text_records": len(native_pointer["events"]),
            "window_adaptive_records": len(native_adaptive["events"]), "measured_holds_ms": native_adaptive["measured_holds_ms"]},
        "memory": memory, "results": statuses, "wallpaper": wallpaper, "desktop_pointer": pointer,
        "adaptive_ux": adaptive, "event_processing_cost": costs,
        "icons": {"upstream": icons["upstream"], "commit": icons["commit"], "license": icons["license"],
                  "selected_svg_count": 18, "sizes": icons["sizes"], "mask_bytes": 2196, "mutable_bytes": 0,
                  "generated_sha256": icons["generated_sha256"], "generator_sha256": icons["generator_sha256"],
                  "runtime_mask_user_va": mask_va, "runtime_mask_physical": 0xA0400000 + mask_offset,
                  "runtime_mask_sha256": sha(mask_data), "runtime_mask_allocation": "single read-only initialized User ELF segment",
                  "collector_offline_binding_check": icon_check},
        "source_sha256": summary["source_sha256"], "native_source_sha256": pipeline["source_sha256"],
        "collector_publication_source_sha256": {name: sha((ROOT / name).read_bytes()) for name in extra_sources},
        "intentional_baseline_source_changes": sorted(MUTABLE_BASELINE),
        "intentional_version_metadata_changes": {"files": sorted(VERSION_METADATA),
            "scope": "Exactly crosshair-shell package 0.1.1-to-0.1.2; every other byte and dependency graph unchanged"},
        "intentional_ui_module_export": {"path": UI_MODULE_EXPORT,
            "scope": "Only pub mod pda immediately after pub mod font; every existing renderer byte unchanged",
            "sha256": sha((ROOT / UI_MODULE_EXPORT).read_bytes())},
        "unchanged_baseline_source_sha256": baseline, "unchanged_baseline_flat_image_sha256": flats,
        "accepted_wave007_1_validation_sha256": sha(git_bytes(BASE, "reports/wave007-1/validation.json")),
        "accepted_wave007_1_kernel_elf_sha256": accepted["shell"]["image_sha256"]["crosshair-shell.elf"],
        "preserved_accepted_report_sha256": preserved_reports,
        "unchanged_kernel_load_segments": check_kernel_loads(loads),
        "copied_evidence_sha256": copied, "original_evidence": originals, "local_protocols": protocols,
    }
    payloads["validation.json"] = (json.dumps(validation, indent=2) + "\n").encode()
    require(not args.check_only or output.is_dir(), "No collected Wave007.2 evidence directory to check")
    if output.exists():
        require(output.is_dir() and not any(path.is_symlink() for path in output.rglob("*")), "Unsafe evidence output directory")
        existing = {str(path.relative_to(output)) for path in output.rglob("*") if path.is_file()}
        require(existing <= set(payloads), "Refusing output directory containing unexpected files")
        if args.check_only:
            require(existing == set(payloads), "Collected Wave007.2 evidence is incomplete")
            for relative, payload in payloads.items():
                require((output / relative).read_bytes() == payload, "Collected evidence differs from verified current input: " + relative)
    if not args.check_only:
        for relative, payload in payloads.items():
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
    print(f"Verified Shell: 4 safety +3 legacy tap/key +2 adaptive ARM boots, {total_captures + pointer['pixel_comparisons'] + adaptive['pixel_comparisons']} pixel comparisons; native pipeline/key/pointer/adaptive-window PASS")
    print(f"Preserved {len(baseline)} baseline sources, {len(flats)} flat outputs; mapped RAM={working_ram}, reserved={working_ram + 8192} bytes")
    print(f"{'Validated' if args.check_only else 'Collected'} {len(payloads)} Wave007.2 files, {sum(map(len, payloads.values()))} bytes; PNG/raw565 pairs={total_captures + pointer['pixel_comparisons'] + adaptive['pixel_comparisons']}")


if __name__ == "__main__":
    main()
