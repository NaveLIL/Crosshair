#!/usr/bin/env bash
# Preserve accepted safety, logical tap and keyboard intent before new phases.
set -euo pipefail
source "$(dirname -- "$0")/shell-env.sh"
scripts/test-wave007-1.sh
scripts/test-shell-adaptive.sh
