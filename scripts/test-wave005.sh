#!/usr/bin/env bash
# All accepted regressions plus the separate User/MMU/SVC experiment.
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
scripts/test-wave004.sh
scripts/test-security.sh
