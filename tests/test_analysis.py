import importlib
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "picam_viewer"))
import analysis  # noqa: E402
import sensor_regs  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake"))
importlib.import_module("fake_profiles")  # registers the fakecam profiles


def synthetic(n=64, h=120, w=160, mean=100.0, temporal=2.0, fpn=3.0, seed=1):
    rng = np.random.default_rng(seed)
    pattern = rng.normal(0, fpn, (h, w))
    return [mean + pattern + rng.normal(0, temporal, (h, w)) for _ in range(n)]


def test_noise_stats_recovers_temporal_and_fpn():
    res = analysis.noise_stats(synthetic())
    assert res["frames"] == 64
    assert res["mean"] == pytest.approx(100.0, abs=0.2)
    assert res["temporal_noise"] == pytest.approx(2.0, rel=0.03)
    assert res["fpn"] == pytest.approx(3.0, rel=0.05)
    assert res["row_temporal_noise"] < 0.5 and res["col_temporal_noise"] < 0.5


def test_single_frame_has_no_temporal_noise():
    res = analysis.noise_stats(synthetic(n=1))
    assert np.isnan(res["temporal_noise"])
    assert res["fpn"] == pytest.approx(np.hypot(2.0, 3.0), rel=0.05)  # still contains temporal noise


def test_roi():
    frames = [np.arange(100.0).reshape(10, 10)] * 2
    res = analysis.noise_stats(frames, roi=(2, 3, 4, 5))
    assert res["pixels"] == 20
    assert res["min"] == 32 and res["max"] == 75


def test_row_fpn_detects_row_pattern():
    frames = [np.full((100, 100), 50.0) for _ in range(4)]
    for f in frames:
        f[::2] += 4.0  # every other row 4 DN higher
    assert analysis.noise_stats(frames)["row_fpn"] == pytest.approx(2.0)
    assert analysis.noise_stats(frames)["col_fpn"] == pytest.approx(0.0)


