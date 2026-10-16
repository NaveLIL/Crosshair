#!/usr/bin/env bash
# User Shell plus a preempted busy workload, real input and framebuffer proof.
set -euo pipefail
source "$(dirname -- "$0")/shell-env.sh"
scripts/test-shell-ui.sh
scripts/build-shell.sh
python3 tools/smoke_shell.py
if [[ $(uname -s) == Darwin ]]; then
    scripts/build-shell-gui.sh
    python3 tools/run_shell.py --headless-test
    python3 tools/run_shell.py --window-test
fi
