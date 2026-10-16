#!/usr/bin/env bash
# Keep all accepted regressions and add the E2B CPU/GPIO execution tests.
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
scripts/test-next-wave.sh
scripts/test-e2b.sh
