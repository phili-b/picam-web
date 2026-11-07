# Picam-web for Raspberry Pi

A camera viewer and a set of small tools for evaluating camera sensors on a Raspberry Pi. It is
built on [picamera2](https://github.com/raspberrypi/picamera2), libcamera and the Raspberry Pi ISP,
and works with any sensor libcamera supports. Sensor-specific extras (named registers, banked
register maps, driver register controls) come from optional
[sensor plugins](registers.md#sensor-plugins).

What it does:

- live preview with the libcamera controls (exposure, gain, AEC/AWB, every other control);
- sensor modes, tuning file selection, camera properties and per-frame metadata;
- raw captures in DN (npz, TIFF, DNG) and raw video recording;
- live raw histogram and named ROIs with their mean;
- noise analysis (temporal noise, FPN, row/column components);
- direct sensor register access (read, write, dump, register sequences);
- a phone-friendly web UI (pinch to zoom);
- the Raspberry Pi ISP's own statistics;
- frame counter, measured frame rate and dropped frames.

## Architecture

Only one program can open the camera at a time. A camera service owns it, and everything else is a
client of that service.

```
                     Raspberry Pi
 +-------------------------------------------------+
 |  picam-web.service  (picam_web/server.py, port 80) |
 |    CameraService: picamera2, MJPEG preview,      |
 |    metadata, histogram, ROIs, ISP stats, I2C     |
 +-------------------------------------------------+
        |  HTTP (USB-C gadget, Ethernet, Wi-Fi)
        +--> web UI in a browser     http://raspberrypi.local/
        +--> Python API (picam_client.Camera) on a PC
        +--> HTTP API, docs at       http://raspberrypi.local/docs

 Desktop (Qt) viewer, picam_viewer/app_full.py: opens the camera itself,
 so run_desktop.sh stops picam-web while it runs.
```

| Part | Directory | Runs on | Purpose |
|------|-----------|---------|---------|
| Camera service | `picam_web/` | Pi | FastAPI server; owns the camera, serves the web UI and the HTTP API |
| Web UI | `web/` | browser, or a window on the Pi desktop | Svelte app: live preview with zoom, controls, captures, analysis, registers |
| Python API | `picam_client/` | any PC | `Camera` class over the HTTP API; needs only numpy |
| Examples | `examples/` | any PC (Windows, macOS, Linux) | ready-to-run scripts for the Python API; see [Examples](examples.md) |
| Desktop viewer | `picam_viewer/` | Pi desktop | Qt viewer with the full set of tabs; also holds the shared analysis, live view, ISP statistics and register code |
| Tools | `tools/` | Pi | small command line helpers (`raw_capture.py`, `convt_raw_pgm.py`, `convt_raw_tiff.py`, `ExtTrigPWM.py`) |

The analysis (`analysis.py`), live view (`live.py`), ISP statistics (`isp_stats.py`) and register
(`sensor_regs.py`) modules in `picam_viewer/` are shared by the desktop viewer and the camera service,
so both give the same numbers.

## Access over USB-C

When the Pi runs as a USB-C network gadget, connect it to a PC with a USB-C cable and open:

- web UI: <http://raspberrypi.local/>
- interactive API docs: <http://raspberrypi.local/docs>

The same URLs work over Ethernet or Wi-Fi, with the Pi's host name or IP address.

## Licence

LGPL-2.1-or-later. The Lexend font is under the SIL Open Font License
(`picam_viewer/fonts/Lexend/OFL.txt`).
