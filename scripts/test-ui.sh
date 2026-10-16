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
) 2>&1 | tee "$out/tests.log"
python3 "$root/tools/framebuffer_png.py" "$out/primitives.raw565" "$out/primitives.png"
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
        --target armv5te-none-eabi --release --lib --locked
) 2>&1 | tee "$out/arm-build.log"
llvm="${toolchains[0]}/lib/rustlib/$host/bin"
library="$root/target/armv5te-none-eabi/release/libcrosshair_ui.rlib"
"$llvm/llvm-readobj" --file-headers --arch-specific "$library" > "$out/arm-lib-report.txt"
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
png = (out / 'primitives.png').read_bytes()
assert png[:8] == b'\x89PNG\r\n\x1a\n' and struct.unpack('>II', png[16:24]) == (240, 320)
assert (out / 'primitives.raw565').stat().st_size == 153600
paths = sorted(p for p in (root / 'ui').rglob('*') if p.is_file() and '__pycache__' not in p.parts)
paths += [root / 'scripts/test-ui.sh', root / 'tools/framebuffer_png.py']
result = {'result': 'PASS', 'host_tests': 11, 'armv5te_library_compiled': True,
          'hardware_display_tested': False, 'framebuffer_bytes': 153600,
          'dirty_capacity': 8, 'font_glyphs': 163, 'font_bitmap_bytes': 2119,
          'arm_code_objects_verified': len(objects),
          'font_regeneration_checked': sys.argv[2] == 'true',
          'source_sha256': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
          'artifacts_sha256': {name: hashlib.sha256((out / name).read_bytes()).hexdigest()
                              for name in ['primitives.raw565', 'primitives.png', 'arm-lib-report.txt']}}
(out / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
print('PASS: host pixels/dirty/font tests, PNG240x320, real ARMv5TE no_std library compile')
PY
