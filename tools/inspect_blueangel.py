#!/usr/bin/env python3
"""Read-only static inventory of one known i-mate PDA2k update package.

Usage: python3 inspect_blueangel.py ORIGINAL.exe NEW_OUTPUT_DIRECTORY
Requires Python 3.10+ and system libarchive with CAB support (tested on Linux).
No executable from the firmware is executed; no USB/device access occurs.
This is a narrow, preliminary parser, not a general CE ROM extractor.
"""
from __future__ import annotations
import argparse
import array
import ctypes as C
import ctypes.util
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

EXPECTED_MD5 = 'e75252819ff60d383be59230c3eb75a9'
EXPECTED_SHA256 = 'ac59e03898d559d50a5f16c58c7ed0f7596a89138dd72a769f6fe5eb627e46c3'
EXPECTED_FILES = {
    'BaUpgradeUt.exe': 434176, 'EnterBL.exe': 4608,
    'GetDeviceData.exe': 9216, 'HTCRUU.conf': 87,
    'HTCRUU.dll': 188416, 'ms_.nbf': 17236096,
    'nk.nbf': 33554560, 'radio_.nbf': 4194432,
}
KEYS = {'nk.nbf': 0x20040521, 'ms_.nbf': 0x20040522,
        'radio_.nbf': 0x20040523}

def hashes(data: bytes) -> dict:
    return {'size': len(data), 'md5': hashlib.md5(data).hexdigest(),
            'sha256': hashlib.sha256(data).hexdigest()}

def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def extract_cab(cab_path: Path, out: Path) -> list[dict]:
    library = ctypes.util.find_library('archive')
    if library is None:
        raise RuntimeError('System libarchive not found. Use a Linux environment with libarchive CAB support.')
    # FFI contract: libarchive owns the archive/entry handles. Entry pointers and
    # pathname strings are borrowed only until the next header; copy them now.
    # read_data may write at most the provided buffer length. The archive handle
    # is freed on every path after allocation, including output-directory errors.
    lib = C.CDLL(library)
    def fn(name, result, arguments):
        f = getattr(lib, name); f.restype = result; f.argtypes = arguments
        return f
    new = fn('archive_read_new', C.c_void_p, [])
    support = fn('archive_read_support_format_cab', C.c_int, [C.c_void_p])
    open_ = fn('archive_read_open_filename', C.c_int, [C.c_void_p, C.c_char_p, C.c_size_t])
    next_ = fn('archive_read_next_header', C.c_int, [C.c_void_p, C.POINTER(C.c_void_p)])
    name_ = fn('archive_entry_pathname', C.c_char_p, [C.c_void_p])
    size_ = fn('archive_entry_size', C.c_int64, [C.c_void_p])
    read_ = fn('archive_read_data', C.c_ssize_t, [C.c_void_p, C.c_void_p, C.c_size_t])
    error = fn('archive_error_string', C.c_char_p, [C.c_void_p])
    free = fn('archive_read_free', C.c_int, [C.c_void_p])
    a = new()
    if not a: raise RuntimeError('archive_read_new failed')
    seen = set(); manifest = []
    try:
        out.mkdir()
        if support(a) < 0: raise RuntimeError(error(a))
        if open_(a, str(cab_path).encode(), 65536) != 0: raise RuntimeError(error(a))
        while True:
            e = C.c_void_p(); status = next_(a, C.byref(e))
            if status == 1: break
            if status != 0: raise RuntimeError(error(a))
            # This known CAB stores root-prefixed names. Restrict to an exact allowlist.
            raw_name = name_(e)
            if raw_name is None: raise ValueError('CAB entry has no pathname')
            original_name = raw_name.decode('ascii')
            name = original_name.replace('\\', '/').lstrip('/')
            if name not in EXPECTED_FILES or name in seen:
                raise ValueError(f'Unexpected or duplicate CAB path: {original_name!r}')
            expected = EXPECTED_FILES[name]
            if size_(e) != expected: raise ValueError(f'Unexpected length for {name}')
            seen.add(name); total = 0; buf = C.create_string_buffer(65536)
            with (out / name).open('xb') as target:
                while True:
                    n = read_(a, buf, len(buf))
                    if n < 0: raise RuntimeError(error(a))
                    if n == 0: break
                    total += n
                    if total > expected: raise ValueError('CAB output exceeds expected length')
                    target.write(buf.raw[:n])
            if total != expected: raise ValueError('Truncated CAB output')
            manifest.append({'name': name, 'archive_name': original_name,
                             **hashes((out / name).read_bytes())})
    finally:
        free(a)
    if seen != set(EXPECTED_FILES): raise ValueError('Missing expected CAB entries')
    return manifest

def xor_words(data: bytes, key: int) -> bytes:
    if len(data) % 4: raise ValueError('NBF length not divisible by four')
    if not 0 <= key <= 0xffffffff: raise ValueError('NBF XOR key must fit an unsigned 32-bit word')
    words = array.array('I'); words.frombytes(data)
    if words.itemsize != 4: raise RuntimeError('Unsupported native unsigned-int size')
    if sys.byteorder != 'little': words.byteswap()
    decoded = array.array('I', (value ^ key for value in words))
    if sys.byteorder != 'little': decoded.byteswap()
    return decoded.tobytes()

