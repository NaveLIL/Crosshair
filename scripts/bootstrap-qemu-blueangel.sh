#!/usr/bin/env bash
# Build a GPL E2A/E2B host experiment in its own QEMU 9.2 tree.
# Existing baseline source/build trees are never patched in place.
# Dependencies match bootstrap-qemu.sh; no pixman/display backend is needed.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
version=9.2.0
commit=ae35f033b874c627d81d51070187fbf55f0bf1a7
archive_sha=f859f0bc65e1f533d040bbe8c92bcfecee5af2c921a6687c652fb44d089bd894
python=${PYTHON:-python3}
jobs=${CROSSHAIR_QEMU_JOBS:-4}
variant=${CROSSHAIR_QEMU_MODEL_VARIANT:-e2a}
case "$variant" in e2a|e2b) ;; *) printf 'Unknown model variant: %s\n' "$variant" >&2; exit 2;; esac
case "$jobs" in ''|*[!0-9]*|0) printf 'CROSSHAIR_QEMU_JOBS must be positive\n' >&2; exit 2;; esac
default_cache="$root/local/qemu-blueangel"
if [[ "$variant" == e2b ]]; then default_cache="$root/local/qemu-e2b"; fi
base=${CROSSHAIR_QEMU_BLUEANGEL_DIR:-"$default_cache"}
baseline=${CROSSHAIR_QEMU_BASELINE_SOURCE:-"$root/local/qemu/qemu-$version"}
downloads=${CROSSHAIR_QEMU_ARCHIVE_DIR:-"$root/local/downloads"}
src="$base/qemu-$version"
build="$base/build"
venv=${CROSSHAIR_QEMU_BUILD_VENV:-"$base/venv"}
evidence="$base/evidence"
overlay="$root/crosshair-emulator/qemu"
archive="$downloads/qemu-$version.tar.xz"
git_tool=git
if [[ $(uname -s) == Darwin ]]; then git_tool=/usr/bin/git; fi
for command in "$python" cc c++ make curl tar git pkg-config; do
    command -v "$command" >/dev/null || { printf 'Missing prerequisite: %s\n' "$command" >&2; exit 1; }
done
mkdir -p "$base" "$build" "$evidence" "$downloads"
base=$(cd "$base" && pwd)
src="$base/qemu-$version"
build="$base/build"
evidence="$base/evidence"
pkg_config=${PKG_CONFIG:-$(command -v pkg-config)}
if [[ $(uname -s) == Darwin ]]; then
    mkdir -p "$base/host-tools"
    cp -X "$pkg_config" "$base/host-tools/pkg-config.partial"
    chmod u+w "$base/host-tools/pkg-config.partial"
    /usr/bin/xattr -c "$base/host-tools/pkg-config.partial"
    /usr/bin/codesign --force --sign - --timestamp=none "$base/host-tools/pkg-config.partial"
    mv "$base/host-tools/pkg-config.partial" "$base/host-tools/pkg-config"
    pkg_config="$base/host-tools/pkg-config"
fi
export PKG_CONFIG="$pkg_config"
if [[ $(uname -s) == Darwin ]]; then
    # QEMU's nested ensurepip also builds a pip user-agent. Keep this C-only
    # build's subprocess PATH free of unrelated unsigned Rust/Homebrew tools.
    export PATH="$base/host-tools:$venv/bin:/usr/bin:/bin:/usr/sbin:/sbin"
fi
"$pkg_config" --exists glib-2.0 || { printf 'glib development package required\n' >&2; exit 1; }
if [[ -d "$baseline" ]] && [[ "$src" -ef "$baseline" ]]; then
    printf 'Refusing to mutate the baseline source tree\n' >&2; exit 1
fi
free_kib=$(df -Pk "$base" | awk 'NR==2 {print $4}')
if (( free_kib < 524288 )); then printf 'Need at least 512 MiB free for emulator build\n' >&2; exit 1; fi
if [[ ! -f "$archive" ]]; then
    curl --fail --location --retry 3 "https://download.qemu.org/qemu-$version.tar.xz" -o "$archive.partial"
    mv "$archive.partial" "$archive"
fi
"$python" - "$archive" "$archive_sha" <<'PY'
import hashlib, pathlib, sys
h = hashlib.sha256()
with pathlib.Path(sys.argv[1]).open('rb') as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        h.update(chunk)
if h.hexdigest() != sys.argv[2]:
    raise SystemExit(f'QEMU source archive hash mismatch: {h.hexdigest()}')
