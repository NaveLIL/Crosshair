#!/usr/bin/env python3
"""Regression tests for bounded native transport and coordinate wire encoding."""
import unittest

from run_shell import NativeInput
from shell_control import pointer_coordinates, pointer_wire, wire


class NativeInputTests(unittest.TestCase):
    def test_single_write_and_split_utf8_free_protocol(self):
        values = [wire(8), pointer_wire(239, 319), 0x0800041E, wire(7)]
        payload = b"".join(f"event {value}\n".encode("ascii") for value in values)
        for split in range(len(payload) + 1):
            decoder = NativeInput()
            decoder.feed(payload[:split])
            decoder.feed(payload[split:])
            self.assertEqual(list(decoder.pending), values)
            self.assertEqual(decoder.buffer, b"")

    def test_coordinate_bits_and_bounds(self):
        encoded = set()
        for y in range(320):
            for x in range(240):
                value = pointer_wire(x, y)
                self.assertEqual(pointer_coordinates(value), (x, y))
                self.assertLessEqual(value & 0xFFFFFF, 0x10FFFF)
                encoded.add(value)
        self.assertEqual(len(encoded), 240 * 320)
        for x, y in ((-1, 0), (240, 0), (0, -1), (0, 320)):
            with self.assertRaises(ValueError):
                pointer_wire(x, y)
        for value in (wire(8), 0x09000101, 0x080F00F0, 0x08104000, 0x0810FFFF):
            self.assertIsNone(pointer_coordinates(value))

    def test_malformed_or_untrusted_frontend_lines(self):
        for line in (b"event -1\n", b"event 4294967296\n", b"event 150994944\n",  # rejected tag9
                     b"event 134273024\n",  # surrogate U+D800
                     b"event 135201008\n",  # pointer x240
                     b"event 135282688\n",  # pointer y320
                     b"event NaN\n", b"event 16777217\n", b"window-ready 0\n", b"oops\n"):
            with self.subTest(line=line), self.assertRaises(ValueError):
                NativeInput().feed(line)

    def test_bounded_backpressure_preserves_pending_order(self):
        decoder = NativeInput()
        values = [pointer_wire(index % 240, index) for index in range(100)]
        decoder.feed(b"".join(f"event {value}\n".encode("ascii") for value in values))
        self.assertEqual(len(decoder.pending), 64)
        first = [decoder.pending.popleft() for _ in range(64)]
        decoder.parse()
        self.assertEqual(first + list(decoder.pending), values)
        self.assertEqual(decoder.buffer, b"")
        with self.assertRaises(ValueError):
            NativeInput().feed(b"x" * 8193)

    def test_close_does_not_admit_later_events(self):
        decoder = NativeInput()
        decoder.feed(f"window-ready 1\nevent {wire(7)}\nquit\nevent {wire(8)}\n".encode("ascii"))
        self.assertTrue(decoder.window_ready)
        self.assertTrue(decoder.quit)
        self.assertEqual(list(decoder.pending), [wire(7)])


if __name__ == "__main__":
    unittest.main()
