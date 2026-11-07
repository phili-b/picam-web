"""Set a manual exposure and gain, capture raw frames and save them.

    python 02_capture_raw.py [http://raspberrypi.local]

Writes to examples/output/: raw_frames.npz (all frames + metadata), frame.tiff (16-bit, DN),
frame.dng, preview.jpg. The frames are numpy arrays in DN (digital numbers at the sensor bit depth).
"""

import json
import os

import numpy as np

from _common import OUT_DIR, connect

EXPOSURE_US = 10000
GAIN = 1.0
FRAMES = 10

cam = connect()
cam.set_controls(AeEnable=False, ExposureTime=EXPOSURE_US, AnalogueGain=GAIN)
cam.capture_raw(2)  # let the new exposure take effect: discard two frames

frames, metadata = cam.capture_raw(FRAMES)
bits = cam.info()["sensor_modes"][cam.info()["mode"]]["bit_depth"]
print(f"{frames.shape[0]} frames of {frames.shape[2]}x{frames.shape[1]}, {bits}-bit, dtype {frames.dtype}")
print(f"mean {frames.mean():.1f} DN, min {frames.min()}, max {frames.max()} (full scale {(1 << bits) - 1})")
print(f"exposure in the metadata: {[m['ExposureTime'] for m in metadata]}")
saturated = (frames >= (1 << bits) - 1).mean() * 100
if saturated > 0.1:
    print(f"warning: {saturated:.1f} % of the pixels are saturated; lower EXPOSURE_US")

path = os.path.join(OUT_DIR, "raw_frames.npz")
np.savez_compressed(path, frames=frames, metadata=json.dumps(metadata))
print("saved", path)
print("saved", cam.save_raw(os.path.join(OUT_DIR, "frame.tiff"), "tiff"))
print("saved", cam.save_raw(os.path.join(OUT_DIR, "frame.dng"), "dng"))
cam.snapshot(os.path.join(OUT_DIR, "preview.jpg"))
print("saved", os.path.join(OUT_DIR, "preview.jpg"))

# Reading the frames back later:
with np.load(path) as z:
    again, md = z["frames"], json.loads(str(z["metadata"]))
assert (again == frames).all()

cam.set_controls(AeEnable=True)  # back to auto exposure
