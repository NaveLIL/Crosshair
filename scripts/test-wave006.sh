#!/usr/bin/env bash
# Preserve Boot/E1/E2A/E2B/UI/display/Security suites before task-runtime tests.
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
scripts/test-wave005.sh
scripts/test-tasks.sh
