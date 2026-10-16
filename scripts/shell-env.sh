#!/usr/bin/env bash
# New Shell commands can reuse sibling caches from a clean public checkout.
# Existing baseline env.sh and its source bindings remain unchanged.
set -euo pipefail
shell_requested_rustup=${RUSTUP_HOME:-}
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
if [[ -n "$shell_requested_rustup" && -d "$shell_requested_rustup/toolchains" ]]; then
    export RUSTUP_HOME="$shell_requested_rustup"
fi
unset shell_requested_rustup
if [[ -z ${RUSTUP_HOME:-} || ! -d "$RUSTUP_HOME/toolchains" ]]; then
    for candidate in "$CROSSHAIR_ROOT/local/toolchains/rustup" "$CROSSHAIR_ROOT/../toolchains/rustup"; do
        if [[ -d "$candidate/toolchains" ]]; then
            export RUSTUP_HOME="$candidate"
            break
        fi
    done
fi
for entry in QEMU_SYSTEM_ARM:qemu QEMU_PXA:qemu-pxa QEMU_BLUEANGEL:qemu-blueangel QEMU_E2B:qemu-e2b QEMU_DISPLAY_TEST:qemu-display-test; do
    name=${entry%%:*}
    cache=${entry#*:}
    current=${!name:-}
    if [[ -z "$current" || ! -x "$current" ]]; then
        for candidate in "$CROSSHAIR_ROOT/local/$cache/bin/qemu-system-arm" "$CROSSHAIR_ROOT/../$cache/bin/qemu-system-arm"; do
            if [[ -x "$candidate" ]]; then
                export "$name=$candidate"
                break
            fi
        done
    fi
done
unset candidate entry name cache current
