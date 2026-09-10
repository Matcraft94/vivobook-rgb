#!/usr/bin/env python3
"""Unit tests for vrgb parsing and pure helpers (no hardware needed).

Run:  python3 tests/test_vrgb.py
"""

import os
import sys
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import vrgb  # noqa: E402


class TestParseColor(unittest.TestCase):
    def test_hex(self):
        self.assertEqual(vrgb.parse_hex_color("ff0000"), (255, 0, 0))
        self.assertEqual(vrgb.parse_hex_color("#00FF7F"), (0, 255, 127))
        self.assertEqual(vrgb.parse_hex_color("102030"), (16, 32, 48))

    def test_hex_invalid(self):
        for bad in ("ff00", "ff00000", "gggggg", "", "red "):
            with self.assertRaises(SystemExit, msg=bad):
                vrgb.parse_hex_color(bad)

    def test_names(self):
        self.assertEqual(vrgb.parse_color("red"), (255, 0, 0))
        self.assertEqual(vrgb.parse_color("RED"), (255, 0, 0))
        self.assertEqual(vrgb.parse_color("WarmWhite"), (0x10, 0x09, 0x00))

    def test_name_falls_back_to_hex(self):
        self.assertEqual(vrgb.parse_color("#cyan"), (0, 255, 255))
        self.assertEqual(vrgb.parse_color("ff5500"), (255, 0x55, 0))

    def test_every_name_is_valid_hex(self):
        for name, hexval in vrgb.COLOR_NAMES.items():
            self.assertEqual(vrgb.parse_color(name), vrgb.parse_hex_color(hexval))


class TestSpeedBrightness(unittest.TestCase):
    def test_brightness_ok(self):
        self.assertEqual(vrgb.parse_brightness("0"), 0)
        self.assertEqual(vrgb.parse_brightness("255"), 255)
        self.assertEqual(vrgb.parse_brightness("128"), 128)

    def test_brightness_invalid(self):
        for bad in ("256", "-1", "abc", "1.5"):
            with self.assertRaises(SystemExit, msg=bad):
                vrgb.parse_brightness(bad)

    def test_speed_defaults(self):
        self.assertEqual(vrgb.parse_speed(None, 4.0), 4.0)
        self.assertEqual(vrgb.parse_speed("", 8.0), 8.0)
        self.assertEqual(vrgb.parse_speed("2.5", 4.0), 2.5)
        self.assertEqual(vrgb.parse_speed("10", 4.0), 10.0)

    def test_speed_invalid(self):
        for bad in ("0", "-3", "fast"):
            with self.assertRaises(SystemExit, msg=bad):
                vrgb.parse_speed(bad, 4.0)


class TestHsv(unittest.TestCase):
    def test_primaries(self):
        self.assertEqual(vrgb.hsv_to_rgb(0, 1, 1), (255, 0, 0))
        self.assertEqual(vrgb.hsv_to_rgb(120, 1, 1), (0, 255, 0))
        self.assertEqual(vrgb.hsv_to_rgb(240, 1, 1), (0, 0, 255))

    def test_wraps(self):
        self.assertEqual(vrgb.hsv_to_rgb(360, 1, 1), (255, 0, 0))
        self.assertEqual(vrgb.hsv_to_rgb(-60, 1, 1), vrgb.hsv_to_rgb(300, 1, 1))

    def test_white(self):
        self.assertEqual(vrgb.hsv_to_rgb(0, 0, 1), (255, 255, 255))


class TestFrameInterval(unittest.TestCase):
    def test_fast_device_clamped_to_default(self):
        # 5000 µs (200 Hz) is faster than the ~30 fps target: the default wins.
        attrs = {"min_update_interval": 5000}
        self.assertEqual(vrgb.frame_interval(attrs), vrgb.DEFAULT_FRAME_S)

    def test_slow_device_respected(self):
        attrs = {"min_update_interval": 50000}  # 50 ms
        self.assertEqual(vrgb.frame_interval(attrs), 0.05)

    def test_zero_uses_default(self):
        self.assertEqual(vrgb.frame_interval({"min_update_interval": 0}),
                         vrgb.DEFAULT_FRAME_S)
        self.assertEqual(vrgb.frame_interval({}), vrgb.DEFAULT_FRAME_S)


