#!/usr/bin/env python3
"""
RGB keyboard control for ASUS Vivobook via HID LampArray protocol.

This tool controls RGB lighting on ASUS Vivobook laptops that use
the ITE5570 HID LampArray controller (e.g., M5606KA, S5406SA).

Author: Lucy E. Arias <matcraft94@github.com>
License: MIT
"""

import sys
import os
import re
import struct
import fcntl
import array
import glob
import json
import time
import math

VENDOR_ID = "0B05"
PRODUCT_ID = "5570"

STATE_FILE = os.path.expanduser("~/.cache/vrgb/state.json")

# Target frame time for software animations (the device accepts up to
# ~330 updates/s, but ~30 fps is plenty smooth and keeps CPU usage low).
DEFAULT_FRAME_S = 0.033

EFFECT_MODES = ("breathe", "cycle", "fade")
STATE_MODES = ("color", "off", "auto") + EFFECT_MODES

# Named colors accepted anywhere a RRGGBB hex is expected.
COLOR_NAMES = {
    "red": "ff0000",
    "green": "00ff00",
    "blue": "0000ff",
    "yellow": "ffff00",
    "cyan": "00ffff",
    "magenta": "ff00ff",
    "orange": "ff5500",
    "purple": "8000ff",
    "pink": "ff69b4",
    "white": "ffffff",
    "warmwhite": "100900",
    "black": "000000",
}


def find_device():
    """Auto-detect hidraw device for ASUS ITE5570 keyboard controller."""
    for uevent_path in glob.glob("/sys/class/hidraw/hidraw*/device/uevent"):
        with open(uevent_path) as f:
            content = f.read()
        if f"0000{VENDOR_ID}:0000{PRODUCT_ID}" in content.upper():
            name = uevent_path.split("/")[4]
            return f"/dev/{name}"
    print("Error: ASUS keyboard RGB controller (ITE5570) not found", file=sys.stderr)
    print("Make sure you have an ASUS Vivobook with RGB keyboard", file=sys.stderr)
    sys.exit(1)


def _IOWR(type_char, nr, size):
    return 0xC0000000 | (size << 16) | (ord(type_char) << 8) | nr


def get_feature_report(fd, report_id, size):
    buf = array.array('B', [report_id] + [0] * (size - 1))
    fcntl.ioctl(fd, _IOWR('H', 0x07, size), buf)
    return buf


def set_feature_report(fd, data):
    buf = array.array('B', data)
    fcntl.ioctl(fd, _IOWR('H', 0x06, len(data)), buf)
    return buf


def get_lamp_array_attributes(fd):
    """Get lamp array information from the keyboard."""
    try:
        report = get_feature_report(fd, 0x41, 23)
        lamp_count = struct.unpack_from('<H', report, 1)[0]
        bbox_w, bbox_h, bbox_d, kind, min_interval = struct.unpack_from('<IIIII', report, 3)
        return {
            'lamp_count': lamp_count,
            'bbox_width': bbox_w,
            'bbox_height': bbox_h,
            'bbox_depth': bbox_d,
            'kind': kind,
            'min_update_interval': min_interval
        }
    except Exception as e:
        print(f"Error getting lamp attributes: {e}", file=sys.stderr)
        return None


def set_autonomous_mode(fd, enabled):
    """Enable/disable firmware autonomous (rainbow) mode."""
    set_feature_report(fd, [0x46, 1 if enabled else 0])


def set_color_range(fd, start, end, r, g, b, intensity=255):
    """Set color for a range of keys."""
    data = [0x45, 0x01]
    data += list(struct.pack('<H', start))
    data += list(struct.pack('<H', end))
    data += [r, g, b, intensity]
    set_feature_report(fd, data)


def send_color(fd, lamp_count, r, g, b, intensity=255):
    """Set the whole (single-zone) keyboard to one color."""
    set_color_range(fd, 0, lamp_count - 1, r, g, b, intensity)


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

def parse_hex_color(arg):
    hex_color = arg.lstrip('#')
    if not re.fullmatch(r'[0-9a-fA-F]{6}', hex_color):
        print(f"Error: Color must be 6 hex digits (RRGGBB), got '{arg}'", file=sys.stderr)
        sys.exit(1)
    return (int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))


def parse_color(arg):
    """Parse a color by name (red, cyan, ...) or hex (RRGGBB / #RRGGBB)."""
    named = COLOR_NAMES.get(arg.lower().lstrip('#'))
    return parse_hex_color(named or arg)


