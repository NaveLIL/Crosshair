#!/usr/bin/env bash
# Retain the complete Wave006 chain before the User Mode Shell session.
set -euo pipefail
source "$(dirname -- "$0")/shell-env.sh"
scripts/test-wave006.sh
scripts/test-shell.sh
