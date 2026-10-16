#!/usr/bin/env python3
"""Offline pinned Tabler subset -> checked-in 1bpp Rust masks; never a guest SVG engine.

--check uses only Python stdlib to bind exact SVG/license/catalog/generator/output.
--regenerate-check additionally requires every pinned host renderer version and
independently rerasterizes all masks for byte equality. No network fetch is used.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'shell/assets/tabler'
MANIFEST = ASSETS / 'PROVENANCE.json'
OUTPUT = ROOT / 'shell/src/icon_assets.rs'
SIZES = [12, 16, 24]
NS = '{http://www.w3.org/2000/svg}'
ROOT_ATTRIBUTES = {'width': '24', 'height': '24', 'viewBox': '0 0 24 24',
                   'fill': 'none', 'stroke': 'currentColor', 'stroke-width': '2',
                   'stroke-linecap': 'round', 'stroke-linejoin': 'round'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_svg(raw):
    """Accept only this bounded outline/path format before any renderer sees it.

    Reconstructing an allowlisted tree removes comments/metadata/processing
    instructions; DTD/entities, links/CSS and every non-path element fail closed.
    The renderer additionally receives a resource fetcher that always rejects.
    """
    require(0 < len(raw) <= 16384, 'SVG length')
    lower = raw.lower()
    require(all(marker not in lower for marker in
                (b'<!doctype', b'<!entity', b'<?', b'url(', b'href', b'<script')), 'active/external SVG input')
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, UnicodeError) as error:
        raise ValueError('malformed SVG') from error
    require(root.tag == NS + 'svg' and root.attrib == ROOT_ATTRIBUTES, 'SVG root/attributes')
    require(not (root.text or '').strip(), 'unexpected SVG text')
    paths = list(root)
    require(1 <= len(paths) <= 32, 'SVG path count')
    safe = ET.Element('svg', {**ROOT_ATTRIBUTES, 'xmlns': NS[1:-1], 'stroke': '#ffffff'})
    for path in paths:
        require(path.tag == NS + 'path' and set(path.attrib) == {'d'} and not list(path), 'unsupported SVG element')
        require(not (path.text or '').strip() and not (path.tail or '').strip(), 'SVG path text')
        d = path.attrib['d']
        require(0 < len(d) <= 4096, 'SVG path length')
        require(re.fullmatch(r'[MmZzLlHhVvCcSsQqTtAa0-9+., eE\-]+', d) is not None, 'unsupported SVG path syntax')
        numbers = re.findall(r'[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?', d)
        require(all(-128 <= float(value) <= 128 for value in numbers), 'SVG coordinates')
        ET.SubElement(safe, 'path', {'d': d})
    return ET.tostring(safe, encoding='utf-8')


def catalog_digest(manifest):
    keys = ('schema', 'upstream', 'commit', 'license', 'icons', 'sizes', 'packing',
            'supersampling', 'alpha_threshold', 'toolchain', 'renderer_lock', 'generated_path', 'mask_bytes', 'mutable_bytes')
    canonical = {key: manifest[key] for key in keys}
    return digest(json.dumps(canonical, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode())


def load_inputs(directory=ASSETS):
    manifest = json.loads((directory / 'PROVENANCE.json').read_text())
    require(manifest['schema'] == 'crosshair-tabler-assets-v1', 'manifest schema')
    require(manifest['upstream'] == 'https://github.com/tabler/tabler-icons', 'upstream')
    require(re.fullmatch('[0-9a-f]{40}', manifest['commit']) is not None, 'commit')
    require(manifest['sizes'] == SIZES and manifest['supersampling'] == 8
            and manifest['alpha_threshold'] == 96, 'raster parameters')
    require(len(manifest['icons']) == 18 and manifest['mask_bytes'] == 2196 and manifest['mutable_bytes'] == 0, 'catalog budget')
    license_info = manifest['license']
    require(license_info['path'] == 'LICENSE' and license_info['spdx'] == 'MIT', 'license path/type')
    require(digest((directory / 'LICENSE').read_bytes()) == license_info['sha256'], 'license hash')
    require(set(manifest['renderer_lock']) == {'requirements.lock.json', 'requirements.txt'}, 'renderer lock paths')
    for name, expected in manifest['renderer_lock'].items():
        require(digest((directory / name).read_bytes()) == expected, 'renderer lock hash')
    sources = []
    names = set()
    for expected_id, icon in enumerate(manifest['icons']):
        name = icon['name']
        require(icon['id'] == expected_id and name not in names, 'stable/unique icon ID')
        require(re.fullmatch('[a-z][a-z0-9-]{0,63}', name) is not None, 'icon name')
        require(re.fullmatch('[A-Z][A-Za-z0-9]{0,31}', icon['symbol']) is not None, 'icon symbol')
        require(icon['local_path'] == f'selected/{name}.svg'
                and icon['upstream_path'] == f'icons/outline/{name}.svg', 'icon paths')
        require(icon['url'] == f"https://raw.githubusercontent.com/tabler/tabler-icons/{manifest['commit']}/{icon['upstream_path']}", 'source URL')
        raw = (directory / icon['local_path']).read_bytes()
        require(len(raw) == icon['bytes'] and digest(raw) == icon['sha256'], 'SVG source hash')
        sources.append(validate_svg(raw))
        names.add(name)
    require({p.name for p in (directory / 'selected').iterdir()} == {f'{name}.svg' for name in names}, 'unexpected SVG/catalog file')
    return manifest, sources


def renderer(manifest):
    import importlib.metadata
    import cairosvg
    import cairocffi
    from PIL import Image
    for package, version in manifest['toolchain'].items():
        actual = cairocffi.cairo_version_string() if package == 'native_cairo' else importlib.metadata.version(package)
        require(actual == version, f'pinned renderer {package}: expected {version}, actual {actual}')
    return cairosvg, Image


def masks(manifest, sources):
    cairosvg, Image = renderer(manifest)
    def deny_resource(*_args, **_kwargs):
        raise ValueError('external SVG resources disabled')
    packed = bytearray()
    observations = []
    for icon, svg in zip(manifest['icons'], sources):
        for size in SIZES:
            png = cairosvg.surface.PNGSurface.convert(bytestring=svg, unsafe=False,
                output_width=size * 8, output_height=size * 8, url_fetcher=deny_resource)
            image = Image.open(io.BytesIO(png)).convert('RGBA')
            alpha = image.getchannel('A').resize((size, size), Image.Resampling.BOX)
            bits = bytearray((size * size + 7) // 8)
            for bit, value in enumerate(alpha.tobytes()):
                if value >= manifest['alpha_threshold']:
                    bits[bit // 8] |= 0x80 >> (bit % 8)
            require(any(bits), f'empty icon {icon["name"]}/{size}')
            observations.append({'id': icon['id'], 'size': size, 'offset': len(packed),
                                 'bytes': len(bits), 'sha256': digest(bits),
                                 'set_pixels': sum(value.bit_count() for value in bits)})
            packed.extend(bits)
    require(len(packed) == 2196, 'packed mask budget')
    return bytes(packed), observations


def rust_source(manifest, data):
    enum = '\n'.join(f'    {icon["symbol"]} = {icon["id"]},' for icon in manifest['icons'])
    arms = '\n'.join(f'            {icon["id"]} => Self::{icon["symbol"]},' for icon in manifest['icons'])
    rows = '\n'.join('    ' + ', '.join(f'0x{value:02x}' for value in data[start:start + 16]) + ','
                     for start in range(0, len(data), 16))
    return f'''// @generated by shell/tools/generate_icons.py; do not edit.
// Derived from Tabler Icons, MIT; Copyright (c) 2020-2026 Paweł Kuna.
// Full upstream notice: shell/assets/tabler/LICENSE. Own generator: project MIT.
// Pinned commit: {manifest['commit']}
// Source/catalog binding SHA-256: {catalog_digest(manifest)}
// Masks: row-major continuous bits, MSB first; 12/16/24px; zero mutable RAM.
#[repr(u16)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IconId {{
{enum}
}}
impl IconId {{
    pub const fn from_u16(value: u16) -> Option<Self> {{
        Some(match value {{
{arms}
            _ => return None,
        }})
    }}
}}
pub const ICON_COUNT: usize = 18;
pub const MASK_BYTES: usize = 2196;
#[derive(Clone, Copy)]
pub struct Mask {{
    pub width: u8,
    pub bits: &'static [u8],
}}
impl Mask {{
    pub fn is_set(self, x: u8, y: u8) -> bool {{
        if x >= self.width || y >= self.width {{ return false; }}
        let bit = y as usize * self.width as usize + x as usize;
        self.bits.get(bit / 8).is_some_and(|byte| byte & (0x80 >> (bit % 8)) != 0)
    }}
}}
pub fn mask(id: IconId, size: u8) -> Option<Mask> {{
    let (offset, length) = match size {{ 12 => (0, 18), 16 => (18, 32), 24 => (50, 72), _ => return None }};
    let start = id as usize * 122 + offset;
    Some(Mask {{ width: size, bits: &ICON_MASK_DATA[start..start + length] }})
}}
// Single read-only allocation; no expanded pixel/color/framebuffer copy.
pub static ICON_MASK_DATA: [u8; MASK_BYTES] = [
{rows}
];
'''.encode()


def check(manifest, generated=OUTPUT):
    require(manifest.get('generator_sha256') == digest(Path(__file__).read_bytes()), 'generator hash')
    raw = generated.read_bytes()
    require(manifest.get('generated_sha256') == digest(raw), 'generated Rust hash')
    require(f'// Source/catalog binding SHA-256: {catalog_digest(manifest)}\n'.encode() in raw, 'generated catalog binding')
    require(manifest.get('mask_sha256') is not None, 'missing mask digest')
    # Parse only the generated byte-array section, never Rust code execution.
    array = raw.split(b'pub static ICON_MASK_DATA: [u8; MASK_BYTES] = [\n', 1)[1].split(b'];', 1)[0]
    values = re.findall(rb'0x([0-9a-f]{2})', array)
    remainder = re.sub(rb'0x[0-9a-f]{2}|[\s,]', b'', array)
    require(not remainder and len(values) == 2196, 'generated mask byte format')
    require(digest(bytes(int(v, 16) for v in values)) == manifest['mask_sha256'], 'mask bytes hash')


def main():
    parser = argparse.ArgumentParser(__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--generate', action='store_true')
    mode.add_argument('--regenerate-check', action='store_true')
    args = parser.parse_args()
    manifest, sources = load_inputs()
    if args.generate:
        data, observations = masks(manifest, sources)
        raw = rust_source(manifest, data)
        OUTPUT.write_bytes(raw)
        manifest.update(generator_sha256=digest(Path(__file__).read_bytes()), generated_sha256=digest(raw),
                        mask_sha256=digest(data), masks=observations)
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    else:
        check(manifest)
        if args.regenerate_check:
            data, observations = masks(manifest, sources)
            require(observations == manifest['masks'] and digest(data) == manifest['mask_sha256'], 'raster regeneration differs')
            require(rust_source(manifest, data) == OUTPUT.read_bytes(), 'regenerated Rust differs')
    print(f'Tabler icons PASS: {len(sources)} pinned SVGs, 54 masks, 2196 ROM bytes, 0 mutable bytes ({"regenerated" if args.regenerate_check or args.generate else "offline source/output binding"})')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, IndexError, OSError, ImportError, json.JSONDecodeError) as error:
        print(f'Icon generation failed: {error}', file=sys.stderr)
        sys.exit(1)
