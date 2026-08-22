import json
import io
import os
import subprocess
import sys
import tarfile
import time
import unittest
from io import StringIO
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wlpdisplays as wlp


SAMPLE = """\
interface: 'wl_output', version: 4, name: 66
	name: HDMI-A-1
	description: BNQ BenQ GL2580
	x: 0, y: 1080, scale: 2,
	physical_width: 544 mm, physical_height: 303 mm,
	make: 'BNQ', model: 'BenQ GL2580',
	subpixel_orientation: unknown, output_transform: normal,
	mode:
		width: 3840 px, height: 2160 px, refresh: 60.000 Hz,
		flags: current
interface: 'wl_output', version: 4, name: 67
	name: DP-1
	description: HKC OVERSEAS LIMITED L21500WDS
	x: 0, y: 0, scale: 1,
	physical_width: 477 mm, physical_height: 268 mm,
	make: 'HKC OVERSEAS LIMITED', model: 'L21500WDS',
	subpixel_orientation: unknown, output_transform: normal,
	mode:
		width: 1920 px, height: 1080 px, refresh: 60.000 Hz,
		flags: current
interface: 'zxdg_output_manager_v1', version: 3, name: 33
	xdg_output_v1
		output: 67
		name: 'DP-1'
		description: 'HKC OVERSEAS LIMITED L21500WDS'
		logical_x: 0, logical_y: 0
		logical_width: 1920, logical_height: 1080
	xdg_output_v1
		output: 66
		name: 'HDMI-A-1'
		description: 'BNQ BenQ GL2580'
		logical_x: 0, logical_y: 1080
		logical_width: 1920, logical_height: 1080
"""


class TestParse(unittest.TestCase):
    def test_parse_splits_outputs(self):
        wl, xdg = wlp.parse_wayland_info(SAMPLE)
        self.assertEqual(set(wl), {"DP-1", "HDMI-A-1"})
        self.assertEqual(set(xdg), {"DP-1", "HDMI-A-1"})

    def test_parse_wl_fields(self):
        wl, _ = wlp.parse_wayland_info(SAMPLE)
        hdmi = wl["HDMI-A-1"]
        self.assertEqual(hdmi["name"], "HDMI-A-1")
        self.assertEqual(hdmi["description"], "BNQ BenQ GL2580")
        self.assertEqual((hdmi["x"], hdmi["y"], hdmi["scale"]), (0, 1080, 2))
        self.assertEqual(hdmi["physical_width_mm"], 544)
        self.assertEqual(
            (hdmi["width_px"], hdmi["height_px"], hdmi["refresh_hz"]),
            (3840, 2160, 60.0),
        )
        self.assertEqual(hdmi["make"], "BNQ")
        self.assertEqual(hdmi["model"], "BenQ GL2580")

    def test_parse_xdg_fields(self):
        _, xdg = wlp.parse_wayland_info(SAMPLE)
        dp = xdg["DP-1"]
        self.assertEqual(dp["output"], 67)
        self.assertEqual((dp["logical_x"], dp["logical_y"]), (0, 0))
        self.assertEqual((dp["logical_width"], dp["logical_height"]), (1920, 1080))


class TestMerge(unittest.TestCase):
    def test_merge_computes_scale(self):
        by_name = {m["name"]: m for m in wlp.get_outputs(raw=SAMPLE)}
        hdmi = by_name["HDMI-A-1"]
        self.assertEqual(hdmi["scale"], 2.0)
        self.assertEqual(hdmi["scale_x"], 2.0)
        self.assertEqual(hdmi["scale_y"], 2.0)
        self.assertEqual(hdmi["int_scale"], 2)
        self.assertEqual(hdmi["logical_y"], 1080)

    def test_sort_top_left_to_bottom_right(self):
        monitors = wlp.get_outputs(raw=SAMPLE, sort=True)
        self.assertEqual([m["name"] for m in monitors], ["DP-1", "HDMI-A-1"])


class TestJson(unittest.TestCase):
    def test_to_json_roundtrip(self):
        monitors = wlp.get_outputs(raw=SAMPLE)
        self.assertEqual(json.loads(wlp.to_json(monitors)), monitors)

    def test_to_json_compact_is_single_line(self):
        monitors = wlp.get_outputs(raw=SAMPLE)
        self.assertNotIn("\n", wlp.to_json(monitors, compact=True))


