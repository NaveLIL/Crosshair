#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/env.sh
source "$(dirname -- "$0")/env.sh"
cargo build --release --locked --no-default-features --features pxa-reference --bin crosshair-pxa-reference
sysroot=$(rustc --print sysroot)
host=$(rustc -vV | sed -n 's/^host: //p')
llvm="$sysroot/lib/rustlib/$host/bin"
out="$CROSSHAIR_ROOT/target/artifacts/pxa-reference"
mkdir -p "$out"
cp target/armv5te-none-eabi/release/crosshair-pxa-reference "$out/crosshair-pxa-reference.elf"
# Keep the low vector blob separate: a flat file spanning PA0..A0008000 would
# be several GiB. The ELF itself has distinct low-vector and SDRAM PT_LOADs.
"$llvm/llvm-objcopy" -O binary --remove-section=.vectors "$out/crosshair-pxa-reference.elf" "$out/crosshair-pxa-reference.bin"
"$llvm/llvm-objcopy" -O binary --only-section=.vectors "$out/crosshair-pxa-reference.elf" "$out/vectors.bin"
python3 tools/verify_image.py "$out" "$llvm" --name crosshair-pxa-reference --split-vectors
echo "Reference guest (not for a PDA): $out"
