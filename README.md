# Picam-web

A camera viewer and small tools for evaluating camera sensors on a Raspberry Pi, built on
[picamera2](https://github.com/raspberrypi/picamera2), libcamera and the Raspberry Pi ISP.
Works with any sensor libcamera supports; sensor-specific extras (named registers, banked register
maps, driver register controls) come from optional [sensor plugins](docs/registers.md#sensor-plugins).

## Web viewer and Python API
A camera service (`picam_web/`, systemd unit `picam-web`, port 80) owns the camera and serves:
- a browser UI at `http://<pi>/`, from any PC on a USB-C network gadget, Ethernet or Wi-Fi
  (`http://raspberrypi.local/`), also usable on a phone: live MJPEG preview with zoom down to the
  raw pixel values, controls, sensor modes, tuning file, raw/DNG/TIFF downloads, frames, histogram,
  ROIs, noise, registers, ISP statistics, camera info;
- an HTTP API with docs at `http://<pi>/docs`;
- the Python API `picam_client` for PCs (needs only numpy):
  ```
  pip install "git+https://github.com/phili-b/picam-web.git"
  ```
  ```python
  from picam_client import Camera
  cam = Camera("http://raspberrypi.local")
  cam.set_controls(AeEnable=False, ExposureTime=5000)
  frames, metadata = cam.capture_raw(16)      # N x H x W uint16 in DN
  print(cam.noise(frames=16, roi=(100, 100, 64, 64)))
  ```
The desktop (Qt) viewer stops the service while it runs (`picam_viewer/run_desktop.sh`), since only one
program can open the camera.

## Install
Raspberry Pi OS Trixie with the camera's driver and libcamera support installed:
```
sudo mkdir -p /opt/picam_viewer
curl -fL https://github.com/phili-b/picam-web/releases/latest/download/picam-web.tar.gz | sudo tar -xz -C /opt/picam_viewer --strip-components=1
sudo /opt/picam_viewer/install.sh
```
This installs the apt/pip dependencies, the web service, a menu entry and a desktop shortcut.

## Desktop viewer
```
python3 /opt/picam_viewer/picam_viewer/app_full.py [--tuning-file FILE] [--camera N] [--tab NAME] [--roi X,Y,W,H ...]
```
On the Wayland desktop the viewer uses Xwayland (`QT_QPA_PLATFORM=xcb`), because the OpenGL preview
cannot initialise EGL as a native Wayland client.

| Tab | |
|-----|-|
| Still Capture / Video | capture jpg/png/dng/raw tiff, record H.264 |
| Image Tuning, Pan/Zoom, AEC/AWB | the usual picamera2 controls |
| Info | all per-frame metadata |
| ISP | every other libcamera control (auto-generated from the camera), free-form `Name=value` controls, the tuning file in use with its algorithms, and switching to another tuning file (restarts the viewer) |
| Frames | frames received, measured vs expected fps, dropped frames (gaps in `SensorTimestamp`) |
| Camera | libcamera camera properties, sensor modes, current streams and SensorBlackLevels |
| ISP Stats | the ISP's own statistics (StatsOutputEnable): AGC histogram, 32x32 zone means, 8x8 focus figure of merit (Pi 5) |
| Histogram | live raw histogram, per colour channel for Bayer sensors |
| ROI | named rectangles (raw pixels) drawn on the preview with their live mean; pixel values drawn when zoomed in to the ISP's maximum |
| Noise | captures N raw frames and reports, in DN for the full frame or an ROI: mean, min/max, temporal noise, total/row/column FPN and row/column temporal noise; histogram; saves CSV + TIFF |
| Raw | raw bursts (TIFF in DN or DNG, metadata JSON per frame) and raw video recording (every frame, with timestamps; read back with `analysis.read_raw_video`) |
| Registers | read/write/poll (8-32 bit), dump ranges, load register sequences (`write <value> to <addr>` or `addr,value` CSV); named registers, banks and contexts with a sensor plugin |

Register access goes over I2C (`/dev/i2c-N`, found from sysfs) next to the driver, or through the
driver's register controls when a sensor plugin describes them: writes are not known to the driver,
which may overwrite them on a mode switch or stream start.

Noise analysis, ROIs, histograms and raw TIFFs need an unpacked raw mode. On a Raspberry Pi 5 all
unpacked modes arrive as 16-bit data, usually left-aligned; the viewer detects the alignment from the
data and converts to DN.

## Tools
`tools/` holds small command line helpers: `raw_capture.py`, `convt_raw_pgm.py`, `convt_raw_tiff.py` and
`ExtTrigPWM.py`. Register access is in `picam_viewer/sensor_regs.py` (also usable from Python on its own).

## Look
Charcoal ground, green `#9ACD56`, grey `#91969D` (`picam_viewer/style.py`). A logo in
`picam_viewer/artwork/logo.png` (and `picam_web/static/logo.png`) is shown when present.

## Development and tests
```
python tests/fake/run_fake.py web                     # web UI with a simulated camera, any PC
pytest tests                                          # unit and API tests, any PC
QT_QPA_PLATFORM=offscreen python3 tests/hw_smoke.py   # on a Pi with a camera
python tests/client_smoke.py http://raspberrypi.local # Python API against a running service, any PC
```
CI runs the tests on every push; a `v*` tag publishes a release archive. Full docs: `docs/`
(`mkdocs serve`).

## Licence
LGPL-2.1-or-later. The Lexend font is under the SIL Open Font License
(`picam_viewer/fonts/Lexend/OFL.txt`).
