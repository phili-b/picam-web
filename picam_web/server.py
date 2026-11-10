#!/usr/bin/python3
"""Web viewer and HTTP API for Raspberry Pi cameras (FastAPI).

Run:  python3 picam_web/server.py [--port 80] [--host 0.0.0.0] [--camera 0] [--tuning-file FILE]
Browser UI at http://<pi>/ (over the USB-C gadget: http://raspberrypi.local/), API docs at /docs.
"""

import argparse
import json
import logging
import os
import sys
import tempfile
import threading
import time

import numpy as np
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from starlette.background import BackgroundTask

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import camera_service  # noqa: E402
import camera_overlay  # noqa: E402
import health  # noqa: E402

VERSION = "1.2.1"
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
# Changes on every start: the UI and the Python client use it to see that the service restarted
INSTANCE = f"{os.getpid()}-{int(time.time())}"
log = logging.getLogger("picam_web")
service: camera_service.CameraService = None

app = FastAPI(title="Picam-web API", version=VERSION,
              description="Live view, controls, raw capture, noise, registers and ISP statistics of a "
                          "Raspberry Pi camera. The Python client is picam_client.Camera.")


def _bad(e):
    raise HTTPException(status_code=400, detail=str(e))


def _unavailable(e):
    """The camera does not deliver frames (stalled, recovering or failed): 503, not 400."""
    raise HTTPException(status_code=503, detail=str(e))


def _download(path, media_type, filename):
    """Send a temporary file and delete it afterwards (large captures do not stay in memory)."""
    return FileResponse(path, media_type=media_type, filename=filename,
                        background=BackgroundTask(lambda: os.path.exists(path) and os.unlink(path)))


def _tempfile(suffix):
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="picam_")
    os.close(fd)
    return path


# Pages and stream ----------------------------------------------------------------------------
# The web UI (web/, built into web/dist with `npm run build`). Without a build, / shows the classic UI.
WEB_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web", "dist")


@app.get("/", include_in_schema=False)
def index():
    page = os.path.join(WEB_DIST, "index.html")
    if not os.path.isfile(page):
        page = os.path.join(STATIC, "index.html")
    return FileResponse(page, headers={"Cache-Control": "no-cache"})


@app.get("/classic", include_in_schema=False)
def classic():
    """The previous, plain JavaScript UI (picam_web/static), while the new one is being tried out."""
    return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-cache"})


@app.get("/stream.mjpg", summary="Live preview (MJPEG)")
def stream():
    def frames():
        count = -1
        while True:
            frame, new = service.stream.wait(count)
            if frame is None or new == count:
                continue  # no new frame within 2 s (camera stalled): keep the connection open
            count = new
            yield (b"--FRAME\r\nContent-Type: image/jpeg\r\nContent-Length: "
                   + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=FRAME",
                             headers={"Cache-Control": "no-store"})


@app.get("/api/snapshot.jpg", summary="Latest preview frame (JPEG)")
def snapshot():
    frame, _ = service.stream.wait(service.stream.count - 1, timeout=0.5)
    if frame is None:
        raise HTTPException(503, "no frame yet")
    return Response(frame, media_type="image/jpeg",
                    headers={"Content-Disposition": "attachment; filename=snapshot.jpg"})


# Camera --------------------------------------------------------------------------------------
@app.get("/api/info", summary="Camera properties, sensor modes, current configuration")
def info():
    return {**service.info(), "version": VERSION, "instance": INSTANCE}


@app.get("/api/controls", summary="All libcamera controls with range, default and current value")
def controls():
    return service.controls()


@app.post("/api/controls", summary="Set libcamera controls, e.g. {\"ExposureTime\": 10000}. "
                                   "remember=true: also use them after a restart")
def set_controls(values: dict = Body(...), remember: bool = False):
    try:
        names = service.set_controls(values)
    except (KeyError, ValueError, TypeError, RuntimeError) as e:
        _bad(e)
    if remember:
        service.remember(values)
    return {"set": names, "remembered": remember}


@app.delete("/api/controls/remembered", summary="Forget the remembered controls (defaults after a restart)")
def forget_controls():
    service.forget_controls()
    return {"remembered": {}}


@app.get("/api/metadata", summary="Metadata of the latest frame")
def metadata():
    return camera_service.metadata_json(service.metadata)


