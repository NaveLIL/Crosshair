#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
scripts/test-wave003.sh
scripts/test-display.sh
