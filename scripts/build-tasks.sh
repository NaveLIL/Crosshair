#!/usr/bin/env bash
# Separate User task-runtime experiment on the unchanged E2B machine.
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
cargo build --release --locked --no-default-features --features tasks-test --bin crosshair-tasks
sysroot=$(rustc --print sysroot)
host=$(rustc -vV | sed -n 's/^host: //p')
llvm="$sysroot/lib/rustlib/$host/bin"
out="$CROSSHAIR_ROOT/target/artifacts/tasks/image"
mkdir -p "$out"
cp target/armv5te-none-eabi/release/crosshair-tasks "$out/crosshair-tasks.elf"
"$llvm/llvm-objcopy" -O binary --remove-section=.vectors "$out/crosshair-tasks.elf" "$out/crosshair-tasks.bin"
"$llvm/llvm-objcopy" -O binary --only-section=.vectors "$out/crosshair-tasks.elf" "$out/vectors.bin"
python3 tools/verify_image.py "$out" "$llvm" --name crosshair-tasks --split-vectors --record-symbol CROSSHAIR_TASK_RECORD
