"""Synthetic parser tests: no manufacturer image, executable, or device is used.

Run: python3 -m unittest discover -s tests -p 'test_inspect_blueangel.py' -v
The CAB fixture is an original, tiny uncompressed cabinet using MS-CAB fields;
layout reference: libarchive v3.8.2 archive_read_support_format_cab.c, lines 139-171.
No decoder implementation is copied from libarchive.
"""
import ctypes.util
import hashlib
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'inspect_blueangel.py'
spec = importlib.util.spec_from_file_location('inspect_blueangel', SCRIPT)
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)


def va(offset):
    return 0x80000000 + offset - 128


def synthetic_rom():
    """One supported ROMHDR, one module, and one non-executable file payload."""
    b = bytearray(1024)
    b[0xc0:0xc4] = b'ECEC'
    struct.pack_into('<I', b, 0xc4, va(0x100))
    fields = [0] * 22
    fields[2], fields[3] = va(128), va(len(b))
    fields[4], fields[12], fields[17] = 1, 1, 0x1c0
    struct.pack_into('<17I2H3I', b, 0x100, *fields)
    struct.pack_into('<8I', b, 0x154, 0, 0, 0, 4,
                     va(0x200), va(0x220), va(0x230), va(0x300))
    struct.pack_into('<7I', b, 0x174, 0, 0, 0, 4, 4,
                     va(0x240), va(0x280))
    b[0x200:0x209] = b'test.dll\0'
    b[0x240:0x249] = b'test.txt\0'
    b[0x280:0x284] = b'TEST'
    return bytes(b)


def synthetic_cab(entries):
    """One CAB folder and one uncompressed data block, at most 32 KiB."""
    file_headers = bytearray()
    payload = bytearray()
    for name, data in entries:
        file_headers.extend(struct.pack('<IIHHHH', len(data), len(payload),
                                        0, 0, 0, 0x20))
        file_headers.extend(name.encode('ascii') + b'\0')
        payload.extend(data)
    data_offset = 44 + len(file_headers)
    header = struct.pack('<4sIIIIIBBHHHHH', b'MSCF', 0,
                         data_offset + 8 + len(payload), 0, 44, 0,
                         3, 1, 1, len(entries), 0, 0, 0)
    folder = struct.pack('<IHH', data_offset, 1, 0)
    block = struct.pack('<IHH', 0, len(payload), len(payload))
    return header + folder + file_headers + block + payload


class InventoryTests(unittest.TestCase):
    def test_valid_synthetic_inventory(self):
        result = parser.inventory(synthetic_rom())
        self.assertEqual(result['counts'], {'regions': 1, 'modules': 1, 'files': 1})
        self.assertEqual([e['name'] for e in result['entries']], ['test.dll', 'test.txt'])
        self.assertEqual(result['entries'][1]['data_offset'], '0x280')

    def test_every_truncated_prefix_is_rejected(self):
        image = synthetic_rom()
        for length in range(len(image)):
            with self.subTest(length=length), self.assertRaises(ValueError):
                parser.inventory(image[:length])

    def test_unsupported_region_stays_explicitly_excluded(self):
        image = bytearray(synthetic_rom())
        image.extend(bytes(0x100c8 - len(image)))
        image[0x100c0:0x100c4] = b'ECEC'
        struct.pack_into('<I', image, 0x100c4, 0x9006e000)
        result = parser.inventory(image)
        self.assertEqual(result['counts']['regions'], 1)
        self.assertEqual(result['excluded_regions'][0]['pointer'], '0x9006e000')

    def test_invalid_region_and_entry_ranges(self):
        # These corruptions cannot cause large allocations or reads beyond input.
        changes = {
            'module count': (0x100 + 4 * 4, 501),
            'file count': (0x100 + 12 * 4, 5001),
            'region start mismatch': (0x100 + 2 * 4, va(132)),
            'reversed region': (0x100 + 3 * 4, va(127)),
            'module E32 out of range': (0x154 + 5 * 4, 0xffffffff),
            'module O32 out of range': (0x154 + 6 * 4, 0xffffffff),
            'name before image mapping': (0x154 + 4 * 4, 0x7fffffff),
            'file pointer out of range': (0x174 + 6 * 4, 0xffffffff),
            'file stored size overflow': (0x174 + 4 * 4, 0xffffffff),
        }
        for name, (offset, value) in changes.items():
            image = bytearray(synthetic_rom())
            struct.pack_into('<I', image, offset, value)
            with self.subTest(name=name), self.assertRaises(ValueError):
                parser.inventory(image)

    def test_unterminated_name(self):
        image = bytearray(synthetic_rom())
        image[0x200:0x300] = b'X' * 256
        with self.assertRaisesRegex(ValueError, 'Unterminated'):
            parser.inventory(image)

    def test_invalid_names(self):
        for value in (0, 1, 31, 127, 128, 255):
            image = bytearray(synthetic_rom())
            image[0x200] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                parser.inventory(image)

    def test_no_supported_regions_is_not_a_success(self):
        with self.assertRaisesRegex(ValueError, 'No supported'):
            parser.inventory(bytes(1024))


