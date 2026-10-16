#!/usr/bin/env bash
# Retain every accepted suite before the new logical stylus/Desktop checks.
set -euo pipefail
source "$(dirname -- "$0")/shell-env.sh"
scripts/test-wave007.sh
scripts/test-shell-pointer.sh
