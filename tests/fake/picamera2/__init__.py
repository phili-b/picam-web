"""A simulated picamera2, to run the web service, the desktop viewer and the tests on a PC.

Only what picam_web and picam_viewer use is implemented. The simulated sensor is a mono
camera (FAKE_CAMERA_COLOUR=1: an RGGB colour one) with two unpacked modes. Frames are a gradient
with temporal and fixed pattern noise, scaled with ExposureTime and AnalogueGain, so the noise
figures, histograms and ROI means react to the controls.

Headless (web service): frames come from a thread while the camera is started. With a Qt preview
(previews.qt.QGlPicamera2) they come from a QTimer in the GUI thread, as with the real preview,
so post_callback runs in the GUI thread.
"""

import json
import os
import threading
import time
from concurrent.futures import CancelledError

import numpy as np

__all__ = ["Picamera2", "CompletedRequest"]

COLOUR = os.environ.get("FAKE_CAMERA_COLOUR") == "1"
MODEL = os.environ.get("FAKE_CAMERA_MODEL", "fakecam")
FULL = (640, 480)
SENSOR_MODES = [
    {"format": ("SRGGB12_CSI2P" if COLOUR else "R12_CSI2P"), "unpacked": ("SRGGB12" if COLOUR else "R12"),
     "bit_depth": 12, "size": FULL, "fps": 60.0, "crop_limits": (0, 0, *FULL),
     "exposure_limits": (10, 1000000, None)},
    {"format": ("SRGGB8" if COLOUR else "R8"), "unpacked": ("SRGGB8" if COLOUR else "R8"),
     "bit_depth": 8, "size": (320, 240), "fps": 120.0, "crop_limits": (0, 0, *FULL),
     "exposure_limits": (10, 1000000, None)},
]
MAX_TICK_FPS = 30   # the simulator does not render faster than this (CPU)


class AttrDict(dict):
    """dict with attribute access, like picamera2's CameraConfiguration (config.main.size)."""

    def __getattr__(self, name):
        try:
            v = self[name]
        except KeyError:
            raise AttributeError(name) from None
        return AttrDict(v) if isinstance(v, dict) and not isinstance(v, AttrDict) else v

    def __setattr__(self, name, value):
        self[name] = value


def _stride(nbytes):
    return (nbytes + 63) & ~63


class Job:
    def __init__(self, signal_function=None):
        self.event = threading.Event()
        self.result = None
        self.cancelled = False
        self.signal_function = signal_function

    def done(self, result):
        self.result = result
        self.event.set()
        if self.signal_function:
            self.signal_function(self)

    def cancel(self):
        self.cancelled = True
        self.event.set()

    def get_result(self, timeout=None):
        if not self.event.wait(timeout):
            raise TimeoutError("capture timed out")
        if self.cancelled:
            raise CancelledError()
        return self.result


class CompletedRequest:
    def __init__(self, picam2, arrays, metadata):
        self.picam2 = picam2
        self.arrays = arrays        # stream name -> uint8 array (rows x stride) or (h, w, 4)
        self.metadata = metadata
        self.released = False

    def get_metadata(self):
        return dict(self.metadata)

    def make_buffer(self, name):
        return self.arrays[name].reshape(-1)

    def make_array(self, name):
        return self.arrays[name]

    def make_image(self, name):
        from PIL import Image
        return Image.fromarray(self.arrays[name][..., :3])

    def save(self, name, path):
        self.make_image(name).save(path)

    def save_dng(self, path, name="raw"):
        self.picam2.helpers.save_dng(self.make_buffer(name), self.metadata, self.picam2.camera_config[name], path)

    def release(self):
        self.released = True


