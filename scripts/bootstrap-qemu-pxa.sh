#!/usr/bin/env bash
# Isolated QEMU 9.1.0 for Crosshair PXA emulator experiments.
# Does not access the PDA or SD devices, and leaves local/qemu (9.2) intact.
# Prerequisites: C/C++ compiler, make, Python >=3.9 + venv, curl, tar, git,
# pkg-config, glib-2.0 and pixman-1 development packages.
# WSL/Ubuntu: sudo apt-get install build-essential python3-venv curl git \
#   pkg-config libglib2.0-dev libpixman-1-dev
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
qemu_version=9.1.0
upstream_commit=fd1952d814da738ed107e05583b3e02ac11e88ff
archive_sha=816b7022a8ba7c2ac30e2e0cf973e826f6bcc8505339603212c5ede8e94d7834
python=${PYTHON:-python3}
jobs=${CROSSHAIR_QEMU_JOBS:-4}
case "$jobs" in ''|*[!0-9]*|0) printf 'CROSSHAIR_QEMU_JOBS must be positive\n' >&2; exit 2;; esac
base="$root/local/qemu-pxa"
archive="$root/local/downloads/qemu-$qemu_version.tar.xz"
src="$base/qemu-$qemu_version"
build="$base/build"
venv="$base/venv"
evidence="$base/evidence"
for command in "$python" cc c++ make curl tar git pkg-config; do
    command -v "$command" >/dev/null || { printf 'Missing prerequisite: %s\n' "$command" >&2; exit 1; }
done
pkg-config --exists glib-2.0 pixman-1 || {
    printf 'Install glib-2.0 and pixman-1 development packages.\n' >&2; exit 1
}
mkdir -p "$base" "$build" "$evidence" "$(dirname "$archive")"
free_kib=$(df -Pk "$base" | awk 'NR==2 { print $4 }')
required_kib=524288
if [[ ! -f "$src/configure" ]]; then required_kib=2097152; fi
if (( free_kib < required_kib )); then
    printf 'Insufficient disk space: %s KiB available, %s KiB required.\n' "$free_kib" "$required_kib" >&2
    exit 1
fi
if [[ ! -f "$archive" ]]; then
    curl --fail --location --retry 3 "https://download.qemu.org/qemu-$qemu_version.tar.xz" -o "$archive.partial"
    mv "$archive.partial" "$archive"
fi
"$python" - "$archive" "$archive_sha" <<'PY'
import hashlib
import pathlib
import sys
h = hashlib.sha256()
with pathlib.Path(sys.argv[1]).open('rb') as stream:
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        h.update(block)
digest = h.hexdigest()
if digest != sys.argv[2]:
    raise SystemExit(f'QEMU archive SHA256 mismatch: {digest}')
print(f'QEMU archive SHA256 verified: {digest}')
PY
if [[ ! -f "$evidence/upstream-tag.txt" ]]; then
    git ls-remote https://gitlab.com/qemu-project/qemu.git \
        "refs/tags/v$qemu_version^{}" > "$evidence/upstream-tag.txt.partial"
    mv "$evidence/upstream-tag.txt.partial" "$evidence/upstream-tag.txt"
fi
actual_commit=$(awk '{print $1}' "$evidence/upstream-tag.txt")
[[ "$actual_commit" == "$upstream_commit" ]] || {
    printf 'Upstream release tag commit mismatch: %s\n' "$actual_commit" >&2; exit 1
}
if [[ ! -f "$src/configure" ]]; then tar -xf "$archive" -C "$base"; fi
cat > "$src/configs/devices/arm-softmmu/crosshair-pxa.mak" <<'CONFIG'
# Crosshair E1: emulator SoC baseline, not a Blue Angel board model.
# Upstream hw/arm/Kconfig: GUMSTIX selects PXA2XX; MAINSTONE selects PXA2XX.
CONFIG_GUMSTIX=y
CONFIG_MAINSTONE=y
CONFIG_GENERIC_LOADER=y
CONFIG
cp "$src/configs/devices/arm-softmmu/crosshair-pxa.mak" "$evidence/device-config.mak"
sed -n '104,110p;184,200p' "$src/hw/arm/Kconfig" > "$evidence/selector-lines.txt"
if [[ ! -x "$venv/bin/python" ]]; then "$python" -m venv "$venv"; fi
"$venv/bin/python" -m pip install --disable-pip-version-check \
    meson==1.5.0 ninja==1.11.1.3 distlib==0.3.9 pycotap==1.3.1
(
    cd "$build"
    export PATH="$venv/bin:$PATH"
    "$src/configure" --target-list=arm-softmmu --without-default-features \
        --without-default-devices --with-devices-arm=crosshair-pxa \
        --enable-system --enable-tcg --enable-pixman --enable-fdt=internal \
        --disable-werror --disable-docs --disable-tools --disable-guest-agent \
        --disable-debug-info --audio-drv-list= --prefix="$base/install" \
        --python="$venv/bin/python" --ninja="$venv/bin/ninja" \
        > configure.log 2>&1 || { tail -n 80 configure.log >&2; exit 1; }
    "$venv/bin/ninja" -j "$jobs" qemu-system-arm 2>&1 | tee build.log
)
qemu="$build/qemu-system-arm"
mkdir -p "$base/bin"
ln -sfn ../build/qemu-system-arm "$base/bin/qemu-system-arm"
"$qemu" --version | tee "$evidence/version.txt"
"$qemu" -machine help > "$evidence/machines.txt"
"$qemu" -cpu help > "$evidence/cpus.txt"
for machine in connex verdex mainstone; do
    grep -Eq "^${machine}[[:space:]]" "$evidence/machines.txt" || { printf 'Missing machine: %s\n' "$machine" >&2; exit 1; }
done
for cpu in pxa255 pxa270-c0 pxa270-c5; do
    grep -Eq "^  ${cpu}$" "$evidence/cpus.txt" || { printf 'Missing CPU: %s\n' "$cpu" >&2; exit 1; }
done
cp "$build/arm-softmmu-config-devices.mak" "$evidence/resolved-devices.mak"
{
    uname -a
    cc --version
    "$venv/bin/python" --version
    "$venv/bin/python" -m pip freeze
    pkg-config --version
    pkg-config --modversion glib-2.0 pixman-1
} > "$evidence/host-tools.txt"
{
    printf 'Source: https://download.qemu.org/qemu-%s.tar.xz\nSHA256: %s\nTag commit: %s\n' "$qemu_version" "$archive_sha" "$upstream_commit"
    printf 'Selectors: hw/arm/Kconfig at pinned commit, CONFIG_GUMSTIX and CONFIG_MAINSTONE.\n'
    for subproject in dtc keycodemapdb berkeley-softfloat-3 berkeley-testfloat-3; do
        printf '\n%s upstream pin (from QEMU archive):\n' "$subproject"
        cat "$src/subprojects/$subproject.wrap"
    done
} > "$evidence/source.txt"
printf 'PXA QEMU ready: %s\nEvidence: %s\n' "$base/bin/qemu-system-arm" "$evidence"
