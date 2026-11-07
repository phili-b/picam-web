# Python API examples (Windows, macOS, Linux)

Scripts that use the Picam-web service on the Raspberry Pi from a PC, through the Python client
`picam_client.Camera`. The client needs only Python 3.9+ and numpy.

## Set up on Windows

1. Install Python from <https://www.python.org/downloads/> (tick *Add python.exe to PATH*).
2. In PowerShell:

   ```powershell
   py -m pip install numpy
   py -m pip install "git+https://github.com/phili-b/picam-web.git"   # optional, see below
   ```

   Without the pip install the examples use `picam_client` from this repository (`..\picam_client`).
   Git is needed for the pip install. `matplotlib` (optional) adds a plot to `04_exposure_sweep.py`.
3. Connect the Pi with the USB-C cable (or put it on the network) and check that
   <http://raspberrypi.local/> opens the web viewer in a browser.

## Run

```powershell
cd examples
py 01_camera_info.py                        # http://raspberrypi.local
py 01_camera_info.py http://192.168.1.42    # another address
$env:PICAM_URL = "http://192.168.1.42"       # or set it once for the session
```

Files are written to `examples\output\`.

| Script | What it shows |
|--------|---------------|
| `01_camera_info.py` | sensor, modes, state, frame rate, metadata of the latest frame |
| `02_capture_raw.py` | manual exposure and gain, raw frames as numpy (DN), `.npz`, `.tiff`, `.dng`, JPEG preview |
| `03_noise.py` | temporal noise and FPN in a ROI, on the Pi and again on the PC with numpy |
| `04_exposure_sweep.py` | mean and noise against exposure time (linearity, photon transfer), CSV and plot |
| `05_rois_and_histogram.py` | live ROI means and the raw histogram |
| `06_registers.py` | named sensor registers, register reads and a dump (reads only) |
| `07_live_stream.py` | JPEG frames of the live MJPEG preview |
| `08_modes_and_recovery.py` | sensor mode switching, ISP statistics, health and a stream restart |

The examples change exposure, gain, the sensor mode and ROIs and set them back; they do not write
registers. The full API is in the documentation (*Python API*) and at `http://raspberrypi.local/docs`.

## Troubleshooting

- **`Cannot reach the Picam-web service`**: `raspberrypi.local` is not found. Use the Pi's IP address
  (on the Pi: `hostname -I`). Windows 10 and 11 resolve `.local` names; a VPN can block them.
- **`HTTP 503`**: the camera is restarting or failed; see the banner in the web viewer, or
  `cam.health()`. `cam.reset("camera")` reopens it, `cam.reset("reboot")` reboots the Pi.
- **Packed sensor modes**: raw captures need an unpacked mode; choose another mode (`cam.set_mode`).
- **No Pi at hand**: run the web service with a simulated camera on the PC
  (`python tests\fake\run_fake.py web`, needs `pip install fastapi uvicorn pillow`), then
  `py 01_camera_info.py http://127.0.0.1:8080`.