class Helpers:
    def __init__(self, picam2):
        self.picam2 = picam2

    def save_dng(self, buffer, metadata, config, filename):
        """Not a real DNG: a 16-bit TIFF with the raw data (the tests only check that a file is written)."""
        from PIL import Image
        w, h = config["size"]
        arr = np.asarray(buffer, dtype=np.uint8).reshape(h, config["stride"])
        bits = 8 if config["format"].endswith("8") else 16
        img = arr[:, :w].astype(np.uint16) if bits == 8 else arr.view(np.uint16)[:, :w]
        Image.fromarray(img).save(filename, format="TIFF")


class _Controls:
    """picam2.controls: attribute writes set controls; also a context manager."""

    def __init__(self, picam2):
        object.__setattr__(self, "_picam2", picam2)

    def __setattr__(self, name, value):
        self._picam2.set_controls({name: value})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Picamera2:
    def __init__(self, camera_num=0, tuning=None):
        if camera_num != 0:
            raise IndexError("list index out of range")
        self.tuning = tuning
        self.post_callback = None
        self.camera_config = None
        self.started = False
        self.frozen = False   # tests: True = the sensor stops delivering frames (a stalled camera)
        self.helpers = Helpers(self)
        self._lock = threading.RLock()
        self._jobs = []
        self._encoders = []   # (encoder, output, stream name)
        self._thread = None
        self._qt = None
        self._frame = 0
        self._mode = SENSOR_MODES[0]
        self._values = {"AeEnable": True, "ExposureTime": 10000, "AnalogueGain": 1.0, "StatsOutputEnable": False,
                        "FrameDurationLimits": (int(1e6 / 30), int(1e6 / 30))}
        self._rng = np.random.default_rng(1)
        self._fpn = None
        self.still_configuration = AttrDict(self.create_still_configuration())
        self.preview_configuration = AttrDict(self.create_preview_configuration())
        self.video_configuration = AttrDict(self.create_video_configuration())

    # Class-level helpers -------------------------------------------------------------------
    @staticmethod
    def global_camera_info():
        return [{"Model": MODEL, "Location": 2, "Rotation": 0, "Id": "/base/fake", "Num": 0}]

    @staticmethod
    def load_tuning_file(path, dir=None):
        with open(path) as fh:
            return json.load(fh)

    # Properties ----------------------------------------------------------------------------
    @property
    def sensor_modes(self):
        return [dict(m) for m in SENSOR_MODES]

    @property
    def sensor_resolution(self):
        return FULL

    @property
    def is_mono(self):
        return not COLOUR

    @property
    def camera_properties(self):
        return {"Model": MODEL, "PipelineHandler": "rpi/pisp", "PixelArraySize": FULL,
                "PixelArrayActiveAreas": [(0, 0, *FULL)], "UnitCellSize": (1500, 1500),
                "ColorFilterArrangement": 0 if COLOUR else 5, "Rotation": 0, "Location": 2,
                "SystemDevices": (20749, 20750)}

    @property
    def camera_controls(self):
        crop = tuple(self._mode["crop_limits"])
        c = {
            "AeEnable": (False, True, True),
            "AeMeteringMode": (0, 3, 0),
            "AeConstraintMode": (0, 3, 0),
            "AeExposureMode": (0, 3, 0),
            "AeFlickerMode": (0, 1, 0),
            "AeFlickerPeriod": (100, 1000000, None),
            "ExposureValue": (-8.0, 8.0, 0.0),
            "ExposureTime": (10, 1000000, 20000),
            "AnalogueGain": (1.0, 16.0, None),
            "Brightness": (-1.0, 1.0, 0.0),
            "Contrast": (0.0, 32.0, 1.0),
            "Sharpness": (0.0, 16.0, 1.0),
            "NoiseReductionMode": (0, 4, 0),
            "FrameDurationLimits": (8333, 1000000, 33333),
            "ScalerCrop": ((0, 0, 64, 64), crop, crop),
            "ScalerCrops": ((0, 0, 0, 0), (65535, 65535, 65535, 65535), None),
            "StatsOutputEnable": (False, True, False),
            "HdrMode": (0, 4, 0),
            "CnnEnableInputTensor": (False, True, False),
        }
        if COLOUR:
            c.update({"AwbEnable": (False, True, None), "AwbMode": (0, 7, 0), "ColourGains": (0.0, 32.0, None),
                      "Saturation": (0.0, 32.0, 1.0), "ColourCorrectionMatrix": (-16.0, 16.0, None),
                      "ColourTemperature": (100, 100000, None)})
        return c

    @property
    def controls(self):
        return _Controls(self)

    # Configuration -------------------------------------------------------------------------
    def _config(self, use_case, main=None, lores=None, raw=None, controls=None, buffer_count=4,
                display="main", encode="main", **kwargs):
        main = {"format": "XBGR8888", "size": (640, 480), **(main or {})}
        return {"use_case": use_case, "main": main, "lores": lores,
                "raw": dict(raw) if raw is not None else {"format": self._mode["unpacked"]},
                "controls": dict(controls or {}), "buffer_count": buffer_count, "display": display,
                "encode": encode, "sensor": {}, **kwargs}

    def create_preview_configuration(self, main=None, lores=None, raw=None, controls=None, buffer_count=4, **kw):
        return self._config("preview", main, lores, raw, controls, buffer_count, **kw)

    def create_still_configuration(self, main=None, lores=None, raw=None, controls=None, buffer_count=1, **kw):
        return self._config("still", main or {"size": FULL}, lores, raw, controls, buffer_count, **kw)

    def create_video_configuration(self, main=None, lores=None, raw=None, controls=None, buffer_count=6, **kw):
        return self._config("video", main or {"size": (1280, 720)}, lores, raw, controls, buffer_count, **kw)

    def __setattr__(self, name, value):
        if name in ("still_configuration", "preview_configuration", "video_configuration") and isinstance(value, dict):
            value = AttrDict(value)
        object.__setattr__(self, name, value)

    def configure(self, config):
        if self.started:
            raise RuntimeError("Camera must be stopped before configuring")
        if isinstance(config, str):
            config = getattr(self, f"{config}_configuration")
        config = {k: (dict(v) if isinstance(v, dict) else v) for k, v in config.items()}
        raw = config.get("raw") or {}
        size = tuple(raw.get("size") or ())
        mode = next((m for m in SENSOR_MODES if tuple(m["size"]) == size), None)
        if mode is None:
            fmt = raw.get("format", "")
            mode = next((m for m in SENSOR_MODES if m["unpacked"] == fmt), SENSOR_MODES[0])
        self._mode = mode
        w, h = mode["size"]
        bpp = 1 if mode["bit_depth"] <= 8 else 2
        raw_fmt = mode["unpacked"]
        if bpp == 2:  # PiSP delivers unpacked modes as 16-bit, left-aligned
            raw_fmt = ("SRGGB16" if COLOUR else "R16")
        mw, mh = tuple(config["main"]["size"])
        config["main"].update({"format": config["main"].get("format", "XBGR8888"), "size": (mw, mh),
                               "stride": mw * 4, "framesize": mw * mh * 4})
        config["raw"] = {"format": raw_fmt, "size": (w, h), "stride": _stride(w * bpp),
                         "framesize": _stride(w * bpp) * h}
        config["sensor"] = {"bit_depth": mode["bit_depth"], "output_size": (w, h)}
        if config.get("lores"):
            lw, lh = tuple(config["lores"]["size"])
            config["lores"] = {"format": "YUV420", "size": (lw, lh), "stride": lw}
        self.camera_config = config
        self._fpn = self._rng.normal(0, 3, size=(h, w)).astype(np.float32)
        if config.get("controls"):
            self.set_controls(config["controls"])

    def stream_configuration(self, name="main"):
        return self.camera_config[name]

    def set_controls(self, controls):
        known = self.camera_controls
        for name, value in dict(controls).items():
            if name == "FrameRate":
                d = int(1e6 / value)
                self._values["FrameDurationLimits"] = (d, d)
                continue
            if name not in known:
                raise RuntimeError(f"Control {name} is not advertised by libcamera")
            self._values[name] = tuple(value) if isinstance(value, list) else value

    # Running -------------------------------------------------------------------------------
    def start(self, config=None, show_preview=False):
        if config is not None:
            self.configure(config)
        if self.camera_config is None:
            self.configure("preview")
        if self.started:
            return
        self.started = True
        if self._qt is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def cancel_all_and_flush(self):
        with self._lock:
            jobs, self._jobs = self._jobs, []
        for job in jobs:
            job.cancel()

    def stop(self):
        if not self.started:
            return
        # As in picamera2, the stop is a job that runs after the jobs queued before it: with a
        # pending capture and no frames (frozen sensor) it would wait forever
        t0 = time.monotonic()
        while self._jobs:
            if time.monotonic() - t0 > 20:
                raise RuntimeError("simulated picamera2: stop() is stuck behind a pending capture")
            time.sleep(0.05)
        self.started = False
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(2)
        self._thread = None

    def close(self):
        self.stop()

    def _period(self):
        fd = self._values.get("FrameDurationLimits") or (33333, 33333)
        fps = min(self._mode["fps"], 1e6 / max(fd[0], 1), MAX_TICK_FPS)
        return 1.0 / fps

    def _run(self):
        next_t = time.monotonic()
        while self.started:
            self.tick()
            next_t += self._period()
            time.sleep(max(0.0, next_t - time.monotonic()))

    def tick(self):
        """Produce one frame: callbacks, encoders, waiting captures."""
        if not self.started or self.camera_config is None or self.frozen:
            return
        with self._lock:
            request = self._make_request()
            jobs, self._jobs = self._jobs, []
        if self.post_callback:
            try:
                self.post_callback(request)
            except Exception:  # noqa: BLE001 - like picamera2: a failing callback does not stop the camera
                import traceback
                traceback.print_exc()
        for encoder, output, name in list(self._encoders):
            encoder._encode(request, name, output)
        if self._qt is not None:
            self._qt._show(request)
        for job in jobs:
            job.done(request)

    def _make_request(self):
        cfg = self.camera_config
        w, h = cfg["raw"]["size"]
        bits = self._mode["bit_depth"]
        top = (1 << bits) - 1
        exposure = int(self._values.get("ExposureTime") or 10000)
        gain = float(self._values.get("AnalogueGain") or 1.0)
        if self._values.get("AeEnable"):
            exposure, gain = 15000, 1.0
        x = np.linspace(0.2, 1.0, w, dtype=np.float32)
        y = np.linspace(0.6, 1.0, h, dtype=np.float32)[:, None]
        signal = (x * y) * (top * 0.5) * (exposure / 20000.0) * gain
        img = signal + 16 + self._fpn + self._rng.normal(0, 2 + 0.02 * np.sqrt(signal + 1), size=(h, w))
        img = np.clip(np.round(img), 0, top).astype(np.uint16)
        self._frame += 1
        stride = cfg["raw"]["stride"]
        raw = np.zeros((h, stride), np.uint8)
        if bits <= 8:
            raw[:, :w] = img.astype(np.uint8)
        else:
            raw[:, :2 * w] = (img << (16 - bits)).astype("<u2").view(np.uint8).reshape(h, 2 * w)
        mw, mh = cfg["main"]["size"]
        ys = (np.arange(mh) * h // mh)[:, None]
        xs = (np.arange(mw) * w // mw)[None, :]
        grey = (img[ys, xs].astype(np.float32) * (255.0 / top)).astype(np.uint8)
        main = np.empty((mh, mw, 4), np.uint8)
        main[..., 0] = main[..., 1] = main[..., 2] = grey
        main[..., 3] = 255
        arrays = {"raw": raw, "main": main}
        if cfg.get("lores"):
            lw, lh = cfg["lores"]["size"]
            arrays["lores"] = np.zeros((lh * 3 // 2, lw), np.uint8)
        fd = self._values.get("FrameDurationLimits") or (33333, 33333)
        duration = max(int(1e6 / self._mode["fps"]), int(fd[0]))
        md = {"SensorTimestamp": int(self._frame * duration * 1000), "FrameDuration": duration,
              "ExposureTime": exposure, "AnalogueGain": gain, "DigitalGain": 1.0, "AeLocked": True,
              "Lux": 400.0, "SensorBlackLevels": (4096, 4096, 4096, 4096),
              "ScalerCrop": tuple(self._values.get("ScalerCrop") or self._mode["crop_limits"]),
              "FocusFoM": 1000, "SensorTemperature": 35.0}
        if COLOUR:
            manual = self._values.get("AwbEnable") is False
            md["ColourGains"] = tuple(manual and self._values.get("ColourGains") or (1.8, 1.6))
            md["ColourTemperature"] = 5000
        if self._values.get("StatsOutputEnable") and self._frame % 2 == 0:
            md["PispStatsOutput"] = _fake_pisp_stats(img, top)
        return CompletedRequest(self, arrays, md)

    # Captures ------------------------------------------------------------------------------
    def capture_request(self, wait=None, signal_function=None, flush=None):
        if not self.started:
            raise RuntimeError("Camera is not running")
        job = Job(signal_function)
        with self._lock:
            self._jobs.append(job)
        if wait is None:
            wait = signal_function is None
        return job.get_result(10) if wait else job

    def wait(self, job, timeout=None):
        return job.get_result(timeout)

    def capture_array(self, name="main", wait=None, signal_function=None):
        request = self.capture_request()
        try:
            return request.make_array(name).copy()
        finally:
            request.release()

    def capture_file(self, path, name="main", format=None, wait=None, signal_function=None):
        request = self.capture_request()
        try:
            request.save(name, path)
        finally:
            request.release()

    # Encoders ------------------------------------------------------------------------------
    def start_encoder(self, encoder, output=None, quality=None, name=None, pts=None):
        if output is not None:
            encoder.output = output
        stream = name or self.camera_config.get("encode") or "main"
        encoder._start(encoder.output)
        self._encoders.append((encoder, encoder.output, stream))

    def stop_encoder(self, encoders=None):
        if encoders is None:
            stop = list(self._encoders)
        else:
            if not isinstance(encoders, (list, tuple, set)):
                encoders = [encoders]
            stop = [e for e in self._encoders if e[0] in encoders]
        for item in stop:
            self._encoders.remove(item)
            item[0]._stop(item[1])

    def set_overlay(self, overlay):
        pass


def _fake_pisp_stats(img, top):
    """A PispStatsOutput buffer (23200 bytes) with a real histogram and zone means."""
    h, w = img.shape
    zones = np.zeros((32 * 32, 4), "<u4")
    zy, zx = h // 32, w // 32
    means = img[:zy * 32, :zx * 32].reshape(32, zy, 32, zx).mean(axis=(1, 3)) * (65535 / top)
    zones[:, 0] = zones[:, 1] = zones[:, 2] = (means.ravel() * 100).astype("<u4")
    zones[:, 3] = 100
    hist = np.histogram(img, bins=1024, range=(0, top + 1))[0].astype("<u4")
    parts = [zones.tobytes(), np.zeros((4, 4), "<u4").tobytes(), np.zeros(512, "<u4").tobytes(), hist.tobytes(),
             np.zeros(4 * 16, np.uint8).tobytes(), (np.arange(64, dtype="<u8") * 10).tobytes(),
             np.zeros(4, "<u8").tobytes()]
    buf = b"".join(parts)
    assert len(buf) == 23200, len(buf)
    return list(buf)
