#!/usr/bin/env bash
# Preserve both accepted baselines alongside E2A and the independent renderer.
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
scripts/test.sh
scripts/test-pxa-reference.sh
scripts/test-e2a.sh
scripts/test-ui.sh
