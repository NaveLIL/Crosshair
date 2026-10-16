#!/usr/bin/env python3
"""Bounded compact wallpaper format and source-binding corruption tests."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_wallpaper as g


class WallpaperTests(unittest.TestCase):
    def test_exact_source_and_generated_binding(self):
        g.check(g.inputs())

    def test_uniform_and_alternating_extreme_rows_round_trip(self):
        for indices in (bytes([3]) * (240 * 320), bytes(index % 16 for index in range(240 * 320))):
            if indices[0] == 3:
                data, rows = g.pack_rows(indices)
                self.assertEqual(len(data), 4800)
                self.assertEqual(g.unpack_rows(data, rows), indices)
            else:
                # A photographic/noisy image that defeats compression fails
                # the intentional ROM budget instead of growing firmware.
                with self.assertRaises(ValueError):
                    g.pack_rows(indices)

    def test_invalid_extents_offsets_and_row_lengths_fail(self):
        palette, rows, data = g.parse_generated(g.OUTPUT.read_bytes())
        for end in sorted(set([0, 1, len(data) - 1] + list(range(0, len(data), 127)))):
            with self.assertRaises(ValueError):
                g.unpack_rows(data[:end], rows)
        for changed in (rows[:-1], [1] + rows[1:], rows[:-1] + [len(data) + 1]):
            with self.assertRaises(ValueError):
                g.unpack_rows(data, changed)
        for value in (0, -1, len(data) + 1):
            bad = rows[:]
            bad[1] = value
            with self.assertRaises(ValueError):
                g.unpack_rows(data, bad)
        bad = bytearray(data)
        bad[0] ^= 0xf0
        with self.assertRaises(ValueError):
            g.unpack_rows(bad, rows)

    def test_generated_bytes_metadata_or_generator_mismatch_fail(self):
        original = g.inputs()
        for key in ('generated_sha256', 'generator_sha256', 'raw565_sha256', 'payload_sha256'):
            changed = copy.deepcopy(original)
            changed[key] = '0' * 64
            with self.assertRaises(ValueError):
                g.check(changed)
        changed = copy.deepcopy(original)
        changed['payload_bytes'] += 1
        with self.assertRaises(ValueError):
            g.check(changed)
        with self.assertRaises(ValueError):
            g.parse_generated(b'pub static DATA: [u8; 1] = [999];')

    def test_source_and_prompt_paths_and_hashes_fail_closed(self):
        original = g.inputs()
        for key, field, value in (('source', 'path', '../private.png'),
                                  ('source', 'sha256', '0' * 64),
                                  ('prompt', 'path', '../../PRIVATE'),
                                  ('prompt', 'bytes', 0)):
            changed = copy.deepcopy(original)
            changed[key][field] = value
            with patch.object(g.json, 'loads', return_value=changed):
                with self.assertRaises(ValueError):
                    g.inputs()


if __name__ == '__main__':
    unittest.main()