class TestRunWaylandInfo(unittest.TestCase):
    def test_returns_raw_output(self):
        with mock.patch("subprocess.check_output", return_value=SAMPLE):
            self.assertEqual(wlp.run_wayland_info(), SAMPLE)

    def test_custom_binary(self):
        with mock.patch("subprocess.check_output", return_value=SAMPLE) as m:
            wlp.run_wayland_info(binary="/usr/bin/wayland-info")
        m.assert_called_once_with(
            ["/usr/bin/wayland-info"], text=True, stderr=subprocess.STDOUT
        )

    def test_get_outputs_custom_binary(self):
        with mock.patch("wlpdisplays.run_wayland_info", return_value=SAMPLE) as m:
            wlp.get_outputs(binary="/usr/bin/wayland-info")
        m.assert_called_once_with(
            "/usr/bin/wayland-info", pull=wlp._PULL_UNSET
        )

    def test_missing_binary_raises(self):
        with mock.patch("subprocess.check_output", side_effect=FileNotFoundError):
            with self.assertRaises(wlp.WaylandInfoError):
                wlp.run_wayland_info()

    def test_failed_binary_raises(self):
        err = subprocess.CalledProcessError(1, ["wayland-info"], output="boom")
        with mock.patch("subprocess.check_output", side_effect=err):
            with self.assertRaises(wlp.WaylandInfoError):
                wlp.run_wayland_info()

    def test_unexecutable_binary_raises(self):
        with mock.patch(
            "wlpdisplays.ensure_wayland_info", return_value="/some/binary"
        ):
            with mock.patch(
                "subprocess.check_output", side_effect=PermissionError
            ):
                with self.assertRaises(wlp.WaylandInfoError):
                    wlp.run_wayland_info()


class TestCli(unittest.TestCase):
    def test_stdin_mode(self):
        with mock.patch("sys.stdin", StringIO(SAMPLE)):
            with mock.patch("sys.argv", ["wlpdisplays", "--stdin"]):
                with mock.patch("sys.stdout", new_callable=StringIO) as out:
                    wlp.main()
        self.assertEqual(json.loads(out.getvalue()), wlp.get_outputs(raw=SAMPLE))

    def test_custom_wayland_info_path(self):
        with mock.patch("sys.argv", ["wlpdisplays", "-w", "/tmp/fake-wayland-info"]):
            with mock.patch("wlpdisplays.run_wayland_info", return_value=SAMPLE) as m:
                with mock.patch("sys.stdout", new_callable=StringIO) as out:
                    wlp.main()
        # explicit -w without pull flags: strict, no download by default
        m.assert_called_once_with(
            binary="/tmp/fake-wayland-info", pull=False
        )
        self.assertEqual(json.loads(out.getvalue()), wlp.get_outputs(raw=SAMPLE))

    def test_explicit_path_with_pull_flags(self):
        with mock.patch(
            "sys.argv", ["wlpdisplays", "-w", "/tmp/fake-wayland-info", "-o"]
        ):
            with mock.patch(
                "wlpdisplays.run_wayland_info", return_value=SAMPLE
            ) as m:
                wlp.main()
        m.assert_called_once_with(binary="/tmp/fake-wayland-info", pull="once")
        with mock.patch(
            "sys.argv", ["wlpdisplays", "-w", "/tmp/fake-wayland-info", "-n"]
        ):
            with mock.patch(
                "wlpdisplays.run_wayland_info", return_value=SAMPLE
            ) as m:
                wlp.main()
        m.assert_called_once_with(binary="/tmp/fake-wayland-info", pull="never")

    def test_pull_flags_passthrough(self):
        cases = [
            ([], "update"),
            (["--pull"], "update"),
            (["-p"], "update"),
            (["--pull-once"], "once"),
            (["-o"], "once"),
            (["--never-pull"], "never"),
            (["-n"], "never"),
            # -w alone is strict, but -w with -p explicitly enables pulling
            (["-w", "/tmp/fake-wayland-info", "-p"], "update"),
        ]
        for extra_args, mode in cases:
            with self.subTest(args=extra_args):
                argv = ["wlpdisplays", *extra_args]
                if mode == "update" and "-w" not in extra_args:
                    binary = "wayland-info"
                else:
                    binary = (
                        "/tmp/fake-wayland-info"
                        if "-w" in extra_args
                        else "wayland-info"
                    )
                with mock.patch("sys.argv", argv):
                    with mock.patch(
                        "wlpdisplays.run_wayland_info", return_value=SAMPLE
                    ) as m:
                        wlp.main()
                m.assert_called_once_with(binary=binary, pull=mode)

    def test_pull_flags_mutually_exclusive(self):
        for combo in (["-o", "-n"], ["-o", "-p"], ["-n", "-p"]):
            with self.subTest(args=combo):
                with mock.patch("sys.argv", ["wlpdisplays", *combo]):
                    with self.assertRaises(SystemExit):
                        wlp.main()


