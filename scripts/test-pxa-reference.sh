#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/env.sh
source "$(dirname -- "$0")/env.sh"
scripts/build-pxa-reference.sh
python3 tools/smoke_pxa.py
python3 tools/qtest_pxa.py
