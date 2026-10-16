#!/usr/bin/env bash
# Run after test-shell.sh has built current host oracle and ARM guest.
set -euo pipefail
source "$(dirname -- "$0")/shell-env.sh"
python3 tools/test_shell_input.py -v
python3 tools/smoke_shell_pointer.py
if [[ $(uname -s) == Darwin ]]; then
    python3 tools/run_shell.py --pointer-window-test
fi
