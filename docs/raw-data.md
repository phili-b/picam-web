# Raw data

All raw values are given in DN: the sensor's own code values, from 0 to 2^bits - 1 for the sensor
mode's bit depth.

## Raw formats

A sensor mode is listed with a packed `format` (for example `SRGGB12_CSI2P` or `R12_CSI2P`) and an
`unpacked` format. The web service always configures the raw stream with the unpacked format; in
the desktop viewer pick an unpacked sensor mode in Still Capture or Video.

Analysis, ROIs, histograms, noise and raw TIFFs need an unpacked raw stream. Packed (`*_CSI2P`) and
PiSP-compressed (`PISP_COMP*`) formats are rejected with "select an unpacked sensor mode".

| Platform | Unpacked raw stream | Data |
|----------|---------------------|------|
| Raspberry Pi 4 (VC4) | sensor depth, e.g. `R12`, `SRGGB10` | right-aligned, already in DN |
| Raspberry Pi 5 (PiSP) | always 16-bit, `R16` / `SRGGB16` | usually left-aligned (low bits zero) |
| any, 8-bit stream | `R8`, `SRGGB8` | 8-bit values |

## Pi 5 16-bit alignment detection

On a Pi 5 every unpacked mode arrives as 16-bit data. It is usually left-aligned, but 8-bit modes
were seen both left- and right-aligned depending on the configuration. `analysis.raw_to_image`
therefore takes the alignment from the data:

- if no pixel has any of the low `16 - bits` bits set, the frame is left-aligned and is shifted right
  by `16 - bits`;
- otherwise it is already right-aligned and kept as is.

A real, noisy right-aligned frame always has some of those low bits set. `bits` is the bit depth of
the sensor mode.

`raw_to_image(array, stream_fmt, size, sensor_bits)` takes the picamera2 raw buffer (uint8, with the
row stride), crops it to `size` (w, h) and returns `(image as uint16 in DN, bit depth)`.

`SensorBlackLevels` in the metadata are on a 16-bit scale; the desktop viewer's Camera tab also
shows them in DN.

## File formats

| Format | From | Content |
|--------|------|---------|
| npz | web Capture tab, `GET /api/capture/raw?format=npz`, `Camera.capture_raw()` | `frames`: N x H x W uint16 in DN; `metadata`: JSON string, one dict per frame; `raw`: JSON string with `format`, `size`, `bit_depth` |
| TIFF | web Capture tab, `format=tiff`, `Camera.save_raw()`, desktop Raw burst | one 16-bit grey frame in DN (Bayer mosaic as is) |
| TIFF (`raw_tiff`) | desktop Still Capture, file type `raw_tiff` | the raw stream values as delivered, cropped to the image size, without the DN conversion (on a Pi 5 usually left-aligned) |
| DNG | web Capture tab, `format=dng`, `Camera.save_raw(format="dng")`, desktop Raw burst, Still Capture `dng` | one frame, written by picamera2 |
| CSV + TIFF | desktop Noise tab **Save...** | `<name>.csv` (quantity, value), `<name>_mean.tiff` (mean frame), `<name>_frame0.tiff` (first frame) |

### Desktop raw burst

The Raw tab writes to the output folder (default `~/captures`) with the name
`<prefix>_<YYYYmmdd_HHMMSS>`:

- `<base>_0000.tiff`, `<base>_0001.tiff`, ... (16-bit, DN) or `.dng`;
- `<base>_metadata.json`: `format`, `size`, `bit_depth`, `values` (`DN` or `DNG`) and `frames`, a list
  with the file name and the metadata of each frame.

The frames are first copied to memory so they are consecutive, then saved. At high frame rates
frames can still be skipped; their `SensorTimestamp` values in the JSON show the gaps. For every
consecutive frame, use raw video.

## Raw video

**Start raw recording** in the desktop Raw tab records every frame of the raw stream, as delivered,
until **Stop raw recording**. It writes three files:

| File | Content |
|------|---------|
| `<base>.raw` | the raw frames back to back, `frame_bytes` each (stride x height, with the row padding) |
| `<base>_pts.txt` | one timestamp per frame (first number on each line; `#` lines are comments) |
| `<base>.json` | `format`, `size` [w, h], `stride`, `bit_depth`, `frame_bytes`, `pts` (name of the timestamp file) |

Read it back with `analysis.read_raw_video`, which yields `(image in DN, timestamp or None)` per frame
and applies the same conversion as `raw_to_image`:

```python
import sys
sys.path.insert(0, "/opt/picam_viewer/picam_viewer")
import numpy as np
import analysis

frames, stamps = [], []
for img, ts in analysis.read_raw_video("/home/pi/captures/raw_20260101_120000.json"):
    frames.append(img)
    stamps.append(ts)
print(len(frames), np.diff(stamps)[:5])
print(analysis.noise_stats(frames[:32]))
```

`analysis.py` needs only numpy, so this also works on a PC with a copy of the files.

## Tools

`tools/` has small helpers for raw data: `raw_capture.py` (adds several raw exposures and saves a
DNG), `convt_raw_pgm.py` and `convt_raw_tiff.py` (convert raw files with packed pixels, e.g. 12-bit,
to PGM or TIFF).