@app.post("/api/mode", summary="Switch sensor mode (index into /api/info sensor_modes)")
def set_mode(index: int = Body(..., embed=True)):
    if not 0 <= index < len(service.picam2.sensor_modes):
        _bad(f"mode index {index} out of range 0-{len(service.picam2.sensor_modes) - 1}")
    try:
        service.configure(index)
    except Exception as e:  # noqa: BLE001 - libcamera errors: report them, the monitor recovers the camera
        log.exception("mode switch failed")
        _unavailable(f"switching to mode {index} failed: {e}")
    service.remember()
    return {"mode": index, "rois": service.rois()}


@app.get("/api/frames", summary="Frame counter, measured/expected fps, dropped frames, the raw area the "
                                "preview shows (view = [x0, y0, x1, y1] in raw pixels)")
def frames():
    s = service.frame_stats
    return {"error": service.error, "frames": s.frames, "dropped": s.dropped, "fps": round(s.fps, 2),
            "expected_fps": round(s.expected_fps, 2), "last_gap_ms": round(s.last_gap_ms, 3),
            "max_gap_ms": round(s.max_gap_ms, 3), "view": service.view()}


@app.post("/api/frames/reset", summary="Reset the frame counters")
def frames_reset():
    service.frame_stats.reset()
    return frames()


# Health and recovery -------------------------------------------------------------------------
@app.get("/api/health", summary="Service state (starting/streaming/recovering/failed), recovery history, "
                                "kernel warnings")
def get_health():
    return {**service.health.as_dict(), "auto_reboot": service.auto_reboot, "instance": INSTANCE}


@app.post("/api/reset", summary="Manual recovery: action = stream | camera | reboot")
def reset(action: str = Body(..., embed=True)):
    try:
        service.reset(action)
    except ValueError as e:
        _bad(e)
    return JSONResponse({"action": action}, status_code=202)


@app.post("/api/auto_reboot", summary="Reboot automatically when the camera cannot be recovered")
def set_auto_reboot(enabled: bool = Body(..., embed=True)):
    service.auto_reboot = enabled
    settings = camera_service.load_settings()
    settings["auto_reboot"] = enabled
    camera_service.save_settings(settings)
    return {"auto_reboot": enabled}


def camera_model_hint():
    """The camera model in config.txt and how to change it: a wrong model is the usual reason the
    camera cannot be opened."""
    retry = "Otherwise reboot the Raspberry Pi (power-cycles the sensor) or retry."
    try:
        status = camera_overlay.status()
    except RuntimeError:
        status = {"available": False}
    if not status["available"]:
        return "Reboot the Raspberry Pi (power-cycles the sensor) or retry."
    cur = status["current"]
    if cur["overlay"]:
        loaded = f"The camera model set is {cur['overlay']} on {cur['port'].upper()}" + (" (mono)" if cur["mono"] else "")
    else:
        loaded = "No camera model is set (the Pi detects it, which works for Raspberry Pi cameras only)"
    if status["reboot_pending"]:
        return f"{loaded}, saved after the last boot: reboot the Raspberry Pi to load it."
    return (f"{loaded}. If another sensor is connected, select it in the Controls tab under "
            f"Camera model (dtoverlay), save and reboot. {retry}")


class Unavailable:
    """Stands in for the camera service when the camera cannot be opened at all: the UI still loads,
    shows the problem and offers a reboot or a new attempt."""

    auto_reboot = False

    def __init__(self, reason):
        self.health = health.Health()
        self.health.set("failed", f"The camera cannot be opened: {reason}. {camera_model_hint()}")

    def reset(self, action):
        if action == "reboot":
            self.health.set("failed", "Rebooting the Raspberry Pi")
            threading.Timer(1, health.reboot).start()
        elif action in ("camera", "stream"):
            threading.Timer(0.5, camera_service.restart_process).start()
        else:
            raise ValueError(f"unknown reset action {action}")

    def close(self):
        pass


# Camera model (dtoverlay) ---------------------------------------------------------------------
@app.get("/api/camera_overlay", summary="Camera model: the sensor overlay in config.txt and the installed ones")
def camera_overlay_get():
    try:
        return camera_overlay.status()
    except RuntimeError as e:
        _bad(e)


@app.put("/api/camera_overlay", summary="Set the camera model (sensor overlay); applies after a reboot")
def camera_overlay_set(overlay: str = Body(..., embed=True), port: str = Body("cam1", embed=True),
                       mono: bool = Body(False, embed=True)):
    try:
        return camera_overlay.set_overlay(overlay, port, mono)
    except (ValueError, RuntimeError) as e:
        _bad(e)


# Also without a camera: a wrong camera model is fixed from the web UI
ALWAYS_AVAILABLE = ("/api/health", "/api/reset", "/api/camera_overlay")


