#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
cargo build --release --locked --no-default-features --features security-test --bin crosshair-security
sysroot=$(rustc --print sysroot)
host=$(rustc -vV | sed -n 's/^host: //p')
llvm="$sysroot/lib/rustlib/$host/bin"
out="$CROSSHAIR_ROOT/target/artifacts/security/image"
mkdir -p "$out"
cp target/armv5te-none-eabi/release/crosshair-security "$out/crosshair-security.elf"
"$llvm/llvm-objcopy" -O binary --remove-section=.vectors "$out/crosshair-security.elf" "$out/crosshair-security.bin"
"$llvm/llvm-objcopy" -O binary --only-section=.vectors "$out/crosshair-security.elf" "$out/vectors.bin"
python3 tools/verify_image.py "$out" "$llvm" --name crosshair-security --split-vectors --record-symbol CROSSHAIR_SECURITY_RECORD
rustc --test --edition=2024 src/security_policy.rs --target "$host" -o "$out/policy-host-tests"
"$out/policy-host-tests" | tee "$out/policy-host-tests.log"
