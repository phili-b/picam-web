# Python API

`picam_client.Camera` controls a Pi running the camera service from any PC that can reach it
(USB-C gadget, Ethernet or Wi-Fi). It wraps the [HTTP API](http-api.md) and needs only numpy.

## Install

```bash
pip install "git+https://github.com/phili-b/picam-web.git"
```

This installs only the `picam_client` package (Python 3.9 or later). On Windows, run it in
PowerShell as `py -m pip install ...`. Ready-to-run scripts are in [Examples](examples.md).

## Connect

```python
from picam_client import Camera, CameraError

cam = Camera("http://raspberrypi.local")          # default URL; timeout=30 s
```

Every method raises `CameraError` (a `RuntimeError`) with the server's message when the service answers
with an error, for example an unknown control or a packed raw mode.

```python
try:
    cam.set_controls(NoSuchControl=1)
except CameraError as e:
    print(e)        # POST /api/controls: 'unknown control NoSuchControl' (HTTP 400)
```

The message ends with the HTTP status: `HTTP 503` means the camera is restarting or does not deliver
frames; check `cam.health()` and retry, or reset it (see *Health and recovery*).

## Camera

```python
info = cam.info()                       # properties, sensor_modes, mode, raw, main, is_mono,
                                        # tuning_file, sensor, version
for i, m in enumerate(info["sensor_modes"]):
    print(i, m["unpacked"], m["size"], m["bit_depth"], m["fps"])

ctrls = cam.controls()                  # {name: {min, max, default, value}}
print(ctrls["ExposureTime"])

cam.set_controls(AeEnable=False, ExposureTime=5000, AnalogueGain=1.0)
cam.set_controls({"FrameDurationLimits": (20000, 20000)})   # tuples are sent as lists
cam.set_controls(ExposureTime=8000, remember=True)          # also used after a service restart
cam.forget_controls()                                       # restart with the default controls

md = cam.metadata()                     # latest frame: ExposureTime, AnalogueGain, SensorTimestamp, ...

cam.set_mode(0)                         # index into info()["sensor_modes"]; restarts the camera
cam.wait_streaming()                    # until frames come again in the new mode

stats = cam.frame_stats()               # error, frames, dropped, fps, expected_fps,
                                        # last_gap_ms, max_gap_ms
cam.frame_stats(reset=True)             # reset the counters, returns the new values
```

## Captures

```python
frames, metadata = cam.capture_raw(16)  # N x H x W uint16 in DN, list of N metadata dicts
print(frames.shape, frames.mean(), metadata[0]["ExposureTime"])

cam.save_raw("frame.tiff")              # one 16-bit TIFF in DN
cam.save_raw("frame.dng", format="dng") # one DNG

jpg = cam.snapshot()                    # latest preview frame as JPEG bytes
cam.snapshot("preview.jpg")             # and saved to a file

for i, jpg in enumerate(cam.stream()):  # JPEG frames of the live MJPEG preview
    if i == 100:
        break
```

`capture_raw` accepts 1-1000 frames, up to 1 GiB per capture (`CameraError` says how many fit). It
needs an unpacked raw mode.

## Analysis

```python
n = cam.noise(frames=16)                         # full frame
n = cam.noise(frames=32, roi=(100, 100, 64, 64)) # (x, y, w, h) in raw pixels
print(n["mean"], n["temporal_noise"], n["fpn"], n["row_fpn"], n["col_fpn"])

h = cam.histogram()                     # {'bits', 'channels': {name: counts}, 'mean', 'min', 'max'}
for name, counts in h["channels"].items():
    print(name, counts.argmax())        # counts are numpy arrays

cam.set_rois([("dark", 0, 0, 64, 64), ("centre", 600, 400, 128, 128)])
cam.set_rois([{"name": "centre", "x": 600, "y": 400, "w": 128, "h": 128}])
for r in cam.rois():                    # name, x, y, w, h, mean, view (position on the preview, 0..1)
    print(r["name"], r["mean"])

s = cam.isp_stats(enable=True)          # switch the statistics on and read them
print(s["histogram"].shape, s["zones_mean"].shape, s["focus"].shape)   # (1024,), (32, 32), (8, 8)
s = cam.isp_stats()                     # read again
cam.isp_stats(enable=False)             # switch off, returns None
```

The noise result has the keys `frames`, `pixels`, `mean`, `min`, `max`, `temporal_noise`, `fpn`,
`row_fpn`, `col_fpn`, `row_temporal_noise`, `col_temporal_noise` (all in DN) plus `format`, `size`,
`bit_depth` and `roi`. See [Noise analysis](noise.md).

`isp_stats()` returns `{"enabled": ..., "error": ...}` instead when the statistics are off, when none
arrived yet, or on a Pi 4.

## Registers

```python
for r in cam.known_registers():         # [{'name', 'address', 'bytes'}] from the sensor profile
    print(r["name"], hex(r["address"]), r["bytes"])

value = cam.read_register(0x000E, nbytes=4)               # big-endian
value = cam.read_register(0x000E, nbytes=4, bank=1, context=0)  # banked sensors

cam.write_register(0x000E, 1000, nbytes=4)                # the driver may overwrite it later

for addr, value in cam.dump_registers(0x0000, count=32):  # 8-bit registers
    print(f"0x{addr:04x} 0x{value:02x}")
```

Access goes through the driver's register controls when it has them, else directly over I2C; see
[Registers](registers.md).

### Contexts (drivers with context controls)

```python
print(cam.contexts())       # {'available': True, 'contexts': 'AB', 'context': 'A', 'current': 'A', ...}
cam.set_controls(AeEnable=False, ExposureTime=10000)   # all contexts
cam.set_contexts(controls_context="B")
cam.set_controls(ExposureTime=2000)                     # context B only
cam.set_contexts(controls_context="A", context="B")     # use B; later changes go to A
```

## Tuning

```python
t = cam.tuning()                        # {'current': path or None, 'files': [installed files]}
cam.set_tuning_file(t["files"][0])      # restarts the service; returns when it streams again
cam.set_tuning_file(None)               # back to libcamera's default file for the sensor
```

`set_tuning_file(path, wait=False)` returns at once; then call `cam.wait_restarted(r["instance"])`.

## Health and recovery

```python
h = cam.health()        # state, message, recovery_level, history, kernel, auto_reboot, instance
if h["state"] != "streaming":
    print(h["message"])

cam.reset("stream")     # restart the stream; returns when it streams again (about 1 s)
cam.reset("camera")     # reopen the camera in a new service process (about 5 s)
cam.reset("reboot")     # reboot the Pi (power-cycles the sensor); returns at once
cam.set_auto_reboot(True)   # reboot by itself when the camera cannot be recovered

cam.wait_streaming(timeout=60)          # until the state is streaming (or failed)
```

States: `starting`, `streaming`, `recovering`, `failed`. When frames stop the service first restarts
the stream, then reopens the camera, then reports `failed`. A long measurement script can check
`cam.health()` between steps and call `cam.reset(...)` when needed.
