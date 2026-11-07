"""Live ROIs and the raw histogram: define ROIs, read their means for a few seconds, get the histogram.

    python 05_rois_and_histogram.py [http://raspberrypi.local]

The ROIs also show on the web UI preview. They are removed at the end.
"""

import time

from _common import connect

cam = connect()
w, h = cam.info()["raw"]["size"]
s = min(w, h) // 8
cam.set_rois([
    ("centre", (w - s) // 2, (h - s) // 2, s, s),
    ("top-left", 0, 0, s, s),
    ("bottom-right", w - s, h - s, s, s),
])

time.sleep(0.5)  # the means are measured 4 times a second
print("ROI means [DN], 4 per second:")
for _ in range(8):
    means = {r["name"]: r["mean"] for r in cam.rois()}
    print("  " + "   ".join(f"{name} {mean:8.1f}" for name, mean in means.items() if mean is not None))
    time.sleep(0.25)

hist = cam.histogram()
if "error" in hist:
    print("histogram:", hist["error"])
else:
    print(f"\nHistogram: {hist['bits']}-bit, mean {hist['mean']:.1f}, min {hist['min']}, max {hist['max']} DN")
    for name, counts in hist["channels"].items():
        top = counts.argmax()
        bin_width = (1 << hist["bits"]) / len(counts)
        print(f"  channel {name}: {len(counts)} bins, peak at {top * bin_width:.0f}-{(top + 1) * bin_width:.0f} DN")

cam.set_rois([])
