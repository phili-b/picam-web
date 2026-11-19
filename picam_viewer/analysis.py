"""Raw image noise analysis and frame statistics (numpy only, no camera or Qt).

Kept simple, with the usual component names, all in DN:
  mean              average signal of the frames
  temporal noise    rms over the pixels of each pixel's std over the frames
  total FPN         spatial std of the mean frame, minus the temporal noise
                    left in an N-frame average: sqrt(var_spatial - var_temporal / N)
  row / column FPN  std of the row (column) means of the mean frame
  row / column      std of the row (column) means of one frame minus the mean
  temporal noise    frame
Colour sensors are analysed as one plane (colour channels mixed).
"""

import math
import time
from dataclasses import dataclass, field

import numpy as np


def raw_to_image(array, stream_fmt, size, sensor_bits=None):
    """Convert a picamera2 'raw' capture (uint8, with stride) to a 2D uint16 image in DN.

    stream_fmt is the raw stream format, size (w, h), sensor_bits the bit depth
    of the sensor mode (picam2.sensor_modes[i]['bit_depth']).

    On a Raspberry Pi 5 (PiSP) every unpacked mode arrives as a 16-bit stream
    ('R16' / 'SRGGB16'). The data is usually left-aligned (low bits zero), but
    8-bit modes were seen both left- and right-aligned depending on the
    configuration, so the alignment is taken from the data: if no pixel has
    any of the low 16 - bits bits set, the frame is shifted back. (A real,
    noisy right-aligned frame always has some of those bits set.) On a Pi 4
    (VC4) the stream keeps the sensor depth ('R12', 'SRGGB10'), right-aligned.
    Returns (image, bit_depth).
    """
    w, h = size
    fmt = stream_fmt.upper()
    if fmt.endswith("_CSI2P") or "PISP_COMP" in fmt:
        raise ValueError(f"raw format {stream_fmt} is packed or compressed; select an unpacked sensor mode")
    stream_bits = bit_depth(fmt)
    bits = sensor_bits or stream_bits
    if stream_bits <= 8:
        return np.asarray(array, dtype=np.uint8)[:h, :w].astype(np.uint16), bits
    img = np.asarray(array).view(np.uint16)[:h, :w]
    if stream_bits == 16 and bits < 16:
        low = (1 << (16 - bits)) - 1
        if not np.any(img & low):
            img = img >> (16 - bits)
    return img, bits


def bit_depth(fmt):
    digits = "".join(c for c in fmt if c.isdigit())
    return int(digits) if digits else 8


def crop(img, roi):
    """roi = (x, y, w, h) in pixels, None for the full image."""
    if roi is None:
        return img
    x, y, w, h = (int(v) for v in roi)
    x, y = max(0, x), max(0, y)
    return img[y:y + max(1, h), x:x + max(1, w)]


def noise_stats(frames, roi=None):
    """Noise figures of a stack of frames (list or array, N x H x W) in the ROI."""
    acc = NoiseAccumulator(roi)
    for f in frames:
        acc.add(f)
    return acc.result()


class NoiseAccumulator:
    """noise_stats one frame at a time: memory for three ROI-sized float64 planes, whatever the
    number of frames. The temporal variance is accumulated with Welford's method (exact, also
    for large signals)."""

    def __init__(self, roi=None):
        self.roi = roi
        self.n = 0
        self.mean = self.m2 = self.first = None

    def add(self, frame):
        f = crop(np.asarray(frame), self.roi).astype(np.float64)
        if self.n == 0:
            self.first = f
            self.mean = f.copy()
            self.m2 = np.zeros_like(f)
            self.n = 1
            return
        if f.shape != self.mean.shape:
            raise ValueError(f"frame {self.n + 1} is {f.shape[1]}x{f.shape[0]}, the first was "
                             f"{self.mean.shape[1]}x{self.mean.shape[0]}")
        self.n += 1
        delta = f - self.mean
        self.mean += delta / self.n
        self.m2 += delta * (f - self.mean)

    def result(self):
        n = self.n
        if n == 0:
            raise ValueError("no frames")
        mean_frame = self.mean
        res = {
            "frames": n,
            "pixels": int(mean_frame.size),
            "mean": float(mean_frame.mean()),
            "min": float(self.first.min()),
            "max": float(self.first.max()),
            "row_fpn": float(mean_frame.mean(axis=1).std()),
            "col_fpn": float(mean_frame.mean(axis=0).std()),
        }
        spatial_var = float(mean_frame.var())
        if n >= 2:
            temporal_var = float((self.m2 / (n - 1)).mean())
            residual = self.first - mean_frame
            res["temporal_noise"] = math.sqrt(temporal_var)
            res["fpn"] = math.sqrt(max(0.0, spatial_var - temporal_var / n))
            res["row_temporal_noise"] = float(residual.mean(axis=1).std())
            res["col_temporal_noise"] = float(residual.mean(axis=0).std())
        else:
            # One frame: no temporal figures, and the FPN still contains the temporal noise
            res["temporal_noise"] = res["row_temporal_noise"] = res["col_temporal_noise"] = float("nan")
            res["fpn"] = math.sqrt(spatial_var)
        return res


