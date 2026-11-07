"""Exposure sweep: mean signal and temporal noise against exposure time (linearity, photon transfer).

    python 04_exposure_sweep.py [http://raspberrypi.local]

Keep the scene and the light constant (e.g. a uniformly lit target). Writes
examples/output/exposure_sweep.csv, and exposure_sweep.png when matplotlib is installed
(pip install matplotlib).
"""

import csv
import os

import numpy as np

from _common import OUT_DIR, connect

EXPOSURES_US = np.geomspace(100, 30000, 12).round().astype(int)
FRAMES = 8
GAIN = 1.0

cam = connect()
w, h = cam.info()["raw"]["size"]
roi = (w // 4, h // 4, w // 2, h // 2)
bits = cam.info()["sensor_modes"][cam.info()["mode"]]["bit_depth"]
full = (1 << bits) - 1

rows = []
for exposure in EXPOSURES_US:
    cam.set_controls(AeEnable=False, ExposureTime=int(exposure), AnalogueGain=GAIN)
    cam.capture_raw(2)  # discard frames with the old exposure
    r = cam.noise(frames=FRAMES, roi=roi)
    actual = cam.metadata()["ExposureTime"]
    rows.append((int(exposure), actual, r["mean"], r["temporal_noise"], r["fpn"]))
    print(f"{exposure:7d} us (sensor {actual:7d}): mean {r['mean']:8.1f} DN, temporal noise {r['temporal_noise']:6.2f} DN")
    if r["mean"] > 0.95 * full:
        print("saturated, stopping")
        break
cam.set_controls(AeEnable=True)

path = os.path.join(OUT_DIR, "exposure_sweep.csv")
with open(path, "w", newline="") as fh:
    out = csv.writer(fh)
    out.writerow(["exposure_us", "exposure_us_actual", "mean_dn", "temporal_noise_dn", "fpn_dn"])
    out.writerows(rows)
print("saved", path)

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    print("matplotlib not installed: no plot")
else:
    data = np.array(rows, dtype=float)
    fig, (a, b) = plt.subplots(1, 2, figsize=(10, 4))
    a.plot(data[:, 1], data[:, 2], "o-")
    a.set_xlabel("exposure [us]")
    a.set_ylabel("mean [DN]")
    a.set_title("Linearity")
    b.loglog(data[:, 2], data[:, 3] ** 2, "o-")
    b.set_xlabel("mean [DN]")
    b.set_ylabel("temporal variance [DN²]")
    b.set_title("Photon transfer")
    fig.tight_layout()
    png = os.path.join(OUT_DIR, "exposure_sweep.png")
    fig.savefig(png, dpi=100)
    print("saved", png)
