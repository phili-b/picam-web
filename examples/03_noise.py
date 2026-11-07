"""Noise measurement: temporal noise and FPN in a ROI, computed on the Pi and on the PC.

    python 03_noise.py [http://raspberrypi.local]

The Pi computes the figures with /api/noise (only the numbers travel over the network). The same
figures can be computed on the PC from raw frames, here with numpy, to check or to extend them.
"""

import numpy as np

from _common import connect

FRAMES = 16
ROI_SIZE = 64

cam = connect()
w, h = cam.info()["raw"]["size"]
roi = ((w - ROI_SIZE) // 2, (h - ROI_SIZE) // 2, ROI_SIZE, ROI_SIZE)   # centre of the frame

cam.set_controls(AeEnable=False, ExposureTime=10000, AnalogueGain=1.0)
cam.capture_raw(2)

# 1. On the Pi
r = cam.noise(frames=FRAMES, roi=roi)
print(f"On the Pi: {r['frames']} frames, ROI {roi}, {r['bit_depth']}-bit")
for key in ("mean", "temporal_noise", "fpn", "row_fpn", "col_fpn", "row_temporal_noise", "col_temporal_noise"):
    print(f"  {key:20s} {r[key]:10.3f} DN")

# 2. On the PC, from the raw frames
frames, _ = cam.capture_raw(FRAMES)
x, y, rw, rh = roi
stack = frames[:, y:y + rh, x:x + rw].astype(np.float64)
temporal = np.sqrt(stack.var(axis=0, ddof=1).mean())
mean_frame = stack.mean(axis=0)
fpn = np.sqrt(max(0.0, mean_frame.var() - temporal ** 2 / FRAMES))
print("On the PC:")
print(f"  {'mean':20s} {stack.mean():10.3f} DN")
print(f"  {'temporal_noise':20s} {temporal:10.3f} DN")
print(f"  {'fpn':20s} {fpn:10.3f} DN")
print("(small differences: other frames were captured)")

cam.set_controls(AeEnable=True)
