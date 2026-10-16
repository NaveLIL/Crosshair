#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/env.sh
source "$(dirname -- "$0")/env.sh"
scripts/build.sh versatilepb
python3 tools/smoke_qemu.py
scripts/build.sh versatilepb --panic-test
python3 tools/smoke_qemu.py --panic-test
scripts/build.sh blueangel
scripts/build.sh versatilepb
python3 -m unittest discover -s tests -v
