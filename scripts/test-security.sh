#!/usr/bin/env bash
# Own ARM User/SVC tests on the existing E2B model; no emulator modifications.
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
scripts/build-security.sh
python3 tools/smoke_security.py
