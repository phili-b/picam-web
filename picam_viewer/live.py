"""Live raw-frame analysis on the preview: ROI rectangles with their means, pixel values
when zoomed in, and histogram data. No Qt here; the tabs in panels.py show the results.

Coordinates: ROIs are in pixels of the raw stream. A raw pixel maps to the preview through the
sensor mode's crop (crop_limits, in sensor pixels) and the current ScalerCrop (the part of the
sensor shown, set by Pan/Zoom). picamera2 stretches the overlay over the displayed image.
"""

import time
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import analysis

ROI_COLOURS = [(154, 205, 86), (0, 173, 253), (255, 170, 0), (226, 84, 255), (255, 90, 90), (255, 255, 255)]
PIXEL_VALUES_MAX = 50   # show pixel values when at most this many raw pixels span the view
HISTOGRAM_STEP = 4      # the histogram counts every 4th pixel in x and y
PIXEL_CELL_MIN = 36     # draw the overlay at a resolution that gives each pixel at least this many px


@dataclass
class Roi:
    name: str
    x: int
    y: int
    w: int
    h: int
    mean: float = float("nan")

    @property
    def rect(self):
        return (self.x, self.y, self.w, self.h)


def raw_info(picam2):
    """(stream format, (w, h), sensor bit depth, sensor mode) of the configured raw stream."""
    cfg = picam2.camera_config or {}
    raw = cfg.get("raw")
    if not raw:
        raise ValueError("the current configuration has no raw stream (switch to Still Capture)")
    size = tuple(raw["size"])
    mode = None
    for m in picam2.sensor_modes:
        if tuple(m["size"]) == size:
            mode = m
    sensor = cfg.get("sensor") or {}
    bits = sensor.get("bit_depth") or (mode or {}).get("bit_depth")
    return raw["format"], size, bits, mode