def test_raw_to_image_pi5_left_aligned():
    # Pi 5: 12-bit data left-aligned in a 16-bit 'R16' stream, stride padding on the right
    w, h, stride = 6, 2, 16
    data = np.zeros((h, stride // 2), dtype=np.uint16)
    data[:, :w] = np.arange(w * h).reshape(h, w) << 4
    img, bits = analysis.raw_to_image(data.view(np.uint8), "R16", (w, h), 12)
    assert bits == 12
    assert img.tolist() == np.arange(w * h).reshape(h, w).tolist()


def test_raw_to_image_pi4_and_8bit():
    data = (np.arange(8, dtype=np.uint16) * 100).reshape(2, 4)
    img, bits = analysis.raw_to_image(data.view(np.uint8), "R12", (4, 2), 12)
    assert img.tolist() == data.tolist() and bits == 12
    img8, bits8 = analysis.raw_to_image(np.arange(8, dtype=np.uint8).reshape(2, 4), "R8", (4, 2), 8)
    assert img8.tolist() == [[0, 1, 2, 3], [4, 5, 6, 7]] and bits8 == 8


def test_raw_to_image_rejects_compressed():
    with pytest.raises(ValueError):
        analysis.raw_to_image(np.zeros((2, 4), np.uint8), "MONO_PISP_COMP1", (4, 2), 12)


def test_frame_stats_counts_drops_and_fps():
    s = analysis.FrameStats()
    ts = 0
    for i in range(60):
        ts += 10_000_000 if i != 30 else 30_000_000  # 100 fps, one gap of 3 frames
        s.update({"SensorTimestamp": ts, "FrameDuration": 10000})
    assert s.frames == 60
    assert s.dropped == 2
    assert s.max_gap_ms == pytest.approx(30.0)
    assert s.expected_fps == pytest.approx(100.0)
    assert 95 < s.fps < 101
    s.reset()
    assert s.frames == s.dropped == 0


def test_parse_sequence_formats(tmp_path):
    txt = tmp_path / "seq.txt"
    txt.write_text("# comment\nwrite 0x01 to 0xE000\nWRITE 16 TO 0x0010  # inline\nsleep 10\n")
    assert sensor_regs.parse_sequence(str(txt)) == [(0xE000, 1), (0x10, 16)]
    csv = tmp_path / "seq.csv"
    csv.write_text("addr,value\n0x2000,0x0a\n8192,11\n")
    assert sensor_regs.parse_sequence(str(csv)) == [(0x2000, 10), (0x2000, 11)]


def test_find_sensor_from_sysfs(tmp_path):
    dev = tmp_path / "10-0036"
    dev.mkdir()
    (dev / "name").write_text("duocam\n")
    (tmp_path / "1-0050").mkdir()
    info = sensor_regs.find_sensor(str(tmp_path))
    assert (info.name, info.bus, info.addr, info.banked) == ("duocam", 10, 0x36, True)
    assert sensor_regs.find_sensor(str(tmp_path / "none")) is None


def test_find_sensor_prefers_the_device_name(tmp_path):
    # one driver (bound as "quadcam") serving a "duocam": the device name decides
    dev = tmp_path / "10-0036"
    dev.mkdir()
    (dev / "name").write_text("duocam\n")
    drivers = tmp_path / "drivers" / "quadcam"
    drivers.mkdir(parents=True)
    try:
        os.symlink(drivers, dev / "driver")
    except OSError:
        pytest.skip("no symlinks here")
    assert sensor_regs.find_sensor(str(tmp_path)).name == "duocam"


def test_find_sensor_by_camera_model(tmp_path):
    # no plugin profile: found by the camera's model name, flat map, no named registers
    dev = tmp_path / "10-001a"
    dev.mkdir()
    (dev / "name").write_text("imx477\n")
    assert sensor_regs.find_sensor(str(tmp_path)) is None
    info = sensor_regs.find_sensor(str(tmp_path), names=["imx477"])
    assert (info.name, info.addr, info.banked, info.registers) == ("imx477", 0x1A, False, [])
    assert info.profile.driver_cid_base is None


def test_profiles_from_plugins(tmp_path):
    (tmp_path / "demo.py").write_text(
        "import sensor_regs as sr\nsr.register_profile(sr.SensorProfile('demo', [('ID', 0x10, 2)], contexts='AB'))\n")
    (tmp_path / "broken.py").write_text("raise RuntimeError('broken plugin')\n")
    sensor_regs.load_plugins(str(tmp_path))  # the broken one is logged and skipped
    info = sensor_regs.SensorInfo("demo", 1, 0x36)
    assert info.registers == [("ID", 0x10, 2)] and info.contexts == "AB" and info.banked
    del sensor_regs.PROFILES["demo"]


def test_live_channels_and_mapping():
    import live
    img = np.arange(16).reshape(4, 4)
    ch = live.channels(img, "SRGGB12")
    assert sorted(ch) == ["B", "G", "R"] and len(ch["G"]) == 8
    assert list(live.channels(img, "R12")) == ["Y"]

    class Cam:  # minimal picamera2 stand-in: 600x400 display of a 576x768 raw mode
        camera_config = {"display": "main", "main": {"size": (600, 400)}}
    lv = live.LiveView(Cam(), set_overlay=lambda overlay: None)
    mode = {"crop_limits": (12, 0, 576, 768)}
    dw, dh, to_overlay, across = lv._mapping(np.zeros((768, 576)), mode, (12, 0, 576, 768))
    assert (dw, dh, across) == (600, 400, 576)
    assert to_overlay(0, 0) == (0, 0) and to_overlay(576, 768) == (600, 400)
    # zoomed to a 24x24 sensor-pixel crop at (300, 200): pixel values are shown
    *_, across = lv._mapping(np.zeros((768, 576)), mode, (300, 200, 24, 24))
    assert across == 24 <= live.PIXEL_VALUES_MAX


def test_isp_stats_decode():
    import isp_stats
    s = np.zeros(1, dtype=isp_stats.PISP_STATS)
    s["agc_histogram"][0, 10] = 500
    z = s["awb_zones"][0]
    z["G"][:] = 1000
    z["counted"][:] = 10
    z["G"][33] = 5000  # zone (1, 1)
    s["cdaf_foms"][0, 9] = 7
    out = isp_stats.decode({"PispStatsOutput": tuple(s.tobytes())})
    assert out["platform"] == "pisp" and out["histogram"][10] == 500 and len(out["histogram"]) == 1024
    assert out["zones_mean"].shape == (32, 32)
    assert out["zones_mean"][0, 0] == 100 and out["zones_mean"][1, 1] == 500
    assert out["focus"][1, 1] == 7
    assert isp_stats.decode({"ExposureTime": 1}) is None
    assert isp_stats.decode({"Bcm2835StatsOutput": (1, 2)}) == {"platform": "vc4"}
    with pytest.raises(ValueError):
        isp_stats.decode({"PispStatsOutput": (0,) * 10})


def test_read_raw_video(tmp_path):
    import json
    w, h, stride = 4, 3, 16  # Pi 5 style: 16-bit left-aligned 12-bit data, padded stride
    frames = [(np.arange(w * h).reshape(h, w) + 100 * k) for k in range(3)]
    with open(tmp_path / "v.raw", "wb") as fh:
        for f in frames:
            buf = np.zeros((h, stride // 2), np.uint16)
            buf[:, :w] = f << 4
            fh.write(buf.tobytes())
    (tmp_path / "v_pts.txt").write_text("# timestamp format v2\n0.000\n10.000\n20.000\n")
    (tmp_path / "v.json").write_text(json.dumps({"format": "R16", "size": [w, h], "stride": stride, "bit_depth": 12,
                                                 "frame_bytes": stride * h, "pts": "v_pts.txt"}))
    out = list(analysis.read_raw_video(str(tmp_path / "v.json")))
    assert len(out) == 3
    assert [t for _, t in out] == [0.0, 10.0, 20.0]
    assert all(img.tolist() == f.tolist() for (img, _), f in zip(out, frames))


def test_raw_to_image_pi5_8bit_both_alignments():
    vals = np.array([[0, 9, 112, 255], [17, 33, 64, 200]], dtype=np.uint16)
    left, bits = analysis.raw_to_image((vals << 8).view(np.uint8), "R16", (4, 2), 8)
    right, _ = analysis.raw_to_image(vals.view(np.uint8), "R16", (4, 2), 8)
    assert bits == 8 and left.tolist() == vals.tolist() and right.tolist() == vals.tolist()