class XorTests(unittest.TestCase):
    def test_little_endian_known_answer_and_round_trip(self):
        source = bytes.fromhex('0001020304050607')
        self.assertEqual(parser.xor_words(source, 0x20040521),
                         bytes.fromhex('2104062325000227'))
        self.assertEqual(parser.xor_words(parser.xor_words(source, 0x20040521),
                                          0x20040521), source)

    def test_rejects_partial_word(self):
        for length in (1, 2, 3, 5):
            with self.subTest(length=length), self.assertRaises(ValueError):
                parser.xor_words(bytes(length), 0)

    def test_rejects_key_outside_word(self):
        for key in (-1, 0x100000000):
            with self.subTest(key=key), self.assertRaises(ValueError):
                parser.xor_words(bytes(4), key)


@unittest.skipUnless(ctypes.util.find_library('archive'), 'system libarchive not installed')
class CabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cab = self.root / 'synthetic.cab'
        self.out = self.root / 'out'

    def extract(self, entries, expected=None):
        self.cab.write_bytes(synthetic_cab(entries))
        with patch.dict(parser.EXPECTED_FILES, expected or {'test.txt': 4}, clear=True):
            return parser.extract_cab(self.cab, self.out)

    def test_real_libarchive_reads_synthetic_cab(self):
        result = self.extract([('test.txt', b'TEST')])
        self.assertEqual((self.out / 'test.txt').read_bytes(), b'TEST')
        self.assertEqual(result[0]['sha256'], hashlib.sha256(b'TEST').hexdigest())

    def test_allowlist_rejects_traversal(self):
        with self.assertRaisesRegex(ValueError, 'Unexpected or duplicate'):
            self.extract([('../test.txt', b'TEST')])
        self.assertFalse((self.root / 'test.txt').exists())

    def test_duplicate_entry_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unexpected or duplicate'):
            self.extract([('test.txt', b'TEST'), ('test.txt', b'FAIL')])
        self.assertEqual((self.out / 'test.txt').read_bytes(), b'TEST')

    def test_unexpected_length_rejected_before_output(self):
        with self.assertRaisesRegex(ValueError, 'Unexpected length'):
            self.extract([('test.txt', b'TOO LONG')])
        self.assertFalse((self.out / 'test.txt').exists())

    def test_missing_entry_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Missing expected'):
            self.extract([('test.txt', b'TEST')], {'test.txt': 4, 'other.txt': 1})

    def test_truncated_cab_data_rejected(self):
        self.cab.write_bytes(synthetic_cab([('test.txt', b'TEST')])[:-2])
        with patch.dict(parser.EXPECTED_FILES, {'test.txt': 4}, clear=True):
            with self.assertRaises((ValueError, RuntimeError)):
                parser.extract_cab(self.cab, self.out)

    def test_invalid_cab_rejected(self):
        self.cab.write_bytes(b'not a cabinet')
        with self.assertRaises(RuntimeError):
            parser.extract_cab(self.cab, self.out)

    def test_existing_directory_preserved(self):
        self.out.mkdir()
        marker = self.out / 'marker'
        marker.write_bytes(b'KEEP')
        with self.assertRaises(FileExistsError):
            self.extract([('test.txt', b'TEST')])
        self.assertEqual(marker.read_bytes(), b'KEEP')


class CommandTests(unittest.TestCase):
    def test_wrong_hash_rejected_without_output_or_input_change(self):
        with tempfile.TemporaryDirectory() as temp:
            source, out = Path(temp) / 'not-firmware.exe', Path(temp) / 'out'
            source.write_bytes(b'No executable firmware in tests')
            before = source.read_bytes()
            result = subprocess.run([sys.executable, str(SCRIPT), str(source), str(out)],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn('hash mismatch', result.stderr)
            self.assertEqual(source.read_bytes(), before)
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
