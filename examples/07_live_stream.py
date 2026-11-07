"""Live preview frames on the PC: save a few JPEG frames from the MJPEG stream and measure the rate.

    python 07_live_stream.py [http://raspberrypi.local]

The preview is the processed (ISP) image, reduced to at most 960 pixels wide and 30 fps. For
measurements use raw frames (02_capture_raw.py). To show the frames in a window, decode them with
Pillow (Image.open(io.BytesIO(jpeg))) or OpenCV (cv2.imdecode).
"""

import os
import time

from _common import OUT_DIR, connect

N = 30

cam = connect()
t0 = time.time()
for i, jpeg in enumerate(cam.stream()):
    if i < 3:
        path = os.path.join(OUT_DIR, f"stream_{i}.jpg")
        with open(path, "wb") as fh:
            fh.write(jpeg)
        print("saved", path)
    if i + 1 >= N:
        break
dt = time.time() - t0
print(f"{N} frames in {dt:.1f} s: {N / dt:.1f} fps over the network")
