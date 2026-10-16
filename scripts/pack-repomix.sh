#!/usr/bin/env bash
# Pack only this public checkout; never the private research parent/history.
set -euo pipefail
crosshair_pack_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$crosshair_pack_root"
exec python3 tools/pack_repomix.py "$@"
