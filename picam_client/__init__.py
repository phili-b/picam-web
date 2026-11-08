"""Python API for a Raspberry Pi running the Picam-web service (picam_web).

Works from any PC that can reach the Pi (USB-C gadget, Ethernet or Wi-Fi). Needs only numpy.

    from picam_client import Camera
    cam = Camera("http://raspberrypi.local")
    cam.set_controls(AeEnable=False, ExposureTime=5000, AnalogueGain=1.0)
    frames, metadata = cam.capture_raw(16)          # N x H x W uint16 in DN
    print(cam.noise(frames=16, roi=(100, 100, 64, 64)))
    print(hex(cam.read_register(0x000E, nbytes=4)))

All endpoints are documented at http://<pi>/docs.
"""

import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np

__all__ = ["Camera", "CameraError"]
__version__ = "1.1.1"


class CameraError(RuntimeError):
    """The service answered with an error (message from the server)."""


class Camera:
    def __init__(self, url="http://raspberrypi.local", timeout=30):
        self.url = url.rstrip("/")
        self.timeout = timeout

    # HTTP --------------------------------------------------------------------------------------
    def _request(self, method, path, query=None, body=None, raw=False, timeout=None):
        url = self.url + path
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        data, headers = None, {}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                content = r.read()
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get("detail", e.reason)
            except ValueError:
                detail = e.reason
            if isinstance(detail, list):  # invalid parameters: [{"loc": [...], "msg": ...}]
                detail = "; ".join(f"{'.'.join(map(str, d.get('loc', [])[1:]))}: {d.get('msg')}" for d in detail)
            raise CameraError(f"{method} {path}: {detail} (HTTP {e.code})") from None
        return content if raw else json.loads(content)

    def _get(self, path, **query):
        return self._request("GET", path, query)

    def _post(self, path, body=None, **query):
        return self._request("POST", path, query, body)

    # Camera ------------------------------------------------------------------------------------
    def info(self):
        """Camera properties, sensor modes and the current configuration."""
        return self._get("/api/info")

    def controls(self):
        """{name: {min, max, default, value}} for every libcamera control."""
        return self._get("/api/controls")

    def set_controls(self, controls=None, remember=False, **kwargs):
        """Set libcamera controls: set_controls(ExposureTime=5000) or set_controls({...}).
        remember=True: the service also starts with them after a restart (merged with earlier ones)."""
        values = {**(controls or {}), **kwargs}
        values = {k: list(v) if isinstance(v, tuple) else v for k, v in values.items()}
        return self._post("/api/controls", values, remember=str(bool(remember)).lower())

    def forget_controls(self):
        """Forget the remembered controls: the service starts with the defaults after a restart."""
        return self._request("DELETE", "/api/controls/remembered")

    def metadata(self):
        """Metadata of the latest frame (ExposureTime, AnalogueGain, SensorTimestamp, ...)."""
        return self._get("/api/metadata")

    def set_mode(self, index):
        """Switch to sensor mode `index` (see info()['sensor_modes']). ROIs outside the new raw
        size are not moved; check rois() afterwards."""
        return self._post("/api/mode", {"index": index})

    def health(self):
        """Service state: 'state' (starting/streaming/stalled/recovering/failed), 'message',
        'recovery_level', 'history', 'kernel' (recent kernel warnings), 'auto_reboot'."""
        return self._get("/api/health")

    def reset(self, action="stream", wait=True, timeout=60):
        """Manual recovery: 'stream' (restart the stream), 'camera' (reopen it in a new service
        process) or 'reboot' (the Pi). wait=True: return once the camera streams again."""
        before = self._instance()
        self._post("/api/reset", {"action": action})
        if not wait or action == "reboot":
            return None
        if action == "camera":
            return self.wait_restarted(before, timeout)
        time.sleep(1)
        return self.wait_streaming(timeout)

    def _instance(self):
        try:
            return self.health().get("instance")
        except (OSError, CameraError):
            return None

    def wait_restarted(self, old_instance, timeout=60):
        """Wait until the service runs as a new process (after a camera reset or a tuning file
        switch) and streams again; returns the health dict."""
        t0 = time.time()
        while True:
            try:
                h = self.health()
                if h.get("instance") != old_instance and h["state"] in ("streaming", "failed"):
                    return h
            except (OSError, CameraError):
                pass
            if time.time() - t0 > timeout:
                raise CameraError(f"the service did not restart within {timeout} s")
            time.sleep(1)

    def set_auto_reboot(self, enabled):
        """Reboot the Pi automatically when the camera cannot be recovered."""
        return self._post("/api/auto_reboot", {"enabled": bool(enabled)})

    def wait_streaming(self, timeout=60):
        """Wait until the service streams again (after a reset); returns the health dict."""
        t0 = time.time()
        while True:
            try:
                h = self.health()
                if h["state"] == "streaming" or h["state"] == "failed" or time.time() - t0 > timeout:
                    return h
            except (OSError, CameraError):
                if time.time() - t0 > timeout:
                    raise
            time.sleep(1)

    def frame_stats(self, reset=False):
        """Frames received, measured/expected fps and dropped frames."""
        return self._post("/api/frames/reset") if reset else self._get("/api/frames")

    # Captures ----------------------------------------------------------------------------------
    def capture_raw(self, count=1):
        """Capture `count` raw frames. Returns (frames N x H x W uint16 in DN, [metadata per frame])."""
        content = self._request("GET", "/api/capture/raw", {"count": count, "format": "npz"}, raw=True,
                                timeout=max(self.timeout, 10 + count))
        with np.load(io.BytesIO(content)) as z:
            return z["frames"], json.loads(str(z["metadata"]))

    def save_raw(self, path, format="tiff"):
        """Save one raw frame as 'tiff' (16-bit, DN) or 'dng' to `path`."""
        content = self._request("GET", "/api/capture/raw", {"format": format}, raw=True)
        with open(path, "wb") as fh:
            fh.write(content)
        return path

    def snapshot(self, path=None):
        """Latest preview frame as JPEG bytes (and saved to `path` if given)."""
        content = self._request("GET", "/api/snapshot.jpg", raw=True)
        if path:
            with open(path, "wb") as fh:
                fh.write(content)
        return content

    # Analysis ----------------------------------------------------------------------------------
    def noise(self, frames=16, roi=None):
        """Capture `frames` raw frames on the Pi and return the noise figures in DN.
        roi = (x, y, w, h) in raw pixels, None for the full frame."""
        return self._post("/api/noise", {"frames": frames, "roi": list(roi) if roi else None})

    def histogram(self):
        """Live raw histogram: {'bits', 'channels': {name: counts}, 'mean', 'min', 'max'}."""
        h = self._get("/api/histogram")
        if "channels" in h:
            h["channels"] = {k: np.asarray(v) for k, v in h["channels"].items()}
        return h

    def rois(self):
        """ROIs with their live means."""
        return self._get("/api/rois")

    def set_rois(self, rois):
        """Replace the ROIs: [(name, x, y, w, h), ...] or [{'name', 'x', 'y', 'w', 'h'}, ...]."""
        items = [r if isinstance(r, dict) else dict(zip(("name", "x", "y", "w", "h"), r)) for r in rois]
        return self._request("PUT", "/api/rois", body=items)

    def isp_stats(self, enable=None):
        """ISP statistics (AGC histogram, 32x32 zone means, 8x8 focus). enable=True/False switches them."""
        if enable is not None:
            self._post("/api/isp_stats/enable", {"enabled": bool(enable)})
            if not enable:
                return None
        s = self._get("/api/isp_stats")
        for k in ("histogram", "zones_mean", "focus"):
            if k in s:
                s[k] = np.asarray(s[k])
        return s

    # Registers ---------------------------------------------------------------------------------
    def known_registers(self):
        """Named registers of the sensor, from the driver: [{'name', 'address', 'bytes'}]."""
        return self._get("/api/registers/known")["registers"]

    def read_register(self, address, nbytes=1, bank=None, context=None):
        return self._get(f"/api/registers/{int(address)}", nbytes=nbytes, bank=bank, context=context)["value"]

    def write_register(self, address, value, nbytes=1, bank=None, context=None):
        """Write a register, through the driver's register controls when it has them, else over I2C.
        The driver does not know about the value and may overwrite it (mode switch, exposure change).
        Banked sensors: bank 0 or 1; context 0.. (A, B, ...) for bank 1 registers."""
        return self._request("PUT", f"/api/registers/{int(address)}",
                             body={"value": int(value), "nbytes": nbytes, "bank": bank, "context": context})

    def dump_registers(self, start, count=64, bank=None, context=None):
        """[(address, value)] of `count` consecutive 8-bit registers."""
        d = self._get("/api/registers/dump", start=int(start), count=count, bank=bank, context=context)
        return [(x["address"], x["value"]) for x in d]

    # Contexts (drivers with context controls) ---------------------------------------------------------
    def contexts(self):
        """The driver's context controls: {'available', 'contexts' ("AB" / "ABCD"), 'context' (the
        one to switch to), 'current' (in use; None when not streaming), 'auto_switch',
        'auto_switch_to', 'controls_context' ("all" or the context exposure and frame time go to)}.
        {'available': False} for sensors or drivers without them."""
        return self._get("/api/sensor/contexts")

    def set_contexts(self, context=None, auto_switch=None, auto_switch_to=None, controls_context=None):
        """Set context controls by name ("A", "B", ...; controls_context also "all"); None: unchanged.

            cam.set_controls(AeEnable=False, ExposureTime=10000)   # all contexts
            cam.set_contexts(controls_context="B")
            cam.set_controls(ExposureTime=2000)                     # context B only
            cam.set_contexts(controls_context="A", context="B")     # use B; later changes go to A
        """
        body = {k: v for k, v in dict(context=context, auto_switch=auto_switch, auto_switch_to=auto_switch_to,
                                      controls_context=controls_context).items() if v is not None}
        return self._request("PUT", "/api/sensor/contexts", body=body)

    # Tuning ------------------------------------------------------------------------------------
    def tuning(self):
        return self._get("/api/tuning")

    def set_tuning_file(self, path, wait=True, timeout=60):
        """Restart the service with another tuning file; path None = the default one for the sensor.
        wait=True: return once the restarted service streams (takes a few seconds)."""
        r = self._post("/api/tuning", {"path": path})
        return self.wait_restarted(r["instance"], timeout) if wait else r

    # Stream ------------------------------------------------------------------------------------
    def stream(self):
        """Yield JPEG frames of the live MJPEG preview."""
        req = urllib.request.Request(self.url + "/stream.mjpg")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            buf = b""
            while True:
                chunk = r.read(65536)
                if not chunk:
                    return
                buf += chunk
                while True:
                    start = buf.find(b"\xff\xd8")
                    end = buf.find(b"\xff\xd9", start + 2)
                    if start < 0 or end < 0:
                        break
                    yield buf[start:end + 2]
                    buf = buf[end + 2:]