class TestStateFile(unittest.TestCase):
    def setUp(self):
        self.orig = vrgb.STATE_FILE
        self.tmp_dir = tempfile.mkdtemp()
        vrgb.STATE_FILE = os.path.join(self.tmp_dir, "state.json")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        vrgb.STATE_FILE = self.orig

    def test_write_and_read_roundtrip(self):
        vrgb.write_state("color", "ff5500", 128, None)
        state = vrgb.read_state()
        self.assertEqual(state["mode"], "color")
        self.assertEqual(state["rgb"], (255, 0x55, 0))
        self.assertEqual(state["brightness"], 128)

    def test_read_named_color(self):
        vrgb.write_state("breathe", "cyan", 255, 6)
        state = vrgb.read_state()
        self.assertEqual(state["rgb"], (0, 255, 255))
        self.assertEqual(state["speed"], 6)

    def test_read_default_speeds(self):
        vrgb.write_state("cycle", "ffffff", 255, None)
        state = vrgb.read_state()
        self.assertEqual(state["speed"], vrgb.DEFAULT_SPEEDS["cycle"])

    def test_read_invalid_mode(self):
        with open(vrgb.STATE_FILE, "w") as f:
            f.write('{"mode": "bogus"}')
        self.assertIsNone(vrgb.read_state())

    def test_read_invalid_json(self):
        with open(vrgb.STATE_FILE, "w") as f:
            f.write("{not json")
        self.assertIsNone(vrgb.read_state())

    def test_read_invalid_color(self):
        with open(vrgb.STATE_FILE, "w") as f:
            f.write('{"mode": "color", "color": "zzz"}')
        self.assertIsNone(vrgb.read_state())

    def test_read_missing_file(self):
        self.assertIsNone(vrgb.read_state())

    def test_cycle_ignores_color(self):
        with open(vrgb.STATE_FILE, "w") as f:
            f.write('{"mode": "cycle", "color": "zzz"}')
        state = vrgb.read_state()
        self.assertEqual(state["mode"], "cycle")
        self.assertEqual(state["rgb"], (255, 255, 255))


class TestEffectEngine(unittest.TestCase):
    def test_fade_terminates_and_reaches_target(self):
        sent = []

        fd = lamp_count = None  # unused by the fake send_color
        attrs = {"lamp_count": 1, "min_update_interval": 0}

        def fake_send_color(fd_, lc, r, g, b, intensity=255):
            sent.append((r, g, b))

        orig = vrgb.send_color
        vrgb.send_color = fake_send_color
        orig_sleep = vrgb.time.sleep
        vrgb.time.sleep = lambda s: None
        try:
            vrgb.run_effect(fd, attrs, "fade", (0, 0, 255), 255, 0.1,
                            from_rgb=(255, 0, 0))
        finally:
            vrgb.send_color = orig
            vrgb.time.sleep = orig_sleep

        self.assertGreater(len(sent), 1)
        self.assertEqual(sent[0], (255, 0, 0))
        self.assertEqual(sent[-1], (0, 0, 255))

    def test_breathe_stops_on_check(self):
        sent = []
        attrs = {"lamp_count": 1, "min_update_interval": 0}
        calls = {"n": 0}

        def fake_send_color(fd_, lc, r, g, b, intensity=255):
            sent.append(intensity)
            calls["n"] += 1

        orig = vrgb.send_color
        vrgb.send_color = fake_send_color
        orig_sleep = vrgb.time.sleep
        vrgb.time.sleep = lambda s: None
        try:
            vrgb.run_effect(None, attrs, "breathe", (255, 0, 0), 200, 4.0,
                            stop_check=lambda: calls["n"] >= 5)
        finally:
            vrgb.send_color = orig
            vrgb.time.sleep = orig_sleep

        self.assertEqual(len(sent), 5)
        self.assertTrue(all(0 <= i <= 200 for i in sent))


if __name__ == "__main__":
    unittest.main()
