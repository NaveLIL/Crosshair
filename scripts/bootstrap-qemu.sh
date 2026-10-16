#!/usr/bin/env bash
# Build upstream QEMU locally; no VM, device or SD access.
# Requires C/C++ compiler, make, Python >=3.9 + venv, curl, tar,
# git, pkg-config, glib-2.0 and pixman-1 development packages.
# WSL/Ubuntu: sudo apt-get install build-essential python3-venv curl git \
#   pkg-config libglib2.0-dev libpixman-1-dev
# macOS: Xcode CLI tools, Python 3, pkgconf, glib, pixman (e.g. Homebrew).
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
qemu_version=9.2.0
archive_sha=f859f0bc65e1f533d040bbe8c92bcfecee5af2c921a6687c652fb44d089bd894
python=${PYTHON:-python3}
jobs=${CROSSHAIR_QEMU_JOBS:-4}
case "$jobs" in ''|*[!0-9]*|0) printf 'CROSSHAIR_QEMU_JOBS must be positive\n' >&2; exit 2;; esac
base="$root/local/qemu"
archive="$root/local/downloads/qemu-$qemu_version.tar.xz"
src="$base/qemu-$qemu_version"
build="$base/build"
venv="$base/venv"
evidence="$base/evidence"
for command in "$python" cc c++ make curl tar git pkg-config; do
    command -v "$command" >/dev/null || { printf 'Missing prerequisite: %s\n' "$command" >&2; exit 1; }
done
pkg-config --exists glib-2.0 pixman-1 || {
    printf 'Install glib-2.0 and pixman-1 development packages (see script header).\n' >&2
    exit 1
}
mkdir -p "$base" "$build" "$evidence" "$(dirname "$archive")"
if [[ ! -f "$archive" ]]; then
    curl --fail --location --retry 3 "https://download.qemu.org/qemu-$qemu_version.tar.xz" -o "$archive.partial"
    mv "$archive.partial" "$archive"
fi
"$python" - "$archive" "$archive_sha" <<'PY'
import hashlib
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
with path.open('rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else None
if digest is None:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    digest = h.hexdigest()
if digest != sys.argv[2]:
    raise SystemExit(f'QEMU archive SHA256 mismatch: {digest}')
print(f'QEMU archive SHA256 verified: {digest}')
PY
if [[ ! -f "$src/configure" ]]; then tar -xf "$archive" -C "$base"; fi
if [[ ! -x "$venv/bin/python" ]]; then "$python" -m venv "$venv"; fi
"$venv/bin/python" -m pip install --disable-pip-version-check \
    meson==1.5.0 ninja==1.11.1.3 distlib==0.3.9 pycotap==1.3.1
(
    cd "$build"
    export PATH="$venv/bin:$PATH"
    # Keep upstream default devices. PXA2xx boards were removed in QEMU 9.2;
    # their absence is recorded below, not hidden by a reduced device config.
    "$src/configure" --target-list=arm-softmmu --without-default-features \
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
grep -Eq '^versatilepb[[:space:]]' "$evidence/machines.txt"
{
    printf 'QEMU upstream removal record: https://www.qemu.org/docs/master/about/removed-features.html\n'
    for machine in versatilepb connex verdex mainstone; do
        if grep -Eq "^${machine}[[:space:]]" "$evidence/machines.txt"; then
            printf '%s: available\n' "$machine"
        else
            printf '%s: absent\n' "$machine"
        fi
    done
} > "$evidence/machine-availability.txt"
grep -Eq '^  arm926$' "$evidence/cpus.txt"
{
    uname -a
    cc --version
    "$venv/bin/python" --version
    "$venv/bin/python" -m pip freeze
    pkg-config --version
    pkg-config --modversion glib-2.0 pixman-1
} > "$evidence/host-tools.txt"
{
    printf 'Source: https://download.qemu.org/qemu-%s.tar.xz\nSHA256: %s\n' "$qemu_version" "$archive_sha"
    for subproject in dtc keycodemapdb berkeley-softfloat-3 berkeley-testfloat-3; do
        printf '\n%s upstream pin (from QEMU archive):\n' "$subproject"
        cat "$src/subprojects/$subproject.wrap"
    done
} > "$evidence/source.txt"
printf 'QEMU ready: %s\nEvidence: %s\n' "$qemu" "$evidence"
