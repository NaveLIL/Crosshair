#!/usr/bin/env bash
# Same Shell state/render library on host; kernel Cargo build settings excluded.
set -euo pipefail
source "$(dirname -- "$0")/shell-env.sh"
: "${RUSTUP_HOME:?Set RUSTUP_HOME to the installed project toolchain}"
host=$(rustc -vV | sed -n 's/^host: //p')
shell_sysroot=$(rustc --print sysroot)
shell_cargo="$shell_sysroot/bin/cargo"
export RUSTC="$shell_sysroot/bin/rustc" RUSTDOC="$shell_sysroot/bin/rustdoc"
out="$CROSSHAIR_ROOT/target/artifacts/shell/host"
mkdir -p "$out"
python3 shell/tools/generate_icons.py --check 2>&1 | tee "$out/icon-check.log"
python3 shell/tools/test_generate_icons.py -v 2>&1 | tee "$out/icon-tests.log"
if [[ -x "$CROSSHAIR_ROOT/local/icon-tools/bin/python" ]]; then
    "$CROSSHAIR_ROOT/local/icon-tools/bin/python" shell/tools/generate_icons.py --regenerate-check 2>&1 | tee "$out/icon-regenerate.log"
fi
neutral=$(mktemp -d /tmp/crosshair-shell-tests.XXXXXX)
trap 'rm -rf "$neutral"' EXIT
(
    cd "$neutral"
    unset RUSTFLAGS CARGO_ENCODED_RUSTFLAGS CARGO_BUILD_TARGET
    export CARGO_TARGET_DIR="$CROSSHAIR_ROOT/target/shell-host"
    "$shell_cargo" test --manifest-path "$CROSSHAIR_ROOT/shell/Cargo.toml" --target "$host" --locked
    "$shell_cargo" build --manifest-path "$CROSSHAIR_ROOT/shell/Cargo.toml" --target "$host" --release --locked --example export
) 2>&1 | tee "$out/tests.log"
printf '%s\n' "$CROSSHAIR_ROOT/target/shell-host/$host/release/examples/export" > "$out/exporter-path.txt"
