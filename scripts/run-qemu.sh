#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/env.sh
source "$(dirname -- "$0")/env.sh"
qemu=${QEMU_SYSTEM_ARM:-qemu-system-arm}
if [[ -x local/qemu/bin/qemu-system-arm && -z ${QEMU_SYSTEM_ARM:-} ]]; then qemu="$PWD/local/qemu/bin/qemu-system-arm"; fi
exec "$qemu" -machine versatilepb,audiodev=audio0 -cpu arm926 -m 128M -accel tcg \
    -display none -monitor none -serial stdio -nic none -audiodev none,id=audio0 \
    -no-reboot -kernel target/artifacts/versatilepb/crosshair-boot.elf "$@"
