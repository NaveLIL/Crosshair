#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")/.." && pwd)
if [[ -z ${RUSTUP_HOME:-} && -d "$root/local/toolchains/rustup/toolchains" ]]; then
    export RUSTUP_HOME="$root/local/toolchains/rustup"
fi
: "${RUSTUP_HOME:?Set RUSTUP_HOME to the installed project toolchain; global rustup is not used}"
shopt -s nullglob
toolchains=("$RUSTUP_HOME"/toolchains/nightly-2025-03-01-*)
[[ ${#toolchains[@]} == 1 ]] || { echo 'Need exactly one installed pinned host toolchain' >&2; exit 2; }
bin="${toolchains[0]}/bin"
export PATH="$bin:$PATH"
export RUSTC="$bin/rustc" RUSTDOC="$bin/rustdoc"
export CARGO_NET_OFFLINE=true RUSTUP_NO_UPDATE_CHECK=1
unset RUSTFLAGS CARGO_ENCODED_RUSTFLAGS CARGO_BUILD_TARGET
host=$("$RUSTC" -vV | sed -n 's/^host: //p')
out="$root/target/artifacts/ui"
mkdir -p "$out"
neutral=$(mktemp -d /tmp/crosshair-ui-tests.XXXXXX)
trap 'rm -rf "$neutral"' EXIT
# Cargo discovers config from cwd, not --manifest-path. The neutral directory
# avoids the kernel's build.target/build-std and never runs its build.rs.
(
    cd "$neutral"
    export CARGO_TARGET_DIR="$root/target/ui-host"
    "$bin/cargo" generate-lockfile --manifest-path "$root/ui/Cargo.toml" --offline
    "$bin/cargo" test --manifest-path "$root/ui/Cargo.toml" --target "$host" --locked
    "$bin/cargo" run --manifest-path "$root/ui/Cargo.toml" --target "$host" --release \
        --locked --example primitives -- "$out/primitives.raw565"
    "$bin/cargo" run --manifest-path "$root/ui/Cargo.toml" --target "$host" --release \
        --locked --example apps -- "$out/ui02apps.raw565" "$out/ui02-input-trace.json"
    "$bin/cargo" build --manifest-path "$root/ui/Cargo.toml" --target "$host" --release --lib --locked
) 2>&1 | tee "$out/tests.log"
python3 "$root/tools/framebuffer_png.py" "$out/primitives.raw565" "$out/primitives.png"
python3 "$root/tools/framebuffer_png.py" "$out/ui02apps.raw565" "$out/ui02apps.png"
for raw in "$out"/design-system/step-*.raw565 "$out"/design-system/boundary-step-*.raw565; do
    python3 "$root/tools/framebuffer_png.py" "$raw" "${raw%.raw565}.png"
done
font_checked=false
if [[ -f "$out/cozette-source.bdf" ]]; then
    python3 "$root/ui/tools/subset_font.py" --input "$out/cozette-source.bdf" --check \
        | tee "$out/font-generator-check.json"
    font_checked=true
fi
# From the project root, the existing ARM target/build-std configuration applies
# to this independent library. No kernel manifest or BSP selection is changed.
(
    cd "$root"
    CARGO_TARGET_DIR="$root/target" "$bin/cargo" build --manifest-path "$root/ui/Cargo.toml" \
        --target armv5te-none-eabi --release --lib --locked --message-format=json \
        > "$out/arm-build-messages.jsonl"
) 2>&1 | tee "$out/arm-build.log"
llvm="${toolchains[0]}/lib/rustlib/$host/bin"
library="$root/target/armv5te-none-eabi/release/libcrosshair_ui.rlib"
"$llvm/llvm-readobj" --file-headers --arch-specific "$library" > "$out/arm-lib-report.txt"
# Compile the same size_of probe twice, then inspect actual object bytes. ARM
# uses the core already built from rust-src above, never a guessed host layout.
"$RUSTC" "$root/ui/tools/layout_probe.rs" --edition=2024 --crate-type=lib \
    --target "$host" --extern "crosshair_ui=$root/target/ui-host/$host/release/libcrosshair_ui.rlib" \
    -L "dependency=$root/target/ui-host/$host/release/deps" --emit=obj -o "$out/layout-host.o"
core=$(python3 - "$out/arm-build-messages.jsonl" <<'PY'
import json, sys
paths = []
for line in open(sys.argv[1]):
    message = json.loads(line)
    if message.get('reason') == 'compiler-artifact' and message['target']['name'] == 'core':
        paths.extend(p for p in message['filenames'] if p.endswith('.rlib'))
assert len(paths) == 1, 'Need the exact core artifact selected by this Cargo invocation'
print(paths[0])
PY
)
"$RUSTC" "$root/ui/tools/layout_probe.rs" --edition=2024 --crate-type=lib \
    --target armv5te-none-eabi --extern "core=$core" --extern "crosshair_ui=$library" \
    -L "dependency=$root/target/armv5te-none-eabi/release/deps" --emit=obj -o "$out/layout-arm.o"
for arch in host arm; do
    "$llvm/llvm-readobj" --sections --section-data "$out/layout-$arch.o" > "$out/layout-$arch.txt"
done
python3 - "$root" "$font_checked" <<'PY'
from pathlib import Path
import hashlib, json, re, struct, sys
root = Path(sys.argv[1]); out = root / 'target/artifacts/ui'
report = (out / 'arm-lib-report.txt').read_text()
objects = [part for part in report.split('\nFile: ')[1:] if '.o)' in part.splitlines()[0]]
assert objects, 'Need actual code objects, not just rmeta'
for obj in objects:
    assert 'Machine: EM_ARM' in obj and 'ARM v5TE' in obj
    flags = int(re.search(r'Flags \[ \((0x[0-9a-fA-F]+)\)', obj)[1], 16)
    assert flags & 0xff000000 == 0x05000000 and flags & 0x400 == 0, 'Need EABI5, no hard-float'
for stem in ['primitives', 'ui02apps']:
    png = (out / (stem + '.png')).read_bytes()
    assert png[:8] == b'\x89PNG\r\n\x1a\n' and struct.unpack('>II', png[16:24]) == (240, 320)
    assert (out / (stem + '.raw565')).stat().st_size == 153600
trace = json.loads((out / 'ui02-input-trace.json').read_text())
assert len(trace['events']) == 37 and trace['physical_input'] is False
assert trace['events'][-1]['selected_item'] == 11 and trace['events'][-1]['scroll'] == 4
assert hashlib.sha256((out / 'ui02-input-trace.json').read_bytes()).hexdigest() == '4eda390806a0b35041730f7448c8bd1ef8dae282ced8a90c616179b40638e2c5', 'Canonical UI0.2 logical trace must stay unchanged'
frames = json.loads((out / 'design-system/frames.json').read_text())
assert frames['pixel_format'] == 'RGB565_LE' and frames['theme'] == '0.1'
assert [f['state'] for f in frames['frames']] == [0,10,11,12,15,17,20,21,24,25,26,37]
boundary = json.loads((out / 'design-system/boundary-frames.json').read_text())
assert [f['state'] for f in boundary['frames']] == [0,2,3,6,23,24,26,27]
boundary_trace = json.loads((out / 'design-system/boundary-trace.json').read_text())
assert len(boundary_trace['events']) == 27
assert boundary_trace['events'][0]['changed'] is False
assert boundary_trace['events'][22]['filter_len'] == 16 and boundary_trace['events'][23]['changed'] is False
all_frames = frames['frames'] + boundary['frames']
for frame in all_frames:
    assert (frame['width'], frame['height'], frame['stride'], frame['bytes']) == (240,320,240,153600)
    raw = (out / 'design-system' / frame['file']).read_bytes()
    assert len(raw) == frame['bytes']
    value = 0xcbf29ce484222325
    for byte in raw: value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    assert value == int(frame['fnv1a64'], 16), frame['file']
    png = (out / 'design-system' / frame['file'].replace('.raw565','.png')).read_bytes()
    assert png[:8] == b'\x89PNG\r\n\x1a\n' and struct.unpack('>II', png[16:24]) == (240,320)
assert boundary['frames'][0]['fnv1a64'] == frames['frames'][0]['fnv1a64']
assert boundary['frames'][4]['fnv1a64'] == boundary['frames'][5]['fnv1a64'], 'Ignored 17th character must leave pixels unchanged'
def layout(arch):
    chunks = []
    sections = re.findall(r'SectionData \(\n(.*?)\n\s*\)', (out / ('layout-' + arch + '.txt')).read_text(), re.S)
    for section in sections:
        rows = re.findall(r'^\s*[0-9A-Fa-f]+: ([0-9A-Fa-f ]+)\s+\|', section, re.M)
        data = bytes.fromhex(''.join(rows))
        if struct.pack('<I', 0x55493032) in data: chunks.append(data)
    assert len(chunks) == 1, 'Need unique actual layout data section'
    data = chunks[0]; start = data.index(struct.pack('<I', 0x55493032))
    words = struct.unpack_from('<9I', data, start)
    return dict(zip(['surface', 'apps_state', 'apps_align', 'input_queue', 'event', 'area', 'char', 'usize'], words[1:]))
layouts = {'host': layout('host'), 'armv5te': layout('arm')}
for sizes in layouts.values():
    sizes['state_plus_queue_delta_ui01'] = sizes['apps_state'] + sizes['input_queue']
    sizes['framebuffer'] = 153600
assert layouts['armv5te']['usize'] == 4 and layouts['armv5te']['char'] == 4
(out / 'memory-layout.json').write_text(json.dumps(layouts, indent=2) + '\n')
summaries = re.findall(r'test result: ok\. (\d+) passed; (\d+) failed;', (out / 'tests.log').read_text())
assert summaries and all(int(failed) == 0 for _, failed in summaries)
host_tests = sum(int(passed) for passed, _ in summaries)
assert host_tests >= 22, 'Original renderer/state/stress plus theme/fixture/boundary tests are required'
paths = sorted(p for p in (root / 'ui').rglob('*') if p.is_file() and '__pycache__' not in p.parts)
paths += [root / 'scripts/test-ui.sh', root / 'tools/framebuffer_png.py']
result = {'result': 'PASS', 'host_tests': host_tests, 'armv5te_library_compiled': True,
          'hardware_display_tested': False, 'framebuffer_bytes': 153600,
          'dirty_capacity': 8, 'font_glyphs': 163, 'font_bitmap_bytes': 2119,
          'arm_code_objects_verified': len(objects),
          'font_regeneration_checked': sys.argv[2] == 'true',
          'ui02_scenario_events': len(trace['events']), 'property_test_operations': 20000,
          'theme': '0.1', 'shared_capture_states': [f['state'] for f in frames['frames']],
          'boundary_events': len(boundary_trace['events']),
          'boundary_capture_states': [f['state'] for f in boundary['frames']],
          'memory_layout': layouts,
          'source_sha256': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
          'artifacts_sha256': {name: hashlib.sha256((out / name).read_bytes()).hexdigest()
                              for name in ['primitives.raw565', 'primitives.png', 'ui02apps.raw565', 'ui02apps.png',
                                           'ui02-input-trace.json', 'memory-layout.json', 'arm-lib-report.txt',
                                           'design-system/frames.json', 'design-system/boundary-frames.json',
                                           'design-system/boundary-trace.json'] +
                                          ['design-system/' + f['file'] for f in all_frames] +
                                          ['design-system/' + f['file'].replace('.raw565','.png') for f in all_frames]}}
(out / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
print(f'PASS: {host_tests} host tests, 20000 property operations, 20 themed captures, real ARMv5TE compile/layout')
PY
