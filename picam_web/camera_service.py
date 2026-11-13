"""The camera service: owns the camera (picamera2) for the web UI and the Python API.

It runs the camera continuously, encodes the main stream to JPEG for the MJPEG preview, and keeps
the latest metadata, frame statistics, raw histogram, ROI means and ISP statistics up to date from
the per-frame callback. Analysis and register code are shared with the desktop viewer (picam_viewer).
"""

import io
import json
import subprocess
import logging
import os
import sys
import threading
import time
from concurrent.futures import CancelledError

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "picam_viewer"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analysis  # noqa: E402
import health  # noqa: E402
import isp_stats  # noqa: E402
import live  # noqa: E402
import sensor_regs  # noqa: E402

log = logging.getLogger("picam_web")

SETTINGS_FILE = os.path.expanduser("~/.config/picam_web.json")
STREAM_FPS = 30          # JPEG preview rate (the sensor may run faster)
STREAM_WIDTH = 960       # width of the preview / JPEG stream
MAX_CAPTURE_BYTES = 1 << 30   # raw frames kept in memory for one capture (the Pi has 2-8 GB)
STALL_TIMEOUT = 10.0     # s without a frame before recovering (long exposures go up to ~6.6 s)
LAUNCHER = None         # command that restarts the service (tests/fake/run_fake.py sets it)


def jsonable(value):
    """libcamera/numpy values as plain JSON types."""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, (int, float, str, bool)) or value is None:
        if isinstance(value, float) and value != value:
            return None  # NaN is not JSON
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(value)} bytes>"
    return str(value)


def metadata_json(md):
    """Request metadata as JSON, without the large ISP statistics buffers."""
    return jsonable({k: v for k, v in md.items() if k not in ("PispStatsOutput", "Bcm2835StatsOutput")})


WHITE_BALANCE = {"AwbEnable", "ColourGains"}