def histogram(img, bits, bins=256):
    """Histogram over the full code range; returns (counts, edges)."""
    top = (1 << bits) if bits > 0 else 256
    return np.histogram(img, bins=min(bins, top), range=(0, top))


@dataclass
class FrameStats:
    """Frame counter, fps and dropped frames from libcamera request metadata.

    Drops are detected from gaps in SensorTimestamp larger than 1.5 frame
    durations; each gap counts round(gap / frame duration) - 1 dropped frames.
    """

    window_s: float = 1.0
    frames: int = 0
    dropped: int = 0
    max_gap_ms: float = 0.0
    last_gap_ms: float = 0.0
    frame_duration_us: float = 0.0
    started: float = field(default_factory=time.monotonic)
    _last_ts: int = None
    _times: list = field(default_factory=list)

    def reset(self):
        self.frames = self.dropped = 0
        self.max_gap_ms = self.last_gap_ms = 0.0
        self._last_ts = None
        self._times = []
        self.started = time.monotonic()

    def update(self, metadata):
        ts = metadata.get("SensorTimestamp")  # ns
        self.frame_duration_us = float(metadata.get("FrameDuration", self.frame_duration_us) or 0)
        self.frames += 1
        if ts is None:
            return
        if self._last_ts is not None and ts > self._last_ts:
            gap_ns = ts - self._last_ts
            self.last_gap_ms = gap_ns / 1e6
            self.max_gap_ms = max(self.max_gap_ms, self.last_gap_ms)
            if self.frame_duration_us > 0:
                expected_ns = self.frame_duration_us * 1e3
                if gap_ns > 1.5 * expected_ns:
                    self.dropped += int(round(gap_ns / expected_ns)) - 1
        self._last_ts = ts
        self._times.append(ts)
        cutoff = ts - int(self.window_s * 1e9)
        while self._times and self._times[0] < cutoff:
            self._times.pop(0)

    @property
    def fps(self):
        """Measured frame rate over the last window."""
        if len(self._times) < 2:
            return 0.0
        span = (self._times[-1] - self._times[0]) / 1e9
        return (len(self._times) - 1) / span if span > 0 else 0.0

    @property
    def expected_fps(self):
        return 1e6 / self.frame_duration_us if self.frame_duration_us > 0 else 0.0


def read_raw_video(json_path):
    """Read a raw video recorded by the Raw tab. Yields (image in DN, timestamp or None) per frame.

    json_path is the <prefix>.json written next to <prefix>.raw and <prefix>_pts.txt.
    """
    import json
    import os
    with open(json_path) as fh:
        info = json.load(fh)
    base = os.path.splitext(json_path)[0]
    stamps = []
    pts = os.path.join(os.path.dirname(json_path), info.get("pts", "")) if info.get("pts") else None
    if pts and os.path.isfile(pts):
        with open(pts) as fh:
            stamps = [float(line.split()[0]) for line in fh if line.strip() and not line.startswith("#")]
    w, h = info["size"]
    stride, frame_bytes = info["stride"], info["frame_bytes"]
    with open(base + ".raw", "rb") as fh:
        i = 0
        while True:
            buf = fh.read(frame_bytes)
            if len(buf) < frame_bytes:
                return
            arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, stride)
            img, _ = raw_to_image(arr, info["format"], (w, h), info.get("bit_depth"))
            yield img, (stamps[i] if i < len(stamps) else None)
            i += 1
