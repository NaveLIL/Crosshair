#!/usr/bin/env python3
"""Execute crosshair-ui in TCG, compare guest RAM/QEMU console with host PNG.

Only the named synthetic board is used. No firmware, physical device or disk.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import time
import zlib

from framebuffer_png import encode
from qemu_control import Qmp, stop_process
from qtest_pxa import QTest, equal
from smoke_e2a import qemu_version

ROOT = Path(__file__).resolve().parents[1]
MACHINE = 'crosshair-blueangel-display-test'
DISPLAY, INPUT = 0x10000000, 0x10001000
FB_BYTES = 153600
READY = 'CROSSHAIR DISPLAY TEST — UI READY\r\n'.encode()
FIELDS = ['magic', 'stage', 'error', 'events', 'frames', 'framebuffer',
          'framebuffer_bytes', 'width', 'height', 'stride', 'guards', 'last_wire',
          'changed', 'view', 'focus', 'selected_item', 'scroll', 'matches',
          'filter_len', 'opened', 'generation', 'present_rects', 'dirty_left',
          'sentinel', 'svc_sp', 'midr', 'sctlr', 'apps_bytes', 'queue_bytes',
          'surface_bytes', 'fault_lr', 'fault_psr']
TAGS = {name: i + 1 for i, name in enumerate(('Up', 'Down', 'Left', 'Right', 'Select', 'Back', 'Menu', 'TextInput'))}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def memory_read(memory, address, size):
    # Small records/guards only. Full framebuffer transfers use QMP pmemsave,
    # keeping giant hex payloads out of the presentation protocol transcript.
    response = memory.request(f'read {address:#x} {size:#x}')
    raw = bytes.fromhex(response[0].removeprefix('0x'))
    equal(len(raw), size, 'complete memory block')
    return raw


def record(memory, address):
    return dict(zip(FIELDS, struct.unpack('<32I', memory_read(memory, address, 128))))


def png_rgb(path):
    """Strict decoder for the project's own RGB888/filter0 reference PNGs."""
    data = path.read_bytes()
    equal(data[:8], b'\x89PNG\r\n\x1a\n', 'PNG signature')
    position, packed, dimensions = 8, bytearray(), None
    ended = False
    while position < len(data):
        length = struct.unpack_from('>I', data, position)[0]
        kind = data[position + 4:position + 8]
        payload = data[position + 8:position + 8 + length]
        equal(len(payload), length, 'PNG chunk length')
        crc = struct.unpack_from('>I', data, position + 8 + length)[0]
        equal(zlib.crc32(kind + payload), crc, 'PNG CRC')
        if kind == b'IHDR':
            dimensions = struct.unpack('>IIBBBBB', payload)
            equal(dimensions, (240, 320, 8, 2, 0, 0, 0), 'PNG geometry/format')
        elif kind == b'IDAT':
            packed.extend(payload)
        elif kind == b'IEND':
            ended = True
        position += 12 + length
    equal((position, ended), (len(data), True), 'complete PNG')
    equal(dimensions is not None, True, 'PNG dimensions present')
    rows = zlib.decompress(packed)
    equal(len(rows), 320 * 721, 'PNG scanline bytes')
    equal(all(rows[y * 721] == 0 for y in range(320)), True, 'reference filter0')
    return b''.join(rows[y * 721 + 1:(y + 1) * 721] for y in range(320))


def ppm_rgb(path):
    data = path.read_bytes()
    header = re.match(rb'P6\n240 320\n255\n', data)
    if not header:
        raise ValueError(f'Unexpected QEMU PPM header: {data[:32]!r}')
    pixels = data[header.end():]
    equal(len(pixels), 240 * 320 * 3, 'QEMU console geometry')
    return pixels


def wire(event):
    return (TAGS[event['kind']] << 24) | (ord(event['text']) if event['kind'] == 'TextInput' else 0)


def check_state(observed, expected):
    view = expected['view']
    view_id = 0 if view == 'List' else 2 if view == 'Menu' else 0x100 | int(re.fullmatch(r'Action\((\d+)\)', view)[1])
    focus = {'List': 0, 'LeftSoftkey': 1, 'RightSoftkey': 2}[expected['focus']]
    for key in ('scroll', 'matches', 'filter_len', 'opened'):
        equal(observed[key], expected[key], f'guest/host {key}')
    equal(observed['view'], view_id, 'guest/host view')
    equal(observed['focus'], focus, 'guest/host keyboard focus')
    equal(observed['selected_item'], expected['selected_item'] if expected['selected_item'] is not None else 0xffffffff, 'guest/host selected item')
    if 'changed' in expected:
        equal(observed['changed'], int(expected['changed']), 'guest/host state-change decision')


