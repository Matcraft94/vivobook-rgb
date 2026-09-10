# Vivobook RGB

RGB keyboard control for ASUS Vivobook laptops using the HID LampArray protocol.

## Description

This tool allows you to control the RGB lighting of ASUS Vivobook keyboards that use the ITE5570 HID LampArray controller. Unlike `asusctl` which uses WMI, this tool communicates directly with the keyboard controller through the HID subsystem.

## Supported Hardware

- ASUS Vivobook S 16 (M5606KA)
- ASUS Vivobook S 14 (S5406SA)
- Any ASUS laptop with ITE5570 keyboard controller

## Installation

### From AUR (when available)

```bash
yay -S vivobook-rgb
# or
paru -S vivobook-rgb
```

### Manual Installation

```bash
git clone https://github.com/matcraft94/vivobook-rgb.git
cd vivobook-rgb
makepkg -si
```

## Usage

```bash
# Show keyboard information
vrgb info

# Set solid color (hex RGB)
vrgb color ff0000    # Red
vrgb color 00ff00    # Green
vrgb color 0000ff    # Blue
vrgb color ff00ff    # Magenta
vrgb color 00ffff    # Cyan
vrgb color ffff00    # Yellow
vrgb color ff5500    # Orange
vrgb color 100900    # Warm white (good for night)

# Optional brightness as second argument (0-255, default 255)
vrgb color ff0000 64     # Red, dimmed to ~25%
vrgb color 00ffff 128    # Cyan, half brightness

# Turn off keyboard lighting
vrgb off

# Enable rainbow mode (firmware controlled)
vrgb auto

# Software effects (run in foreground, Ctrl+C stops keeping last color)
vrgb effect breathe 00ffff 5   # Cyan pulse, 5s period
vrgb effect cycle 12           # Slow HSV color wheel
vrgb effect fade ff5500 2      # Fade from current color to orange in 2s

# Daemon driven by a state file (for scripts / other tools)
vrgb daemon &                  # background watcher
vrgb set color 00ff00 128      # applied by the daemon immediately
vrgb set breathe ff00ff 6      # effects also work through the daemon
vrgb set off                   # stop effects, turn off LEDs
```

## Post-Installation

To use `vrgb` without sudo, add your user to the `vrgb` group (created on
install), then log out and back in:

```bash
sudo usermod -aG vrgb $USER
```

If the keyboard was already connected, reload udev rules:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### Optional: Set default color on boot (and restore after suspend)

```bash
sudo systemctl enable --now vrgb-default.service
```

The service is also hooked to `suspend.target`, so the color is re-applied
when the machine resumes (the ITE5570 forgets it on suspend).

Edit `/etc/vrgb.conf` to change the default color and brightness — no need to
touch the unit file:

```bash
VRGB_COLOR=ff5500
VRGB_BRIGHTNESS=128
```

## Why this exists

ASUS Vivobook keyboards use the HID LampArray protocol (Windows Dynamic Lighting standard) instead of the WMI interface used by ROG and TUF laptops. This means `asusctl` cannot control the RGB colors on these laptops, only brightness.

This tool bridges that gap by communicating directly with the ITE5570 controller via hidraw.

Note: the ITE5570 exposes the keyboard as a **single lamp** (one zone), so the
whole keyboard shares one color — per-key control is not possible on this
hardware. Also, the keyboard backlight *brightness* exposed at
`/sys/class/leds/asus::kbd_backlight/` is independent of the RGB color channel;
both can be combined.

## Requirements

- Python 3
- Linux kernel with hidraw support
- Access to `/dev/hidraw*` (configured via udev rules)

## Author

Lucy E. Arias (@matcraft94)

## License

MIT License - see LICENSE file for details
