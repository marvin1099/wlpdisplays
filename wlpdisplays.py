#!/usr/bin/env python3

from __future__ import annotations

import argparse
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from typing import Any, Literal

__version__ = "0.3.0"

PullMode = Literal["update", "once", "never"]

# Sentinel for "pull argument not specified": resolves to "update" for the
# default binary name, but to "never" (offline-safe) for explicit paths.
_PULL_UNSET: Any = object()

__all__ = [
    "__version__",
    "WaylandInfoError",
    "run_wayland_info",
    "ensure_wayland_info",
    "parse_wayland_info",
    "merge_outputs",
    "get_outputs",
    "to_json",
    "main",
]

# Debian pool directory hosting precompiled 'wayland-info' (package wayland-utils).
_DEBIAN_POOL_URL = "https://deb.debian.org/debian/pool/main/w/wayland-utils/"
_DEFAULT_BINARY = "wayland-info"
_PULL_INTERVAL = 24 * 60 * 60  # check for updates at most once per day

# Maps uname -m to Debian package architectures.
_DEB_ARCH_MAP = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv7l": "armhf",
    "armv8l": "armhf",
    "armhf": "armhf",
    "i386": "i386",
    "i486": "i386",
    "i586": "i386",
    "i686": "i386",
    "riscv64": "riscv64",
    "ppc64le": "ppc64el",
    "ppc64el": "ppc64el",
    "s390x": "s390x",
}


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


def cache_dir() -> str:
    """Directory where the downloaded binary and its metadata JSON are kept."""
    base = os.environ.get("WLPDISPLAYS_CACHE_DIR")
    if not base:
        xdg = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
        base = os.path.join(xdg, "wlpdisplays")
    return base


def cached_binary_path() -> str:
    return os.path.join(cache_dir(), "bin", "wayland-info")


def _meta_path() -> str:
    return os.path.join(cache_dir(), "wayland-info.json")


