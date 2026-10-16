#!/usr/bin/env python3
"""Collect explicit Wave004 text evidence without replacing accepted reports.

Run only after test-wave004.sh exits0. Own PNG/raw/ELF outputs remain in target.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'b1f3323a39322886650d370be948eb291c904d98'
spec = importlib.util.spec_from_file_location('public_export', ROOT / 'scripts/export-public.py')
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--qemu-cache', type=Path, default=ROOT / 'local/qemu-display-test')
    args = parser.parse_args()
    artifacts, output = ROOT / 'target/artifacts', ROOT / 'reports/wave004'
    copies, statuses = {}, {}

    def add(relative, source):
        copies[relative] = source
        if source.name in ('result.json', 'smoke-test.json', 'qtest-result.json', 'validation.json'):
            status = json.loads(source.read_text())['result']
            if status not in ('PASS', 'PASS_WITH_RECORDED_MODEL_LIMITATIONS'):
                raise ValueError(f'Cannot collect failed evidence: {relative}: {status}')
            statuses[relative] = status

    for name in ('image.json', 'size.txt', 'elf-report.txt', 'disassembly.txt'):
        add('image/' + name, artifacts / 'display-test/image' / name)
    for name in ('result.json', 'qemu-uart.log', 'qemu-stderr.log'):
        add('execution/' + name, artifacts / 'display-test/execution' / name)
    for name in ('result.json', 'qemu-stderr.log'):
        add('qtest/' + name, artifacts / 'display-qtest' / name)
    for name in ('source.json', 'version.txt', 'machines.txt', 'displays.txt', 'host-tools.txt', 'resolved-devices.mak', 'loader.txt'):
        add('build/' + name, args.qemu_cache / 'evidence' / name)
    for name in ('validation.json', 'tests.log', 'memory-layout.json', 'arm-lib-report.txt', 'font-generator-check.json', 'encoder-generator-checks.json', 'ui02-input-trace.json'):
        add('ui/' + name, artifacts / 'ui' / name)
    for name in ('frames.json', 'boundary-frames.json', 'boundary-trace.json'):
        add('ui/' + name, artifacts / 'ui/design-system' / name)
    add('all-tests.log', artifacts / 'wave004/all-tests.log')
    add('missing-reference-check.json', artifacts / 'wave004/missing-reference-check.json')
    for board in ('versatilepb', 'versatilepb-panic'):
        add('regressions/' + board + '.json', artifacts / board / 'smoke-test.json')
    for board in ('connex', 'verdex', 'mainstone'):
        add(f'regressions/e1-{board}-tcg.json', artifacts / 'pxa-reference' / board / 'smoke-test.json')
        add(f'regressions/e1-{board}-qtest.json', artifacts / 'pxa-qtest' / board / 'qtest-result.json')
    for wave, scenarios in (('e2a', ('boot-reset', 'fault-1', 'fault-2', 'fault-3', 'fault-4')),
                            ('e2b', ('gpio-boot-reset', 'fault-1', 'fault-2', 'fault-3', 'fault-4', 'fault-5'))):
        for scenario in scenarios:
            add(f'regressions/{wave}-{scenario}.json', artifacts / (wave + '-tests') / scenario / 'result.json')
        add(f'regressions/{wave}-qtest.json', artifacts / (wave + '-qtest') / 'result.json')

    ui = json.loads((artifacts / 'ui/validation.json').read_text())
    for name, expected in ui['source_sha256'].items():
        assert sha((ROOT / name).read_bytes()) == expected, name
    for name, expected in ui['artifacts_sha256'].items():
        assert sha((artifacts / 'ui' / name).read_bytes()) == expected, name
    run = json.loads((artifacts / 'display-test/execution/result.json').read_text())
    image = json.loads((artifacts / 'display-test/image/image.json').read_text())
    assert run['image_sha256'] == image['sha256']
    for name, expected in image['sha256'].items():
        assert sha((artifacts / 'display-test/image' / name).read_bytes()) == expected, name
    build = json.loads((args.qemu_cache / 'evidence/source.json').read_text())
    assert run['qemu_sha256'] == build['qemu_sha256'] == sha((args.qemu_cache / 'bin/qemu-system-arm').read_bytes())
    assert sha((ROOT / 'crosshair-emulator/qemu/crosshair-blueangel-display-test.c').read_bytes()) == build['overlay_sha256']
    assert run['pixel_comparisons'] == 23
    assert sum(b['events'] for b in run['boots']) == 101
    assert json.loads((artifacts / 'display-qtest/result.json').read_text())['qemu_sha256'] == build['qemu_sha256']
    for name, expected in run['ui_source_sha256'].items():
        assert sha((ROOT / name).read_bytes()) == expected, name

    # Preserve exact accepted implementation bytes and flat machine-code images.
    old = json.loads((ROOT / 'reports/wave003/validation.json').read_text())
    baseline = dict(old['unchanged_baseline_source_sha256'])
    for name in ('crosshair-emulator/qemu/crosshair-blueangel-e2b.c', 'src/e2b.rs', 'src/arch/e2b_entry.S', 'tools/smoke_e2b.py', 'tools/qtest_e2b.py'):
        payload = subprocess.check_output(['/usr/bin/git', '-C', str(ROOT), 'show', BASE + ':' + name])
        baseline[name] = sha(payload)
    for name, expected in baseline.items():
        assert sha((ROOT / name).read_bytes()) == expected, name
    binary_hashes = {}
    for old_manifest, current in (
        ('crosshair-emulator/evidence/pxa-reference/image.json', 'pxa-reference/image.json'),
        ('crosshair-emulator/evidence/e2a/images/normal/image.json', 'e2a/normal/image.json'),
        ('crosshair-emulator/evidence/e2b/images/normal/image.json', 'e2b/normal/image.json'),
        ('crosshair-emulator/evidence/e2b/images/negative-test/image.json', 'e2b/negative-test/image.json'),
    ):
        accepted = json.loads(subprocess.check_output(['/usr/bin/git', '-C', str(ROOT), 'show', BASE + ':' + old_manifest]))
        now = json.loads((artifacts / current).read_text())
        for name, expected in accepted['sha256'].items():
            if not name.endswith('.elf'):
                assert now['sha256'][name] == expected, name
                binary_hashes[current + ':' + name] = expected

    copied = {}
    for relative, source in copies.items():
        original = source.read_bytes()
        text = export.normalize(original.decode('utf8'), ROOT)
        if export.PRIVATE_PATH.search(text) or export.LOCAL_HOST.search(text) or export.SECRET.search(text):
            raise ValueError('Private material: ' + relative)
        payload = text.encode('utf8')
        if source.name == 'qemu-uart.log':
            assert payload == original, 'UART must remain byte-exact'
        destination = output / relative
        destination.parent.mkdir(exist_ok=True, parents=True)
        destination.write_bytes(payload)
        copied[relative] = sha(payload)
    sources = ('src/display_test.rs', 'src/arch/mod.rs', 'link/display-test.ld', 'Cargo.toml', 'Cargo.lock', 'build.rs', 'tools/smoke_display.py', 'tools/qtest_display.py', 'scripts/build-display-test.sh', 'scripts/test-display.sh', 'scripts/test-wave004.sh', 'scripts/bootstrap-qemu-display-test.sh', 'scripts/bootstrap-qemu-blueangel.sh')
    (output / 'validation.json').write_text(json.dumps({
        'result': 'PASS', 'accepted_base': BASE,
        'scope': 'executed ARM UI via TCG/synthetic display; no physical HTC or ATI emulation',
        'normalization': 'host paths/hostnames/sockets only; UART byte-exact',
        'results': statuses, 'source_sha256': {n: sha((ROOT / n).read_bytes()) for n in sources},
        'unchanged_baseline_source_sha256': baseline, 'unchanged_baseline_flat_image_sha256': binary_hashes,
        'copied_evidence_sha256': copied,
        'local_protocols': {str(p.relative_to(ROOT)): {'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())}
                            for p in (artifacts / 'display-test/execution/memory-protocol.log', artifacts / 'display-qtest/protocol.log')},
    }, indent=2) + '\n')
    print(f'Collected {len(copies)} Wave004 text files, {len(statuses)} test records; accepted evidence unchanged')


if __name__ == '__main__':
    if not __debug__:
        raise SystemExit('Evidence verification requires assertions; unset PYTHONOPTIMIZE')
    main()
