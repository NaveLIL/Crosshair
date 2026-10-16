#!/usr/bin/env bash
# Native adapter only: QEMU pixels and logical keys, no host Shell renderer.
set -euo pipefail
source "$(dirname -- "$0")/shell-env.sh"
[[ $(uname -s) == Darwin ]] || { echo 'The native Shell frontend requires macOS AppKit.' >&2; exit 2; }
out="$CROSSHAIR_ROOT/target/artifacts/shell/gui"
mkdir -p "$out"
xcrun swiftc --version > "$out/swift-version.txt" 2>&1
printf '%s\n' 'xcrun swiftc tools/crosshair_gui.swift -O -framework AppKit -o target/artifacts/shell/gui/crosshair-gui' > "$out/compile-command.txt"
shell_gui_source_sha=$(python3 -c 'from pathlib import Path; import hashlib; print(hashlib.sha256(Path("tools/crosshair_gui.swift").read_bytes()).hexdigest())')
shell_gui_compiled_sha=$(cat "$out/source-sha256.txt" 2>/dev/null || true)
if [[ ! -x "$out/crosshair-gui" || ! -f "$out/compile.log" || "$shell_gui_source_sha" != "$shell_gui_compiled_sha" || tools/crosshair_gui.swift -nt "$out/crosshair-gui" ]]; then
    xcrun swiftc tools/crosshair_gui.swift -O -framework AppKit -o "$out/crosshair-gui" > "$out/compile.log" 2>&1
    printf '%s\n' "$shell_gui_source_sha" > "$out/source-sha256.txt"
fi
