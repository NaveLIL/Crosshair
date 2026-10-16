#!/usr/bin/env bash
# Separate E2B cache; reuse the pinned host dependency/bootstrap machinery.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export CROSSHAIR_QEMU_MODEL_VARIANT=e2b
export CROSSHAIR_QEMU_BLUEANGEL_DIR=${CROSSHAIR_QEMU_E2B_DIR:-"$root/local/qemu-e2b"}
exec "$root/scripts/bootstrap-qemu-blueangel.sh" "$@"
