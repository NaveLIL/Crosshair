#!/usr/bin/env bash
# Real ARM TCG task execution, timer preemption, isolation, and reset/reboot.
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
scripts/build-tasks.sh
python3 tools/smoke_tasks.py
