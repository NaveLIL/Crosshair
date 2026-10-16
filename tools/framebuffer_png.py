#!/usr/bin/env python3
"""Encode little-endian RGB565 rows as PNG using Python's standard library.

The encoder streams rows and IDAT chunks: it does not allocate a second full
framebuffer. It neither reads nor writes physical display/device memory.
"""
import argparse
from pathlib import Path
import struct
import zlib


def encode(source: Path, destination: Path, width=240, height=320, stride=None):
    stride = width if stride is None else stride
    if not (0 < width <= 240 and 0 < height <= 320 and stride >= width):
        raise ValueError('invalid geometry/stride')
    if stride * height * 2 > 153600 or source.stat().st_size != stride * height * 2:
        raise ValueError('input length or framebuffer memory budget mismatch')
    if source.resolve() == destination.resolve():
        raise ValueError('output must differ from input')
    with source.open('rb') as reader, destination.open('wb') as writer:
        def chunk(kind, data):
            writer.write(struct.pack('>I', len(data)) + kind + data +
                         struct.pack('>I', zlib.crc32(kind + data)))
        writer.write(b'\x89PNG\r\n\x1a\n')
        chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
        compressor = zlib.compressobj(level=9)
        for _ in range(height):
            packed = reader.read(stride * 2)
            if len(packed) != stride * 2:
                raise ValueError('input changed/truncated during encoding')
            row = bytearray(1 + width * 3)  # PNG filter 0; at most 721 bytes.
            for x in range(width):
                pixel = packed[2 * x] | (packed[2 * x + 1] << 8)
                r, g, b = pixel >> 11, (pixel >> 5) & 63, pixel & 31
                row[1 + x * 3:4 + x * 3] = bytes(((r << 3) | (r >> 2),
                                                  (g << 2) | (g >> 4),
                                                  (b << 3) | (b >> 2)))
            compressed = compressor.compress(row)
            if compressed:
                chunk(b'IDAT', compressed)
        if reader.read(1):
            raise ValueError('input grew during encoding')
        chunk(b'IDAT', compressor.flush())
        chunk(b'IEND', b'')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        encode(args.input, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f'error: {error}\n')
    print('PNG 240x320 RGB888 encoded from one RGB565 framebuffer')


if __name__ == '__main__':
    main()