def load_settings():
    try:
        with open(SETTINGS_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    """Written atomically: a power cut while writing must not leave a broken settings file."""
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(settings, fh, indent=1)
    os.replace(tmp, SETTINGS_FILE)


def probe_tuning(path):
    """Try a tuning file in a throwaway process: libcamera only registers the camera if the file
    loads. Works while this service holds the camera. Returns None if fine, else the reason."""
    code = ("from picamera2 import Picamera2; import sys; "
            "sys.exit(0 if Picamera2.global_camera_info() else 3)")
    env = {**os.environ, "LIBCAMERA_RPI_TUNING_FILE": path}
    if LAUNCHER:  # simulator: the probe must find the same (simulated) picamera2
        env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    try:
        r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return "probe timed out"
    if r.returncode == 0:
        return None
    # The probe also logs that the controls are busy (this service holds the camera): not the reason
    errors = [line.split("] ", 1)[-1] for line in r.stderr.splitlines()
              if " ERROR " in line and "busy" not in line.lower()]
    return "; ".join(errors[:2]) or "the camera is not registered with it"


def restart_process():
    """Replace this process by a fresh one. Not os.execv: that keeps libcamera's open media
    device handles, and the new image then finds no camera. Under systemd, exit and let it
    restart the service; otherwise start a detached copy (it waits for the camera) and exit."""
    if os.environ.get("INVOCATION_ID"):  # running under systemd
        os._exit(3)
    args = [a for a in sys.argv[1:]]
    if "--tuning-file" in args:  # the saved setting applies, not the start option
        i = args.index("--tuning-file")
        del args[i:i + 2]
    command = LAUNCHER or [os.path.abspath(sys.argv[0])]
    subprocess.Popen([sys.executable, *command, *args], start_new_session=True,
                     close_fds=True, stdin=subprocess.DEVNULL)
    os._exit(0)


class StreamingOutput(io.BufferedIOBase):
    """Receives JPEG frames from picamera2's encoder; clients wait for the next one."""

    def __init__(self):
        self.frame = None
        self.count = 0
        self.condition = threading.Condition()

    def write(self, buf):
        with self.condition:
            self.frame = bytes(buf)
            self.count += 1
            self.condition.notify_all()
        return len(buf)

    def wait(self, last_count, timeout=2.0):
        with self.condition:
            self.condition.wait_for(lambda: self.count != last_count, timeout)
            return self.frame, self.count


class CameraService:
    def __init__(self, camera=0, tuning_file=None):
        from picamera2 import Picamera2
        self.lock = threading.RLock()
        settings = load_settings()
        self.tuning_file = tuning_file or settings.get("tuning_file")
        tuning = Picamera2.load_tuning_file(self.tuning_file) if self.tuning_file else None
        self.picam2 = Picamera2(camera, tuning=tuning)
        self.stream = StreamingOutput()
        self.frame_stats = analysis.FrameStats()
        self.live = live.LiveView(self.picam2, rate=4, set_overlay=lambda overlay: None)
        self.live.show_pixels = False
        self.live.show_rois = False    # the browser draws the ROIs: no overlay image per analysed frame
        # The histogram and the raw copy for crops are only made while a client asks for them
        # (see ON_DEMAND): analysing a full raw frame in the camera callback slows a small Pi down
        self.metadata = {}
        self.requested = {}   # controls set through set_controls: the metadata lags them by several frames
        self.isp_stats = None
        self.isp_stats_count = 0
        self.encoder = None
        self.started = time.monotonic()
        self.last_frame = 0.0
        self.health = health.Health()
        self.health.level = health.load_recovery().get("level", 0)
        self.auto_reboot = bool(settings.get("auto_reboot", False))
        health.KernelLog(self.health).start()
        # the sensor on I2C: a plugin profile, else the camera's model name
        self.sensor_info = sensor_regs.find_sensor(names=[self.picam2.camera_properties.get("Model", "")])
        self._regs = None
        modes = self.picam2.sensor_modes
        default = max(range(len(modes)), key=lambda i: (modes[i]["bit_depth"], modes[i]["size"]))
        mode = settings.get("mode", default)
        self.configure(mode if 0 <= mode < len(modes) else default)
        if "AwbEnable" in self.picam2.camera_controls:   # colour cameras start with auto white balance
            self.set_controls({"AwbEnable": True})
        if settings.get("controls"):
            try:
                self.set_controls(settings["controls"])
            except (KeyError, ValueError, RuntimeError, TypeError) as e:
                log.warning("could not restore controls: %s", e)
        threading.Thread(target=self._monitor, daemon=True).start()
        health.sd_notify("READY=1")
        interval = health.watchdog_interval()
        if interval:
            threading.Thread(target=self._systemd_watchdog, args=(interval,), daemon=True).start()

    # Camera ------------------------------------------------------------------------------
    def configure(self, mode_index):
        """(Re)start the camera in sensor mode mode_index with the JPEG preview stream."""
        from picamera2.encoders import JpegEncoder
        from picamera2.outputs import FileOutput
        with self.lock:
            mode = self.picam2.sensor_modes[mode_index]
            if self.encoder:
                try:
                    self.picam2.stop_encoder(self.encoder)
                except Exception as e:  # noqa: BLE001 - the encoder may already be gone after a failure
                    log.warning("stop_encoder: %s", e)
                self.encoder = None
            self.picam2.stop()
            w, h = mode["size"]
            sw = min(STREAM_WIDTH, w) & ~1
            sh = int(sw * h / w) & ~1
            config = self.picam2.create_video_configuration(
                main={"size": (sw, sh)},
                raw={"format": mode["unpacked"], "size": mode["size"]},
                # The video configuration caps the sensor at 30 fps; run it at the mode's
                # maximum instead (only the JPEG preview is reduced, see frame_skip_count)
                controls={"FrameDurationLimits": (int(1e6 / mode["fps"]) + 1, 1_000_000)},
                buffer_count=6)
            self.picam2.configure(config)
            self.picam2.post_callback = self._on_request
            self.picam2.start()
            self.encoder = JpegEncoder(q=80)
            skip = max(1, round(mode["fps"] / STREAM_FPS))
            if hasattr(self.encoder, "frame_skip_count"):
                self.encoder.frame_skip_count = skip
            self.picam2.start_encoder(self.encoder, FileOutput(self.stream), name="main")
            self.mode_index = mode_index
            self.frame_stats.reset()
            self.requested = {}   # a new configuration starts with the default controls
            self.started = time.monotonic()
            self.health.set("starting", f"Starting sensor mode {mode['unpacked']} {w}x{h}")

    # Health and recovery ------------------------------------------------------------------
    @property
    def error(self):
        h = self.health
        return None if h.state in ("streaming", "starting") else h.message

    def _stall_timeout(self):
        fps = self.frame_stats.expected_fps or 10
        return max(STALL_TIMEOUT, 5.0 / fps)

    def _monitor(self):
        """Background thread: detects missing frames and escalates the recovery. Never ends."""
        while True:
            time.sleep(0.5)
            try:
                self._check_frames()
            except Exception:  # noqa: BLE001 - the monitor must survive anything
                log.exception("frame monitor")

    def _check_frames(self):
        h = self.health
        if h.state in ("recovering", "failed"):
            return
        now = time.monotonic()
        if self.last_frame > self.started:
            silent = now - self.last_frame
            if silent < self._stall_timeout():
                if h.state != "streaming":
                    h.set("streaming", "Streaming")
                elif h.level and now - max(self.last_recovery_ok, self.started) > 20:
                    h.level = 0          # stable again: the incident is over
                    health.clear_recovery()
                return
            reason = f"no frames for {silent:.1f} s"
        elif now - self.started > STALL_TIMEOUT:
            reason = "no frames since the camera started"
        else:
            return
        self.recover(reason)

    last_recovery_ok = 0.0

    def _sensor_answers(self):
        try:
            self.regs.read(0x0000)
            return True
        except Exception:  # noqa: BLE001 - any I2C or lookup failure
            return False

    def recover(self, reason, level=None):
        """Escalate: 1 restart the stream, 2 reopen the camera in a fresh process, 3 failed (reboot)."""
        h = self.health
        level = level or h.level + 1
        h.level = level
        diagnosis = "" if self._sensor_answers() else " The sensor does not answer on I2C."
        if level == 1:
            h.set("recovering", f"{reason}; restarting the stream.{diagnosis}")
            log.warning("recovery 1: %s, restarting the stream", reason)
            try:
                with self.lock:
                    self.picam2.cancel_all_and_flush()  # nothing queued may hold up the stop
                    self.picam2.stop()
                    time.sleep(0.5)
                    self.picam2.start()
                    self.started = time.monotonic()
                self.last_recovery_ok = time.monotonic()
                h.set("starting", "Stream restarted, waiting for frames")
            except Exception as e:  # noqa: BLE001
                log.error("stream restart failed: %s", e)
                self.recover(f"stream restart failed ({e})", 2)
        elif level == 2:
            h.set("recovering", f"{reason}; reopening the camera.{diagnosis}")
            log.warning("recovery 2: %s, reopening the camera in a fresh process", reason)
            health.save_recovery(2)
            threading.Thread(target=self._reopen, daemon=True).start()
        else:
            msg = (f"{reason}. The camera did not recover after restarting the stream and reopening the "
                   f"camera.{diagnosis} The sensor needs a power cycle: reboot the Raspberry Pi.")
            h.set("failed", msg)
            log.error("recovery failed: %s", reason)
            if self.auto_reboot:
                h.set("failed", msg + " Rebooting automatically in 10 s.")
                threading.Timer(10, self.reboot).start()

    def _reopen(self):
        try:
            self.close()
        finally:
            time.sleep(2)  # off time: a fast close/reopen left some sensors without frames
            restart_process()

    def reset(self, action):
        """Manual recovery: 'stream', 'camera' or 'reboot'."""
        if action == "stream":
            self.recover("manual reset", 1)
        elif action == "camera":
            self.recover("manual reset", 2)
        elif action == "reboot":
            self.health.set("failed", "Rebooting the Raspberry Pi")
            threading.Timer(1, self.reboot).start()
        else:
            raise ValueError(f"unknown reset action {action}")

    def reboot(self):
        try:
            self.close()
        finally:
            health.reboot()

    def _systemd_watchdog(self, interval):
        """Tell systemd we are alive, as long as the camera lock is not stuck (a hung camera call)."""
        while True:
            if self.lock.acquire(timeout=interval):
                self.lock.release()
                health.sd_notify("WATCHDOG=1")
            time.sleep(interval)

    _callback_error_at = 0.0
    isp_stats_on = False

    def _on_request(self, request):
        """Per-frame callback (camera thread). Must never raise: that would stop the frame handling."""
        self.last_frame = time.monotonic()
        try:
            md = request.get_metadata()
            self.frame_stats.update(md)
            self.metadata = md
            # The sensor rate follows the exposure (a long exposure gives few frames a second): skip
            # frames by the rate it runs at now, not by the mode's maximum, or the preview stalls
            fps = self.frame_stats.expected_fps
            if fps and self.encoder is not None and hasattr(self.encoder, "frame_skip_count"):
                self.encoder.frame_skip_count = max(1, round(fps / STREAM_FPS))
            self.live.process(request)
            stats = isp_stats.decode(md) if self.isp_stats_on else None
            if stats:
                self.isp_stats = stats
                self.isp_stats_count += 1
        except Exception:  # noqa: BLE001
            now = time.monotonic()
            if now - self._callback_error_at > 10:  # log at most every 10 s
                self._callback_error_at = now
                log.exception("frame callback")

    def close(self):
        with self.lock:
            try:
                if self.encoder:
                    self.picam2.stop_encoder(self.encoder)
                    self.encoder = None
                self.picam2.stop()
            finally:
                self.picam2.close()

    # Information ---------------------------------------------------------------------------
    def info(self):
        with self.lock:  # not halfway through a mode switch: the configuration would be incomplete
            return self._info()

    def _info(self):
        p = self.picam2
        cfg = p.camera_config or {}
        return jsonable({
            "properties": {k: v for k, v in p.camera_properties.items() if k != "SystemDevices"},
            "sensor_modes": [{k: m[k] for k in ("format", "unpacked", "size", "bit_depth", "fps", "crop_limits",
                                                "exposure_limits") if k in m} for m in p.sensor_modes],
            "mode": self.mode_index,
            "raw": {k: cfg.get("raw", {}).get(k) for k in ("format", "size", "stride")},
            "main": {k: cfg.get("main", {}).get(k) for k in ("format", "size")},
            "is_mono": p.is_mono,
            "tuning_file": self.tuning_file,
            "sensor": str(self.sensor_info) if self.sensor_info else None,
        })

    def controls(self):
        md = self.metadata
        out = {}
        for name, (lo, hi, default) in self.picam2.camera_controls.items():
            # What was set, else what the camera reports: the metadata lags a new value by several
            # frames (seconds with long exposures) and has no AeEnable
            out[name] = {"min": lo, "max": hi, "default": default, "value": self.requested.get(name, md.get(name))}
        return jsonable(out)

    def set_controls(self, controls):
        """Set libcamera controls; lists become tuples. Raises KeyError for unknown controls."""
        clean = {}
        for name, value in controls.items():
            if name not in self.picam2.camera_controls:
                raise KeyError(f"unknown control {name}")
            clean[name] = tuple(value) if isinstance(value, list) else value
        self.picam2.set_controls(clean)
        self.requested.update(clean)
        if self.requested.get("AeEnable"):   # auto exposure chooses them again: report the camera's values
            self.requested.pop("ExposureTime", None)
            self.requested.pop("AnalogueGain", None)
        return list(clean)

    def remember(self, controls=None):
        """Store mode, tuning file and controls so the service starts with them next time."""
        settings = load_settings()
        settings["mode"] = self.mode_index
        if self.tuning_file:
            settings["tuning_file"] = self.tuning_file
        if controls is not None:
            stored = settings.get("controls", {})
            # A new white balance choice replaces the old one: libcamera would apply them all, gains last
            if WHITE_BALANCE & controls.keys():
                stored = {k: v for k, v in stored.items() if k not in WHITE_BALANCE}
            settings["controls"] = {**stored, **controls}
        save_settings(settings)

    def forget_controls(self):
        """Start with the default controls next time."""
        settings = load_settings()
        settings.pop("controls", None)
        save_settings(settings)

    # Captures ------------------------------------------------------------------------------
    def raw_info(self):
        return live.raw_info(self.picam2)

    def _capture_timeout(self):
        """How long one capture may take before the camera counts as stuck."""
        fps = self.frame_stats.expected_fps or self.frame_stats.fps or 1
        return max(STALL_TIMEOUT, 10.0 / fps)

    def capture_request(self):
        """The next completed request, or RuntimeError if no frame arrives in time (the camera is
        stalled; the monitor recovers it). The caller must release() it. Hold self.lock."""
        if self.health.state in ("recovering", "failed"):
            raise RuntimeError(f"the camera is {self.health.state}: {self.health.message}")
        timeout = self._capture_timeout()
        job = self.picam2.capture_request(wait=False)
        try:
            return self.picam2.wait(job, timeout=timeout)
        except TimeoutError:
            # The job must not stay queued: picamera2 runs its jobs in order, so a stop() (mode
            # switch, recovery) queued behind it would wait for a frame that never comes.
            self.picam2.cancel_all_and_flush()
            raise RuntimeError(f"no frame from the camera within {timeout:.0f} s; see /api/health") from None
        except CancelledError:
            raise RuntimeError("the capture was cancelled (the camera is being recovered)") from None

    def check_capture_size(self, count):
        """Refuse captures that do not fit in memory."""
        size = self.raw_info()[1]
        need = count * size[0] * size[1] * 2
        if need > MAX_CAPTURE_BYTES:
            fit = max(1, MAX_CAPTURE_BYTES // (size[0] * size[1] * 2))
            raise ValueError(f"{count} frames of {size[0]}x{size[1]} need {need / 2**20:.0f} MB; "
                             f"at most {fit} frames fit in one capture")

    def raw_frames(self, count):
        """Yield (image in DN as uint16, metadata) for count captures, one at a time (low memory)."""
        first = None
        for _ in range(count):
            with self.lock:  # one camera operation at a time (captures, mode and tuning switches, resets)
                # The format is read with the frame: a mode switch may come between two frames
                fmt, size, bits, _ = self.raw_info()
                stride = self.picam2.camera_config["raw"]["stride"]
                first = first or size
                if size != first:
                    raise ValueError("the sensor mode changed during the capture; capture again")
                request = self.capture_request()
                try:
                    buf, md = request.make_buffer("raw").copy(), request.get_metadata()
                finally:
                    request.release()
            arr = np.asarray(buf, dtype=np.uint8).reshape(size[1], stride)
            yield analysis.raw_to_image(arr, fmt, size, bits)[0].astype(np.uint16), md

    def capture_raw(self, count=1):
        """Capture count raw frames in DN. Returns (frames N x H x W uint16, [metadata], info).
        The raw buffers are copied first and converted afterwards, so the frames are consecutive."""
        buffers = []
        with self.lock:  # one camera operation at a time (captures, mode and tuning switches, resets)
            self.check_capture_size(count)
            fmt, size, bits, _ = self.raw_info()
            raw_cfg = dict(self.picam2.camera_config["raw"])
            for _ in range(count):
                request = self.capture_request()
                try:
                    buffers.append((request.make_buffer("raw").copy(), request.get_metadata()))
                finally:
                    request.release()
        frames = np.empty((count, size[1], size[0]), np.uint16)
        metas = []
        for i in range(count):
            buf, md = buffers[i]
            buffers[i] = None  # free each raw copy as soon as it is converted
            arr = np.asarray(buf, dtype=np.uint8).reshape(size[1], raw_cfg["stride"])
            frames[i] = analysis.raw_to_image(arr, fmt, size, bits)[0]
            metas.append(metadata_json(md))
        return frames, metas, {"format": fmt, "size": list(size), "bit_depth": bits}

    def capture_dng(self, path):
        """Save the next frame as DNG (picamera2's writer)."""
        with self.lock:
            request = self.capture_request()
            try:
                request.save_dng(path)
            finally:
                request.release()

    def noise(self, count=16, roi=None):
        """Noise figures of count frames. Frames are added one at a time, so any count fits in memory."""
        with self.lock:
            fmt, size, bits, _ = self.raw_info()
        if roi is not None:
            x, y, w, h = roi
            if w < 1 or h < 1 or x < 0 or y < 0 or x >= size[0] or y >= size[1]:
                raise ValueError(f"ROI {tuple(roi)} is outside the {size[0]}x{size[1]} raw frame")
        acc = analysis.NoiseAccumulator(roi)
        for img, _ in self.raw_frames(count):
            acc.add(img)
        return {**jsonable(acc.result()), "format": fmt, "size": list(size), "bit_depth": bits,
                "roi": list(roi) if roi else None}

    # Live analysis -------------------------------------------------------------------------
    ON_DEMAND = 3.0   # s the live analysis keeps running after a client asked for it

    def histogram(self):
        now = time.monotonic()
        if now >= self.live.histogram_until:   # nobody asked for a while: what is stored is old
            self.live.histogram = None
        self.live.histogram_until = now + self.ON_DEMAND
        h = self.live.histogram
        if not h:
            return {"error": self.live.error or "no histogram yet"}
        counts, bits = h
        return jsonable({"bits": bits, "channels": counts, **(self.live.stats or {})})

    def rois(self):
        """ROIs with their live means and their position on the preview (0..1)."""
        out = []
        mapping = None
        try:
            fmt, size, bits, mode = self.raw_info()
            crop = self.metadata.get("ScalerCrop")
            mapping = self.live._mapping(np.zeros((size[1], size[0])), mode, crop)
        except (ValueError, KeyError):
            pass
        for r in self.live.rois:
            item = {"name": r.name, "x": r.x, "y": r.y, "w": r.w, "h": r.h, "mean": jsonable(r.mean)}
            if mapping:
                dw, dh, to_overlay, _ = mapping
                (u0, v0), (u1, v1) = to_overlay(r.x, r.y), to_overlay(r.x + r.w, r.y + r.h)
                item["view"] = [u0 / dw, v0 / dh, u1 / dw, v1 / dh]
            out.append(item)
        return out

    MAX_CROP_PIXELS = 128 * 128

    def raw_crop(self, x, y, w, h):
        """Pixel values (DN) of a raw area of the latest analysed frame (updated 4 times a second).
        No capture: cheap enough for every pan or zoom of the viewer."""
        now = time.monotonic()
        if now >= self.live.keep_until:   # nobody asked for a while: the stored frame is old
            self.live.last_image = None
        self.live.keep_until = now + self.ON_DEMAND
        last = self.live.last_image
        if last is None:
            raise RuntimeError(self.live.error or "no analysed frame yet")
        img, bits, at = last
        height, width = img.shape
        if w < 1 or h < 1 or w * h > self.MAX_CROP_PIXELS:
            raise ValueError(f"crop {w}x{h}: 1 to {self.MAX_CROP_PIXELS} pixels")
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + w), min(height, y + h)
        if x0 >= x1 or y0 >= y1:
            raise ValueError(f"crop ({x}, {y}, {w}x{h}) is outside the {width}x{height} raw frame")
        sub = img[y0:y1, x0:x1]
        return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "bits": bits, "width": width, "height": height,
                "age_s": round(time.monotonic() - at, 3), "values": sub.ravel().tolist()}

    def view(self):
        """The raw area the preview shows: [x0, y0, x1, y1] in raw pixels (follows ScalerCrop)."""
        try:
            fmt, size, bits, mode = self.raw_info()
            crop = self.metadata.get("ScalerCrop")
            mapping = self.live._mapping(np.zeros((size[1], size[0]), np.uint8), mode, crop)
        except (ValueError, KeyError, TypeError):
            return None
        if not mapping:
            return [0, 0, size[0], size[1]]
        dw, dh, to_overlay, _ = mapping
        (u0, v0), (u1, v1) = to_overlay(0, 0), to_overlay(size[0], size[1])
        # to_overlay is linear: invert it for the preview corners (0, 0) and (dw, dh)
        sx, sy = size[0] / (u1 - u0), size[1] / (v1 - v0)
        return [round(-u0 * sx, 2), round(-v0 * sy, 2), round((dw - u0) * sx, 2), round((dh - v0) * sy, 2)]

    def set_rois(self, rois):
        """Replace the ROIs. x, y >= 0 and w, h >= 1, inside the raw frame (w, h are clipped to it)."""
        try:
            width, height = self.raw_info()[1]
        except ValueError:
            width = height = None
        new = []
        for i, r in enumerate(rois):
            roi = live.Roi(str(r.get("name") or f"ROI{i + 1}"), int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"]))
            if roi.x < 0 or roi.y < 0 or roi.w < 1 or roi.h < 1:
                raise ValueError(f"{roi.name}: x and y must be >= 0, w and h >= 1")
            if width:
                if roi.x >= width or roi.y >= height:
                    raise ValueError(f"{roi.name}: ({roi.x}, {roi.y}) is outside the {width}x{height} raw frame")
                roi.w, roi.h = min(roi.w, width - roi.x), min(roi.h, height - roi.y)
            new.append(roi)
        self.live.rois = new
        return self.rois()

    def enable_isp_stats(self, enabled):
        if "StatsOutputEnable" not in self.picam2.camera_controls:
            raise ValueError("this camera has no StatsOutputEnable control")
        self.picam2.set_controls({"StatsOutputEnable": bool(enabled)})
        self.isp_stats_on = bool(enabled)
        if not enabled:
            self.isp_stats = None
            self.isp_stats_count = 0

    def isp_statistics(self):
        s = self.isp_stats
        if not self.isp_stats_on:
            return {"enabled": False, "error": "ISP statistics are off"}
        if not s:
            return {"enabled": True, "error": "waiting for ISP statistics (the ISP does not produce them every frame)"}
        if s["platform"] != "pisp":
            return {"enabled": True, "platform": s["platform"], "error": "VC4 (Pi 4) statistics are not decoded"}
        return jsonable({"enabled": True, "platform": "pisp", "count": self.isp_stats_count,
                         "histogram": s["histogram"], "zones_mean": np.round(s["zones_mean"], 1),
                         "focus": s["focus"]})

    # Registers -----------------------------------------------------------------------------
    @property
    def regs(self):
        if self._regs is None:
            if not self.sensor_info:
                raise RuntimeError("no sensor found on an I2C bus")
            self._regs = sensor_regs.SensorRegs(self.sensor_info)
        return self._regs

    def known_registers(self):
        regs = self.sensor_info.registers if self.sensor_info else []
        return [{"name": n, "address": a, "bytes": b} for n, a, b in regs]

    def contexts(self):
        """Context controls of the driver, or {"available": False} without them."""
        c = self.regs.contexts() if self.sensor_info else None
        return {"available": False} if c is None else {"available": True, **c}

    def set_contexts(self, **values):
        return {"available": True, **self.regs.set_contexts(**values)}

    # Tuning --------------------------------------------------------------------------------
    def tuning_files(self):
        import glob
        platform = "pisp" if self.picam2.camera_properties.get("PipelineHandler", "").endswith("pisp") else "vc4"
        files = []
        for prefix in ("/usr/local/share/libcamera/ipa/rpi", "/usr/share/libcamera/ipa/rpi"):
            files += sorted(glob.glob(os.path.join(prefix, platform, "*.json")))
        return files

    def restart_with_tuning(self, path):
        """Remember the tuning file and restart this process with it (works with or without systemd).
        path None or "" goes back to libcamera's default tuning file for the sensor."""
        settings = load_settings()
        if path:
            if not os.path.isfile(path):
                raise ValueError(f"no such tuning file: {path}")
            problem = probe_tuning(path)
            if problem:
                raise ValueError(f"{os.path.basename(path)} does not load for this sensor: {problem}")
            settings["tuning_file"] = path
        else:
            settings.pop("tuning_file", None)
        save_settings(settings)

        def _restart():
            time.sleep(0.5)  # let the HTTP answer go out first
            try:
                self.close()
            finally:
                time.sleep(2)  # off time before the new process opens the camera
                restart_process()
        threading.Thread(target=_restart, daemon=True).start()
