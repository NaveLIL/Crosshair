#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
cargo build --release --locked --no-default-features --features display-test --bin crosshair-display-test
sysroot=$(rustc --print sysroot)
host=$(rustc -vV | sed -n 's/^host: //p')
llvm="$sysroot/lib/rustlib/$host/bin"
out="$CROSSHAIR_ROOT/target/artifacts/display-test/image"
mkdir -p "$out"
cp target/armv5te-none-eabi/release/crosshair-display-test "$out/crosshair-display-test.elf"
"$llvm/llvm-objcopy" -O binary --remove-section=.vectors "$out/crosshair-display-test.elf" "$out/crosshair-display-test.bin"
"$llvm/llvm-objcopy" -O binary --only-section=.vectors "$out/crosshair-display-test.elf" "$out/vectors.bin"
python3 tools/verify_image.py "$out" "$llvm" --name crosshair-display-test --split-vectors --record-symbol CROSSHAIR_DISPLAY_RECORD