@app.middleware("http")
async def camera_required(request, call_next):
    path = request.url.path
    needs_camera = path.startswith("/api/") or path == "/stream.mjpg"
    if isinstance(service, Unavailable) and needs_camera and path not in ALWAYS_AVAILABLE:
        return JSONResponse({"detail": service.health.message}, status_code=503)
    return await call_next(request)


# Captures ------------------------------------------------------------------------------------
@app.get("/api/capture/raw", summary="Raw frames in DN: npz (frames + metadata), tiff (1 frame) or dng (1 frame)")
def capture_raw(count: int = Query(1, ge=1, le=1000), format: str = Query("npz", pattern="^(npz|tiff|dng)$")):
    try:
        if format == "dng":
            path = _tempfile(".dng")
            try:
                service.capture_dng(path)
            except BaseException:
                os.unlink(path)
                raise
            return _download(path, "image/x-adobe-dng", "frame.dng")
        frames_, metas, raw = service.capture_raw(count if format == "npz" else 1)
    except ValueError as e:
        _bad(e)
    except RuntimeError as e:
        _unavailable(e)
    if format == "tiff":
        path = _tempfile(".tiff")
        Image.fromarray(frames_[0]).save(path, format="TIFF")
        return _download(path, "image/tiff", "frame.tiff")
    path = _tempfile(".npz")
    np.savez(path, frames=frames_, metadata=np.array(json.dumps(metas)), raw=np.array(json.dumps(raw)))
    del frames_
    return _download(path, "application/octet-stream", f"raw_{count}.npz")


@app.post("/api/noise", summary="Capture N raw frames and return the noise figures (DN)")
def noise(frames: int = Body(16, ge=1, le=1000), roi: list[int] | None = Body(None)):
    if roi is not None and len(roi) != 4:
        _bad("roi must be [x, y, w, h]")
    try:
        return service.noise(frames, tuple(roi) if roi else None)
    except ValueError as e:
        _bad(e)
    except RuntimeError as e:
        _unavailable(e)


# Live analysis -------------------------------------------------------------------------------
@app.get("/api/raw/crop", summary="Pixel values in DN of a raw area (at most 128x128) of the latest analysed "
                                  "frame; values row by row")
def raw_crop(x: int, y: int, w: int = Query(..., ge=1, le=128), h: int = Query(..., ge=1, le=128)):
    try:
        return service.raw_crop(x, y, w, h)
    except ValueError as e:
        _bad(e)
    except RuntimeError as e:
        _unavailable(e)


@app.get("/api/histogram", summary="Live raw histogram (per channel)")
def histogram():
    return service.histogram()


@app.get("/api/rois", summary="ROIs with live means and their position on the preview")
def rois():
    return service.rois()


@app.put("/api/rois", summary="Replace the ROIs: [{name, x, y, w, h}] in raw pixels")
def set_rois(values: list[dict] = Body(...)):
    try:
        return service.set_rois(values)
    except (KeyError, ValueError, TypeError) as e:
        _bad(e)


@app.post("/api/isp_stats/enable", summary="Turn the ISP statistics output on or off")
def isp_stats_enable(enabled: bool = Body(..., embed=True)):
    try:
        service.enable_isp_stats(enabled)
    except (KeyError, ValueError, RuntimeError) as e:
        _bad(e)
    return {"enabled": enabled}


@app.get("/api/isp_stats", summary="Latest ISP statistics: AGC histogram, 32x32 zone means, 8x8 focus")
def isp_stats_get():
    return service.isp_statistics()


# Registers -----------------------------------------------------------------------------------
@app.get("/api/registers/known", summary="Named registers of this sensor (from its plugin profile)")
def registers_known():
    info_ = service.sensor_info
    backend = None
    if info_:
        try:
            backend = service.regs.backend
        except RuntimeError:
            pass
    return {"sensor": str(info_) if info_ else None, "name": info_.name if info_ else None,
            "banked": bool(info_ and info_.banked), "contexts": info_.contexts if info_ else "",
            "backend": backend, "registers": service.known_registers()}


@app.get("/api/sensor/contexts", summary="Context controls of the driver (sensors whose plugin profile has contexts)")
def contexts_get():
    try:
        return service.contexts()
    except (OSError, RuntimeError) as e:
        _bad(e)


@app.put("/api/sensor/contexts", summary="Set context controls; omitted fields stay as they are")
def contexts_set(context: str | None = Body(None, embed=True), auto_switch: bool | None = Body(None, embed=True),
                 auto_switch_to: str | None = Body(None, embed=True),
                 controls_context: str | None = Body(None, embed=True)):
    try:
        return service.set_contexts(context=context, auto_switch=auto_switch, auto_switch_to=auto_switch_to,
                                    controls_context=controls_context)
    except (OSError, RuntimeError, ValueError) as e:
        _bad(e)


