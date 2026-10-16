#!/usr/bin/env bash
# A project-local rustup home avoids touching the user's default toolchain.
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")/.." && pwd)
command -v rustup >/dev/null || { echo "Install rustup first (see BUILDING.md)" >&2; exit 1; }
export RUSTUP_HOME="$root/local/toolchains/rustup"
export RUSTUP_NO_UPDATE_CHECK=1
rustup toolchain install nightly-2025-03-01 --profile minimal \
    --component rust-src --component llvm-tools-preview --component rustfmt --no-self-update
