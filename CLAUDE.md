# CLAUDE.md

Picam-web: camera viewer, web UI and Python API for evaluating camera sensors on Raspberry Pi
(picamera2 / libcamera). User docs are in `docs/` (mkdocs, nav in `mkdocs.yml`, published to GitHub
Pages by `.github/workflows/docs.yml`); keep them updated with UI/API changes.

## Layout

- `picam_web/` - FastAPI service (`server.py`, `camera_service.py`), serves `web/dist` (or the classic UI in `picam_web/static` without a build)
- `web/` - Svelte web UI: `npm run check`, `npm run build` (-> `web/dist`, git-ignored, so rebuild after every change)
- `picam_viewer/` - Qt desktop viewer (`app_full.py`) and the shared analysis, live view, ISP statistics and register modules
- `picam_viewer/sensor_plugins/` - optional sensor profiles (git-ignored apart from the README); keep sensor-specific data out of the core
- `picam_client/` - Python API for PCs
- `tests/fake/` - simulated picamera2, smbus2 and driver controls: `python tests/fake/run_fake.py web` -> http://127.0.0.1:8080/
- `pytest tests` - unit and API tests against the simulator (fake sensors: fakecam, duocam, quadcam)

## Camera facts worth knowing

- New controls take several frames to show in the metadata; with long exposures that is seconds
- Exposures over 1 s need `FrameDurationLimits` raised
- libcamera has no digital gain control: a gain above the analogue maximum becomes ISP digital gain
  (processed image only, not raw), capped by the tuning file's `max_digital_gain` (default 4)
- The service's stall/capture timeout is 10 s (`STALL_TIMEOUT`) so long exposures pass
- The service exits on purpose to reopen the camera; it relies on systemd `Restart=always`

## Testing the web UI

- In a hidden browser pane `requestAnimationFrame` never fires and the preview/HUD do not redraw:
  load the page in an iframe whose `requestAnimationFrame` is a `setTimeout` shim
- Use the mobile viewport (375x812) to check the phone layout and touch (pinch) handling
