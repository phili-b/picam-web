#!/usr/bin/python3
"""Hardware smoke test of the viewer panels on a Raspberry Pi with a camera.

Runs without a display:  QT_QPA_PLATFORM=offscreen python3 tests/hw_smoke.py
Only reads registers; sets exposure and gain on the camera. Exit code 0 = all checks passed.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "picam_viewer"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

from picamera2 import Picamera2  # noqa: E402

import panels  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
    if not ok:
        failures.append(name)


p = Picamera2()
modes = sorted(p.sensor_modes, key=lambda m: m["bit_depth"])
mode = modes[-1]
p.configure(p.create_still_configuration(raw={"format": mode["unpacked"], "size": mode["size"]}, buffer_count=3))
frame_tab = panels.FrameTab()
p.post_callback = lambda request: frame_tab.update_metadata(request.get_metadata())
p.start()
# Pick an exposure that does not saturate in the current lighting
exposure = 5000
while True:
    p.set_controls({"AeEnable": False, "ExposureTime": exposure, "AnalogueGain": 1.0})
    time.sleep(0.5)
    peak = p.capture_array("raw").view("uint16").max() if mode["bit_depth"] > 8 else p.capture_array("raw").max()
    if peak < 0.8 * 65535 or exposure <= 50:
        break
    exposure //= 2
print(f"exposure {exposure} us")
time.sleep(1.5)

# Frames
s = frame_tab.stats
check("frames", s.frames > 10 and s.fps > 0,
      f"{s.frames} frames, measured {s.fps:.1f} fps, expected {s.expected_fps:.1f}, "
      f"dropped {s.dropped}, max gap {s.max_gap_ms:.1f} ms")

# Noise (worker run synchronously)
noise_tab = panels.NoiseTab(p)
out = {}
noise_tab.sig.done.disconnect()
noise_tab.sig.done.connect(out.update)
fmt, size, bits = noise_tab._raw_info()
noise_tab._capture(fmt, size, bits, 8, None)
app.processEvents()
if "error" in out:
    check("noise", False, out["error"])
else:
    r = out["result"]
    check("noise", r["max"] < (1 << bits) and r["temporal_noise"] > 0,
          f"{fmt} {bits}-bit {size}: mean {r['mean']:.2f} DN, temporal {r['temporal_noise']:.3f}, "
          f"FPN {r['fpn']:.3f}, row FPN {r['row_fpn']:.3f}, col FPN {r['col_fpn']:.3f}, max {r['max']:.0f}")
    out.clear()
    noise_tab._capture(fmt, size, bits, 4, (100, 100, 64, 64))
    app.processEvents()
    r = out["result"]
    check("noise roi", r["pixels"] == 64 * 64, f"{r['pixels']} pixels, mean {r['mean']:.1f} DN")

# Registers (read only)
reg_tab = panels.RegisterTab()
check("register sensor", reg_tab.regs is not None, str(reg_tab.info))
if reg_tab.regs:
    exp = reg_tab.known.findText("EXP_TIME_L", flags=__import__("PyQt5.QtCore").QtCore.Qt.MatchStartsWith)
    check("known registers", exp > 0, f"{reg_tab.known.count() - 1} named registers")
    reg_tab.known.setCurrentIndex(exp)
    reg_tab.on_read()
    reg_tab.dump_start.setText("0x0000")
    reg_tab.dump_count.setValue(32)
    reg_tab.on_dump()
    text = reg_tab.log.toPlainText()
    print(text)
    check("register read/dump", "ERROR" not in text and "dump 0x0000 +32" in text)

# ISP controls
isp_tab = panels.IspTab(p, {"ExposureTime", "AnalogueGain", "AeEnable", "ScalerCrop", "FrameDurationLimits"}, set())
check("isp widgets", len(isp_tab.widgets) > 3, ", ".join(sorted(isp_tab.widgets)))
isp_tab.raw.setPlainText("ExposureTime=8000\nAnalogueGain=2.0")
isp_tab.apply_raw()
time.sleep(0.5)
md = p.capture_metadata()
check("isp set controls", abs(md["ExposureTime"] - 8000) < 200 and abs(md["AnalogueGain"] - 2.0) < 0.1,
      f"{isp_tab.msg.text()} -> ExposureTime {md['ExposureTime']}, AnalogueGain {md['AnalogueGain']:.2f}")
isp_tab.apply()
check("isp apply all", isp_tab.msg.text().startswith("Set"), isp_tab.msg.text())
print("Tuning:", isp_tab.tuning.text().splitlines()[:3])

# Live view: ROIs, histogram and the overlay (captured instead of drawn: no preview here)
import live  # noqa: E402

overlays = []
lv = live.LiveView(p, rate=100, set_overlay=overlays.append)
lv.histogram_enabled = True
fmt, size, bits, mode = live.raw_info(p)
lv.rois = [live.Roi("centre", size[0] // 2 - 32, size[1] // 2 - 32, 64, 64), live.Roi("corner", 0, 0, 32, 32)]
p.post_callback = lambda request: lv.process(request)
time.sleep(1)
check("live roi means", all(r.mean == r.mean and 0 < r.mean < (1 << bits) for r in lv.rois),
      ", ".join(f"{r.name} {r.mean:.1f}" for r in lv.rois))
counts, hbits = lv.histogram
check("live histogram", sum(int(c.sum()) for c in counts.values()) == size[0] * size[1],
      f"channels {sorted(counts)}, {hbits}-bit")
check("live overlay (ROIs)", bool(overlays) and overlays[-1] is not None and overlays[-1][..., 3].any(),
      f"{len(overlays)} overlays, last {None if not overlays or overlays[-1] is None else overlays[-1].shape}")
# Zoom in on 24x24 sensor pixels: the overlay must now carry pixel values
crop_limits = mode["crop_limits"]
smallest = p.camera_controls["ScalerCrop"][0]
p.set_controls({"ScalerCrop": (crop_limits[0] + 200, crop_limits[1] + 200, smallest[2], smallest[3])})
lv.rois = []
overlays.clear()
time.sleep(1)
drawn = overlays[-1] if overlays else None
check("live overlay (pixel values)", drawn is not None and drawn[..., 3].mean() > 1,
      f"{len(overlays)} overlays, {0 if drawn is None else (drawn[..., 3] > 0).mean() * 100:.1f}% of the overlay drawn")
if drawn is not None:
    from PIL import Image as _Image  # noqa: E402
    _Image.fromarray(drawn).save("/tmp/pixel_overlay.png")

# ISP statistics, raw burst, raw video (Camera/ISP Stats/Raw tabs)
import json  # noqa: E402
import tempfile  # noqa: E402

import analysis  # noqa: E402
import camera_panels  # noqa: E402
import isp_stats  # noqa: E402

p.set_controls({"ScalerCrop": p.camera_controls["ScalerCrop"][1]})
p.set_controls({"StatsOutputEnable": True})
stats = None
for _ in range(120):
    stats = isp_stats.decode(p.capture_metadata()) or stats
    if stats:
        break
check("isp statistics", stats is not None and stats.get("histogram") is not None and stats["histogram"].sum() > 0,
      "no PispStatsOutput in 120 frames" if not stats else
      f"histogram sum {stats['histogram'].sum()}, zone means {stats['zones_mean'].min():.0f}-{stats['zones_mean'].max():.0f}")
p.set_controls({"StatsOutputEnable": False})

camera_tab = camera_panels.CameraTab(p)
check("camera tab", camera_tab.findChildren(type(camera_tab.live)), f"{len(p.sensor_modes)} sensor modes")
check("tuning files", bool(camera_panels.tuning_files()), f"{len(camera_panels.tuning_files())} installed")

out_dir = tempfile.mkdtemp(prefix="picam_smoke_")
raw_tab = camera_panels.RawTab(p)
raw_tab.folder.setText(out_dir)
done = []
raw_tab.sig.done.disconnect()
raw_tab.sig.done.connect(done.append)
fmt, size, bits, _ = live.raw_info(p)
for dng in (False, True):
    done.clear()
    base = os.path.join(out_dir, f"burst_{'dng' if dng else 'tiff'}")
    raw_tab._burst(base, 5, dng, fmt, size, bits)
    app.processEvents()
    files = sorted(f for f in os.listdir(out_dir) if f.startswith(os.path.basename(base)))
    check(f"raw burst {'dng' if dng else 'tiff'}", done and not done[0].startswith("Error") and len(files) == 6,
          f"{done[0] if done else 'no result'}; files {files[:2]}...")
with open(os.path.join(out_dir, "burst_tiff_metadata.json")) as fh:
    meta = json.load(fh)
tiff0 = analysis.np.asarray(__import__("PIL.Image").Image.open(os.path.join(out_dir, meta["frames"][0]["file"])))
check("burst tiff in DN", tiff0.max() < (1 << bits) and "ExposureTime" in meta["frames"][0],
      f"max {tiff0.max()}, {len(meta['frames'])} metadata entries")

raw_tab.on_video()
time.sleep(1.0)
raw_tab.on_video()
jsons = [f for f in os.listdir(out_dir) if f.endswith(".json") and "metadata" not in f]
video = list(analysis.read_raw_video(os.path.join(out_dir, jsons[0]))) if jsons else []
check("raw video", len(video) > 20 and video[0][0].max() < (1 << bits) and video[1][1] is not None,
      f"{raw_tab.status.text()}; read back {len(video)} frames"
      + (f", {video[0][0].shape}, pts {video[0][1]}-{video[-1][1]} ms" if video else ""))

p.stop()
p.close()
print("ALL PASSED" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