def check_guards(memory, symbols, fb):
    base = symbols['DISPLAY_FRAMEBUFFER']
    equal(fb, base + 64, 'pixel field starts after prefix guard')
    for address, count, magic in ((base, 16, 0xc17e0000), (fb + FB_BYTES, 16, 0xf00d0000), (symbols['DISPLAY_SENTINEL'], 64, 0x51a70000)):
        observed = struct.unpack(f'<{count}I', memory_read(memory, address, count * 4))
        equal(observed, tuple(magic ^ i for i in range(count)), 'framebuffer/sentinel bounds')
    equal(memory_read(memory, symbols['__stack_guard'], 64), b'\xcd' * 64, 'stack lower guard')
    equal(memory_read(memory, 0xa0700000, 256), b'\xa7' * 256, 'remote ordinary RAM sentinel')


def capture(qmp, memory, symbols, observed, host_raw, out, name):
    check_guards(memory, symbols, observed['framebuffer'])
    raw, png, ppm = (out / (name + suffix) for suffix in ('.raw565', '.png', '.ppm'))
    qmp.request('pmemsave', {'val': observed['framebuffer'], 'size': FB_BYTES, 'filename': str(raw)})
    equal(raw.read_bytes(), host_raw.read_bytes(), 'byte-exact ARM vs host RGB565')
    encode(raw, png)
    host_png = host_raw.with_suffix('.png')
    encode(host_raw, host_png)
    qmp.request('screendump', {'filename': str(ppm)})
    reference, guest, console = png_rgb(host_png), png_rgb(png), ppm_rgb(ppm)
    count = sum(guest[i:i + 3] != reference[i:i + 3] for i in range(0, len(guest), 3))
    console_count = sum(console[i:i + 3] != reference[i:i + 3] for i in range(0, len(console), 3))
    equal((count, console_count), (0, 0), 'ARM PNG and QEMU console pixel-diff')
    return {'name': name, 'events': observed['events'], 'generation': observed['generation'],
            'different_pixels_guest_host': count, 'different_pixels_console_host': console_count,
            'raw565_sha256': sha(raw.read_bytes()), 'guest_png_sha256': sha(png.read_bytes()),
            'host_png_sha256': sha(host_png.read_bytes()), 'rgb888_sha256': sha(console)}


def await_events(memory, address, count, process):
    deadline = time.monotonic() + 15
    while True:
        observed = record(memory, address)
        if observed['stage'] == 0xff or (observed['magic'] == 0x4453504c and observed['error']):
            raise AssertionError(f'guest fault: {observed}')
        if observed['magic'] == 0x4453504c and observed['stage'] == 2 and observed['events'] == count:
            return
        if process.poll() is not None or time.monotonic() > deadline:
            raise TimeoutError(f'guest event timeout: expected {count}, got {observed}')
        time.sleep(0.002)


