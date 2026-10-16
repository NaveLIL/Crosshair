#!/usr/bin/env bash
# Isolated synthetic display/input model; prior emulator caches stay unchanged.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export CROSSHAIR_QEMU_MODEL_VARIANT=display-test
export CROSSHAIR_QEMU_BLUEANGEL_DIR=${CROSSHAIR_QEMU_DISPLAY_TEST_DIR:-"$root/local/qemu-display-test"}
exec "$root/scripts/bootstrap-qemu-blueangel.sh" "$@"
