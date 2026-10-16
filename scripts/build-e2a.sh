#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
features=e2a
variant=normal
if [[ "${1:-}" == "--mmio-test" ]]; then
    features=e2a-mmio-test
    variant=mmio-test
elif [[ $# != 0 ]]; then
    echo "Usage: $0 [--mmio-test]" >&2
    exit 2
fi
cargo build --release --locked --no-default-features --features "$features" --bin crosshair-pxa-reference
sysroot=$(rustc --print sysroot)
host=$(rustc -vV | sed -n 's/^host: //p')
llvm="$sysroot/lib/rustlib/$host/bin"
out="$CROSSHAIR_ROOT/target/artifacts/e2a/$variant"
mkdir -p "$out"
cp target/armv5te-none-eabi/release/crosshair-pxa-reference "$out/crosshair-e2a.elf"
"$llvm/llvm-objcopy" -O binary --remove-section=.vectors "$out/crosshair-e2a.elf" "$out/crosshair-e2a.bin"
"$llvm/llvm-objcopy" -O binary --only-section=.vectors "$out/crosshair-e2a.elf" "$out/vectors.bin"
python3 tools/verify_image.py "$out" "$llvm" --name crosshair-e2a --split-vectors
echo "E2A emulator-only guest: $out"
