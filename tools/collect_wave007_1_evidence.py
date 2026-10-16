#!/usr/bin/env python3
"""Verify the complete Wave007.1 run and collect public text/frame evidence.

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

BASE = "bcc3fe9f385be3686db980197665811968b1398c"
MACHINE = "crosshair-blueangel-display-test"
START_UART = "CROSSHAIR SHELL — USER SESSION START\r\n".encode()
GUI_SENTINEL = "PASS live frontend pipeline: real ARM User input and QEMU console frames; native keymap/PPM decoder"
WINDOW_SENTINEL = "PASS native window: actual NSWindow keyDowns reached ARM Launcher/About/Back/Home with QEMU frame publication"
POINTER_WINDOW_SENTINEL = "PASS native pointer window: actual NSWindow mouseDown coordinates, keys and Cyrillic text reached ARM with QEMU frames"
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
}
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
    "tools/pack_repomix.py",
}
VERSION_METADATA = {"Cargo.lock", "shell/Cargo.lock", "shell/Cargo.toml"}

# Derived from the complete accepted ELF whose SHA256 is recorded by Wave007.
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


def check_baseline(artifacts, output, accepted_kernel=None):
    require(subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", BASE + "^{commit}"], text=True).strip() == BASE,
            "Accepted Wave007 base is unavailable")
    subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", BASE, "HEAD"], check=True)
    require(output == ROOT / "reports/wave007-1" or not output.is_relative_to(ROOT / "reports"),
            "Only the new Wave007.1 report directory may be written inside reports")
    accepted = json.loads(git_bytes(BASE, "reports/wave007/validation.json"))
    require(read_json(ROOT / "reports/wave007/validation.json") == accepted,
            "Accepted Wave007 validation changed")
    paths = subprocess.check_output(["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", BASE,
                                     "--", "reports", "crosshair-emulator/evidence"], text=True).splitlines()
    preserved = {}
    for name in paths:
        expected = sha(git_bytes(BASE, name))
        checked_hash(ROOT / name, expected)
        preserved[name] = expected
    baseline = dict(accepted["unchanged_baseline_source_sha256"])
    baseline.update(accepted["source_sha256"])
    baseline.update(accepted["native_source_sha256"])
    baseline.update(accepted["collector_publication_source_sha256"])
    for name in VERSION_METADATA:
        old = git_bytes(BASE, name)
        before = b'name = "crosshair-shell"\nversion = "0.1.0"'
        after = b'name = "crosshair-shell"\nversion = "0.1.1"'
        require(old.count(before) == 1 and (ROOT / name).read_bytes() == old.replace(before, after),
                "Only the Shell0.1.0-to-0.1.1 metadata update is accepted: " + name)
    for name in MUTABLE_BASELINE | VERSION_METADATA:
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
    cached_elf = accepted_kernel or artifacts / "wave007-1/baseline/accepted-crosshair-shell.elf"
    require(cached_elf.is_file(),
            "Accepted Wave007 ELF is needed for independent segment comparison; rebuild bcc3fe9 with the pinned toolchain and pass --accepted-kernel")
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
    for label in ("outside-menu-no-fallthrough", "menu-keyboard-back"):
        value = named[label]["render_metrics"]
        require(value[2] == 44880 and value[6:] == [0, 1], "Desktop menu dismissal did not restore its bounded covered union")
    for label in ("initial", "app-back", "keyboard-home", "home-again", "home-menu", "launcher-back-home"):
        value = named[label]["render_metrics"]
        require(value[2] == 65280 and value[6:] == [1, 1], "Desktop full entry did not compose only its 240x272 workspace wallpaper")
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
    require(len(raw) == FB_BYTES, "Framebuffer must be exactly153600 bytes")
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
    parser.add_argument("--output", type=Path, default=ROOT / "reports/wave007-1")
    parser.add_argument("--accepted-kernel", type=Path,
                        help="Original accepted Wave007 ELF, default artifacts/wave007-1/baseline/accepted-crosshair-shell.elf")
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
        "kernel_flat_file_bytes": (shell_dir / "image/crosshair-shell.bin").stat().st_size,
        "kernel_elf_file_bytes": (shell_dir / "image/crosshair-shell.elf").stat().st_size,
        "user_flat_file_bytes": len(user_flat), "user_elf_file_bytes": (shell_dir / "user-image/crosshair-shell-user.elf").stat().st_size,
        "sparse_flat_gaps_are_not_working_ram": True,
    }
    require(memory["shell_user_bss_bytes"] == FB_BYTES + 128 + 176 + 48 + 8192 + 32,
            "User BSS no longer equals one guarded framebuffer plus declared record/metrics/journal/render stats")
    require(user_symbols["SHELL_FRAMEBUFFER"] == 0x01010000 and user_symbols["SHELL_TRACE"] + 8192 <= 0x0103F000,
            "User framebuffer/journal allocation exceeds data/guard boundary")
    require(symbols["__bss_start"] <= symbols["SHELL_L1"] <= symbols["__bss_end"] - 32768
            and symbols["__bss_start"] <= symbols["SHELL_L2"] <= symbols["__bss_end"] - 2048, "Page tables outside own kernel BSS")
    type_path = shell_dir / "user-image/type-sizes.txt"
    type_text = type_path.read_text()
    checked_hash(ROOT / "target/armv5te-none-eabi/release/crosshair-shell-user", user["sha256"]["crosshair-shell-user.elf"])
    type_sizes = {}
    for name, expected in (("crosshair_shell::Shell", None), ("crosshair_ui::Surface<'_>", (88, 4)),
                           ("crosshair_shell::Snapshot", (64, 4)), ("crosshair_shell::RuntimeInfo", (48, 4)),
                           ("crosshair_shell::RenderStats", (32, 4)), ("Framebuffer", (153728, 8))):
        match = re.search(r"print-type-size type: `" + re.escape(name) + r"`: (\d+) bytes, alignment: (\d+) bytes", type_text)
        require(match is not None, "Missing actual ARM type layout: " + name)
        observed = tuple(map(int, match.groups()))
        require(observed == expected if expected else 196 < observed[0] <= 512 and observed[1] == 4,
                "Unexpected actual ARM type layout: " + name)
        type_sizes[name] = {"bytes": observed[0], "alignment": observed[1]}
    memory["arm_type_sizes"] = type_sizes
    memory["delta_from_wave007"] = {key: memory[key] - accepted["memory"][key] for key in (
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
            require(re.fullmatch(r"frames/(?:canonical|burst-reset|fault-reset|role-reset|pointer|keyboard-reset|pointer-burst-reset)/step-\d{2}\.(?:png|raw565)", relative) is not None,
                    "Only validated own Shell framebuffer assets may be copied")
        else:
            export.safe_name("reports/wave007-1/" + relative)
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
    require((shell_dir / "execution/qemu-uart.log").read_bytes() == START_UART * 4, "Unexpected Shell reset UART bytes")
    for label, directory in (("shell", shell_dir / "execution"),
                             ("pointer", shell_dir / "pointer"),
                             ("gui/pipeline", shell_dir / "gui/pipeline"),
                             ("gui/window-test", shell_dir / "gui/window-test"),
                             ("gui/pointer-window-test", shell_dir / "gui/pointer-window-test")):
        require((directory / "qemu-uart.log").read_bytes() == START_UART * (4 if label == "shell" else 3 if label == "pointer" else 1),
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
    window = read_json(shell_dir / "gui/window-test-result.json")
    require((window["result"], window["mode"], window["window_ready"]) == ("PASS", "native-window-test", True),
            "Actual native NSWindow event-path test did not complete")
    require(window["logs"] == "window-test", "Native window test logs must be separate from manual input")
    require(window["automation_isolation"] is True, "Native keyboard automation did not reject unscheduled events")
    require(window["image_sha256"] == image["sha256"] and window["user_image_sha256"] == user["sha256"]
            and window["qemu_sha256"] == summary["qemu_sha256"] and window["frontend_sha256"] == pipeline["frontend_sha256"],
            "Native window tested different guest/runtime/frontend bytes")
    bindings(window["source_sha256"], GUI_SOURCES, "Native window event-path test")
    require([event["event"] for event in window["events"]] == [1, 2, 3, 4]
            and [event["screen"] for event in window["events"]] == [2, 3, 2, 0]
            and window["aborted_pending_on_window_close"] == 0,
            "Native NSApp keyDowns did not reach actual ARM Launcher/About/Back/Home")
    for event in window["events"]:
        path = shell_dir / "gui" / f"window-step-{event['event']}.ppm"
        require(sha(ppm_rgb(path)) == event["console_rgb_sha256"], "Native-window QEMU frame mismatch")
        protocols["gui/" + path.name] = {"bytes": path.stat().st_size, "sha256": sha(path.read_bytes())}
    add("gui/window-test-result.json", shell_dir / "gui/window-test-result.json")

    native_pointer = read_json(shell_dir / "gui/pointer-window-test-result.json")
    require((native_pointer["result"], native_pointer["mode"], native_pointer["window_ready"], native_pointer["logs"])
            == ("PASS", "native-pointer-window-test", True, "pointer-window-test"),
            "Actual native mouseDown/key/text window test did not complete")
    require(native_pointer["automation_isolation"] is True, "Native pointer automation did not reject unscheduled events")
    require(native_pointer["image_sha256"] == image["sha256"] and native_pointer["user_image_sha256"] == user["sha256"]
            and native_pointer["qemu_sha256"] == summary["qemu_sha256"]
            and native_pointer["frontend_sha256"] == pipeline["frontend_sha256"]
            and Path(native_pointer["command"][0]).resolve() == runtime,
            "Native pointer window tested other image/runtime/frontend bytes")
    bindings(native_pointer["source_sha256"], GUI_SOURCES, "Native pointer event path")
    events = native_pointer["events"]
    require([event["event"] for event in events] == list(range(1, 8))
            and [event["screen"] for event in events] == [1, 0, 2, 2, 3, 2, 0]
            and native_pointer["aborted_pending_on_window_close"] == 0,
            "Native mouse/keyboard/Cyrillic sequence did not reach actual ARM screens")
    for number, point in ((1, [40, 68]), (3, [25, 12]), (6, [227, 12])):
        event = events[number - 1]
        expected_wire = 0x08000000 | (0xF0000 + (point[1] << 8) + point[0])
        require(event["pointer"] == point and event["wire"] == expected_wire,
                "Native mouse coordinate-to-wire-to-ARM mapping mismatch")
    require(events[3]["wire"] == 0x0800041E and events[3]["pointer"] is None,
            "Native Cyrillic text collided with reserved coordinate carrier")
    for event in events:
        path = shell_dir / "gui" / f"pointer-window-step-{event['event']}.ppm"
        require(sha(ppm_rgb(path)) == event["console_rgb_sha256"], "Native pointer-window QEMU frame mismatch")
        protocols["gui/" + path.name] = {"bytes": path.stat().st_size, "sha256": sha(path.read_bytes())}
    add("gui/pointer-window-test-result.json", shell_dir / "gui/pointer-window-test-result.json")

    log_path = artifacts / "wave007-1/all-tests.log"
    full_log = log_path.read_text()
    require(full_log.rstrip().endswith(POINTER_WINDOW_SENTINEL) and WINDOW_SENTINEL in full_log
            and GUI_SENTINEL in full_log and OLD_TASK_SENTINEL in full_log,
            "Full Wave007.1 log lacks final native pointer/window/pipeline and prior task success")
    require("PASS User pointer: 3 real ARM boots, 56 delivered events, 34 host/ARM/QEMU pixels; coordinate bounds/malformed/keyboard/updatecost checks" in full_log,
            "Full run omitted complete ARM pointer/keyboard/updatecost checks")
    require("Ran 5 tests" in full_log and "test_coordinate_bits_and_bounds" in full_log
            and "test_malformed_or_untrusted_frontend_lines" in full_log,
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
    extra_sources = ("tools/collect_wave007_1_evidence.py", "tools/collect_wave007_evidence.py", "tools/collect_wave006_evidence.py", "scripts/export-public.py",
                     "tools/pack_repomix.py", "scripts/pack-repomix.sh", "repomix.config.json")
    validation = {
        "result": "PASS", "accepted_base": BASE,
        "scope": "Complete prior safety chain plus three ARM Desktop pointer/keyboard/reset/burst boots on unchanged kernel/display model; native NSWindow keyboard/mouse/text adapters, real state/pixels/software update costs; no physical PDA validation",
        "normalization": "host/workspace/cache/socket paths and hostnames only; UART and validated framebuffer PNG/raw565 byte-exact",
        "shell": {"result": "PASS", "boots": 4, "events": sum(boot["events"] for boot in summary["boots"]),
                  "pixel_comparisons": total_captures, "image_sha256": image["sha256"], "user_image_sha256": user["sha256"], "qemu_sha256": summary["qemu_sha256"]},
        "native_frontend": {"status": "Headless pipeline and actual NSWindow/NSApp-posted keyDown/mouseDown event paths PASS; extended manual use remains separate evidence", "frontend_sha256": pipeline["frontend_sha256"]},
        "memory": memory, "results": statuses, "wallpaper": wallpaper, "desktop_pointer": pointer,
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
            "scope": "Exactly crosshair-shell package0.1.0-to-0.1.1; every other byte and dependency graph unchanged"},
        "unchanged_baseline_source_sha256": baseline, "unchanged_baseline_flat_image_sha256": flats,
        "accepted_wave007_validation_sha256": sha(git_bytes(BASE, "reports/wave007/validation.json")),
        "accepted_wave007_kernel_elf_sha256": accepted["shell"]["image_sha256"]["crosshair-shell.elf"],
        "preserved_accepted_report_sha256": preserved_reports,
        "unchanged_kernel_load_segments": check_kernel_loads(loads),
        "copied_evidence_sha256": copied, "original_evidence": originals, "local_protocols": protocols,
    }
    payloads["validation.json"] = (json.dumps(validation, indent=2) + "\n").encode()
    require(not args.check_only or output.is_dir(), "No collected Wave007.1 evidence directory to check")
    if output.exists():
        require(output.is_dir() and not any(path.is_symlink() for path in output.rglob("*")), "Unsafe evidence output directory")
        existing = {str(path.relative_to(output)) for path in output.rglob("*") if path.is_file()}
        require(existing <= set(payloads), "Refusing output directory containing unexpected files")
        if args.check_only:
            require(existing == set(payloads), "Collected Wave007.1 evidence is incomplete")
            for relative, payload in payloads.items():
                require((output / relative).read_bytes() == payload, "Collected evidence differs from verified current input: " + relative)
    if not args.check_only:
        for relative, payload in payloads.items():
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
    print(f"Verified Shell: 4 safety +3 pointer ARM boots, {total_captures + pointer['pixel_comparisons']} pixel comparisons; native pipeline/keyboard/pointer-window PASS")
    print(f"Preserved {len(baseline)} baseline sources, {len(flats)} flat outputs; mapped RAM={working_ram}, reserved={working_ram + 8192} bytes")
    print(f"{'Validated' if args.check_only else 'Collected'} {len(payloads)} Wave007.1 files, {sum(map(len, payloads.values()))} bytes; PNG/raw565 pairs={total_captures + pointer['pixel_comparisons']}")


if __name__ == "__main__":
    main()
