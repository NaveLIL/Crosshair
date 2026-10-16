#!/usr/bin/env bash
# Source from project scripts. Respect normal rustup on fresh WSL installations.
set -euo pipefail
CROSSHAIR_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$CROSSHAIR_ROOT"
if [[ -d "$CROSSHAIR_ROOT/local/toolchains/rustup/toolchains" ]]; then
    export RUSTUP_HOME="$CROSSHAIR_ROOT/local/toolchains/rustup"
fi
export RUSTUP_NO_UPDATE_CHECK=1
