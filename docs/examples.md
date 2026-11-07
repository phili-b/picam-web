# Examples

The `examples/` folder has small Python scripts that use the [Python API](python-api.md) from a PC.
They run on Windows, macOS and Linux and need only Python 3.9+ and numpy.

## Set up on Windows

1. Install Python from <https://www.python.org/downloads/> and tick *Add python.exe to PATH*.
2. In PowerShell:

    ```powershell
    py -m pip install numpy
    py -m pip install "git+https://github.com/phili-b/picam-web.git"   # optional
    ```

    Without the second line the examples use `picam_client` from the repository they are in. The
    pip install needs Git for Windows. Install `matplotlib` as well for the plot of the exposure sweep.

3. Connect the Pi with the USB-C cable (or put it on the network) and check that
   <http://raspberrypi.local/> opens the web viewer.

## Run

```powershell
cd picam-web\examples
py 01_camera_info.py                          # http://raspberrypi.local
py 01_camera_info.py http://192.168.1.42      # another address
$env:PICAM_URL = "http://192.168.1.42"         # or once for the PowerShell session
```

Results go to `examples\output\`.

| Script | What it shows |
|--------|---------------|
| `01_camera_info.py` | sensor, sensor modes, state, frame rate, the latest frame's metadata |
| `02_capture_raw.py` | manual exposure and gain; raw frames as numpy arrays in DN; `.npz`, `.tiff`, `.dng` and the JPEG preview saved; reading the npz back |
| `03_noise.py` | temporal noise and FPN in a ROI, computed on the Pi, then again on the PC with numpy |
| `04_exposure_sweep.py` | mean and temporal noise against the exposure time (linearity, photon transfer); CSV, and a plot with matplotlib |
| `05_rois_and_histogram.py` | three ROIs and their live means; the raw histogram per channel |
| `06_registers.py` | the sensor's named registers, register reads and a dump (reads only; writes shown in comments) |
| `07_live_stream.py` | JPEG frames from the MJPEG preview and the frame rate over the network |
| `08_modes_and_recovery.py` | every sensor mode with its frame rate, ISP statistics, health and a stream restart |

The scripts change exposure, gain, the sensor mode and ROIs, and set them back at the end. They
do not write registers.

A minimal script:

```python
from picam_client import Camera

cam = Camera("http://raspberrypi.local")
cam.set_controls(AeEnable=False, ExposureTime=10000, AnalogueGain=1.0)
frames, metadata = cam.capture_raw(8)          # 8 x H x W, uint16, DN
print(frames.mean(), cam.noise(frames=16)["temporal_noise"])
```

## Troubleshooting

| Problem | |
|---------|-|
| `Cannot reach the Picam-web service` | `raspberrypi.local` is not resolved: use the Pi's IP address (on the Pi: `hostname -I`). A VPN can block `.local` names |
| `HTTP 503` | the camera is restarting or failed: see the banner in the web viewer or `cam.health()`; `cam.reset("camera")` reopens it |
| `... is packed or compressed` | raw captures need an unpacked sensor mode: `cam.set_mode(...)` |
| No Pi at hand | run the service with the simulated camera on the PC (see [Development](development.md#running-without-a-raspberry-pi)) and use `http://127.0.0.1:8080` |
