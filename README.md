# wlpdisplays

A simple Python utility that prints connected **Wayland monitor information** in structured JSON format.  
It parses the output of `wayland-info` and provides merged `wl_output` and `xdg_output` data for easier consumption in scripts and automation tools.

---

## Features

- Extracts and merges display data from `wayland-info`
- Provides detailed per-monitor information:
  - Name, description
  - Physical size, resolution, refresh rate
  - Logical position and size
  - Scale factors (`scale`, `scale_x`, `scale_y`)
- JSON output for easy parsing
- Optional sorting and compact modes
- Warns if no monitors are detected or if not running on Wayland

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
    "width_px": 3840,
    "height_px": 2160,
    "refresh_hz": 60.0,
    "logical_x": 0,
    "logical_y": 0,
    "logical_width": 2560,
    "logical_height": 1440,
    "scale_x": 1.5,
    "scale_y": 1.5,
    "int_scale": 2
  }
]
````

---

## Usage

```bash
wlpdisplays [options]
```

### Options

| Flag            | Description                             |
| --------------- | --------------------------------------- |
| `-h, --help`    | Show help and exit                      |
| `-c, --compact` | Print JSON on one line (no indentation) |
| `-s, --sort`    | Sort monitors top-left to bottom-right  |

Example:

```bash
wlpdisplays --sort
```

---

## Requirements

* Python 3.8+
* `wayland-info` (from `wayland-utils`)

Install on Arch Linux:

```bash
sudo pacman -S wayland-utils
```

---

## Installation

Clone and run directly:

```bash
git clone https://github.com/YOURNAME/wlpdisplays.git
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

---