print(f'QEMU source archive hash verified: {h.hexdigest()}')
PY
if [[ ! -f "$evidence/upstream-tag.txt" ]]; then
    "$git_tool" ls-remote https://gitlab.com/qemu-project/qemu.git "refs/tags/v$version^{}" > "$evidence/upstream-tag.txt.partial"
    mv "$evidence/upstream-tag.txt.partial" "$evidence/upstream-tag.txt"
fi
[[ $(awk '{print $1}' "$evidence/upstream-tag.txt") == "$commit" ]] || { printf 'QEMU tag commit mismatch\n' >&2; exit 1; }
if [[ ! -f "$src/configure" ]]; then
    if [[ -d "$baseline" ]] && [[ $(uname -s) == Darwin ]]; then
        # macOS/APFS clonefile, private copy-on-write files; no hard links.
        cp -cR "$baseline" "$src"
        printf 'macOS clonefile copy of baseline\n' > "$evidence/source-copy.txt"
    elif [[ -d "$baseline" ]] && cp --reflink=auto -a "$baseline" "$src" 2>/dev/null; then
        printf 'GNU cp private copy (reflink when available)\n' > "$evidence/source-copy.txt"
    else
        # Fresh source extraction is also valid when no baseline exists.
        tar -xf "$archive" -C "$base"
        printf 'Verified release archive extracted\n' > "$evidence/source-copy.txt"
    fi
fi
# Validate the copied baseline's patch targets against the verified archive,
# then apply an idempotent overlay solely inside the isolated source tree.
"$python" - "$src" "$overlay" "$archive" "$variant" <<'PY'
from pathlib import Path
import sys, tarfile
src, overlay, archive = map(Path, sys.argv[1:4])
variant = sys.argv[4]
symbol = 'CROSSHAIR_BLUEANGEL_' + variant.upper()
if (src / 'VERSION').read_text().strip() != '9.2.0':
    raise SystemExit('Unexpected QEMU source version')
kconfig = f'\nconfig {symbol}\n    bool\n    depends on TCG && ARM\n    select SERIAL\n'
meson = f"\narm_ss.add(when: 'CONFIG_{symbol}', if_true: files('crosshair-blueangel-{variant}.c'))\n"
with tarfile.open(archive) as source:
    for relative, addition in [('hw/arm/Kconfig', kconfig), ('hw/arm/meson.build', meson)]:
        original = source.extractfile('qemu-9.2.0/' + relative).read().decode()
        path = src / relative
        current = path.read_text()
        if current not in (original, original + addition):
            raise SystemExit(f'Unexpected pre-existing source changes: {relative}')
        if current != original + addition:
            path.write_text(original + addition)
for name in (['e2a'] if variant == 'e2a' else ['e2a', 'e2b']):
    target = src / f'hw/arm/crosshair-blueangel-{name}.c'
    payload = (overlay / target.name).read_bytes()
    if not target.exists() or target.read_bytes() != payload:
        target.write_bytes(payload)
config = src / f'configs/devices/arm-softmmu/crosshair-blueangel-{variant}.mak'
payload = f'CONFIG_{symbol}=y\nCONFIG_GENERIC_LOADER=y\n'.encode()
if not config.exists() or config.read_bytes() != payload:
    config.write_bytes(payload)
PY
if [[ ! -x "$venv/bin/python" ]]; then "$python" -m venv "$venv"; fi
if ! "$venv/bin/python" - <<'PY'
import importlib.metadata as metadata
import sys
pins = {'meson': '1.5.0', 'ninja': '1.11.1.3', 'distlib': '0.3.9', 'pycotap': '1.3.1'}
try:
    sys.exit(0 if all(metadata.version(name) == version for name, version in pins.items()) else 1)
except metadata.PackageNotFoundError:
    sys.exit(1)
PY
then
    if [[ $(uname -s) == Darwin ]]; then
        # pip's user-agent probes rustc when it is on PATH. Host QEMU is C;
        # avoid probing an unrelated global Rust installation on macOS.
        PATH=/usr/bin:/bin:/usr/sbin:/sbin "$venv/bin/python" -m pip install --disable-pip-version-check \
            meson==1.5.0 ninja==1.11.1.3 distlib==0.3.9 pycotap==1.3.1
    else
        "$venv/bin/python" -m pip install --disable-pip-version-check \
            meson==1.5.0 ninja==1.11.1.3 distlib==0.3.9 pycotap==1.3.1
    fi
