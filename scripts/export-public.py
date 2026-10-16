#!/usr/bin/env python3
"""Assemble a reviewed public tree in an existing clean public Git checkout.

Run from the private research tree, or from a public checkout to refresh its
publication templates: python3 scripts/export-public.py --destination PATH
The destination must already be cloned from public origin/main. This program
never clones, commits, pushes, reads home credentials, or copies Git history.
It preserves the destination's committed MIT LICENSE byte for byte.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from urllib.parse import unquote, urlsplit


# Explicit filenames only. New source or evidence must be reviewed and added.
SOURCE_FILES = (
    '.cargo/config.toml', '.gitattributes', '.gitignore', 'Cargo.lock',
    'Cargo.toml', 'build.rs', 'rust-toolchain.toml',
    'link/blueangel.ld', 'link/sections.ld', 'link/versatilepb.ld',
    'scripts/bootstrap-qemu.sh', 'scripts/bootstrap-rust.sh',
    'scripts/build.sh', 'scripts/env.sh', 'scripts/run-qemu.sh', 'scripts/test.sh',
    'scripts/export-public.py', 'src/arch/entry.S', 'src/arch/mod.rs',
    'src/bsp/blueangel.rs', 'src/bsp/versatilepb.rs',
    'src/drivers/mod.rs', 'src/drivers/pl011.rs', 'src/main.rs',
    'tests/test_inspect_blueangel.py', 'tools/inspect_blueangel.py',
    'tools/inspect_haret_static.py', 'tools/requirements-haret.txt',
    'tools/smoke_qemu.py', 'tools/verify_image.py',
    'ARCHITECTURE.md', 'BOOT.md', 'BUILDING.md',
    'docs/BLUEANGEL_BOOT_RESEARCH.md', 'docs/RESEARCH_NEXT.md',
    'crosshair-emulator/README.md', 'crosshair-emulator/FEASIBILITY.md',
    'crosshair-emulator/ROADMAP.md',
    'crosshair-emulator/evidence/qemu-9.1.0-tree-search.json',
    'crosshair-emulator/evidence/qemu-9.2.0-inventory.json',
    'crosshair-emulator/evidence/qemu-source-manifest.json',
    'templates/HARDWARE_OBSERVATION.md', 'templates/TEST_RECORD.md',
    'research/initial_static_report.md', 'research/package_report.json',
    'research/extracted_manifest.json', 'research/rom_inventory.json',
    'publication/templates/public_docs.json',
)
OPTIONAL_SOURCE_FILES = (
    'scripts/bootstrap-qemu-pxa.sh', 'scripts/build-pxa-reference.sh',
    'scripts/test-pxa-reference.sh', 'src/pxa_reference.rs',
    'src/arch/pxa_entry.S', 'src/drivers/pxa_uart.rs', 'link/pxa-reference.ld',
    'tools/smoke_pxa.py', 'tools/qtest_pxa.py', 'tools/qemu_control.py',
    'docs/PXA_REFERENCE_CONTRACT.md', 'docs/PXA_QTEST.md',
)
REPORT_FILES = (
    'reports/BOOT_0.1.md', 'reports/artifacts-sha256.json',
    'reports/cargo.txt', 'reports/rustc.txt', 'reports/target-cfg.txt',
    'reports/target-spec.json', 'reports/rebuild.json', 'reports/test-suite.log',
    'reports/qemu/cpus.txt', 'reports/qemu/host-tools.txt',
    'reports/qemu/machine-availability.txt', 'reports/qemu/machines.txt',
    'reports/qemu/probe-connex.txt', 'reports/qemu/probe-mainstone.txt',
    'reports/qemu/probe-verdex.txt', 'reports/qemu/source.txt',
    'reports/qemu/version.txt',
) + tuple(
    f'reports/{board}/{name}'
    for board in ('blueangel', 'versatilepb', 'versatilepb-panic')
    for name in ('disassembly.txt', 'elf-report.txt', 'image.json', 'size.txt',
                 'qemu-stderr.log', 'qemu-uart.log', 'smoke-test.json')
)
OPTIONAL_REPORT_FILES = ('reports/E1_PXA_REFERENCE.md',
                         'reports/public-validation.json', 'reports/public-validation.log') + tuple(
    f'crosshair-emulator/evidence/pxa-reference/{board}/{name}'
    for board in ('connex', 'verdex', 'mainstone')
    for name in ('disassembly.txt', 'elf-report.txt', 'image.json', 'size.txt',
                 'qemu-stderr.log', 'qemu-uart.log', 'smoke-test.json',
                 'qtest.json', 'qtest.log', 'uart.log', 'test-report.json',
                 'qtest-result.json', 'protocol.log')
) + tuple(
    f'crosshair-emulator/evidence/pxa-reference/{name}'
    for name in ('source.json', 'source.txt', 'version.txt', 'machines.txt',
                 'cpus.txt', 'host-tools.txt', 'baseline-summary.json',
                 'baseline-summary.md', 'image.json', 'disassembly.txt',
                 'elf-report.txt', 'size.txt')
)
AUDIT_PATH = 'reports/public-export-audit.json'
DENIED_TOP = {'.git', 'local', 'private', 'work', 'target', 'history', 'evidence'}
DENIED_SUFFIX = {'.jpg', '.jpeg', '.png', '.gif', '.zip', '.exe', '.dll',
                 '.nbf', '.nba', '.cab', '.bin', '.elf', '.iso', '.vmdk'}
DENIED_NAMES = {'HISTORY.md', 'PROJECT_DOSSIER.md', 'device_baseline.json',
                'RESTORATION.md', 'LOCALIZATION_AND_ARCHIVE.md',
                'PROJECT_CROSSHAIR_v0.1_original.md', 'input-validation.json',
                'document-validation.json'}
PRIVATE_PATH = re.compile(r'/(?:Users|home)/[^/\s"\'<>]+/|/(?:private/)?var/folders/')
LOCAL_HOST = re.compile(r'\b[A-Za-z0-9][A-Za-z0-9._-]*\.local\b')
SECRET = re.compile(
    r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|'
    r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b|'
    r'\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b|'
    r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|'
    r'\b[A-Z0-9]{5}(?:-[A-Z0-9]{5}){4}\b|'
    r'(?<![A-Za-z0-9])\d{15}(?![A-Za-z0-9])|'
    r'https?://[^/\s:@]+:[^/\s@]+@'
)
PERSONAL_STORY = re.compile(r'в детстве|семейной поездке|забрал у отца|Мать владельца', re.I)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(name: str) -> str:
    p = PurePosixPath(name)
    if (p.is_absolute() or not p.parts or '..' in p.parts or
            p.parts[0] in DENIED_TOP or p.suffix.lower() in DENIED_SUFFIX or
            p.name in DENIED_NAMES):
        raise ValueError(f'Not an allowed public path: {name!r}')
    return p.as_posix()


def safe_file(root: Path, name: str) -> Path:
    name = safe_name(name)
    path = root / name
    if not path.resolve().is_relative_to(root):
        raise ValueError(f'Path escapes checkout: {name}')
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError(f'Symlinks are not exported: {name}')
    return path


def git(root: Path, *args: str) -> str:
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def normalize(text: str, source: Path) -> str:
    text = text.replace(str(source), '<workspace>')
    text = re.sub(r'/(?:Users|home)/[^/\s"\'<>]+(?:/[^\s"\'<>`),;]+)*',
                  '<host-path>', text)
    text = re.sub(r'/(?:private/)?var/folders/[^\s"\'<>`),;]+',
                  '<temporary-qmp-socket>', text)
    text = re.sub(r'/tmp/crosshair-[^/\s"\'<>]+/qmp\.sock',
                  '<temporary-qmp-socket>', text)
    return LOCAL_HOST.sub('<build-host>', text)


def public_text(name: str, text: str, source: Path) -> str:
    # These targeted transformations remove private bundle references from
    # otherwise technical documents; the private original is never edited.
    if name == '.gitattributes':
        text = text.replace('# Preserve this historical source file\'s final blank line.\n'
                            'evidence/INDEX.md whitespace=-blank-at-eol,-blank-at-eof\n', '')
    if name == 'reports/BOOT_0.1.md':
        text = '\n'.join(line for line in text.split('\n')
                         if not line.startswith('| Входные материалы |'))
        text = text.replace('публичного репозитория и публикации ROM нет.',
                            'ROM не публикуется; исходники доступны отдельным чистым экспортом.')
    if name == 'docs/RESEARCH_NEXT.md':
        start, end = text.find('## Ревизия входа и воспроизводимость'), text.find('## M1 —')
        if start >= 0 and end > start:
            text = text[:start] + (
                '## Воспроизводимость\n\n'
                'Полный ROM-анализ требует исходных EXE/NBA, отсутствующих в публичном репозитории. '
                'Исторические каталоги не являются текущим rerun. '
                'Parser проверен 19 синтетическими тестами, включая CAB backend и повреждённый ввод.\n\n'
            ) + text[end:]
    if name == 'docs/BLUEANGEL_BOOT_RESEARCH.md':
        text = text.replace('совпадает с фото RAM 128 MB в HARDWARE.md.',
                            'соответствует историческому профилю Blue Angel.')
        text = text.replace('ещё не выбранную лицензию Crosshair',
                            'MIT лицензию собственного кода Crosshair')
    if name == 'crosshair-emulator/FEASIBILITY.md':
        text = text.replace('Лицензия Crosshair по-прежнему не выбрана.',
                            'Собственный код Crosshair распространяется по MIT; '
                            'условия сторонних исходников остаются отдельными.')
    if name == 'docs/PXA_REFERENCE_CONTRACT.md':
        text = text.replace('лицензия Crosshair по-прежнему не выбирается автоматически.',
                            'собственный код Crosshair распространяется по MIT, '
                            'сторонние исходники сохраняют свои условия.')
    return normalize(text, source)


def anchors(text: str) -> set[str]:
    result = set(re.findall(r'<a\s+(?:id|name)=["\']([^"\']+)', text))
    seen: dict[str, int] = {}
    for heading in re.findall(r'^#{1,6}\s+(.+)$', text, re.M):
        heading = re.sub(r'<[^>]+>', '', heading).lower().replace('`', '')
        base = re.sub(r'[^\w\- ]', '', heading, flags=re.UNICODE).replace(' ', '-')
        number = seen.get(base, 0)
        result.add(base if not number else f'{base}-{number}')
        seen[base] = number + 1
    return result


def validate(files: dict[str, dict], license_data: bytes) -> int:
    texts = {name: item['data'].decode('utf-8') for name, item in files.items()}
    known = set(files) | {'LICENSE', AUDIT_PATH}
    links = 0
    for name, text in texts.items():
        if PRIVATE_PATH.search(text) or LOCAL_HOST.search(text) or SECRET.search(text):
            raise ValueError(f'Private path, hostname or credential pattern in {name}')
        if name.endswith('.md') and PERSONAL_STORY.search(text):
            raise ValueError(f'Personal narrative in {name}')
        if name.endswith('.json'):
            json.loads(text)
        if not name.endswith('.md'):
            continue
        for target in re.findall(r'\]\(([^)\s]+)(?:\s+[^)]*)?\)', text):
            if urlsplit(target).scheme or target.startswith('//'):
                continue
            url = urlsplit(unquote(target.strip('<>')))
            path = os.path.normpath(str(PurePosixPath(name).parent / url.path)).replace(os.sep, '/')
            if not url.path:
                path = name
            if path not in known:
                raise ValueError(f'Broken public link in {name}: {target}')
            if url.fragment and path.endswith('.md') and url.fragment not in anchors(texts[path]):
                raise ValueError(f'Broken public anchor in {name}: {target}')
            links += 1
    if not license_data.startswith(b'MIT License\n'):
        raise ValueError('Destination LICENSE is not the expected existing MIT license')
    return links


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--destination', type=Path,
                   help='Existing public clone; default SOURCE/local/public-crosshair')
    args = p.parse_args()
    source = args.source.resolve()
    destination = (args.destination or source / 'local/public-crosshair').resolve()
    if source == destination or source.is_relative_to(destination):
        raise ValueError('Destination must be a separate public checkout')
    if not (destination / '.git').is_dir():
        raise ValueError('Clone public origin/main into the destination first')
    base = git(destination, 'rev-parse', 'refs/remotes/origin/main')
    subprocess.run(['git', '-C', str(destination), 'merge-base', '--is-ancestor',
                    base, 'HEAD'], check=True, capture_output=True)
    license_path = destination / 'LICENSE'
    if license_path.is_symlink():
        raise ValueError('Refusing symlink LICENSE')
    license_data = license_path.read_bytes()
    committed_license = subprocess.run(['git', '-C', str(destination), 'show', 'HEAD:LICENSE'],
                                       check=True, capture_output=True).stdout
    if committed_license != license_data:
        raise ValueError('Destination LICENSE differs from its committed original')

    files: dict[str, dict] = {}
    for name in SOURCE_FILES + OPTIONAL_SOURCE_FILES + REPORT_FILES + OPTIONAL_REPORT_FILES:
        path = safe_file(source, name)
        if not path.is_file():
            if name in SOURCE_FILES:
                raise ValueError(f'Required allowlisted source missing: {name}')
            continue
        data = path.read_bytes()
        text = public_text(name, data.decode('utf-8'), source)
        files[name] = {'data': text.encode('utf-8'),
                       'mode': stat.S_IMODE(path.stat().st_mode),
                       'kind': 'source' if name in SOURCE_FILES + OPTIONAL_SOURCE_FILES else 'report',
                       'normalized': normalize(data.decode('utf-8'), source).encode('utf-8') != data,
                       'transformed': text.encode('utf-8') != data}

    templates = json.loads((source / 'publication/templates/public_docs.json').read_text())
    if templates.get('format') != 1:
        raise ValueError('Unsupported public template format')
    pxa_status = ('PXA reference: [контракт](docs/PXA_REFERENCE_CONTRACT.md), '
                  '[результаты](reports/E1_PXA_REFERENCE.md). '
                  'Это исторические reference boards, не Blue Angel.') if (
                      'docs/PXA_REFERENCE_CONTRACT.md' in files and
                      'reports/E1_PXA_REFERENCE.md' in files) else 'PXA reference baseline готовится отдельно.'
    for name, text in templates['files'].items():
        safe_name(name)
        text = text.replace('@@PXA_REFERENCE_STATUS@@', pxa_status)
        files[name] = {'data': text.encode('utf-8'), 'mode': 0o644,
                       'kind': 'public-template', 'normalized': False, 'transformed': False}

    link_count = validate(files, license_data)
    audit_file = destination / AUDIT_PATH
    old_files = json.loads(audit_file.read_text()).get('files', {}) if audit_file.exists() else {}
    # Preserve any edits made directly in the export checkout after a prior run.
    for name, old in old_files.items():
        if name == 'LICENSE':
            continue
        path = safe_file(destination, name)
        if path.exists() and digest(path.read_bytes()) != old['sha256']:
            raise ValueError(f'Export file edited outside exporter; preserve/reconcile first: {name}')
    allowed_existing = set(old_files) | {'README.md'}
    for name, item in files.items():
        path = safe_file(destination, name)
        if path.exists() and name not in allowed_existing and path.read_bytes() != item['data']:
            raise ValueError(f'Unmanaged destination file would be overwritten: {name}')
    for name in set(old_files) - set(files) - {'LICENSE'}:
        path = safe_file(destination, name)
        if path.is_file():
            path.unlink()
    for name, item in sorted(files.items()):
        path = safe_file(destination, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(item['data'])
        path.chmod(item['mode'])

    records = {name: {'sha256': digest(item['data']), 'bytes': len(item['data']),
                       'kind': item['kind'], 'host_paths_normalized': item['normalized'],
                       'public_presentation_transformed': item['transformed']}
               for name, item in sorted(files.items())}
    records['LICENSE'] = {'sha256': digest(license_data), 'bytes': len(license_data),
                          'kind': 'preserved-upstream-license', 'host_paths_normalized': False}
    audit = {'format': 1, 'generated_utc': datetime.now(timezone.utc).isoformat(),
             'public_base_commit': base, 'license_preserved_byte_for_byte': True,
             'policy': 'Explicit allowlist; no private Git history, photos, ROM, device data or input archives',
             'reports': 'Presentation copies; host paths/hostnames/QMP temporaries normalized; guest bytes/hashes retained',
             'validation': {'json_readable': True, 'local_markdown_links_checked': link_count,
                            'private_path_hostname_and_known_secret_pattern_hits': 0},
             'files': records,
             'audit_self_hash': 'Omitted to avoid recursive hashing; all delivered source/template/report paths are listed'}
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    audit_file.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    if license_path.read_bytes() != license_data:
        raise RuntimeError('LICENSE changed unexpectedly')
    print(f'Public export prepared: {len(records)} files; {link_count} local Markdown links checked.')
    print('LICENSE preserved. No commit, push or private history transfer performed.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
