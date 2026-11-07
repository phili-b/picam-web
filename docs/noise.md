# Noise analysis

The Noise tab (web and desktop), `POST /api/noise` and `Camera.noise()` capture N raw frames
and compute the noise figures with `analysis.noise_stats` (`picam_viewer/analysis.py`). The
definitions are kept simple, with the usual component names (temporal noise, total/row/column FPN).
All values are in DN.

## Definitions

N frames of the ROI (or the full frame) form a stack. The **mean frame** is the per-pixel average over
the N frames.

| Figure | Key | Definition |
|--------|-----|------------|
| Mean | `mean` | average of the mean frame |
| Min, Max | `min`, `max` | minimum and maximum of the first frame |
| Temporal noise | `temporal_noise` | rms over the pixels of each pixel's standard deviation over the frames: sqrt(mean of the per-pixel variance, ddof = 1) |
| Total FPN | `fpn` | spatial standard deviation of the mean frame, minus the temporal noise left in an N-frame average: sqrt(var_spatial - var_temporal / N) (0 if negative) |
| Row FPN | `row_fpn` | standard deviation of the row means of the mean frame |
| Column FPN | `col_fpn` | standard deviation of the column means of the mean frame |
| Row temporal noise | `row_temporal_noise` | standard deviation of the row means of (first frame - mean frame) |
| Column temporal noise | `col_temporal_noise` | standard deviation of the column means of (first frame - mean frame) |

The result also has `frames` (N) and `pixels` (pixels in the ROI).

With one frame there are no temporal figures (NaN, shown as `-`; `null` in JSON) and the total FPN
still contains the temporal noise.

Colour sensors are analysed as one plane, with the colour channels mixed.

## Notes

- Use an unpacked raw sensor mode; packed and compressed modes are rejected.
- Set the exposure and gain by hand (auto exposure off) so all frames are taken with the same settings.
- More frames give a better estimate of the temporal noise and remove more of it from the FPN.
- An ROI is `(x, y, w, h)` in raw pixels of the current sensor mode.

## From Python

```python
from picam_client import Camera
cam = Camera("http://raspberrypi.local")
cam.set_controls(AeEnable=False, ExposureTime=5000, AnalogueGain=1.0)
print(cam.noise(frames=32, roi=(100, 100, 64, 64)))
```

Or on your own frames (for example from `capture_raw` or a raw video), with numpy only:

```python
import sys
sys.path.insert(0, "picam_viewer")
import analysis

frames, _ = cam.capture_raw(32)
print(analysis.noise_stats(frames, roi=(100, 100, 64, 64)))
```
