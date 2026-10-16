#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
scripts/build-e2a.sh
scripts/build-e2a.sh --mmio-test
python3 tools/smoke_e2a.py
python3 tools/qtest_e2a.py
