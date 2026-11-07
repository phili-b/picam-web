#!/usr/bin/env python3
"""Smoke test of the Python API against a running Picam-web service, from any PC.

    python tests/client_smoke.py http://raspberrypi.local
Reads registers only; changes exposure/gain and ROIs. Exit code 0 = all checks passed.
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from picam_client import Camera, CameraError  # noqa: E402

url = sys.argv[1] if len(sys.argv) > 1 else "http://raspberrypi.local"
cam = Camera(url)
failures = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
    if not ok:
        failures.append(name)


info = cam.info()
mode = info["sensor_modes"][info["mode"]]
check("info", bool(info["properties"].get("Model")),
      f"{info['properties']['Model']}, mode {mode['unpacked']} {mode['size']} {mode['bit_depth']}-bit, version {info['version']}")
ctrls = cam.controls()
check("controls", "ExposureTime" in ctrls, f"{len(ctrls)} controls")

# Pick an exposure that does not saturate
bits = mode["bit_depth"]
exposure = 5000
while True:
    cam.set_controls(AeEnable=False, ExposureTime=exposure, AnalogueGain=1.0)
    time.sleep(0.5)
    frames, md = cam.capture_raw(1)
    if frames.max() < 0.8 * (1 << bits) or exposure <= 50:
        break
    exposure //= 2
md = cam.metadata()
check("set controls", abs(md["ExposureTime"] - exposure) < 0.05 * exposure + 20,
      f"asked {exposure} us, metadata {md['ExposureTime']} us, gain {md['AnalogueGain']:.2f}")

t0 = time.time()
frames, metas = cam.capture_raw(8)
dt = time.time() - t0
check("capture_raw", frames.shape[0] == 8 and frames.dtype.name == "uint16" and frames.max() < (1 << bits)
      and "SensorTimestamp" in metas[0],
      f"{frames.shape} {frames.dtype}, max {frames.max()}, {frames.nbytes / 1e6:.1f} MB in {dt:.1f} s")

n = cam.noise(frames=8, roi=(100, 100, 64, 64))
check("noise", n["pixels"] == 4096 and n["temporal_noise"] is not None and n["temporal_noise"] > 0,
      f"mean {n['mean']:.1f} DN, temporal {n['temporal_noise']:.2f}, FPN {n['fpn']:.2f}")

h = cam.histogram()
check("histogram", "channels" in h and sum(int(c.sum()) for c in h["channels"].values()) > 0,
      f"{h.get('bits')}-bit, channels {sorted(h.get('channels', {}))}")

cam.set_rois([("centre", 250, 350, 64, 64), ("corner", 0, 0, 32, 32)])
time.sleep(1)
r = cam.rois()
check("rois", len(r) == 2 and all(x["mean"] is not None for x in r) and "view" in r[0],
      ", ".join(f"{x['name']} {x['mean']:.1f} at {[round(v, 2) for v in x.get('view', [])]}" for x in r))

f = cam.frame_stats()
check("frames", f["fps"] > 0, f"{f['fps']} fps, {f['dropped']} dropped")

known = cam.known_registers()
reg = next((k for k in known if k["name"] == "EXP_TIME_L"), None)
try:
    value = cam.read_register(reg["address"], reg["bytes"]) if reg else cam.read_register(0)
    dump = cam.dump_registers(0, 16)
    check("registers", len(dump) == 16, f"{len(known)} known, EXP_TIME_L = {value}")
except CameraError as e:
    check("registers", False, str(e))

s = cam.isp_stats(enable=True)
for _ in range(20):
    if "histogram" in s:
        break
    time.sleep(0.3)
    s = cam.isp_stats()
cam.isp_stats(enable=False)
check("isp stats", "histogram" in s, f"{s.get('count')} frames, zones {s['zones_mean'].shape}" if "histogram" in s else s)

with tempfile.TemporaryDirectory() as d:
    for fmt in ("tiff", "dng"):
        path = cam.save_raw(os.path.join(d, f"frame.{fmt}"), format=fmt)
        check(f"save_raw {fmt}", os.path.getsize(path) > 100_000, f"{os.path.getsize(path) / 1e6:.2f} MB")
    jpg = cam.snapshot(os.path.join(d, "snap.jpg"))
    check("snapshot", jpg[:2] == b"\xff\xd8", f"{len(jpg) / 1e3:.0f} kB")

t0, count = time.time(), 0
for frame in cam.stream():
    count += 1
    if time.time() - t0 > 2:
        break
check("mjpeg stream", count > 20, f"{count / (time.time() - t0):.1f} fps")

cam.set_rois([])
cam.set_controls(AeEnable=True)
print("ALL PASSED" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