def _load_meta() -> dict[str, Any] | None:
    try:
        with open(_meta_path(), encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def _save_meta(meta: dict[str, Any]) -> None:
    os.makedirs(cache_dir(), exist_ok=True)
    tmp = _meta_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    os.replace(tmp, _meta_path())


def _deb_arch() -> str:
    machine = platform.machine()
    arch = _DEB_ARCH_MAP.get(machine.lower())
    if arch is None:
        raise WaylandInfoError(
            f"Unsupported architecture '{machine}' for downloading "
            "'wayland-info' from Debian."
        )
    return arch


def _deb_version_key(version: str) -> tuple:
    parts = []
    for seg in version.split("."):
        m = re.match(r"\d+", seg)
        parts.append((int(m.group()) if m else 0, seg))
    return tuple(parts)


def _parse_pool_listing(html: str, arch: str) -> tuple[tuple, str, str] | None:
    """Return (version_key, full_version, filename) of the newest .deb, or None."""
    best: tuple[tuple, str, str] | None = None
    for m in re.finditer(
        rf"wayland-utils_([^/_\s]+)_{re.escape(arch)}\.deb", html
    ):
        full = m.group(1)
        upstream = full.split("-", 1)[0]
        key = (_deb_version_key(upstream), full)
        if best is None or key > best[:2]:
            best = (key[0], key[1], m.group())
    return best


def _latest_deb_release(arch: str | None = None) -> tuple[str, str]:
    """Query the Debian pool listing; return (upstream version, .deb URL)."""
    arch = arch or _deb_arch()
    req = urllib.request.Request(
        _DEBIAN_POOL_URL,
        headers={"User-Agent": f"wlpdisplays/{__version__}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError) as e:
        raise WaylandInfoError(f"Could not reach {_DEBIAN_POOL_URL}: {e}") from None
    found = _parse_pool_listing(html, arch)
    if found is None:
        raise WaylandInfoError(
            f"No wayland-utils .deb found for architecture '{arch}' "
            f"at {_DEBIAN_POOL_URL}"
        )
    _, _, filename = found
    upstream = filename.split("_")[1].split("-", 1)[0]
    return upstream, _DEBIAN_POOL_URL + filename


def _extract_deb_binary(deb: bytes) -> bytes:
    """Extract usr/bin/wayland-info from a .deb (ar archive), pure Python."""
    if not deb.startswith(b"!<arch>\n"):
        raise WaylandInfoError("Downloaded file is not a Debian package (.deb).")
    off = 8
    while off < len(deb):
        hdr = deb[off : off + 60]
        if len(hdr) < 60:
            break
        name = hdr[0:16].decode("ascii", errors="replace").strip()
        size = int(hdr[48:58])
        data = deb[off + 60 : off + 60 + size]
        off += 60 + size + (size % 2)
        if name.startswith("data.tar"):
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
                for member in tf.getmembers():
                    norm = re.sub(r"^\./", "", member.name)
                    if norm == "usr/bin/wayland-info":
                        fobj = tf.extractfile(member)
                        if fobj is None:
                            break
                        return fobj.read()
            break
    raise WaylandInfoError(
        "'usr/bin/wayland-info' not found inside the downloaded package."
    )


def _install_binary(data: bytes, dest: str) -> None:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = f"{dest}.tmp.{os.getpid()}"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _download_to_cache(url: str, version: str) -> str:
    """Download the .deb, extract 'wayland-info', cache it and update the JSON."""
    req = urllib.request.Request(
        url, headers={"User-Agent": f"wlpdisplays/{__version__}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            deb = resp.read()
    except (urllib.error.URLError, OSError) as e:
        raise WaylandInfoError(f"Download failed ({url}): {e}") from None
    dest = cached_binary_path()
    _install_binary(_extract_deb_binary(deb), dest)
    now = int(time.time())
    _save_meta(
        {
            "last_pulled": now,
            "last_check": now,
            "version": version,
            "url": url,
            "arch": _deb_arch(),
            "binary": dest,
        }
    )
    warn(f"Pulled wayland-info {version} from Debian into {dest}")
    return dest


def _normalize_pull(pull: bool | PullMode | None) -> PullMode:
    """Map shortcuts: None → 'update', True → 'once', False → 'never'."""
    if pull is None:
        return "update"
    if isinstance(pull, bool):
        return "once" if pull else "never"
    if pull in ("update", "once", "never"):
        return pull  # type: ignore[return-value]
    raise ValueError(f"Invalid pull mode: {pull!r}")


def _disabled_error(binary: str) -> str:
    return (
        f"'{binary}' not found and downloading is disabled.\n"
        "Install wayland-utils (e.g., 'sudo pacman -S wayland-utils') "
        "or enable pulling: add --pull-once, drop --never-pull/-w, or "
        "use pull=None/'update' in the library."
    )


def _resolve_pull(pull: Any, binary: str) -> PullMode:
    """Resolve an unspecified ``pull`` based on the requested binary.

    Unspecified defaults to "never" for explicit paths (offline-safe, like
    the CLI's ``-w``) and to "update" for the default binary name.
    """
    if pull is _PULL_UNSET:
        return "update" if binary == _DEFAULT_BINARY else "never"
    return _normalize_pull(pull)


def ensure_wayland_info(
    binary: str = _DEFAULT_BINARY, *, pull: bool | PullMode | None = _PULL_UNSET
) -> str:
    """Return a runnable path to 'wayland-info', downloading it if needed.

    Resolution order:
      1. An explicit ``binary`` path (used as-is when it exists).
      2. ``wayland-info`` on the system PATH (default name only).
      3. The cached copy in ``~/.cache/wlpdisplays/bin/``.

    ``pull`` controls online behavior:
      - unspecified: ``"update"`` for the default binary name, but
        ``"never"`` for explicit paths (offline-safe by default).
      - ``None`` or ``"update"``: use/download the cache and check Debian
        for newer versions at most once per day (unix timestamps in meta
        JSON); also re-enables pulling for explicit paths.
      - ``True`` or ``"once"``: only pull if no cached copy exists yet;
        never updates.
      - ``False`` or ``"never"``: never touch the network.
    """
    pull = _resolve_pull(pull, binary)

    if binary != _DEFAULT_BINARY:
        # Explicit path: used as-is when present and executable. When
        # missing, only pulling-enabled modes may continue to the
        # cached-copy chain below.
        if shutil.which(binary) or (
            os.path.isfile(binary) and os.access(binary, os.X_OK)
        ):
            return binary
        if os.path.isfile(binary):
            raise WaylandInfoError(
                f"'{binary}' exists but is not executable.\n"
                "Fix permissions (e.g., 'chmod +x') or point -w at a "
                "runnable 'wayland-info' binary."
            )
        if pull == "never":
            raise WaylandInfoError(_disabled_error(binary))

    if path := shutil.which(binary):
        return path

    cached = cached_binary_path()
    have_cached = os.path.isfile(cached) and os.access(cached, os.X_OK)

    if pull == "never":
        if have_cached:
            return cached
        raise WaylandInfoError(_disabled_error(binary))

    if have_cached and pull == "once":
        return cached

    if have_cached and pull == "update":
        meta = _load_meta() or {}
        last = max(meta.get("last_pulled", 0), meta.get("last_check", 0))
        if int(time.time()) - last < _PULL_INTERVAL:
            return cached
        try:
            version, url = _latest_deb_release(meta.get("arch"))
            current = _deb_version_key(str(meta.get("version", "")))
            if _deb_version_key(version) > current:
                return _download_to_cache(url, version)
            _save_meta({**meta, "last_check": int(time.time())})
        except WaylandInfoError as e:
            warn(f"Update check failed, using cached copy:\n{e}")
        return cached

    # No usable cache yet ('once' first run or first 'update' pull): pull it.
    try:
        version, url = _latest_deb_release()
        return _download_to_cache(url, version)
    except WaylandInfoError as e:
        raise WaylandInfoError(
            f"{e}\n"
            "Alternatively install wayland-utils via your package manager "
            "(e.g., 'sudo pacman -S wayland-utils')."
        ) from None


def run_wayland_info(
    binary: str = _DEFAULT_BINARY, *, pull: bool | PullMode | None = _PULL_UNSET
) -> str:
    """Run ``wayland-info`` (or the given ``binary``) and return its raw output.

    ``pull`` accepts ``None``/``"update"``, ``True``/``"once"`` and
    ``False``/``"never"`` as in :func:`ensure_wayland_info`; when omitted
    it defaults to offline-safe for explicit paths.
    """
    resolved = ensure_wayland_info(binary, pull=pull)
    try:
        return subprocess.check_output(
            [resolved], text=True, stderr=subprocess.STDOUT
        )
    except FileNotFoundError:
        raise WaylandInfoError(
            f"'{resolved}' not found.\n"
            "Please install it (e.g., 'sudo pacman -S wayland-utils')."
        ) from None
    except subprocess.CalledProcessError as e:
        raise WaylandInfoError(
            f"'{binary}' failed with exit code {e.returncode}:\n"
            f"{e.output.strip()}"
        ) from None
    except OSError as e:
        raise WaylandInfoError(f"Failed to execute '{resolved}': {e}") from None


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
    binary: str = _DEFAULT_BINARY,
    pull: bool | PullMode | None = _PULL_UNSET,
) -> list[dict[str, Any]]:
    """Return connected monitors as a list of dicts.

    Pass ``raw`` wayland-info text to avoid running ``wayland-info``
    (the library equivalent of the CLI's ``--stdin``). Set ``sort=True``
    to order monitors top-left to bottom-right, or ``binary`` to use a
    different path to the ``wayland-info`` binary. ``pull`` selects how a
    missing ``wayland-info`` is obtained: unspecified = ``"update"``
    (auto) for the default name but offline-safe for explicit paths;
    ``None``/``"update"`` forces auto-update, ``True``/``"once"`` is a
    first-time pull only, ``False``/``"never"`` stays offline.
    """
    if raw is None:
        raw = run_wayland_info(binary, pull=pull)

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
        default=None, metavar="PATH",
        help="Path to the 'wayland-info' binary (default: 'wayland-info'). "
             "Explicit paths are used as-is and not downloaded unless "
             "--pull-once is also given."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-o", "--pull-once", dest="pull_once", action="store_true",
        help="If 'wayland-info' is missing from PATH, download it once into "
             "the cache; never check for or apply updates."
    )
    group.add_argument(
        "-n", "--never-pull", dest="never_pull", action="store_true",
        help="Never download 'wayland-info'; only use a system-installed "
             "or already-cached copy."
    )
    group.add_argument(
        "-p", "--pull", dest="auto_pull", action="store_true",
        help="Explicitly enable auto-update pulling (the default behavior): "
             "use/download the cached 'wayland-info' and check Debian for "
             "newer versions at most once per day. Mainly useful to override "
             "the no-download default of -w/--wayland-info-path."
    )
    args = parser.parse_args()

    if args.version:
        print(f"wlpdisplays {__version__}")
        return

    if args.never_pull:
        pull: bool | PullMode | None = "never"
    elif args.pull_once:
        pull = "once"
    elif args.auto_pull:
        pull = "update"
    elif args.wayland_info_path is not None:
        pull = False  # explicit -w path: use as-is, don't download by default
    else:
        pull = "update"

    try:
        if args.stdin:
            raw = sys.stdin.read()
        else:
            check_display_server()
            raw = run_wayland_info(
                binary=args.wayland_info_path or _DEFAULT_BINARY, pull=pull
            )
    except WaylandInfoError as e:
        error(str(e))

    print(to_json(get_outputs(raw, sort=args.sort), compact=args.compact))


if __name__ == "__main__":
    main()