fi
ninja="$venv/bin/ninja"
if [[ $(uname -s) == Darwin ]]; then
    # Native unsigned wheel executables can stall in macOS code validation.
    # Sign only our private runtime copy; never alter a shared helper cache.
    mkdir -p "$base/host-tools"
    ninja="$base/host-tools/ninja"
    cp -X "$venv/bin/ninja" "$ninja.partial"
    chmod u+w "$ninja.partial"
    /usr/bin/xattr -c "$ninja.partial"
    /usr/bin/codesign --force --sign - --timestamp=none "$ninja.partial"
    mv "$ninja.partial" "$ninja"
fi
(
    cd "$build"
    export PATH="$venv/bin:$PATH"
    "$src/configure" --target-list=arm-softmmu --without-default-features \
        --without-default-devices --with-devices-arm="crosshair-blueangel-$variant" \
        --enable-system --enable-tcg --enable-fdt=internal --disable-pixman \
        --disable-werror --disable-docs --disable-tools --disable-guest-agent --disable-rust \
        --disable-debug-info --audio-drv-list= --prefix="$base/install" \
        --python="$venv/bin/python" --ninja="$ninja" \
        > configure.log 2>&1 || { tail -n 100 configure.log >&2; exit 1; }
    "$ninja" -j "$jobs" qemu-system-arm 2>&1 | tee build.log
)
if [[ $(uname -s) == Darwin ]]; then
    # Preserve the upstream build output but replace its runtime inode with
    # an ad-hoc signed copy. Empty FinderInfo/ResourceFork metadata also
    # makes codesign reject an otherwise valid Mach-O; omit and clear it.
    cp -X "$build/qemu-system-arm" "$build/qemu-system-arm.runtime"
    /usr/bin/xattr -c "$build/qemu-system-arm.runtime"
    /usr/bin/codesign --force --sign - --timestamp=none "$build/qemu-system-arm.runtime"
    mv "$build/qemu-system-arm.runtime" "$build/qemu-system-arm"
fi
mkdir -p "$base/bin"
ln -sfn ../build/qemu-system-arm "$base/bin/qemu-system-arm"
"$base/bin/qemu-system-arm" --version | tee "$evidence/version.txt"
"$base/bin/qemu-system-arm" -machine help > "$evidence/machines.txt"
"$base/bin/qemu-system-arm" -cpu help > "$evidence/cpus.txt"
"$base/bin/qemu-system-arm" -device loader,help > "$evidence/loader.txt"
grep -Eq "^crosshair-blueangel-$variant[[:space:]]" "$evidence/machines.txt"
cp "$build/arm-softmmu-config-devices.mak" "$evidence/resolved-devices.mak"
{
    uname -a
    cc --version
    "$venv/bin/python" --version
    "$venv/bin/python" - <<'PY'
import importlib.metadata as metadata
for name in ('meson', 'ninja', 'distlib', 'pycotap', 'pip'):
    print(f'{name}=={metadata.version(name)}')
PY
    "$ninja" --version
    "$pkg_config" --version
    "$pkg_config" --modversion glib-2.0
} > "$evidence/host-tools.txt"
"$python" - "$evidence/source.json" "$base/bin/qemu-system-arm" "$overlay/crosshair-blueangel-$variant.c" "$archive_sha" "$commit" "$variant" <<'PY'
import hashlib, json
from pathlib import Path
import sys
output, binary, overlay, archive_sha, commit, variant = sys.argv[1:]
result = {
    'upstream_version': '9.2.0', 'upstream_commit': commit,
    'upstream_archive_sha256': archive_sha,
    'overlay_sha256': hashlib.sha256(Path(overlay).read_bytes()).hexdigest(),
    'qemu_sha256': hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
    'host_license': 'GPL-2.0-only; see crosshair-emulator/qemu/COPYING.GPL-2.0',
}
if variant == 'e2b':
    result['included_e2a_sha256'] = hashlib.sha256(Path(overlay).with_name('crosshair-blueangel-e2a.c').read_bytes()).hexdigest()
    result['machine'] = 'crosshair-blueangel-e2b'
Path(output).write_text(json.dumps(result, indent=2) + '\n')
PY
printf '%s emulator ready: %s\n' "$variant" "$base/bin/qemu-system-arm"
