# HTTP API

The camera service (`picam_web/server.py`, FastAPI) serves the API on port 80. Interactive docs, where
every endpoint can be tried from the browser, are at `http://<pi>/docs` (for example
<http://raspberrypi.local/docs>). The [Python API](python-api.md) wraps these endpoints.

Request bodies are JSON. Errors return `{"detail": "<message>"}` with:

| Status | When |
|--------|------|
| 400 | a request the service refuses: unknown control, packed raw mode, I2C failure, value or ROI out of range, a capture that does not fit in memory |
| 422 | a parameter of the wrong type or outside its range (`detail` is then a list of `{loc, msg}`) |
| 503 | the camera does not deliver frames right now (stalled, recovering, failed, or a mode switch failed), or it could not be opened at all; see `/api/health` |

A capture never waits forever: if no frame arrives within 10 s (longer at very low frame rates) it
returns 503 while the service recovers the camera in the background.

## Endpoints

### Pages and stream

| Method | Path | Parameters | Response |
|--------|------|------------|----------|
| GET | `/` | | the web UI |
| GET | `/classic` | | the classic web UI |
| GET | `/stream.mjpg` | | live preview, `multipart/x-mixed-replace` MJPEG stream |
| GET | `/api/snapshot.jpg` | | latest preview frame (JPEG); 503 if there is no frame yet |
| GET | `/docs` | | interactive API docs |

### Camera

| Method | Path | Parameters | Response |
|--------|------|------------|----------|
| GET | `/api/info` | | `properties`, `sensor_modes` (format, unpacked, size, bit_depth, fps, crop_limits, exposure_limits), `mode`, `raw` (format, size, stride), `main` (format, size), `is_mono`, `tuning_file`, `sensor`, `version`, `instance` |
| GET | `/api/controls` | | `{name: {min, max, default, value}}` for every libcamera control; `value` from the latest metadata |
| POST | `/api/controls` | body: `{name: value, ...}`; query `remember` (bool, default false) | `{"set": [names], "remembered": bool}`; lists become tuples; with `remember=true` the controls are stored for the next start, merged with the ones stored before |
| DELETE | `/api/controls/remembered` | | forgets the stored controls: the next start uses the defaults |
| GET | `/api/metadata` | | metadata of the latest frame (ISP statistics blobs left out) |
| POST | `/api/mode` | body: `{"index": n}` | `{"mode": n, "rois": [...]}`; restarts the camera in that sensor mode and remembers it; 503 if libcamera refuses the mode |
| GET | `/api/frames` | | `error`, `frames`, `dropped`, `fps`, `expected_fps`, `last_gap_ms`, `max_gap_ms`, `view` (the raw area the preview shows, `[x0, y0, x1, y1]` in raw pixels) |
| POST | `/api/frames/reset` | | the same, after resetting the counters |

### Health and recovery

| Method | Path | Parameters | Response |
|--------|------|------------|----------|
| GET | `/api/health` | | `state` (`starting`, `streaming`, `recovering`, `failed`), `message`, `since`, `recovery_level`, `history` (last state changes), `kernel` (recent kernel warnings about the sensor), `auto_reboot`, `instance` |
| POST | `/api/reset` | body: `{"action": "stream" \| "camera" \| "reboot"}` | 202; `stream` restarts the stream (about 1 s), `camera` reopens the camera in a new service process (about 5 s), `reboot` reboots the Pi |
| POST | `/api/auto_reboot` | body: `{"enabled": true}` | `{"auto_reboot": ...}`; reboot automatically when the camera cannot be recovered |

`instance` changes every time the service starts. After a `camera` reset or a tuning file switch,
wait until `/api/health` answers with another `instance` and `state` `streaming`
(`Camera.wait_restarted` does this). `/api/health` and `/api/reset` also answer when the camera
could not be opened at all; the other endpoints then return 503.

When frames stop, the service escalates by itself: it restarts the stream, then reopens the camera
in a new process, then reports `failed` (the sensor needs a power cycle: reboot the Pi).

### Captures

| Method | Path | Parameters | Response |
|--------|------|------------|----------|
| GET | `/api/capture/raw` | query `count` (1-1000, default 1), `format` (`npz`, `tiff` or `dng`, default `npz`) | `npz`: arrays `frames` (N x H x W uint16, DN), `metadata` (JSON string, list per frame), `raw` (JSON string: format, size, bit_depth). `tiff`: one 16-bit frame in DN. `dng`: one frame. `count` applies to npz only; at most 1 GiB of frames per capture (400 with the number that fits) |
| POST | `/api/noise` | body: `{"frames": 16, "roi": [x, y, w, h] or null}` (frames 1-1000) | noise figures in DN (see [Noise analysis](noise.md)) plus `format`, `size`, `bit_depth`, `roi`. Frames are added up one at a time, so any number fits in memory |

The frames of an npz capture are consecutive (copied first, converted afterwards). A mode switch
during a noise capture stops it with 400 ("the sensor mode changed during the capture").

### Live analysis

| Method | Path | Parameters | Response |
|--------|------|------------|----------|
| GET | `/api/raw/crop` | query `x`, `y`, `w`, `h` (w and h 1-128) | pixel values in DN of that raw area of the last analysed frame (4 per second, no capture): `x`, `y`, `w`, `h` (clipped to the frame), `bits`, `width`, `height`, `age_s`, `values` (row by row) |
| GET | `/api/histogram` | | `bits`, `channels` (`{name: counts}`, R/G/B or Y, up to 256 bins), `mean`, `min`, `max`; or `{"error": ...}` |
| GET | `/api/rois` | | `[{name, x, y, w, h, mean, view}]`; `view` = `[u0, v0, u1, v1]` position on the preview (0..1) |
| PUT | `/api/rois` | body: `[{name, x, y, w, h}, ...]` in raw pixels | the new ROIs, as GET. x, y >= 0 and inside the raw frame, w, h >= 1; w and h are clipped to the frame |
| POST | `/api/isp_stats/enable` | body: `{"enabled": true}` | `{"enabled": ...}`; sets `StatsOutputEnable` |
| GET | `/api/isp_stats` | | `enabled`, `platform`, `count`, `histogram` (1024), `zones_mean` (32x32), `focus` (8x8); or `enabled` and `error` when they are off, none arrived yet, or on a Pi 4 (VC4) |

### Registers

| Method | Path | Parameters | Response |
|--------|------|------------|----------|
| GET | `/api/registers/known` | | `{"sensor": "<name> on /dev/i2c-N at 0xNN", "name", "banked", "contexts" ("AB", "ABCD" or ""), "backend" ("driver" or "i2c"), "registers": [{name, address, bytes}]}` |
| GET | `/api/registers/dump` | query `start` (required), `count` (1-4096, default 64), `bank`, `context` | `[{address, value}]` of 8-bit registers |
| GET | `/api/registers/{address}` | query `nbytes` (1-4, default 1), `bank`, `context` | `{address, value, bytes}`; big-endian |
| PUT | `/api/registers/{address}` | body: `{"value": v, "nbytes": 1, "bank": null, "context": null}` | `{address, value, bytes}`. The driver may overwrite it later |
| GET | `/api/sensor/contexts` | | `{"available": false}`, or the driver's context controls: `{"available": true, "contexts", "context", "current" (null when not streaming), "auto_switch", "auto_switch_to", "controls_context" ("all" or a context)}` |
| PUT | `/api/sensor/contexts` | body: any of `context`, `auto_switch`, `auto_switch_to`, `controls_context` | as GET |

Addresses and values are decimal integers in the URL and JSON. `bank` and `context` apply to sensors
whose plugin profile has a banked register map (context 0 up to the number of contexts - 1); contexts in
`/api/sensor/contexts` are names (`"A"`, `"B"`, ...). See [Registers](registers.md).

### Tuning

| Method | Path | Parameters | Response |
|--------|------|------------|----------|
| GET | `/api/tuning` | | `{"current": path or null, "files": [installed tuning files for this platform]}` |
| POST | `/api/tuning` | body: `{"path": "/usr/share/libcamera/ipa/rpi/pisp/<file>.json"}`, or `{"path": null}` for the sensor's default file | 202 `{"restarting": true, "tuning_file": path, "instance": ...}`; the service checks that the file loads for this sensor (400 if not) and restarts with it a moment later |

### Camera model

| Method | Path | Parameters | Response |
|--------|------|------------|----------|
| GET | `/api/camera_overlay` | | `{"available", "overlays": [installed camera sensor overlays], "current": {"overlay", "port" ("cam0"/"cam1"), "mono", "line", "camera_auto_detect"}, "reboot_pending"}`; `available` false (and `current` null) without `/boot/firmware/config.txt` |
| PUT | `/api/camera_overlay` | body: `{"overlay": "imx477", "port": "cam1", "mono": false}` | as GET; 400 for an overlay that is not installed or not a camera sensor. Applies after a reboot (`POST /api/reset {"action": "reboot"}`) |

Both also answer when the camera cannot be opened.

The installed tuning files are looked up in `/usr/local/share/libcamera/ipa/rpi/<platform>/` and
`/usr/share/libcamera/ipa/rpi/<platform>/`, with platform `pisp` (Pi 5) or `vc4` (Pi 4).

## Examples with curl

```bash
curl http://raspberrypi.local/api/info
curl -X POST http://raspberrypi.local/api/controls \
     -H "Content-Type: application/json" -d '{"AeEnable": false, "ExposureTime": 10000}'
curl -o frames.npz "http://raspberrypi.local/api/capture/raw?count=10&format=npz"
curl -X POST http://raspberrypi.local/api/noise \
     -H "Content-Type: application/json" -d '{"frames": 16, "roi": [100, 100, 64, 64]}'
curl "http://raspberrypi.local/api/registers/14?nbytes=4"
```

## Reading an npz download

```python
import json
import numpy as np

with np.load("frames.npz") as z:
    frames = z["frames"]                       # N x H x W uint16, DN
    metadata = json.loads(str(z["metadata"]))  # list of dicts, one per frame
    raw = json.loads(str(z["raw"]))            # {'format', 'size', 'bit_depth'}
```
