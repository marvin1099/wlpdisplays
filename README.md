# wlpdisplays

A Python utility that prints connected **Wayland monitor information** as structured JSON by parsing `wayland-info` output.

AI was used during development, with parts of human code, human review and testing of all code.  
This is a personal tool I wanted and I'm sharing it in case it's useful to others.

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
| `-w, --wayland-info-path PATH` | Path to the `wayland-info` binary (default: `wayland-info`)   |

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

- Python 3.9+
- `wayland-info` (from `wayland-utils`) — not needed when using `--stdin`

Install on Arch Linux:

```bash
sudo pacman -S wayland-utils
```

---

## Installation

### As a dependency (PyPI)

```bash
pipx install wlpdisplays
```

or with uv:

```bash
uv tool install wlpdisplays
```

On many distributions a plain `pip install wlpdisplays` is refused due to PEP 668  
("externally managed environment"). Install it in a virtual environment instead,  
e.g. `pipx`, `uv tool install`, or your project's venv:

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install wlpdisplays
```

Once installed, the `wlpdisplays` command is available on your `PATH`,  
and the module can be imported in your own code.

### As a single file

The entire tool lives in one self-contained file, `wlpdisplays.py`.  
Grab it from the repo and run it directly, no install needed:

```bash
git clone https://codeberg.org/marvin1099/wlpdisplays.git
cd wlpdisplays
chmod +x wlpdisplays.py
./wlpdisplays.py
```

A `wlpdisplays` symlink to the `.py` file is included, so `./wlpdisplays` works too.

Or download just the file:

```bash
curl -O https://codeberg.org/marvin1099/wlpdisplays/raw/branch/main/wlpdisplays.py
./wlpdisplays.py
```

Optionally install it into your `PATH` **without** the `.py` extension, user-wide (`~/.local/bin`) needs no sudo:

```bash
install -Dm755 wlpdisplays.py ~/.local/bin/wlpdisplays
```

...or system-wide:

```bash
sudo install -Dm755 wlpdisplays.py /usr/local/bin/wlpdisplays
```

After that, `wlpdisplays` is a plain command: `wlpdisplays --sort --compact`.

---

## Library Usage

`wlpdisplays.py` is also a normal Python module, so you can use it as a library:

```python
import wlpdisplays as wlp

# Query the running Wayland session directly
monitors = wlp.get_outputs()

# ...or push in raw wayland-info text (e.g. from a file or another machine)
with open("waylandinfo.log") as f:
    raw = f.read()
monitors = wlp.get_outputs(raw=raw)

# Sort top-left to bottom-right
monitors = wlp.get_outputs(raw=raw, sort=True)

# Compact, single-line JSON — the library equivalent of the -c flag
print(wlp.to_json(monitors, compact=True))
```

The data and formatting steps are separate, so you can grab monitor dicts,  
work with them, and only serialize when needed.  
The lower-level building blocks are still exposed:

```python
wl_outputs, xdg_outputs = wlp.parse_wayland_info(raw)
monitors = wlp.merge_outputs(wl_outputs, xdg_outputs)
```

Public API:

| Function                    | Description                                                      |
| --------------------------- | ---------------------------------------------------------------- |
| `get_outputs(raw=None, *, sort=False, binary="wayland-info")` | Get monitor dicts; pass `raw` to skip running `wayland-info` |
| `to_json(outputs, *, compact=False)`                          | Serialize monitor dicts to JSON (one line when `compact`)    |
| `run_wayland_info(binary="wayland-info")`                     | Run `wayland-info` (or `binary`) and return its raw output   |
| `parse_wayland_info(raw)`   | Parse raw `wayland-info` text into `(wl_outputs, xdg_outputs)`    |
| `merge_outputs(...)`        | Merge parsed `wl_output` + `xdg_output_v1` data into one list     |
| `WaylandInfoError`          | Raised when `wayland-info` cannot be run                          |

> **Note:** when used as a library, failures raise `WaylandInfoError` instead of exiting the process. The `wlpdisplays` CLI still exits with an error message.

---

## Development

Run the test suite (stdlib only, no dependencies):

```bash
python3 -m unittest discover
```

---

## Notes

This tool is designed for **Wayland** environments.  
If run under X11 or headless setups, it will issue a warning and attempt to continue gracefully.  
Unknown fields in `wayland-info` output are captured automatically via a key-value fallback parser  
with type coercion, no code changes needed if the protocol adds new properties.
