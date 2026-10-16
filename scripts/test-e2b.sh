#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
scripts/build-e2b.sh
scripts/build-e2b.sh --negative-test
python3 tools/smoke_e2b.py
python3 tools/qtest_e2b.py
