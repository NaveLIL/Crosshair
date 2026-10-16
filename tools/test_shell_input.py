#!/usr/bin/env python3
"""Regression tests for bounded native transport and coordinate wire encoding."""
import unittest

from run_shell import NativeInput
from shell_control import pointer_coordinates, pointer_wire, pointer_phase_wire, hardware_key_wire, wire


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

    def test_atomic_phases_and_hardware_edges_do_not_alias(self):
        values = [pointer_phase_wire(phase,239,319) for phase in (1,2,3)] + [pointer_wire(239,319)]
        self.assertEqual(len(set(values)),4)
        for value in values:
            self.assertEqual(pointer_coordinates(value),(239,319))
        self.assertEqual(pointer_phase_wire(4),0x0800E006)
        self.assertEqual(pointer_phase_wire(5,held_ms=600),0x0800E358)
        self.assertEqual(pointer_phase_wire(5,held_ms=9000),0x0800F0FF)
        for edge in range(3):
            for key in range(13):
                self.assertEqual(hardware_key_wire(edge,key),0x0800E010+(edge<<4)+key)

    def test_physical_source_lines_and_measured_hold_validation(self):
        payload = b"pointer 1 239 319 0\npointer 2 100 100 0\npointer 3 100 100 0\nkey 0 11\nkey 1 11\nkey 2 11\npointer 5 100 100 650\n"
        expected = [pointer_phase_wire(1,239,319),pointer_phase_wire(2,100,100),pointer_phase_wire(3,100,100),
                    hardware_key_wire(0,11),hardware_key_wire(1,11),hardware_key_wire(2,11),pointer_phase_wire(5,held_ms=650)]
        for split in range(len(payload)+1):
            decoder = NativeInput();decoder.feed(payload[:split]);decoder.feed(payload[split:])
            self.assertEqual(list(decoder.pending),expected)
            self.assertEqual(decoder.measured_holds_ms,[650])
        for invalid in (b"pointer 1 240 0 0\n",b"pointer 2 0 320 0\n",b"pointer 5 0 0 599\n",
                        b"pointer 5 0 0 -1\n",b"pointer 6 0 0 0\n",b"key 3 0\n",b"key 0 13\n"):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError): NativeInput().feed(invalid)

    def test_close_does_not_admit_later_events(self):
        decoder = NativeInput()
        decoder.feed(f"window-ready 1\nevent {wire(7)}\nquit\nevent {wire(8)}\n".encode("ascii"))
        self.assertTrue(decoder.window_ready)
        self.assertTrue(decoder.quit)
        self.assertEqual(list(decoder.pending), [wire(7)])


if __name__ == "__main__":
    unittest.main()
