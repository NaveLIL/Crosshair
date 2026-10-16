#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/env.sh
source "$(dirname -- "$0")/env.sh"
board=${1:-versatilepb}
case "$board" in versatilepb|blueangel) ;; *) echo "Unknown BSP: $board" >&2; exit 2;; esac
features=$board
suffix=$board
if [[ ${2:-} == --panic-test ]]; then features="$board,panic-test"; suffix="$board-panic"; fi
cargo build --release --no-default-features --features "$features" --locked
sysroot=$(rustc --print sysroot)
host=$(rustc -vV | sed -n 's/^host: //p')
llvm="$sysroot/lib/rustlib/$host/bin"
out="$CROSSHAIR_ROOT/target/artifacts/$suffix"
mkdir -p "$out"
cp target/armv5te-none-eabi/release/crosshair-boot "$out/crosshair-boot.elf"
"$llvm/llvm-objcopy" -O binary "$out/crosshair-boot.elf" "$out/crosshair-boot.bin"
if [[ $board == blueangel ]]; then
    # HaRET copies pages; zero padding makes the file's final page explicit.
    python3 - "$out" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
data = (p / 'crosshair-boot.bin').read_bytes()
(p / 'crosshair-haret.bin').write_bytes(data + bytes((-len(data)) % 4096))
PY
fi
python3 tools/verify_image.py "$out" "$llvm"
echo "Artifacts: $out"