def inventory(b: bytes) -> dict:
    # Addresses in the mapped main OS refer to 0x80000000; NBA includes a 128-byte header.
    if len(b) < 128: raise ValueError('Truncated NBA header')
    def offset(va: int) -> int: return va - 0x80000000 + 128
    def bounds(p: int, n: int) -> None:
        if p < 128 or n < 0 or p + n > len(b):
            raise ValueError(f'Out-of-bounds range {p:#x}, length {n}')
    def name_at(va: int) -> str:
        p = offset(va); bounds(p, 1)
        end = b.find(b'\0', p, min(len(b), p + 256))
        if end < 0: raise ValueError('Unterminated ROM name')
        name = b[p:end].decode('ascii')
        if not name or any(not 32 <= ord(ch) < 127 for ch in name):
            raise ValueError('Invalid ROM name')
        return name
    regions = []; entries = []; excluded = []
    for m in re.finditer(b'ECEC', b):
        sig = m.start()
        # Narrow recognition rule for this exact package; not universal for Windows CE.
        if sig & 0xffff != 0xc0: continue
        bounds(sig, 8)
        va = struct.unpack_from('<I', b, sig + 4)[0]; hdr = offset(va)
        if not 128 <= hdr <= len(b) - 84:
            excluded.append({'signature_offset': hex(sig), 'pointer': hex(va),
                             'reason': 'Outside the supported main-OS mapping'})
            continue
        v = struct.unpack_from('<17I2H3I', b, hdr)
        mods, files = v[4], v[12]
        if mods > 500 or files > 5000: raise ValueError('Implausible ROMHDR counts')
        bounds(hdr + 84, mods * 32 + files * 28)
        if offset(v[2]) != sig - 0x40:
            raise ValueError('Region start does not match ROM signature position')
        bounds(offset(v[2]), v[3] - v[2])
        region = {'signature_offset': hex(sig), 'romhdr_va': hex(va),
                  'romhdr_offset': hex(hdr), 'physical_first': hex(v[2]),
                  'physical_last': hex(v[3]), 'modules': mods, 'files': files,
                  'cpu_type_from_romhdr': hex(v[17])}
        regions.append(region)
        for j in range(mods):
            p = hdr + 84 + j * 32; a = struct.unpack_from('<8I', b, p)
            bounds(offset(a[5]), 1); bounds(offset(a[6]), 1)
            entries.append({'kind': 'module', 'name': name_at(a[4]),
                            'toc_offset': hex(p), 'size': a[3],
                            'e32_va': hex(a[5]), 'o32_va': hex(a[6]),
                            'load_va': hex(a[7]), 'region_start': hex(v[2])})
        for j in range(files):
            p = hdr + 84 + mods * 32 + j * 28
            a = struct.unpack_from('<7I', b, p); loc = offset(a[6]); bounds(loc, a[4])
            entries.append({'kind': 'file', 'name': name_at(a[5]),
                            'toc_offset': hex(p), 'size': a[3],
                            'stored_size': a[4], 'load_va': hex(a[6]),
                            'data_offset': hex(loc), 'region_start': hex(v[2])})
    if not regions: raise ValueError('No supported main-OS ROMHDR regions found')
    return {'scope': 'Preliminary main-OS ROMHDR/TOC inventory only. Does not include all device storage. No file-payload decompression or driver-function analysis performed.',
            'counts': {'regions': len(regions),
                       'modules': sum(r['modules'] for r in regions),
                       'files': sum(r['files'] for r in regions)},
            'excluded_regions': excluded, 'regions': regions, 'entries': entries}

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input', type=Path); p.add_argument('output', type=Path)
    args = p.parse_args(); source = args.input.resolve(); data = source.read_bytes()
    initial = hashes(data)
    if initial['md5'] != EXPECTED_MD5 or initial['sha256'] != EXPECTED_SHA256:
        raise ValueError('This narrow parser is restricted to the previously inspected PDA2k 1.22 package (hash mismatch).')
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    cab_start = 0x4855d
    if data[cab_start:cab_start+8] != b'MSCF\0\0\0\0':
        raise ValueError('Expected CAB signature missing')
    cab_size = struct.unpack_from('<I', data, cab_start+8)[0]
    if cab_size != 27143235 or cab_start + cab_size > len(data):
        raise ValueError('Unexpected CAB length')
    cab_path = out / 'payload.cab'; cab_path.write_bytes(data[cab_start:cab_start+cab_size])
    manifest = extract_cab(cab_path, out / 'extracted')
    write_json(out / 'extracted_manifest.json', manifest)
    decoded_dir = out / 'decoded'; decoded_dir.mkdir(); headers = []
    for name, key in KEYS.items():
        decoded = xor_words((out / 'extracted' / name).read_bytes(), key)
        def field(start: int, end: int) -> str:
            return decoded[start:end].split(b'\0', 1)[0].decode('ascii')
        if field(0,16) != 'PH20B' or field(56,72) != 'BlueAngel':
            raise ValueError('NBF header validation failed')
        (decoded_dir / name.replace('.nbf','.nba')).write_bytes(decoded)
        headers.append({'name': name, 'outer_xor_key': hex(key),
                        'device': field(0,16), 'vendor': field(16,32),
                        'language': field(32,40), 'version': field(40,56),
                        'platform': field(56,72),
                        'note': 'Outer XOR decoded. No embedded NBF checksum verification or full payload interpretation.',
                        'decoded': hashes(decoded)})
        if name == 'nk.nbf':
            write_json(out / 'rom_inventory.json', inventory(decoded))
    if hashes(source.read_bytes()) != initial: raise RuntimeError('Source file changed during analysis')
    write_json(out / 'package_report.json', {'source_name': source.name, **initial,
               'cab_offset': hex(cab_start), 'cab_size': cab_size,
               'nbf_headers': headers, 'source_unchanged': True,
               'executed_firmware_code': False, 'device_access': False})
    print(f'Inventory written to {out}')
    print(json.loads((out/'rom_inventory.json').read_text())['counts'])

if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, RuntimeError, UnicodeError, struct.error) as exc:
        print(f'ERROR: {exc}', file=sys.stderr); sys.exit(1)
