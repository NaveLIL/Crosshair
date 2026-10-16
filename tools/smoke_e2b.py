#!/usr/bin/env python3
"""Execute CP15/MMU/GPIO and exception probes on the experimental E2B board."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import struct
import tempfile
import time

from qemu_control import Qmp, stop_process
from qtest_pxa import QTest, equal
from smoke_e2a import qemu_version, settle_idle, wait_uart, words

ROOT = Path(__file__).resolve().parents[1]
MACHINE = 'crosshair-blueangel-e2b'
GPIO, PIC = 0x40e00000, 0x40d00000
READY = 'CROSSHAIR E2B — GPIO READY\r\n'.encode()
PASS = 'CROSSHAIR E2B — CP15 MMU GPIO IRQ PASS\r\n'.encode()
EXCEPTION = 'CROSSHAIR E2B — EXPECTED EXCEPTION PASS\r\n'.encode()
FIELDS = ['magic', 'stage', 'error', 'irq_count', 'midr', 'ctr', 'reset_sctlr',
          'reset_ttbr', 'reset_dacr', 'reset_pid', 'debug_id', 'cache_readback',
          'mmu_readback', 'alias_read', 'alias_write', 'restored', 'pending',
          'edges', 'irq_sp', 'fault_kind', 'fault_lr', 'fault_psr', 'dfsr', 'dfar',
          'direction', 'alternate', 'checks', 'expected_source', 'probe_selector']
EVENTS = [(0, 1, 8), (1, 1, 9), (2, 1, 10), (2, 0, 10), (89, 1, 10)]
FAULTS = {1: ('unsupported_GPIO_offset', 0x40e0006c),
          2: ('write_read_only_GPLR', GPIO),
          3: ('byte_width_GPDR', GPIO + 0x14),
          4: ('unsupported_CP14_CLKCFG', None),
          5: ('unsupported_CP14_PWRMODE', None)}


def record(qmp, address):
    values = words(qmp.monitor(f'xp /{len(FIELDS)}wx {address:#x}'))
    equal(len(values), len(FIELDS), 'complete E2B record')
    return dict(zip(FIELDS, values))


def check_cpu(r):
    for key, value in {'magic': 0x45324243, 'error': 0, 'midr': 0x69052903,
                       'ctr': 0x0d172172, 'reset_sctlr': 0x78, 'reset_ttbr': 0,
                       'reset_dacr': 0, 'reset_pid': 0, 'debug_id': 0,
                       'cache_readback': 0x107c, 'mmu_readback': 0x79,
                       'alias_read': 0x13579bdf, 'alias_write': 0x2468ace0,
                       'restored': 1}.items():
        equal(r[key], value, key)


def inject(memory, pin, level):
    # This is a test adapter to QEMU GPIO input pins, not a keyboard driver or
    # a procedure for changing the actual PDA's electrical GPIO levels.
    if not (isinstance(pin, int) and 0 <= pin < 90 and level in (0, 1)):
        raise ValueError('invalid synthetic GPIO input')
    memory.request(f'set_irq_in /machine/gpio unnamed-gpio-in {pin} {level}')


def await_count(memory, address, expected, process, uart, timeout=5):
    deadline = time.monotonic() + timeout
    while True:
        value = memory.readl(address + 4 * FIELDS.index('irq_count'))
        if value == expected:
            return
        if value > expected or process.poll() is not None or b'FAIL' in uart.read_bytes() or time.monotonic() > deadline:
            raise RuntimeError(f'GPIO IRQ count expected {expected}, observed {value}; UART={uart.read_bytes()!r}')
        time.sleep(0.001)


def run(qemu, selector=0):
    image_dir = ROOT / 'target/artifacts/e2b' / ('negative-test' if selector else 'normal')
    out = ROOT / 'target/artifacts/e2b-tests' / (f'fault-{selector}' if selector else 'gpio-boot-reset')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'result.json').unlink(missing_ok=True)
    image = json.loads((image_dir / 'image.json').read_text())
    actual = {p: hashlib.sha256((image_dir / p).read_bytes()).hexdigest() for p in image['sha256']}
    equal(actual, image['sha256'], 'current guest images match manifest')
    symbols = image['symbols']
    equal(symbols['E2B_L1'] & 0x3fff, 0, 'L1 table 16 KiB alignment')
    result = {'result': 'FAIL', 'machine': MACHINE, 'image_sha256': actual,
              'qemu_version': qemu_version(qemu),
              'qemu_sha256': hashlib.sha256(Path(shutil.which(qemu) or qemu).read_bytes()).hexdigest(),
              'scope': 'TCG functional CPU and register-level GPIO subset; hardware validation none'}
    with tempfile.TemporaryDirectory(prefix='crosshair-e2b-') as temp:
        qmp_path, memory_path = Path(temp) / 'qmp', Path(temp) / 'memory'
        command = [qemu, '-machine', MACHINE, '-accel', 'tcg', '-S', '-display', 'none',
                   '-monitor', 'none', '-serial', 'stdio', '-nic', 'none', '-d', 'guest_errors',
                   '-device', f"loader,file={image_dir / 'crosshair-e2b.elf'},cpu-num=0",
                   '-qmp', f'unix:{qmp_path},server=on,wait=off',
                   '-qtest', f'unix:{memory_path},server=on,wait=off',
                   '-qtest-log', str(out / 'memory-server.log')]
        if selector:
            command += ['-device', f'loader,addr=0xa0000100,data={selector},data-len=4']
        result['command'] = command
        uart_path = out / 'qemu-uart.log'
        with uart_path.open('wb') as uart, (out / 'qemu-stderr.log').open('wb') as stderr, (out / 'memory-protocol.log').open('w') as transcript:
            process = subprocess.Popen(command, stdout=uart, stderr=stderr, stdin=subprocess.DEVNULL)
            qmp = memory = None
            try:
                qmp = Qmp(qmp_path, process)
                memory = QTest(memory_path, process, transcript)
                rounds, emitted = [], b''
                for boot in range(1 if selector else 2):
                    deadline = time.monotonic() + 3
                    while int(re.search(r'R15=([0-9a-fA-F]+)', qmp.monitor('info registers'))[1], 16) != symbols['_start']:
                        if time.monotonic() > deadline:
                            raise TimeoutError('reset did not restore ELF entry')
                        time.sleep(0.001)
                    reset_samples = [memory.readl(GPIO), memory.readl(GPIO + 8)]
                    for pin in (0, 1, 2, 89):
                        inject(memory, pin, 0)
                    stage = symbols['CROSSHAIR_E2B_RECORD'] + 4
                    memory.writel(stage, 0xa5a5a5a5)
                    equal(memory.readl(stage), 0xa5a5a5a5, 'pre-entry BSS poison readback')
                    qmp.request('cont')
                    trace = []
                    if not selector:
                        wait_uart(process, uart_path, emitted + READY, 10)
                        qmp.request('stop')
                        ready = record(qmp, symbols['CROSSHAIR_E2B_RECORD'])
                        check_cpu(ready)
                        equal((ready['stage'], ready['irq_count'], ready['checks']), (1, 0, 0x1f), 'CPU and GPIO initialization completed')
                        equal(ready['direction'], 1 << 25, 'GPIO89 inverted input direction')
                        equal(ready['alternate'], 1 << 18, 'GPIO89 AF1')
                        for index, (pin, level, source) in enumerate(EVENTS):
                            inject(memory, pin, level)
                            if index == 0:
                                equal(memory.readl(PIC + 4), 0, 'PIC initially masks the pending GPIO0 edge')
                                equal(memory.readl(PIC), 0, 'masked edge does not reach CPU IRQ')
                                equal(memory.readl(PIC + 0x10), 1 << source, 'masked edge remains raw pending')
                            else:
                                equal(memory.readl(PIC), 1 << source, 'source reached PIC before guest IRQ execution')
                            qmp.request('cont')
                            await_count(memory, symbols['CROSSHAIR_E2B_RECORD'], index + 1, process, uart_path)
                            qmp.request('stop')
                            observed = record(qmp, symbols['CROSSHAIR_E2B_RECORD'])
                            equal(observed['error'], 0, 'handler reported no error')
                            equal(observed['pending'], 1 << source, 'handler read expected PIC source')
                            equal(observed['edges'], 1 << (pin % 32), 'handler read the correct GEDR bit')
                            trace.append({'pin': pin, 'level': level, 'source': source,
                                          'irq_count': observed['irq_count'], 'pending': observed['pending'], 'edges': observed['edges']})
                        qmp.request('cont')
                    expected_uart = EXCEPTION if selector else emitted + READY + PASS
                    wait_uart(process, uart_path, expected_uart, 10)
                    qmp.request('stop')
                    registers = settle_idle(qmp, symbols['kernel_idle'])
                    observed = record(qmp, symbols['CROSSHAIR_E2B_RECORD'])
                    check_cpu(observed)
                    reg = lambda name: int(re.search(rf'{name}=([0-9a-fA-F]+)', registers)[1], 16)
                    equal(reg('PSR') & 0xff, 0xd3, 'terminal SVC with IRQ/FIQ masked')
                    if not (symbols['__stack_bottom'] <= reg('R13') <= symbols['__stack_top'] and reg('R13') % 8 == 0):
                        raise AssertionError('invalid SVC stack')
                    if selector:
                        equal((observed['stage'], observed['irq_count'], observed['checks']), (5, 0, 0xf), 'expected exception after CPU probes')
                        equal(observed['probe_selector'], selector, 'negative selector')
                        equal((observed['direction'], observed['alternate']), (0, 0), 'negative probe leaves GPIO reset direction/AF intact')
                        equal(observed['fault_psr'] & 0xff, 0xd3, 'captured pre-fault SVC state')
                        if selector <= 3:
                            equal(observed['fault_kind'], 3, 'actual data-abort vector')
                            equal(observed['dfsr'] & 0x100f, 0x1008, 'DFSR precise external MEMTX_ERROR')
                            equal(observed['dfar'], FAULTS[selector][1], 'exact failing GPIO address')
                        else:
                            equal(observed['fault_kind'], 1, 'actual undefined-instruction vector for absent CP14 register')
                            opcode_address = observed['fault_lr'] - 4
                            expected_opcode = 0xee160e10 if selector == 4 else 0xee170e10
                            offset = opcode_address - image['entry']
                            raw = (image_dir / 'crosshair-e2b.bin').read_bytes()
                            if not (0 <= offset <= len(raw) - 4):
                                raise AssertionError('undefined opcode outside current RAM image')
                            equal(struct.unpack_from('<I', raw, offset)[0], expected_opcode,
                                  'actual ELF instruction at UNDEF LR-4 is the selected CP14 MRC')
                            equal(memory.readl(opcode_address), expected_opcode, 'executed opcode matches hashed image')
                            result['undefined_opcode'] = hex(expected_opcode)

                        if not (image['entry'] < observed['fault_lr'] < image['entry'] + image['segments'][1]['filesz']):
                            raise AssertionError('exception LR outside current executable text')
                        result['probe'] = FAULTS[selector][0]
                    else:
                        equal((observed['stage'], observed['irq_count'], observed['checks']), (2, 5, 0x7f), 'masked edge, five GPIO IRQs and terminal success')
                        if not (symbols['__irq_stack_bottom'] <= observed['irq_sp'] < symbols['__irq_stack_top'] and observed['irq_sp'] % 8 == 0):
                            raise AssertionError('invalid IRQ stack')
                        equal(memory.readl(PIC + 4), 0, 'PIC masked at completion')
                        equal(memory.readl(GPIO + 0x48), 0, 'GEDR0 acknowledged')
                        equal(memory.readl(GPIO + 0x50), 0, 'GEDR2 acknowledged')
                    rounds.append({'boot': boot + 1, 'pre_entry_stage': 0xa5a5a5a5,
                                   'reset_external_samples': reset_samples, 'gpio_trace': trace,
                                   'record': observed, 'registers': registers})
                    emitted = expected_uart
                    if boot == 0 and not selector:
                        qmp.request('system_reset')
                equal(uart_path.read_bytes(), emitted, 'exact UART bytes')
                result.update(boots=rounds, uart_utf8=emitted.decode())
                qmp.request('quit')
                process.wait(timeout=3)
                equal(process.returncode, 0, 'clean QEMU exit')
                result['result'] = 'PASS'
            except Exception as error:
                result.update(result='FAIL', error=f'{type(error).__name__}: {error}')
                if qmp and process.poll() is None:
                    try:
                        qmp.request('stop')
                        result['failure_registers'] = qmp.monitor('info registers')
                        result['failure_record'] = record(qmp, symbols['CROSSHAIR_E2B_RECORD'])
                    except Exception:
                        pass
                raise
            finally:
                try:
                    if memory: memory.close()
                    if qmp: qmp.close()
                    stop_process(process)
                except Exception as error:
                    result.update(result='FAIL', cleanup_error=f'{type(error).__name__}: {error}')
                    raise
                finally:
                    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f"PASS E2B {FAULTS[selector][0] if selector else 'CP15/MMU/GPIO five IRQs + reset reboot'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', default=os.environ.get('QEMU_E2B', str(ROOT / 'local/qemu-e2b/bin/qemu-system-arm')))
    args = parser.parse_args()
    run(args.qemu)
    for selector in FAULTS:
        run(args.qemu, selector)


if __name__ == '__main__':
    main()