POOL_HTML = """
<a href="wayland-utils_1.1.0-1_amd64.deb">wayland-utils_1.1.0-1_amd64.deb</a>
<a href="wayland-utils_1.2.0-2_amd64.deb">wayland-utils_1.2.0-2_amd64.deb</a>
<a href="wayland-utils_1.3.0-1_amd64.deb">wayland-utils_1.3.0-1_amd64.deb</a>
<a href="wayland-utils_1.3.0-1_arm64.deb">wayland-utils_1.3.0-1_arm64.deb</a>
<a href="wayland-utils_1.3.0.orig.tar.xz">wayland-utils_1.3.0.orig.tar.xz</a>
"""


class TestPullHelpers(unittest.TestCase):
    def test_version_key_ordering(self):
        self.assertLess(wlp._deb_version_key("1.9"), wlp._deb_version_key("1.10"))
        self.assertLess(wlp._deb_version_key("1.2.0"), wlp._deb_version_key("1.3.0"))
        self.assertEqual(
            wlp._deb_version_key("1.3.0"), wlp._deb_version_key("1.3.0")
        )

    def test_parse_pool_listing_picks_newest(self):
        found = wlp._parse_pool_listing(POOL_HTML, "amd64")
        self.assertIsNotNone(found)
        _, full, fname = found
        self.assertEqual(full, "1.3.0-1")
        self.assertEqual(fname, "wayland-utils_1.3.0-1_amd64.deb")

    def test_parse_pool_listing_prefers_binmu(self):
        html = (
            '<a href="wayland-utils_1.3.0-1+b1_amd64.deb">'
            'wayland-utils_1.3.0-1+b1_amd64.deb</a>'
            '<a href="wayland-utils_1.3.0-1_amd64.deb">'
            'wayland-utils_1.3.0-1_amd64.deb</a>'
        )
        found = wlp._parse_pool_listing(html, "amd64")
        self.assertEqual(found[2], "wayland-utils_1.3.0-1+b1_amd64.deb")

    def test_parse_pool_listing_arch_filter(self):
        self.assertIsNone(wlp._parse_pool_listing(POOL_HTML, "mips64el"))

    def test_deb_arch_mapping(self):
        cases = {"x86_64": "amd64", "aarch64": "arm64", "armv7l": "armhf"}
        for machine, arch in cases.items():
            with self.subTest(machine=machine):
                with mock.patch("platform.machine", return_value=machine):
                    self.assertEqual(wlp._deb_arch(), arch)

    def test_deb_arch_unsupported(self):
        with mock.patch("platform.machine", return_value="sparc64"):
            with self.assertRaises(wlp.WaylandInfoError):
                wlp._deb_arch()

    def _make_deb(self, bin_data: bytes) -> bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo("./usr/bin/wayland-info")
            info.size = len(bin_data)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(bin_data))
        data_tar = buf.getvalue()

        out = io.BytesIO()
        out.write(b"!<arch>\n")
        members = ((b"debian-binary   ", b"2.0\n"), (b"data.tar.gz     ", data_tar))
        for name, content in members:
            hdr = (
                name[:16].ljust(16)
                + b"0".ljust(12)
                + b"0".ljust(6)
                + b"0".ljust(6)
                + b"100644 ".ljust(8)
                + str(len(content)).encode().ljust(10)
                + b"`\n"
            )
            out.write(hdr)
            out.write(content)
            if len(content) % 2:
                out.write(b"\n")
        return out.getvalue()

    def test_extract_deb_binary(self):
        deb = self._make_deb(b"#!/bin/sh\necho hi\n")
        self.assertEqual(
            wlp._extract_deb_binary(deb), b"#!/bin/sh\necho hi\n"
        )

    def test_extract_deb_rejects_garbage(self):
        with self.assertRaises(wlp.WaylandInfoError):
            wlp._extract_deb_binary(b"not an ar archive")