def hsv_to_rgb(h, s, v):
    """HSV (h 0-360, s/v 0-1) to RGB (0-255) without external deps."""
    h = h % 360.0
    c = v * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = v - c
    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    return round((r + m) * 255), round((g + m) * 255), round((b + m) * 255)


def lerp(a, b, t):
    return round(a + (b - a) * t)


def frame_interval(attrs):
    """Animation frame time: at least the device minimum, ~30 fps target."""
    min_us = attrs.get('min_update_interval') or 0
    return max(min_us / 1_000_000.0, DEFAULT_FRAME_S)


# ---------------------------------------------------------------------------
# Effect engine
# ---------------------------------------------------------------------------

def run_effect(fd, attrs, mode, rgb, brightness, period, stop_check=None, from_rgb=(0, 0, 0)):
    """Run a software animation until stop_check() returns True.

    Used standalone by `vrgb effect` (stop on Ctrl+C) and by the daemon
    (stop when the state file changes). Leaves the last frame applied.
    """
    lamp_count = attrs['lamp_count']
    dt = frame_interval(attrs)
    start = time.monotonic()

    if mode == "fade":
        r0, g0, b0 = from_rgb
        r1, g1, b1 = rgb
        t = 0.0
        while t < period:
            if stop_check and stop_check():
                return
            t = min(time.monotonic() - start, period)
            k = t / period if period > 0 else 1.0
            send_color(fd, lamp_count,
                       lerp(r0, r1, k), lerp(g0, g1, k), lerp(b0, b1, k),
                       brightness)
            time.sleep(dt)
        send_color(fd, lamp_count, r1, g1, b1, brightness)
        return

    if mode == "breathe":
        while True:
            if stop_check and stop_check():
                return
            t = time.monotonic() - start
            phase = (t % period) / period
            level = (math.sin(2 * math.pi * phase) + 1) / 2
            send_color(fd, lamp_count, *rgb, round(brightness * level))
            time.sleep(dt)

    if mode == "cycle":
        while True:
            if stop_check and stop_check():
                return
            t = time.monotonic() - start
            hue = 360.0 * ((t % period) / period)
            r, g, b = hsv_to_rgb(hue, 1.0, 1.0)
            send_color(fd, lamp_count, r, g, b, brightness)
            time.sleep(dt)

    print(f"Error: unknown effect '{mode}'", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Daemon (state file)
# ---------------------------------------------------------------------------

def read_state():
    """Read and validate the state file; return None if missing/invalid."""
    def warn(msg):
        print(f"vrgb daemon: {msg}", file=sys.stderr)

    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as e:
        warn(f"ignoring invalid state file: {e}")
        return None

    mode = state.get("mode")
    if mode not in STATE_MODES:
        warn(f"invalid mode '{mode}', ignoring")
        return None

    color = state.get("color", "ffffff")
    if mode in ("color", "breathe", "fade"):
        try:
            rgb = parse_color(color)
        except SystemExit:
            warn("invalid color in state file, ignoring")
            return None
    else:
        rgb = (255, 255, 255)

    try:
        brightness = int(state.get("brightness", 255))
        speed = float(state.get("speed", 0))
    except (TypeError, ValueError):
        warn("invalid brightness/speed in state file, ignoring")
        return None
    if not 0 <= brightness <= 255:
        brightness = max(0, min(255, brightness))
    if speed <= 0:
        speed = {"breathe": 4.0, "cycle": 8.0, "fade": 1.0}.get(mode, 1.0)

    return {"mode": mode, "rgb": rgb, "brightness": brightness, "speed": speed}


def write_state(mode, color="ffffff", brightness=255, speed=None):
    """Write a new state file (used by `vrgb set`)."""
    if mode not in STATE_MODES:
        print(f"Error: mode must be one of: {', '.join(STATE_MODES)}", file=sys.stderr)
        sys.exit(1)
    state = {"mode": mode, "color": color.lstrip('#').lower(), "brightness": brightness}
    if speed is not None:
        state["speed"] = speed
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    os.replace(tmp, STATE_FILE)
    print(f"State written to {STATE_FILE} (applied by `vrgb daemon` if running)")


def state_mtime():
    try:
        return os.stat(STATE_FILE).st_mtime_ns
    except FileNotFoundError:
        return None


def cmd_daemon(fd, attrs):
    """Watch the state file and apply/animate it until killed."""
    print(f"vrgb daemon: watching {STATE_FILE}")
    print("Write state with: vrgb set <mode> [args]  (Ctrl+C to stop)")
    last_mtime = object()  # sentinel: differs from any real mtime on first pass
    last_rgb = (0, 0, 0)

    while True:
        time.sleep(0.2)
        mtime = state_mtime()
        if mtime == last_mtime:
            continue
        last_mtime = mtime
        if mtime is None:
            continue

        state = read_state()
        if state is None:
            continue

        mode = state["mode"]
        if mode in EFFECT_MODES:
            run_effect(fd, attrs, mode, state["rgb"], state["brightness"],
                       state["speed"],
                       stop_check=lambda: state_mtime() != last_mtime,
                       from_rgb=last_rgb)
            last_rgb = state["rgb"]
            # effect was interrupted by a state change (or finished, for fade)
            continue

        # one-shot modes
        set_autonomous_mode(fd, mode == "auto")
        if mode == "color":
            send_color(fd, attrs['lamp_count'], *state["rgb"], state["brightness"])
            last_rgb = state["rgb"]
        elif mode == "off":
            send_color(fd, attrs['lamp_count'], 0, 0, 0, 0)
            last_rgb = (0, 0, 0)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def usage():
    prog = os.path.basename(sys.argv[0])
    print("Usage:")
    print(f"  {prog} info                       - Show lamp array info")
    print(f"  {prog} color RRGGBB [BRIGHTNESS]  - Set solid color (hex, e.g., ff0000)")
    print(f"                                        BRIGHTNESS: 0-255 (optional, default 255)")
    print(f"  {prog} off                        - Turn off LEDs")
    print(f"  {prog} auto                       - Re-enable autonomous (rainbow) mode")
    print()
    print("Effects (run in foreground, Ctrl+C to stop keeping last color):")
    print(f"  {prog} effect breathe RRGGBB [S]  - Pulsing color (period S, default 4)")
    print(f"  {prog} effect cycle [S]           - HSV color wheel (period S, default 8)")
    print(f"  {prog} effect fade RRGGBB [S]     - Fade to color (duration S, default 1)")
    print()
    print("Daemon (background, driven by a state file):")
    print(f"  {prog} daemon                     - Watch {STATE_FILE}")
    print(f"  {prog} set color RRGGBB [BRIGHTNESS]   - Write state (others: off, auto,")
    print(f"  {prog} set breathe RRGGBB [S]          -       breathe, cycle, fade)")
    print(f"  {prog} set cycle [S]")
    print(f"  {prog} set fade RRGGBB [S]")
    print()
    print("Examples:")
    print(f"  {prog} color ff0000        # Red, full brightness")
    print(f"  {prog} color 00ff00 128    # Green, half brightness")
    print(f"  {prog} effect breathe 00ffff 5   # Cyan pulse, 5s period")
    print(f"  {prog} effect cycle 12     # Slow rainbow")
    print(f"  {prog} daemon &            # Start daemon in background")
    print(f"  {prog} set breathe ff00ff 6     # Daemon picks it up")


def parse_brightness(arg):
    try:
        value = int(arg, 10)
    except ValueError:
        print(f"Error: Brightness must be an integer 0-255, got '{arg}'", file=sys.stderr)
        sys.exit(1)
    if not 0 <= value <= 255:
        print(f"Error: Brightness must be 0-255, got {value}", file=sys.stderr)
        sys.exit(1)
    return value


def parse_speed(arg, default):
    if arg is None or not arg.strip():
        return default
    try:
        value = float(arg)
    except ValueError:
        print(f"Error: Speed must be a number of seconds, got '{arg}'", file=sys.stderr)
        sys.exit(1)
    if value <= 0:
        print(f"Error: Speed must be > 0 seconds, got {value}", file=sys.stderr)
        sys.exit(1)
    return value


DEFAULT_SPEEDS = {"breathe": 4.0, "cycle": 8.0, "fade": 1.0}


def cmd_effect(fd, attrs, argv):
    if not argv:
        print("Error: effect requires a mode: breathe, cycle or fade", file=sys.stderr)
        sys.exit(1)
    mode = argv[0]
    if mode not in EFFECT_MODES:
        print(f"Error: unknown effect '{mode}' (use: breathe, cycle, fade)", file=sys.stderr)
        sys.exit(1)

    if mode == "cycle":
        # cycle has no color: the argument is the period
        rgb = (255, 255, 255)
        period = parse_speed(argv[1] if len(argv) > 1 else None, DEFAULT_SPEEDS[mode])
    else:
        rgb = parse_color(argv[1]) if len(argv) > 1 else (255, 255, 255)
        period = parse_speed(argv[2] if len(argv) > 2 else None, DEFAULT_SPEEDS[mode])

    set_autonomous_mode(fd, False)
    print(f"Running {mode} (Ctrl+C stops, last color is kept)...")
    try:
        run_effect(fd, attrs, mode, rgb, 255, period)
    except KeyboardInterrupt:
        pass


def cmd_set(argv):
    if not argv:
        print("Error: set requires a mode", file=sys.stderr)
        sys.exit(1)
    mode = argv[0]
    if mode not in STATE_MODES:
        print(f"Error: mode must be one of: {', '.join(STATE_MODES)}", file=sys.stderr)
        sys.exit(1)

    color = argv[1] if len(argv) > 1 else None
    if mode in ("color", "breathe", "fade"):
        if not color:
            print(f"Error: mode '{mode}' requires a color, e.g.: set {mode} ff0000",
                  file=sys.stderr)
            sys.exit(1)
        parse_color(color)  # validate
    elif color:
        print(f"Warning: mode '{mode}' ignores the color argument", file=sys.stderr)

    brightness = 255
    if mode in ("color",) and len(argv) > 2 and argv[2].strip():
        brightness = parse_brightness(argv[2])

    # Only store a color for modes that use one; anything else gets the default.
    stored_color = (color or "ffffff") if mode in ("color", "breathe", "fade") else "ffffff"

    speed = None
    if mode in EFFECT_MODES:
        speed_idx = 1 if mode == "cycle" else 2
        if len(argv) > speed_idx:
            speed = parse_speed(argv[speed_idx], DEFAULT_SPEEDS[mode])

    write_state(mode, stored_color, brightness, speed)


def open_device():
    """Open the hidraw device; returns (fd, device_path)."""
    device = find_device()
    try:
        return os.open(device, os.O_RDWR), device
    except PermissionError:
        print(f"Error: Permission denied accessing {device}", file=sys.stderr)
        print("Try running with sudo, or ensure udev rules are properly configured.",
              file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"Error: Device {device} not found", file=sys.stderr)
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)

    if sys.argv[1] in ("-h", "--help"):
        usage()
        sys.exit(0)

    cmd = sys.argv[1]

    # `set` only writes the state file; no device access needed.
    if cmd == "set":
        cmd_set(sys.argv[2:])
        return

    fd, device = open_device()

    try:
        if cmd == "info":
            attrs = get_lamp_array_attributes(fd)
            if attrs:
                kinds = {
                    0: "Undefined", 1: "Keyboard", 2: "Mouse", 3: "GameController",
                    4: "Peripheral", 5: "Scene", 6: "Notification", 7: "Chassis",
                    8: "Wearable", 9: "Furniture"
                }
                print(f"Device:              {device}")
                print(f"Lamp count:          {attrs['lamp_count']}")
                print(f"Kind:                {kinds.get(attrs['kind'], 'Unknown')} ({attrs['kind']})")
                print(f"Bounding box:        {attrs['bbox_width']}x{attrs['bbox_height']}x{attrs['bbox_depth']} µm")
                print(f"Min update interval: {attrs['min_update_interval']} µs")
            else:
                print("Could not get lamp array attributes")
                sys.exit(1)

        elif cmd == "color":
            if len(sys.argv) < 3:
                print("Error: Provide a color (hex like ff0000 or a name like red)",
                      file=sys.stderr)
                sys.exit(1)
            r, g, b = parse_color(sys.argv[2])

            brightness = parse_brightness(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].strip() else 255

            attrs = get_lamp_array_attributes(fd)
            if attrs:
                set_autonomous_mode(fd, False)
                send_color(fd, attrs['lamp_count'], r, g, b, brightness)
            else:
                print("Failed to get lamp attributes", file=sys.stderr)
                sys.exit(1)

        elif cmd == "off":
            attrs = get_lamp_array_attributes(fd)
            if attrs:
                set_autonomous_mode(fd, False)
                send_color(fd, attrs['lamp_count'], 0, 0, 0, 0)
            else:
                print("Failed to get lamp attributes", file=sys.stderr)
                sys.exit(1)

        elif cmd == "auto":
            set_autonomous_mode(fd, True)

        elif cmd == "effect":
            attrs = get_lamp_array_attributes(fd)
            if not attrs:
                print("Failed to get lamp attributes", file=sys.stderr)
                sys.exit(1)
            cmd_effect(fd, attrs, sys.argv[2:])

        elif cmd == "daemon":
            attrs = get_lamp_array_attributes(fd)
            if not attrs:
                print("Failed to get lamp attributes", file=sys.stderr)
                sys.exit(1)
            try:
                cmd_daemon(fd, attrs)
            except KeyboardInterrupt:
                print("\nvrgb daemon: stopped")

        else:
            print(f"Unknown command: {cmd}", file=sys.stderr)
            usage()
            sys.exit(1)

    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
