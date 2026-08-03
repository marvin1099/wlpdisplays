#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any

__version__ = "0.2.0"

__all__ = [
    "__version__",
    "WaylandInfoError",
    "run_wayland_info",
    "parse_wayland_info",
    "merge_outputs",
    "get_outputs",
    "to_json",
    "main",
]


class WaylandInfoError(RuntimeError):
    """Raised when 'wayland-info' cannot be run."""


def error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(1)


def warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr)


def check_display_server() -> None:
    """Warn if we're not running under Wayland."""
    if os.environ.get("WAYLAND_DISPLAY"):
        return
    if os.environ.get("DISPLAY"):
        warn("Running under X11 (DISPLAY detected).\nThis script is meant for Wayland.")
        return
    warn("No display server variables detected.\nPossibly running headless.")


def run_wayland_info(binary: str = "wayland-info") -> str:
    """Run ``wayland-info`` (or the given ``binary``) and return its raw output."""
    try:
        return subprocess.check_output(
            [binary], text=True, stderr=subprocess.STDOUT
        )
    except FileNotFoundError:
        raise WaylandInfoError(
            f"'{binary}' not found.\n"
            "Please install it (e.g., 'sudo pacman -S wayland-utils')."
        ) from None
    except subprocess.CalledProcessError as e:
        raise WaylandInfoError(
            f"'{binary}' failed with exit code {e.returncode}:\n"
            f"{e.output.strip()}"
        ) from None


# wl_output field patterns
_RE_WL_NAME = re.compile(r"name: (\S+)")
_RE_WL_DESC = re.compile(r"description: (.+)")
_RE_WL_POS = re.compile(r"x: (-?\d+), y: (-?\d+), scale: (\d+),")
_RE_WL_PHYS = re.compile(r"physical_width: (\d+) mm, physical_height: (\d+) mm,")
_RE_WL_MODE = re.compile(r"width: (\d+) px, height: (\d+) px, refresh: ([\d.]+) Hz,")


def _coerce(val: str) -> Any:
    v = val.lower()
    if v in ("true", "false"):
        return v == "true"
    if v in ("yes", "no"):
        return v == "yes"
    try:
        return int(val)
    except ValueError:
        try:
            return float(val)
        except ValueError:
            return val


def _parse_extra_kv(line: str, acc: dict[str, Any]) -> None:
    for part in line.split(","):
        part = part.strip()
        if ":" in part:
            key, _, val = part.partition(":")
            key = key.strip()
            val = val.strip().strip("'").rstrip(",")
            if key and val:
                acc.setdefault(key, _coerce(val))


def _parse_wl_line(line: str, acc: dict[str, Any]) -> None:
    if m := _RE_WL_NAME.match(line):
        acc["name"] = m.group(1)
    elif m := _RE_WL_DESC.match(line):
        acc["description"] = m.group(1)
    elif m := _RE_WL_POS.match(line):
        acc.update(x=int(m[1]), y=int(m[2]), scale=int(m[3]))
    elif m := _RE_WL_PHYS.match(line):
        acc.update(physical_width_mm=int(m[1]), physical_height_mm=int(m[2]))
    elif m := _RE_WL_MODE.match(line):
        acc.update(width_px=int(m[1]), height_px=int(m[2]), refresh_hz=float(m[3]))
    else:
        _parse_extra_kv(line, acc)


# xdg_output_v1 field patterns
_RE_XDG_OUTPUT = re.compile(r"output: (\d+)")
_RE_XDG_NAME = re.compile(r"name: '(.+)'")
_RE_XDG_DESC = re.compile(r"description: '(.+)'")
_RE_XDG_POS = re.compile(r"logical_x: (-?\d+), logical_y: (-?\d+)")
_RE_XDG_SIZE = re.compile(r"logical_width: (\d+), logical_height: (\d+)")


def _parse_xdg_line(line: str, acc: dict[str, Any]) -> None:
    if m := _RE_XDG_OUTPUT.match(line):
        acc["output"] = int(m.group(1))
    elif m := _RE_XDG_NAME.match(line):
        acc["name"] = m.group(1)
    elif m := _RE_XDG_DESC.match(line):
        acc["description"] = m.group(1)
    elif m := _RE_XDG_POS.match(line):
        acc.update(logical_x=int(m[1]), logical_y=int(m[2]))
    elif m := _RE_XDG_SIZE.match(line):
        acc.update(logical_width=int(m[1]), logical_height=int(m[2]))
    else:
        _parse_extra_kv(line, acc)


