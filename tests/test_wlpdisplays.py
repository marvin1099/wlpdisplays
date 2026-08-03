import json
import os
import subprocess
import sys
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
        m.assert_called_once_with("/usr/bin/wayland-info")

    def test_missing_binary_raises(self):
        with mock.patch("subprocess.check_output", side_effect=FileNotFoundError):
            with self.assertRaises(wlp.WaylandInfoError):
                wlp.run_wayland_info()

    def test_failed_binary_raises(self):
        err = subprocess.CalledProcessError(1, ["wayland-info"], output="boom")
        with mock.patch("subprocess.check_output", side_effect=err):
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
        m.assert_called_once_with(binary="/tmp/fake-wayland-info")
        self.assertEqual(json.loads(out.getvalue()), wlp.get_outputs(raw=SAMPLE))


if __name__ == "__main__":
    unittest.main()
