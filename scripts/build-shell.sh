#!/usr/bin/env bash
# User Mode Shell on the existing synthetic display-test board.
set -euo pipefail
source "$(dirname -- "$0")/shell-env.sh"
python3 shell/tools/generate_icons.py --check
python3 shell/tools/generate_wallpaper.py --check
sysroot=$(rustc --print sysroot)
host=$(rustc -vV | sed -n 's/^host: //p')
llvm="$sysroot/lib/rustlib/$host/bin"
user_out="$CROSSHAIR_ROOT/target/artifacts/shell/user-image"
mkdir -p "$user_out"
cargo build --release --locked --no-default-features --features shell-user --bin crosshair-shell-user
cp target/armv5te-none-eabi/release/crosshair-shell-user "$user_out/crosshair-shell-user.elf"
"$llvm/llvm-objcopy" -O binary "$user_out/crosshair-shell-user.elf" "$user_out/crosshair-shell-user.bin"
python3 tools/verify_shell_user.py "$user_out" "$llvm"
cargo build --release --locked --no-default-features --features shell-test --bin crosshair-shell
out="$CROSSHAIR_ROOT/target/artifacts/shell/image"
mkdir -p "$out"
cp target/armv5te-none-eabi/release/crosshair-shell "$out/crosshair-shell.elf"
"$llvm/llvm-objcopy" -O binary --remove-section=.vectors "$out/crosshair-shell.elf" "$out/crosshair-shell.bin"
"$llvm/llvm-objcopy" -O binary --only-section=.vectors "$out/crosshair-shell.elf" "$out/vectors.bin"
python3 tools/verify_image.py "$out" "$llvm" --name crosshair-shell --split-vectors --record-symbol CROSSHAIR_SHELL_RECORD