def run(qemu, host=None, out=None):
    artifacts = ROOT / 'target/artifacts'
    image_dir = artifacts / 'display-test/image'
    out = out or artifacts / 'display-test/execution'
    host = host or artifacts / 'ui/design-system'
    out.mkdir(exist_ok=True, parents=True)
    (out / 'result.json').write_text(json.dumps({'result': 'FAIL', 'error': 'test not completed'}) + '\n')
    # Remove only this harness's generated snapshots; missing references must
    # never be rescued by screenshots left over from a previous execution.
    for prefix in ('canonical-', 'burst-', 'boundary-'):
        for suffix in ('.png', '.ppm', '.raw565'):
            for old in out.glob(prefix + '*' + suffix):
                old.unlink()
    image = json.loads((image_dir / 'image.json').read_text())
    actual = {n: sha((image_dir / n).read_bytes()) for n in image['sha256']}
    equal(actual, image['sha256'], 'current ELF/flat images')
    symbols = image['symbols']
    normal = json.loads((artifacts / 'ui/ui02-input-trace.json').read_text())['events']
    boundary = json.loads((host / 'boundary-trace.json').read_text())['events']
    equal((len(normal), len(boundary)), (37, 27), 'complete shared input fixtures')
    references = {}
    for name, manifest, count in (('canonical', 'frames.json', 12), ('boundary', 'boundary-frames.json', 8)):
        frames = json.loads((host / manifest).read_text())['frames']
        equal(len(frames), count, 'complete declared host captures')
        references[name] = {}
        for frame in frames:
            expected_name = ('boundary-' if name == 'boundary' else '') + f"step-{frame['state']:02d}.raw565"
            equal(frame['file'], expected_name, 'bounded reference path')
            raw = (host / expected_name).read_bytes()  # Missing reference is fatal.
            equal(len(raw), FB_BYTES, 'reference framebuffer bytes')
            value = 0xcbf29ce484222325
            for byte in raw:
                value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
            equal(f'0x{value:016x}', frame['fnv1a64'], 'host capture manifest hash')
            equal((frame['width'], frame['height'], frame['stride']), (240, 320, 240), 'reference geometry')
            references[name][frame['state']] = host / expected_name
        equal(len(references[name]), count, 'unique capture state numbers')
    references['burst'] = references['canonical']
    layouts = json.loads((artifacts / 'ui/memory-layout.json').read_text())['armv5te']
    initial = {'view': 'List', 'focus': 'List', 'selected_item': 0, 'scroll': 0, 'matches': 16, 'filter_len': 0, 'opened': 0}
    result = {'result': 'FAIL', 'machine': MACHINE, 'scope': 'TCG ARM UI on synthetic display/input; no ATI or physical hardware',
              'qemu_version': qemu_version(qemu), 'qemu_sha256': sha(Path(shutil.which(qemu) or qemu).read_bytes()),
              'image_sha256': actual, 'boots': []}
    with tempfile.TemporaryDirectory(prefix='crosshair-display-') as temp:
        qmp_path, qt_path = Path(temp) / 'qmp', Path(temp) / 'memory'
        command = [qemu, '-machine', MACHINE, '-accel', 'tcg', '-S', '-display', 'none',
                   '-monitor', 'none', '-serial', 'stdio', '-nic', 'none', '-d', 'guest_errors',
                   '-device', f"loader,file={image_dir / 'crosshair-display-test.elf'},cpu-num=0",
                   '-qmp', f'unix:{qmp_path},server=on,wait=off', '-qtest', f'unix:{qt_path},server=on,wait=off',
                   '-qtest-log', str(out / 'memory-server.log')]
        result['command'] = command
        with (out / 'qemu-uart.log').open('wb') as uart, (out / 'qemu-stderr.log').open('wb') as stderr, (out / 'memory-protocol.log').open('w') as transcript:
            process = subprocess.Popen(command, stdout=uart, stderr=stderr, stdin=subprocess.DEVNULL)
            qmp = memory = None
            try:
                qmp = Qmp(qmp_path, process)
                memory = QTest(qt_path, process, transcript)
                for boot, (name, trace, batch) in enumerate((('canonical', normal, 1), ('burst', normal, 8), ('boundary', boundary, 1))):
                    equal(memory.readl(DISPLAY), 0, 'reset framebuffer base')
                    equal(memory.readl(DISPLAY + 0x14), 0, 'reset display generation')
                    equal(memory.readl(INPUT), 0, 'reset input count')
                    equal(memory.readl(INPUT + 0x10), 0, 'reset rejected input counter')
                    equal(int(re.search(r'R15=([a-fA-F0-9]+)', qmp.monitor('info registers'))[1], 16), symbols['_start'], 'ELF reset entry')
                    bss = symbols['__bss_end'] - symbols['__bss_start']
                    memory.request(f"memset {symbols['__bss_start']:#x} {bss:#x} 0xa5")
                    equal(memory.readl(symbols['CROSSHAIR_DISPLAY_RECORD'] + 4), 0xa5a5a5a5, 'pre-entry BSS poison')
                    memory.request(f"memset {symbols['__stack_guard']:#x} {64 + 16384 + 4096:#x} 0xcd")
                    memory.request('memset 0xa0700000 0x100 0xa7')
                    qmp.request('cont')
                    await_events(memory, symbols['CROSSHAIR_DISPLAY_RECORD'], 0, process)
                    qmp.request('stop')
                    observed = record(memory, symbols['CROSSHAIR_DISPLAY_RECORD'])
                    for key, value in {'magic': 0x4453504c, 'stage': 2, 'error': 0, 'events': 0, 'frames': 1,
                                       'framebuffer_bytes': FB_BYTES, 'width': 240, 'height': 320, 'stride': 240,
                                       'guards': 1, 'sentinel': 1, 'generation': 1, 'present_rects': 1, 'dirty_left': 0,
                                       'midr': 0x69052903, 'sctlr': 0x78, 'apps_bytes': layouts['apps_state'],
                                       'queue_bytes': layouts['input_queue'], 'surface_bytes': layouts['surface']}.items():
                        equal(observed[key], value, key)
                    check_state(observed, initial)
                    required = {0}
                    required.update(n for n in references[name] if n % batch == 0 or n == len(trace))
                    captured = {0}
                    frames = [capture(qmp, memory, symbols, observed, references[name][0], out, name + '-00')]
                    states = []
                    expected_frames = 1
                    completed = 0
                    while completed < len(trace):
                        group = trace[completed:completed + batch]
                        for expected in group:
                            memory.writel(INPUT + 8, wire(expected['event']))
                        equal(memory.readl(INPUT), len(group), 'queued test events before ARM execution')
                        if name == 'burst' and completed == 0:
                            memory.writel(INPUT + 8, 7 << 24)  # Full FIFO: must not enter UI.
                            memory.writel(INPUT + 8, (8 << 24) | 0xd800)  # Invalid scalar.
                            equal(memory.readl(INPUT), 8, 'rejected injections preserve queued input')
                            equal(memory.readl(INPUT + 0x10), 2, 'observable rejection counter')
                        qmp.request('cont')
                        completed += len(group)
                        await_events(memory, symbols['CROSSHAIR_DISPLAY_RECORD'], completed, process)
                        qmp.request('stop')
                        observed = record(memory, symbols['CROSSHAIR_DISPLAY_RECORD'])
                        expected = group[-1]
                        expected_frames += sum(int(e['changed']) for e in group)
                        check_state(observed, expected)
                        equal(observed['last_wire'], wire(expected['event']), 'last input encoding')
                        equal((observed['error'], observed['frames'], observed['generation']), (0, expected_frames, expected_frames), 'events cause exactly expected frame generations')
                        equal((observed['dirty_left'], memory.readl(INPUT)), (0, 0), 'present clears dirty and adapter drains')
                        check_guards(memory, symbols, observed['framebuffer'])
                        states.append(observed)
                        if completed in required:
                            candidate = references[name][completed]
                            frames.append(capture(qmp, memory, symbols, observed, candidate, out, f'{name}-{completed:02d}'))
                            captured.add(completed)
                    equal(captured, required, 'all required pixel comparisons executed')
                    registers = qmp.monitor('info registers')
                    sp = int(re.search(r'R13=([a-fA-F0-9]+)', registers)[1], 16)
                    pc = int(re.search(r'R15=([a-fA-F0-9]+)', registers)[1], 16)
                    equal(int(re.search(r'PSR=([a-fA-F0-9]+)', registers)[1], 16) & 0xff, 0xd3, 'privileged ARM with IRQ/FIQ masked')
                    equal(symbols['__stack_bottom'] <= sp <= symbols['__stack_top'] and sp % 8 == 0, True, 'live SVC stack bounds/alignment')
                    equal(image['entry'] <= pc < image['entry'] + image['segments'][1]['filesz'], True, 'live PC in actual ARM image')
                    stack = memory_read(memory, symbols['__stack_bottom'], 16384)
                    first = next((i for i, b in enumerate(stack) if b != 0xcd), len(stack))
                    result['boots'].append({'name': name, 'events': len(trace), 'batch_size': batch, 'frames': frames,
                                            'states': states, 'final_record': observed, 'registers': registers,
                                            'observed_modified_stack_span_bytes': len(stack) - first,
                                            'rejected_inputs': memory.readl(INPUT + 0x10)})
                    # Let the completed initializer finish UART if host observed
                    # STAGE=2 in the few instructions preceding its first send.
                    qmp.request('cont')
                    deadline = time.monotonic() + 3
                    while (out / 'qemu-uart.log').read_bytes() != READY * (boot + 1):
                        if time.monotonic() > deadline:
                            raise TimeoutError('missing exact UART ready line')
                        time.sleep(0.002)
                    qmp.request('stop')
                    if boot < 2:
                        qmp.request('system_reset')
                canonical_final = out / 'canonical-37.raw565'
                equal(canonical_final.read_bytes(), (out / 'burst-37.raw565').read_bytes(), 'single vs burst input framebuffer')
                result['all_logical_event_kinds'] = sorted({e['event']['kind'] for e in normal + boundary})
                equal(len(result['all_logical_event_kinds']), 8, 'all logical event kinds executed')
                result['pixel_comparisons'] = sum(len(b['frames']) for b in result['boots'])
                result['ui_source_sha256'] = {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in sorted((ROOT / 'ui/src').glob('*.rs'))}
                result['memory'] = {'framebuffer_bytes': FB_BYTES, 'framebuffer_guards_bytes': 128, 'sentinel_bytes': 256,
                                    'stack_guard_bytes': 64, 'svc_stack_bytes': 16384, 'irq_stack_bytes': 4096,
                                    'image_ram_extent_bytes': symbols['__image_end'] - image['entry'],
                                    'elf_file_bytes': (image_dir / 'crosshair-display-test.elf').stat().st_size,
                                    'flat_image_bytes': (image_dir / 'crosshair-display-test.bin').stat().st_size,
                                    'arm_layout': layouts}
                qmp.request('quit')
                process.wait(timeout=3)
                equal(process.returncode, 0, 'clean QEMU exit')
                result['result'] = 'PASS'
            except Exception as error:
                result['error'] = f'{type(error).__name__}: {error}'
                if qmp and process.poll() is None:
                    try:
                        qmp.request('stop')
                        result['failure_registers'] = qmp.monitor('info registers')
                        result['failure_record'] = record(memory, symbols['CROSSHAIR_DISPLAY_RECORD'])
                    except Exception:
                        pass
                raise
            finally:
                if memory: memory.close()
                if qmp: qmp.close()
                stop_process(process)
                (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f"PASS ARM display: three boots, {37 * 2 + len(boundary)} events, {result['pixel_comparisons']} exact guest/host/QEMU pixel comparisons, guards, reset, burst/rejection")


