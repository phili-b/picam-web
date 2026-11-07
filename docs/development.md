# Development

## Repository layout

| Path | |
|------|-|
| `picam_web/server.py` | FastAPI app: HTTP endpoints, web UI, start-up with retries |
| `picam_web/camera_service.py` | `CameraService`: owns the camera, MJPEG encoder, per-frame callback, settings in `~/.config/picam_web.json` |
| `web/` | web UI: Svelte 5, TypeScript, Vite; built into `web/dist/`, served at `/` |
| `picam_web/static/` | the classic web UI (at `/classic`), icon and logo |
| `desktop/open_web_ui.sh` | opens the web UI in its own window (Chromium app mode) |
| `picam_client/__init__.py` | Python API (`Camera`, `CameraError`) |
| `picam_viewer/app_full.py` | desktop (Qt) viewer |
| `picam_viewer/panels.py` | desktop tabs: Registers, Noise, Frames, ISP, Histogram, ROI |
| `picam_viewer/camera_panels.py` | desktop tabs: Camera, ISP Stats, tuning file switch, Raw |
| `picam_viewer/live.py` | live raw analysis: ROI means, histogram, overlay with pixel values (no Qt) |
| `picam_viewer/analysis.py` | raw conversion, noise figures, frame statistics, raw video reader (numpy only) |
| `picam_viewer/isp_stats.py` | decoder of the Pi 5 ISP statistics (numpy only) |
| `picam_viewer/sensor_regs.py` | register access (driver controls or I2C), contexts, sensor detection, sequence parser |
| `picam_viewer/style.py` | look: colours, font, stylesheet |
| `picam_viewer/run_desktop.sh` | starts the desktop viewer, stopping the web service meanwhile |
| `systemd/picam-web.service` | systemd unit template (`@VIEWER_DIR@`, `@VIEWER_USER@`) |
| `desktop/` | menu entry templates |
| `install.sh` | installer for the Pi |
| `requirements-apt.txt` | apt packages |
| `pyproject.toml` | pip package `picam-client` (only `picam_client`) |
| `tools/` | small command line helpers |
| `examples/` | Python API examples for a PC (see [Examples](examples.md)) |
| `tests/` | unit tests, API tests, smoke and stress tests |
| `tests/fake/` | simulated `picamera2` and `smbus2`, `run_fake.py` (service or viewer on a PC), `desktop_smoke.py` |

`picam_web` imports `analysis`, `isp_stats`, `live` and `sensor_regs` from `picam_viewer/` by adding it
to `sys.path`; there is no installed package for them.

## Web UI

The web UI in `web/` is a Svelte 5 + TypeScript app built with Vite. It needs Node.js 20 or later
to build; the Pi only serves the built files from `web/dist/` (without them `/` shows the classic UI).

```bash
cd web
npm install
npm run dev        # http://localhost:5173/, live reload; the API goes to the simulator
PICAM_URL=http://raspberrypi.local npm run dev     # ... or to a Pi
npm run check      # type check
npm run build      # -> web/dist/
```

| File | |
|------|-|
| `src/lib/api.ts` | typed client for the HTTP API |
| `src/lib/live.svelte.ts` | live state (health, frames, ROIs, camera info), polled twice a second |
| `src/components/Viewer.svelte` | the preview: zoom, pan, ROIs, raw pixel values |
| `src/components/HistogramPlot.svelte` | histogram plot (uPlot) |
| `src/tabs/*.svelte` | one file per tab |

## Running without a Raspberry Pi

`tests/fake/` simulates the camera and the sensor's I2C registers, so the web service, the web UI,
the Python API and the desktop viewer run on any PC:

```bash
pip install numpy pillow fastapi uvicorn         # + PyQt5 for the desktop viewer
python tests/fake/run_fake.py web                # web UI at http://127.0.0.1:8080/
python tests/fake/run_fake.py desktop            # desktop viewer
```

