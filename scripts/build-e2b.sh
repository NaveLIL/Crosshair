#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
features=e2b
variant=normal
if [[ "${1:-}" == "--negative-test" ]]; then
    features=e2b-negative-test
    variant=negative-test
elif [[ $# != 0 ]]; then
    echo "Usage: $0 [--negative-test]" >&2; exit 2
fi
cargo build --release --locked --no-default-features --features "$features" --bin crosshair-e2b
sysroot=$(rustc --print sysroot)
host=$(rustc -vV | sed -n 's/^host: //p')
llvm="$sysroot/lib/rustlib/$host/bin"
out="$CROSSHAIR_ROOT/target/artifacts/e2b/$variant"
mkdir -p "$out"
cp target/armv5te-none-eabi/release/crosshair-e2b "$out/crosshair-e2b.elf"
"$llvm/llvm-objcopy" -O binary --remove-section=.vectors "$out/crosshair-e2b.elf" "$out/crosshair-e2b.bin"
"$llvm/llvm-objcopy" -O binary --only-section=.vectors "$out/crosshair-e2b.elf" "$out/vectors.bin"
python3 tools/verify_image.py "$out" "$llvm" --name crosshair-e2b --split-vectors --record-symbol CROSSHAIR_E2B_RECORD