def check_missing_reference():
    """Regression for silent capture skipping, using isolated generated copies."""
    source = ROOT / 'target/artifacts/ui/design-system'
    with tempfile.TemporaryDirectory(prefix='crosshair-reference-check-') as temp:
        host, out = Path(temp) / 'host', Path(temp) / 'execution'
        host.mkdir(); out.mkdir()
        for candidate in source.iterdir():
            if candidate.suffix in ('.json', '.raw565'):
                shutil.copyfile(candidate, host / candidate.name)
        (host / 'step-37.raw565').unlink()
        for name in ('canonical-37.raw565', 'burst-37.raw565'):
            (out / name).write_bytes(b'stale previous output')
        try:
            # This path must never be executed: missing reference is preflight.
            run('/nonexistent-crosshair-qemu-preflight', host=host, out=out)
        except FileNotFoundError as error:
            equal(Path(error.filename), host / 'step-37.raw565', 'failed on required reference before QEMU launch')
        else:
            raise AssertionError('missing reference unexpectedly passed')
        equal(json.loads((out / 'result.json').read_text())['result'], 'FAIL', 'failed preflight cannot retain old PASS')
        equal(any(out.glob('*.raw565')), False, 'stale outputs removed')
    destination = ROOT / 'target/artifacts/wave004/missing-reference-check.json'
    destination.parent.mkdir(exist_ok=True, parents=True)
    destination.write_text(json.dumps({'result': 'PASS', 'scope': 'negative harness test',
                                       'missing_required_reference_fails': True, 'fails_before_qemu_launch': True,
                                       'stale_outputs_cannot_supply_success': True}, indent=2) + '\n')
    print('PASS missing-reference regression: fail closed before QEMU, old outputs cannot pass')


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--qemu', default=os.environ.get('QEMU_DISPLAY_TEST', str(ROOT / 'local/qemu-display-test/bin/qemu-system-arm')))
    parser.add_argument('--check-missing-reference', action='store_true')
    args = parser.parse_args()
    if args.check_missing_reference:
        check_missing_reference()
    else:
        run(args.qemu)


if __name__ == '__main__':
    main()