def parse_wayland_info(
    raw: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Parse raw ``wayland-info`` text into wl_output/xdg_output maps keyed by name."""
    wl_outputs: dict[str, dict[str, Any]] = {}
    xdg_outputs: dict[str, dict[str, Any]] = {}

    buf_wl: dict[str, Any] | None = None
    buf_xdg: dict[str, Any] | None = None
    wl_name: str | None = None
    xdg_name: str | None = None

    def flush_wl() -> None:
        nonlocal buf_wl, wl_name
        if buf_wl is not None and wl_name is not None:
            wl_outputs.setdefault(wl_name, {}).update(buf_wl)
        buf_wl = None
        wl_name = None

    def flush_xdg() -> None:
        nonlocal buf_xdg, xdg_name
        if buf_xdg is not None and xdg_name is not None:
            xdg_outputs.setdefault(xdg_name, {}).update(buf_xdg)
        buf_xdg = None
        xdg_name = None

    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if not raw_line[0].isspace() and line.startswith("interface:"):
            flush_wl()
            flush_xdg()
            buf_wl = {} if "'wl_output'" in line else None
            buf_xdg = None
            continue

        if line.startswith("xdg_output_v1"):
            flush_xdg()
            buf_xdg = {}
            continue

        if buf_wl is not None:
            _parse_wl_line(line, buf_wl)
            if "name" in buf_wl:
                wl_name = buf_wl["name"]

        if buf_xdg is not None:
            _parse_xdg_line(line, buf_xdg)
            if "name" in buf_xdg:
                xdg_name = buf_xdg["name"]

    flush_wl()
    flush_xdg()

    return wl_outputs, xdg_outputs


def merge_outputs(
    wl_outputs: dict[str, dict[str, Any]],
    xdg_outputs: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge parsed wl_output and xdg_output data into one list of monitor dicts."""
    merged: list[dict[str, Any]] = []
    for name, wl_data in wl_outputs.items():
        entry = dict(wl_data)
        if name in xdg_outputs:
            entry.update(xdg_outputs[name])

            scale_x: float | None = None
            scale_y: float | None = None
            if "width_px" in entry and "logical_width" in entry:
                scale_x = entry["width_px"] / entry["logical_width"]
            if "height_px" in entry and "logical_height" in entry:
                scale_y = entry["height_px"] / entry["logical_height"]

            if scale_x is not None and scale_y is not None:
                entry["scale"] = (scale_x + scale_y) / 2
                entry["scale_x"] = scale_x
                entry["scale_y"] = scale_y
            elif scale_x is not None:
                entry["scale"] = scale_x
            elif scale_y is not None:
                entry["scale"] = scale_y

            orig_scale = wl_data.get("scale")
            if orig_scale is not None:
                entry["int_scale"] = orig_scale

        merged.append(entry)

    return merged


def get_outputs(
    raw: str | None = None,
    *,
    sort: bool = False,
    binary: str = "wayland-info",
) -> list[dict[str, Any]]:
    """Return connected monitors as a list of dicts.

    Pass ``raw`` wayland-info text to avoid running ``wayland-info``
    (the library equivalent of the CLI's ``--stdin``). Set ``sort=True``
    to order monitors top-left to bottom-right, or ``binary`` to use a
    different path to the ``wayland-info`` binary.
    """
    if raw is None:
        raw = run_wayland_info(binary)

    wl_outputs, xdg_outputs = parse_wayland_info(raw)

    if not wl_outputs and not xdg_outputs:
        warn("No monitors detected.\n"
             "Ensure you're running under Wayland with active outputs.")

    merged = merge_outputs(wl_outputs, xdg_outputs)

    if sort:
        merged.sort(key=lambda m: (m.get("y", 0), m.get("x", 0)))

    return merged


def to_json(outputs: list[dict[str, Any]], *, compact: bool = False) -> str:
    """Serialize monitor dicts to a JSON string.

    Use ``compact=True`` for single-line output (the library equivalent
    of the CLI's ``-c``).
    """
    return json.dumps(outputs, indent=None if compact else 2)


def main() -> None:
    """Entry point for the ``wlpdisplays`` CLI."""
    parser = argparse.ArgumentParser(
        description="List Wayland display outputs as JSON."
    )
    parser.add_argument(
        "-c", "--compact", action="store_true",
        help="Output JSON in one line (no pretty-printing)."
    )
    parser.add_argument(
        "-s", "--sort", action="store_true",
        help="Sort monitors top-left to bottom-right."
    )
    parser.add_argument(
        "-v", "--version", action="store_true",
        help="Show version and exit."
    )
    parser.add_argument(
        "-i", "--stdin", action="store_true",
        help="Read raw wayland-info data from stdin instead of running 'wayland-info'."
    )
    parser.add_argument(
        "-w", "--wayland-info-path", dest="wayland_info_path",
        default="wayland-info", metavar="PATH",
        help="Path to the 'wayland-info' binary (default: 'wayland-info')."
    )
    args = parser.parse_args()

    if args.version:
        print(f"wlpdisplays {__version__}")
        return

    try:
        if args.stdin:
            raw = sys.stdin.read()
        else:
            check_display_server()
            raw = run_wayland_info(binary=args.wayland_info_path)
    except WaylandInfoError as e:
        error(str(e))

    print(to_json(get_outputs(raw, sort=args.sort), compact=args.compact))


if __name__ == "__main__":
    main()