@app.get("/api/registers/dump", summary="Read count 8-bit registers from start")
def registers_dump(start: int, count: int = Query(64, ge=1, le=4096), bank: int | None = None,
                   context: int | None = None):
    try:
        return [{"address": a, "value": v} for a, v in service.regs.dump(start, count, bank, context)]
    except (OSError, RuntimeError, ValueError) as e:
        _bad(e)


@app.get("/api/registers/{address}", summary="Read a register (big-endian, nbytes 1-4)")
def register_read(address: int, nbytes: int = Query(1, ge=1, le=4), bank: int | None = None,
                  context: int | None = None):
    try:
        return {"address": address, "value": service.regs.read(address, nbytes, bank, context), "bytes": nbytes}
    except (OSError, RuntimeError, ValueError) as e:
        _bad(e)


@app.put("/api/registers/{address}", summary="Write a register (through the driver if it can). The driver may overwrite it later.")
def register_write(address: int, value: int = Body(..., embed=True), nbytes: int = Body(1, embed=True, ge=1, le=4),
                   bank: int | None = Body(None, embed=True), context: int | None = Body(None, embed=True)):
    try:
        service.regs.write(address, value, nbytes, bank, context)
        return {"address": address, "value": value, "bytes": nbytes}
    except (OSError, RuntimeError, ValueError, OverflowError) as e:
        _bad(e)


# Tuning --------------------------------------------------------------------------------------
@app.get("/api/tuning", summary="Tuning file in use and the installed ones")
def tuning():
    return {"current": service.tuning_file, "files": service.tuning_files()}


@app.post("/api/tuning", summary="Restart the service with another tuning file (null: the default one)")
def tuning_set(path: str | None = Body(None, embed=True)):
    try:
        service.restart_with_tuning(path)
    except ValueError as e:
        _bad(e)
    return JSONResponse({"restarting": True, "tuning_file": path or None, "instance": INSTANCE}, status_code=202)


class RevalidatedFiles(StaticFiles):
    """Static files that browsers check again on every load (ETag), so an update of the viewer is
    picked up at once instead of running an old cached app.js against the new API."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", RevalidatedFiles(directory=STATIC), name="static")
if os.path.isdir(os.path.join(WEB_DIST, "assets")):
    # Vite names these files after their content, so they can be cached
    app.mount("/assets", StaticFiles(directory=os.path.join(WEB_DIST, "assets")), name="assets")


def start_service(args, wait=20.0):
    """Start the camera service.

    - Camera busy (a previous instance still closing it): retried for `wait` seconds.
    - No camera listed while a tuning file chosen in the UI is in use: libcamera did not register
      the camera because the tuning file does not load for this sensor (e.g. a colour file on a
      mono sensor). libcamera keeps that state for the whole process, so the file is dropped and a
      fresh process starts with the default tuning.
    """
    deadline = time.monotonic() + wait
    while True:
        try:
            return camera_service.CameraService(args.camera, args.tuning_file)
        except (RuntimeError, IndexError) as e:
            cause = e.__cause__ or e
            saved = camera_service.load_settings()
            if isinstance(e, IndexError) and saved.get("tuning_file") and not args.tuning_file:
                log.error("no camera with tuning file %s (it does not load for this sensor); "
                          "restarting with the default tuning", saved["tuning_file"])
                del saved["tuning_file"]
                camera_service.save_settings(saved)
                camera_service.restart_process()
            if "busy" in str(cause).lower() and time.monotonic() < deadline:
                log.warning("camera busy (%s), retrying", cause)
                time.sleep(1)
                continue
            raise


def main():
    global service
    parser = argparse.ArgumentParser(description="Picam-web viewer and API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=80)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--tuning-file")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    # When systemd's watchdog kills a hung service (SIGABRT), log where every thread was stuck
    import faulthandler
    faulthandler.enable(all_threads=True)
    try:
        service = start_service(args)
    except Exception as e:  # noqa: BLE001 - keep serving the UI so it can show the problem
        log.error("camera service could not start: %s", e)
        service = Unavailable(str(e.__cause__ or e))
        health.sd_notify("READY=1")
        interval = health.watchdog_interval()
        if interval:  # stay alive for systemd: the UI must keep showing the problem

            def ping():
                while True:
                    health.sd_notify("WATCHDOG=1")
                    time.sleep(interval)
            threading.Thread(target=ping, daemon=True).start()
    import uvicorn
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        service.close()


if __name__ == "__main__":
    main()
