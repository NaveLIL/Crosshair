#!/usr/bin/env bash
# Visible Mac window: actual QEMU console pixels, keys forwarded to synthetic FIFO.
set -euo pipefail
source "$(dirname -- "$0")/shell-env.sh"
[[ $(uname -s) == Darwin ]] || { echo 'This native frontend currently requires macOS AppKit.' >&2; exit 2; }
scripts/build-shell.sh
scripts/build-shell-gui.sh
exec python3 tools/run_shell.py "$@"
