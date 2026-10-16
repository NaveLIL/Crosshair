#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
# Requires current host references from test-ui.sh; test-wave004 runs it first.
scripts/build-display-test.sh
python3 tools/smoke_display.py --check-missing-reference
python3 tools/smoke_display.py
python3 tools/qtest_display.py