def channels(img, fmt, step=1):
    """{name: pixels} for the histogram: R/G/B for Bayer formats, one 'Y' channel otherwise.
    step > 1 takes every step-th pixel of each colour plane (a strided view: the rest is not touched)."""
    order = fmt[1:5].upper() if fmt.upper().startswith("S") else ""
    if order not in ("RGGB", "GRBG", "GBRG", "BGGR"):
        return {"Y": img[::step, ::step]}
    planes = {}
    for i, c in enumerate(order):
        plane = img[i // 2::2 * step, i % 2::2 * step]
        planes.setdefault(c, []).append(plane.ravel())
    return {c: np.concatenate(p) for c, p in planes.items()}


class LiveView:
    """Fed every request from the post callback; does its work at most `rate` times a second."""

    def __init__(self, picam2, rate=4.0, set_overlay=None):
        self.picam2 = picam2
        # The Qt preview widgets take overlays themselves (picam2.set_overlay only works for
        # previews started with picam2.start_preview)
        self.set_overlay = set_overlay or picam2.set_overlay
        self.period = 1.0 / rate
        self.rois = []
        self.show_rois = True
        self.show_pixels = True
        self.histogram_enabled = False
        self.histogram = None      # {channel: counts}, bits
        self.stats = None          # mean/min/max of the last frame
        self.keep_last = False     # keep a copy of the last analysed frame (web service: raw crops)
        # Web service: work only while a client asks for it (time.monotonic() until which it is wanted)
        self.histogram_until = 0.0
        self.keep_until = 0.0
        self.last_image = None     # (image in DN, bits, time.monotonic()) when kept
        self.error = None
        self._last = 0.0
        self._overlay_on = False
        self._font_cache = {}

    def process(self, request):
        now = time.monotonic()
        if now - self._last < self.period:
            return
        self._last = now
        histogram = self.histogram_enabled or now < self.histogram_until
        keep = self.keep_last or now < self.keep_until
        if not (self.rois or self.show_pixels or histogram or keep):
            self._clear_overlay()
            return
        try:
            fmt, size, bits, mode = raw_info(self.picam2)
            img, bits = analysis.raw_to_image(request.make_array("raw"), fmt, size, bits)
        except (ValueError, KeyError, RuntimeError) as e:
            self.error = str(e)
            self._clear_overlay()
            return
        self.error = None
        if keep:  # a copy: the request's buffer goes back to the camera
            self.last_image = (np.array(img, dtype=np.uint16), bits, now)
        for roi in self.rois:
            sub = analysis.crop(img, roi.rect)
            roi.mean = float(sub.mean()) if sub.size else float("nan")
        if histogram:
            # Counts of a strided sample (every HISTOGRAM_STEP-th pixel in x and y), scaled back to
            # the whole frame: np.histogram over 2 Mpixel takes ~50 ms, this ~1 ms
            bins = min(256, 1 << bits)
            shift = max(0, bits - 8)
            k = HISTOGRAM_STEP ** 2
            self.stats = {"mean": float(img[::HISTOGRAM_STEP, ::HISTOGRAM_STEP].mean()), "min": int(img.min()),
                          "max": int(img.max()), "bits": bits}
            self.histogram = ({c: np.bincount((p >> shift).ravel(), minlength=bins)[:bins] * k
                               for c, p in channels(img, fmt, HISTOGRAM_STEP).items()}, bits)
        crop = request.get_metadata().get("ScalerCrop")
        try:
            self._draw(img, mode, crop)
        except (RuntimeError, ValueError) as e:  # never let the frame callback raise
            self.error = f"overlay: {e}"

    # Overlay ------------------------------------------------------------------------------
    def _clear_overlay(self):
        if self._overlay_on:
            self.set_overlay(None)
            self._overlay_on = False

    def _mapping(self, img, mode, crop):
        """Return (overlay w, h, function raw (x, y) -> overlay (u, v)) or None."""
        if not crop:
            return None
        cfg = self.picam2.camera_config
        display = cfg.get("display") or "main"
        dw, dh = cfg[display]["size"]
        cx, cy, cw, ch = crop
        mx, my, mw, mh = (mode or {}).get("crop_limits") or (0, 0, img.shape[1], img.shape[0])
        sx, sy = mw / img.shape[1], mh / img.shape[0]   # sensor pixels per raw pixel

        def to_overlay(x, y):
            return ((mx + x * sx - cx) / cw * dw, (my + y * sy - cy) / ch * dh)
        return dw, dh, to_overlay, cw / sx

    def _font(self, size):
        size = int(max(8, min(32, size)))
        if size not in self._font_cache:
            try:
                self._font_cache[size] = ImageFont.load_default(size=size)
            except TypeError:  # Pillow < 10.1
                self._font_cache[size] = ImageFont.load_default()
        return self._font_cache[size]

    def _draw(self, img, mode, crop):
        mapping = self._mapping(img, mode, crop)
        draw_pixels = False
        if mapping:
            dw, dh, to_overlay, raw_pixels_across = mapping
            draw_pixels = self.show_pixels and raw_pixels_across <= PIXEL_VALUES_MAX
        if not mapping or not ((self.show_rois and self.rois) or draw_pixels):
            self._clear_overlay()
            return
        if draw_pixels:
            # picamera2 stretches the overlay over the preview, so a larger overlay gives
            # readable values even when the display stream itself is small
            k = max(1.0, PIXEL_CELL_MIN * raw_pixels_across / dw)
            dw, dh = int(dw * k), int(dh * k)
            base = to_overlay

            def to_overlay(x, y):
                u, v = base(x, y)
                return u * k, v * k
        overlay = Image.new("RGBA", (dw, dh), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)

        if draw_pixels:
            (u0, v0), (u1, v1) = to_overlay(0, 0), to_overlay(1, 1)
            cell = min(u1 - u0, v1 - v0)
            font = self._font(cell / 3)
            # raw pixels visible in the view
            x_first = max(0, int(-u0 / (u1 - u0)) - 1)
            y_first = max(0, int(-v0 / (v1 - v0)) - 1)
            x_last = min(img.shape[1], x_first + int(dw / (u1 - u0)) + 3)
            y_last = min(img.shape[0], y_first + int(dh / (v1 - v0)) + 3)
            for y in range(y_first, y_last):
                for x in range(x_first, x_last):
                    u, v = to_overlay(x + 0.5, y + 0.5)
                    if 0 <= u < dw and 0 <= v < dh:
                        text = str(int(img[y, x]))
                        d.text((u, v), text, font=font, anchor="mm", fill=(255, 255, 255, 255),
                               stroke_width=1, stroke_fill=(0, 0, 0, 255))

        if self.show_rois:
            for i, roi in enumerate(self.rois):
                colour = ROI_COLOURS[i % len(ROI_COLOURS)]
                (u0, v0), (u1, v1) = to_overlay(roi.x, roi.y), to_overlay(roi.x + roi.w, roi.y + roi.h)
                d.rectangle([u0, v0, u1, v1], outline=colour + (255,), width=2)
                label = f"{roi.name}: {roi.mean:.1f}" if roi.mean == roi.mean else roi.name
                d.text((u0 + 4, v0 + 3), label, font=self._font(14), fill=colour + (255,),
                       stroke_width=1, stroke_fill=(0, 0, 0, 255))

        self.set_overlay(np.asarray(overlay))
        self._overlay_on = True
