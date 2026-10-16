#!/usr/bin/env python3
"""Corrupted-input/source-binding tests; stdlib only, no SVG execution/network."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('icons_generator', Path(__file__).with_name('generate_icons.py'))
GEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GEN)


class IconInputTests(unittest.TestCase):
    def test_complete_pinned_catalog_and_output(self):
        manifest, sources = GEN.load_inputs()
        self.assertEqual(len(sources), 18)
        GEN.check(manifest)

    def test_changed_svg_and_license_fail_before_render(self):
        for mutation in ('svg', 'license', 'renderer_lock'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp) / 'assets'
                shutil.copytree(GEN.ASSETS, folder)
                name = 'selected/calendar.svg' if mutation == 'svg' else 'requirements.txt' if mutation == 'renderer_lock' else 'LICENSE'
                path = folder / name
                path.write_bytes(path.read_bytes() + b' ')
                with self.assertRaisesRegex(ValueError, 'hash'):
                    GEN.load_inputs(folder)

    def test_duplicate_id_and_path_escape_rejected(self):
        for field, value in (('id', 0), ('local_path', '../../outside.svg')):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp) / 'assets'
                shutil.copytree(GEN.ASSETS, folder)
                path = folder / 'PROVENANCE.json'
                manifest = json.loads(path.read_text())
                manifest['icons'][1][field] = value
                path.write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    GEN.load_inputs(folder)

    def test_generated_corruption_rejected(self):
        manifest, _ = GEN.load_inputs()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'generated.rs'
            output.write_bytes(GEN.OUTPUT.read_bytes().replace(b'0x00', b'0x01', 1))
            with self.assertRaisesRegex(ValueError, 'generated Rust hash'):
                GEN.check(manifest, output)

    def test_hostile_or_unbounded_xml_never_reaches_rasterizer(self):
        original = (GEN.ASSETS / 'selected/calendar.svg').read_bytes()
        hostile = [b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + original,
                   original.replace(b'<path ', b'<script ', 1),
                   original.replace(b'<path ', b'<image href="https://example.invalid/a" ', 1),
                   original.replace(b'<path ', b'<path style="stroke:url(https://example.invalid/a)" ', 1),
                   original.replace(b'width="24"', b'width="99999999"'),
                   original.replace(b'viewBox="0 0 24 24"', b'viewBox="0 0 24 24" onload="alert(1)"'),
                   b'<svg', b'x' * 16385]
        for raw in hostile:
            with self.subTest(prefix=raw[:48]), self.assertRaises(ValueError):
                GEN.validate_svg(raw)

    def test_all_truncated_svg_prefixes_fail_safely(self):
        raw = (GEN.ASSETS / 'selected/layout-grid.svg').read_bytes()
        # Upstream's trailing newline/whitespace can be omitted without damage;
        # every prefix before the root closing token is malformed.
        end = raw.index(b'</svg>') + len(b'</svg>')
        for size in range(end):
            with self.assertRaises(ValueError):
                GEN.validate_svg(raw[:size])


if __name__ == '__main__':
    unittest.main()
