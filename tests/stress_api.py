#!/usr/bin/env python3
"""Stability test of the web service: many clients at once for a while, then check it still streams.

    python tests/stress_api.py http://raspberrypi.local [seconds]
    python tests/stress_api.py http://127.0.0.1:8080 60        (simulator: tests/fake/run_fake.py web)

In parallel: 3 MJPEG viewers, polling like the web UI, raw captures, noise runs, register reads,
ROI updates and sensor mode switches. Reads registers only. Exit code 0 when no request failed with
a server error and the camera streams at the end. Changes the sensor mode back to the original one.
"""

import os
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from picam_client import Camera, CameraError  # noqa: E402

url = sys.argv[1] if len(sys.argv) > 1 else "http://raspberrypi.local"
duration = float(sys.argv[2]) if len(sys.argv) > 2 else 60
cam = Camera(url, timeout=60)
stop = threading.Event()
counts, errors, lock = {}, [], threading.Lock()


def count(name, error=None):
    with lock:
        counts[name] = counts.get(name, 0) + 1
        if error is not None:
            errors.append(f"{name}: {error}")


def loop(name, fn, pause):
    while not stop.is_set():
        try:
            fn()
            count(name)
        except CameraError as e:
            # Expected now and then with a mode switch running in parallel, not failures: 503 (camera
            # restarting), a capture interrupted by the switch, a ROI made for the other raw size
            expected = ("HTTP 503", "sensor mode changed", "outside the")
            count(name, None if any(x in str(e) for x in expected) else e)
        except Exception as e:  # noqa: BLE001
            count(name, repr(e))
        stop.wait(pause)


def viewer():
    while not stop.is_set():
        try:
            frames = 0
            for _ in cam.stream():
                frames += 1
                if stop.is_set() or frames >= 100:
                    break
            count("mjpeg (100 frames)")
        except Exception as e:  # noqa: BLE001
            count("mjpeg (100 frames)", repr(e))


def poll_ui():
    for path in ("/api/health", "/api/frames", "/api/rois", "/api/metadata", "/api/histogram"):
        with urllib.request.urlopen(url + path, timeout=30) as r:
            r.read()


info = cam.info()
modes = len(info["sensor_modes"])
start_mode = info["mode"]
known = cam.known_registers()
reg = known[0] if known else None
mode_i = [start_mode]


def switch_mode():
    mode_i[0] = (mode_i[0] + 1) % modes
    cam.set_mode(mode_i[0])


def set_rois():
    w, h = cam.info()["raw"]["size"]
    cam.set_rois([("A", 0, 0, w // 4, h // 4), ("B", w // 2, h // 2, w // 8, h // 8)])


jobs = [
    ("ui poll", poll_ui, 0.5),
    ("capture_raw(4)", lambda: cam.capture_raw(4), 0.5),
    ("noise(8)", lambda: cam.noise(frames=8, roi=(0, 0, 64, 64)), 1.0),
    ("snapshot", cam.snapshot, 0.3),
    ("rois", set_rois, 1.0),
]
if reg:
    jobs.append(("register read", lambda: cam.read_register(reg["address"], reg["bytes"]), 0.2))
if modes > 1:
    jobs.append(("mode switch", switch_mode, 5.0))

threads = [threading.Thread(target=viewer, daemon=True) for _ in range(3)]
threads += [threading.Thread(target=loop, args=job, daemon=True) for job in jobs]
print(f"Stressing {url} for {duration:.0f} s with {len(threads)} clients...")
for t in threads:
    t.start()
time.sleep(duration)
stop.set()
for t in threads:
    t.join(90)

if modes > 1:
    cam.set_mode(start_mode)
h = cam.wait_streaming(30)
time.sleep(2)
f1 = cam.frame_stats()["frames"]
time.sleep(1)
f2 = cam.frame_stats()["frames"]
for name, n in sorted(counts.items()):
    print(f"  {name:22s} {n}")
for e in errors[:20]:
    print("  ERROR", e)
stuck = [t.name for t in threads if t.is_alive()]
ok = not errors and not stuck and h["state"] == "streaming" and f2 > f1
print(f"{'PASS' if ok else 'FAIL'}: state {h['state']}, {f2 - f1} frames in the last second, "
      f"{len(errors)} errors, {len(stuck)} stuck clients")
sys.exit(0 if ok else 1)
