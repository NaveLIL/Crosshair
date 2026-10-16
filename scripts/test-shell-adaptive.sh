#!/usr/bin/env bash
# Additional hardware-first UX checks after the retained Shell chain builds it.
set -euo pipefail
source "$(dirname -- "$0")/shell-env.sh"
python3 tools/smoke_shell_adaptive.py
if [[ $(uname -s) == Darwin ]]; then
    python3 tools/run_shell.py --adaptive-window-test
fi
