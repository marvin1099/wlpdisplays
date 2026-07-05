# wlpdisplays

A Python utility that prints connected **Wayland monitor information** as structured JSON by parsing `wayland-info` output.

---

## Features

- Merges `wl_output` and `xdg_output_v1` data from `wayland-info`
- Per-monitor details: name, description, physical size, resolution, refresh rate, logical position/size, scale factors
- Future-proof: unknown key-value fields are auto-captured with type coercion (`"true"` → `true`, `"42"` → `42`)
- JSON output for easy consumption in scripts and status bars
- Sort monitors top-left to bottom-right
- Compact one-line output
- `--stdin` mode for debugging with pre-recorded `wayland-info` output

---

## Example Output

```json
[
  {
    "name": "HDMI-A-1",
    "description": "Samsung Electric Company U28E590",
    "x": 0,
    "y": 0,
    "scale": 1.5,
    "physical_width_mm": 608,
    "physical_height_mm": 345,
    "make": "Samsung Electric Company",
    "model": "U28E590",
    "subpixel_orientation": "unknown",
    "output_transform": "normal",
    "width_px": 3840,
    "height_px": 2160,
    "refresh_hz": 60.0,
    "flags": "current",
    "output": 66,
    "logical_x": 0,
    "logical_y": 0,
    "logical_width": 2560,
    "logical_height": 1440,
    "scale_x": 1.5,
    "scale_y": 1.5,
    "int_scale": 2
  }
]
```

---

## Usage

```bash
wlpdisplays [options]
```

### Options

| Flag               | Description                                                |
| ------------------ | ---------------------------------------------------------- |
| `-h, --help`       | Show help and exit                                         |
| `-c, --compact`    | Print JSON on one line (no indentation)                    |
| `-s, --sort`       | Sort monitors top-left to bottom-right                     |
| `-v, --version`    | Show version and exit                                      |
| `-i, --stdin`      | Read raw `wayland-info` data from stdin instead of running `wayland-info` |

### Examples

```bash
# Normal usage
wlpdisplays

# Sorted, compact output
wlpdisplays --sort --compact

# Debug with pre-recorded output from another machine
wlpdisplays --stdin < waylandinfo-streaming-raw-out.log
```

---

## Requirements

- Python 3.8+
- `wayland-info` (from `wayland-utils`) — not needed when using `--stdin`

Install on Arch Linux:

```bash
sudo pacman -S wayland-utils
```

---

## Installation

Clone and run directly:

```bash
git clone https://codeberg.org/marvin1099/wlpdisplays.git
cd wlpdisplays
chmod +x wlpdisplays
./wlpdisplays
```

Optionally install system-wide:

```bash
sudo install -Dm755 wlpdisplays /usr/local/bin/wlpdisplays
```

---

## Notes

This tool is designed for **Wayland** environments.
If run under X11 or headless setups, it will issue a warning and attempt to continue gracefully.
Unknown fields in `wayland-info` output are captured automatically via a key-value fallback parser
with type coercion — no code changes needed if the protocol adds new properties.