class TestEnsureWaylandInfo(unittest.TestCase):
    NEWER = ("9.9.9", "http://example.invalid/wayland-utils_9.9.9-1_amd64.deb")
    SAME = ("1.3.0", "http://example.invalid/wayland-utils_1.3.0-1_amd64.deb")

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self._old_env = os.environ.get("WLPDISPLAYS_CACHE_DIR")
        os.environ["WLPDISPLAYS_CACHE_DIR"] = self._tmp.name

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("WLPDISPLAYS_CACHE_DIR", None)
        else:
            os.environ["WLPDISPLAYS_CACHE_DIR"] = self._old_env
        self._tmp.cleanup()

    def make_cached(self):
        path = wlp.cached_binary_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(path, 0o755)
        return path

    def write_meta(self, **overrides):
        meta = {
            "last_pulled": int(time.time()),
            "last_check": int(time.time()),
            "version": "1.3.0",
            "url": self.SAME[1],
            "arch": "amd64",
            "binary": wlp.cached_binary_path(),
        }
        meta.update(overrides)
        wlp._save_meta(meta)

    def test_invalid_mode_raises(self):
        with self.assertRaises(ValueError):
            wlp.ensure_wayland_info(pull="sometimes")  # type: ignore[arg-type]

    def test_boolean_pull_shortcuts(self):
        self.assertEqual(wlp._normalize_pull(True), "once")
        self.assertEqual(wlp._normalize_pull(False), "never")
        self.assertEqual(wlp._normalize_pull(None), "update")

    def test_unspecified_pull_depends_on_binary(self):
        # default name -> auto-update; explicit path -> offline-safe
        self.assertEqual(
            wlp._resolve_pull(wlp._PULL_UNSET, "wayland-info"), "update"
        )
        self.assertEqual(
            wlp._resolve_pull(wlp._PULL_UNSET, "/custom/path"), "never"
        )
        with mock.patch("shutil.which", return_value=None):
            with mock.patch(
                "wlpdisplays._latest_deb_release", side_effect=AssertionError
            ):
                with self.assertRaises(wlp.WaylandInfoError):
                    wlp.get_outputs(binary="/no/such/binary")
        for value, mode in ((True, "once"), (False, "never")):
            with self.subTest(pull=value):
                cached = self.make_cached()
                with mock.patch("shutil.which", return_value=None):
                    self.assertEqual(
                        wlp.ensure_wayland_info(pull=value), cached
                    )
                os.unlink(cached)
        # pull=False must never touch the network even without a cache
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaises(wlp.WaylandInfoError):
                wlp.ensure_wayland_info(pull=False)

    def test_run_wayland_info_accepts_boolean_pull(self):
        with mock.patch(
            "wlpdisplays.ensure_wayland_info", return_value="resolved"
        ) as ensure:
            with mock.patch("subprocess.check_output", return_value=SAMPLE):
                wlp.run_wayland_info(pull=True)
        ensure.assert_called_once_with("wayland-info", pull=True)

    def test_explicit_path_passthrough_and_missing(self):
        self.assertEqual(
            wlp.ensure_wayland_info(__file__, pull="never"), __file__
        )
        with self.assertRaises(wlp.WaylandInfoError):
            wlp.ensure_wayland_info("/no/such/binary", pull=False)

    def test_explicit_non_executable_path_raises(self):
        import tempfile

        with tempfile.NamedTemporaryFile() as f:
            os.chmod(f.name, 0o644)
            with self.assertRaisesRegex(wlp.WaylandInfoError, "not executable"):
                wlp.ensure_wayland_info(f.name, pull=None)
        # pull=None re-enables the cache chain for explicit paths
        with mock.patch("shutil.which", return_value=None):
            with mock.patch(
                "wlpdisplays._latest_deb_release",
                side_effect=AssertionError("no network expected here"),
            ):
                cached = wlp.cached_binary_path()
                os.makedirs(os.path.dirname(cached), exist_ok=True)
                with open(cached, "w") as f:
                    f.write("#!/bin/sh\n")
                os.chmod(cached, 0o755)
                self.write_meta()  # fresh meta: no online check needed
                self.assertEqual(
                    wlp.ensure_wayland_info("/no/such/binary", pull=None),
                    cached,
                )

    def test_pull_none_enables_download_for_missing_path(self):
        def fake_download(url, version):
            return self.make_cached()

        with mock.patch("shutil.which", return_value=None):
            with mock.patch(
                "wlpdisplays._latest_deb_release", return_value=self.NEWER
            ):
                with mock.patch(
                    "wlpdisplays._download_to_cache", side_effect=fake_download
                ) as dl:
                    result = wlp.ensure_wayland_info(
                        "/no/such/binary", pull=None
                    )
        self.assertEqual(result, wlp.cached_binary_path())
        dl.assert_called_once()

    def test_system_binary_wins_without_network(self):
        downloader = mock.Mock()
        with mock.patch("shutil.which", return_value="/usr/bin/wayland-info"):
            with mock.patch.dict(
                "wlpdisplays.__dict__", {"_latest_deb_release": downloader}
            ):
                self.assertEqual(
                    wlp.ensure_wayland_info(pull="update"),
                    "/usr/bin/wayland-info",
                )
        downloader.assert_not_called()

    def test_never_mode_offline(self):
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaises(wlp.WaylandInfoError):
                wlp.ensure_wayland_info(pull="never")
            cached = self.make_cached()
            self.assertEqual(wlp.ensure_wayland_info(pull="never"), cached)

    def test_once_downloads_only_first_time(self):
        def fake_download(url, version):
            return self.make_cached()

        with mock.patch("shutil.which", return_value=None):
            with mock.patch(
                "wlpdisplays._latest_deb_release", return_value=self.NEWER
            ):
                with mock.patch(
                    "wlpdisplays._download_to_cache", side_effect=fake_download
                ) as dl:
                    first = wlp.ensure_wayland_info(pull="once")
                    second = wlp.ensure_wayland_info(pull="once")
        cached = wlp.cached_binary_path()
        self.assertEqual(first, cached)
        self.assertEqual(second, cached)
        dl.assert_called_once_with(self.NEWER[1], self.NEWER[0])

    def test_update_fresh_meta_skips_network(self):
        cached = self.make_cached()
        self.write_meta()
        with mock.patch("shutil.which", return_value=None):
            with mock.patch(
                "wlpdisplays._latest_deb_release", side_effect=AssertionError
            ):
                self.assertEqual(wlp.ensure_wayland_info(pull="update"), cached)

    def test_update_stale_same_version_bumps_check(self):
        cached = self.make_cached()
        self.write_meta(
            last_pulled=int(time.time()) - 2 * 86400,
            last_check=int(time.time()) - 2 * 86400,
        )
        with mock.patch("shutil.which", return_value=None):
            with mock.patch(
                "wlpdisplays._latest_deb_release", return_value=self.SAME
            ):
                self.assertEqual(wlp.ensure_wayland_info(pull="update"), cached)
        meta = wlp._load_meta()
        self.assertAlmostEqual(meta["last_check"], int(time.time()), delta=5)

    def test_update_stale_newer_redownloads(self):
        cached = self.make_cached()
        self.write_meta(
            last_pulled=int(time.time()) - 2 * 86400,
            last_check=int(time.time()) - 2 * 86400,
        )
        new_cached = self.make_cached()
        with mock.patch("shutil.which", return_value=None):
            with mock.patch(
                "wlpdisplays._latest_deb_release", return_value=self.NEWER
            ):
                with mock.patch(
                    "wlpdisplays._download_to_cache", return_value=new_cached
                ) as dl:
                    result = wlp.ensure_wayland_info(pull="update")
        self.assertEqual(result, new_cached)
        dl.assert_called_once_with(self.NEWER[1], self.NEWER[0])

    def test_update_network_error_falls_back_to_cache(self):
        cached = self.make_cached()
        self.write_meta(
            last_pulled=int(time.time()) - 2 * 86400,
            last_check=int(time.time()) - 2 * 86400,
        )
        err = wlp.WaylandInfoError("offline")
        with mock.patch("shutil.which", return_value=None):
            with mock.patch(
                "wlpdisplays._latest_deb_release", side_effect=err
            ):
                self.assertEqual(wlp.ensure_wayland_info(pull="update"), cached)

    def test_run_wayland_info_resolves_via_ensure(self):
        with mock.patch(
            "wlpdisplays.ensure_wayland_info", return_value="resolved"
        ) as ensure:
            with mock.patch(
                "subprocess.check_output", return_value=SAMPLE
            ) as co:
                raw = wlp.run_wayland_info(pull="never")
        self.assertEqual(raw, SAMPLE)
        ensure.assert_called_once_with("wayland-info", pull="never")
        co.assert_called_once_with(["resolved"], text=True, stderr=subprocess.STDOUT)


if __name__ == "__main__":
    unittest.main()