The simulated sensor is a mono camera with a 12-bit 640x480 mode and an 8-bit 320x240
mode, as on a Pi 5 (16-bit left-aligned raw stream, ISP statistics). Its frames are a gradient with
temporal noise and FPN that follow `ExposureTime` and `AnalogueGain`. `FAKE_CAMERA_COLOUR=1` makes it
an RGGB sensor, `FAKE_CAMERA_MODEL=duocam` (or `quadcam`) a sensor with register banks and two (four) contexts, and
`FAKE_DRIVER_CONTROLS=0` for register access over I2C instead of the simulated driver controls.
Settings go to a temporary folder, not `~/.config`. Camera resets and tuning file switches restart
the simulated service as on the Pi. Tuning files are not simulated (the list is empty on a PC).

The simulator is for developing the UI and the API; it does not replace the hardware tests below.

## Tests

| Command | Where | What |
|---------|-------|------|
| `pytest tests` | any PC | unit tests (`test_analysis.py`, `test_health.py`, numpy and Pillow) and, when `fastapi` and `httpx` are installed, `test_web_api.py`: every HTTP endpoint against the simulated camera, including a stalled camera and its recovery |
| `python tests/fake/desktop_smoke.py` | any PC with PyQt5 | clicks every button and check box of the desktop viewer with the simulated camera; takes a photo in every file type and records a video |
| `python tests/stress_api.py http://<pi> 60` | any PC | stability: 3 MJPEG viewers, UI polling, captures, noise runs, register reads, ROI updates and mode switches in parallel for 60 s; then checks that the camera still streams |
| `QT_QPA_PLATFORM=offscreen python3 tests/hw_smoke.py` | Pi with a sensor, web service stopped | the desktop panels against the real camera |
| `python tests/client_smoke.py http://raspberrypi.local` | any PC | the Python API against a running web service |

The unit tests cover: noise figures (temporal noise and FPN recovered from synthetic frames, single
frame, ROI, row pattern), `raw_to_image` (Pi 5 left-aligned, Pi 4, 8-bit with both alignments,
compressed formats rejected), frame statistics (drops and fps), sequence file formats, sensor
detection from a fake sysfs, the named register lists, live channels and ROI mapping, ISP statistics
decoding, and reading a raw video.

`hw_smoke.py` reads registers only, and sets exposure and gain. It checks frames and fps, noise for
the full frame and a 64x64 ROI, register read and dump, the ISP tab controls, live ROI means,
histogram and overlays (ROIs and pixel values), ISP statistics, the Camera tab, tuning files, raw
bursts (TIFF and DNG) and raw video.

`client_smoke.py` reads registers only, and changes exposure, gain and ROIs. It checks info, controls,
`capture_raw`, noise, histogram, ROIs, frame statistics, registers, ISP statistics, `save_raw`
(TIFF and DNG), snapshot and the MJPEG stream.

Both smoke tests print `PASS` / `FAIL` per check and exit with 0 when all checks pass.

## CI

`.github/workflows/ci.yml` runs on pushes to `main`, on `v*` tags and on pull requests, with Python
3.13 (as on Raspberry Pi OS Trixie):

1. `pip install numpy pillow pytest pyflakes fastapi httpx PyQt5`;
2. `pyflakes` on `picam_web`, `picam_client`, the new `picam_viewer` modules, `examples` and `tests`;
3. `python -m compileall` on `picam_viewer`, `tools`, `examples` and `tests`;
4. `pytest -q tests` (unit and API tests);
5. `tests/fake/desktop_smoke.py` off-screen;
6. `bash -n install.sh`.

A `v*` tag also builds `picam-web-<tag>.tar.gz` with `git archive` and publishes it as a GitHub
release.

## Documentation

This site is built with MkDocs and the Material theme:

```bash
pip install mkdocs-material
mkdocs serve          # http://127.0.0.1:8000/
mkdocs build --strict
```

## Known limitations

- **Frame rate from the driver**: the expected fps and the dropped frame count come from the
  `FrameDuration` the driver reports; if the driver's timing is off, so are they. The measured fps
  is always correct.
- **Colour tuning files on a mono sensor**: they do not load; libcamera then does not register the
  camera. The web service drops a tuning file chosen in the UI in that case and restarts with the
  default tuning.
- **ISP statistics** are decoded on the Raspberry Pi 5 (PiSP) only; Pi 4 (VC4) statistics are not.
- **One camera user**: the web service and the desktop viewer cannot run at the same time.
- **Register writes** are not known to the driver and may be overwritten on a mode switch, stream
  start or exposure change. Through the driver controls, registers are only accessible while streaming.
