# Desktop viewer

The desktop viewer (`picam_viewer/app_full.py`) is a Qt application for the Pi's own desktop, with an
OpenGL preview. It has the same look as the web UI (charcoal ground, green
`#9ACD56`, Lexend font).

## Starting it

From the menu entry **Picam-web (desktop viewer)**, or:

```bash
/opt/picam_viewer/picam_viewer/run_desktop.sh [options]
```

Only one program can open the camera. `run_desktop.sh` therefore stops the `picam-web` service
(with `sudo systemctl stop picam-web`) if it is running, starts the viewer, and starts the service
again when the viewer exits. Running `app_full.py` directly while the service runs fails because the
camera is busy.

```bash
python3 /opt/picam_viewer/picam_viewer/app_full.py [--tuning-file FILE] [--camera N] [--tab NAME] [--roi X,Y,W,H ...]
```

| Option | Default | |
|--------|---------|-|
| `--tuning-file FILE` | libcamera's default | libcamera tuning file (JSON) to use |
| `--camera N` | 0 | camera index |
| `--tab NAME` | first tab | open this settings tab, e.g. `Noise` or `Registers` (case-insensitive) |
| `--roi X,Y,W,H` | none | add a ROI in raw pixels; repeat for more (named ROI1, ROI2, ...) |

On the Wayland desktop the viewer sets `QT_QPA_PLATFORM=xcb` (Xwayland), because the OpenGL preview
cannot initialise EGL as a native Wayland client. Set `QT_QPA_PLATFORM` yourself to override this.

## Layout

The window has the capture settings on the left (**Still Capture** and **Video** tabs with the
**Take Photo** button), the preview in the middle, and the settings tabs on the right. The `>`
button hides or shows the settings tabs. Under the **Take Photo** / **Start recording** button a line
shows where the last photo or video went, or why it failed (for example a folder that does not
exist); the button always works again afterwards.

## Capture tabs

| Tab | |
|-----|-|
| Still Capture | file name and type (`jpg`, `png`, `bmp`, `gif`, `dng`, `raw_tiff`), resolution, sensor mode, preview format |
| Video | file name and container (`mp4`, `mkv`, `ts`, `mov`, `avi`, `h264`), quality, frame rate, resolution (height at most 1080), sensor mode; records H.264 |

## Settings tabs

| Tab | |
|-----|-|
| Image Tuning | saturation, contrast, sharpness, brightness and the other picamera2 image controls |
| Pan/Zoom | scroll to zoom, drag to pan (sets `ScalerCrop`) |
| AEC/AWB | auto exposure (metering, constraint and exposure modes, EV), manual exposure and gain, AWB and colour gains (colour sensors) |
| Info | all per-frame metadata |
| Camera | libcamera camera properties (model, pipeline, pixel array, active area, unit cell size, colour filter, rotation, sensor sensitivity, tuning file), the sensor modes with exposure limits, the current raw and main streams, and `SensorBlackLevels` (16-bit scale and in DN) |
| ISP | every libcamera control not handled by the other tabs (auto-generated from the camera, **Apply** / **Defaults**); free-form `Name=value` controls, one per line (`FrameDurationLimits=33333,33333`); the tuning file in use with its version, target and algorithms; **Switch tuning file**: pick an installed file or browse, then restart the viewer with it |
| ISP Stats | the ISP's own statistics (`StatsOutputEnable`): AGC histogram (1024 bins), 32x32 zone means, 8x8 focus figure of merit; Pi 5 only |
| Frames | frames received, dropped frames, measured fps, expected fps (from `FrameDuration`), last and maximum frame gap, running time |
| Histogram | live raw histogram, per colour channel for Bayer sensors; optional logarithmic counts |
| ROI | named rectangles in raw pixels with their live mean; drawn on the preview; edit a cell to move a ROI. Optionally shows pixel values on the preview when zoomed in so that at most 50 raw pixels span the view |
| Noise | captures N raw frames and shows the noise figures for the full frame or an ROI, with a histogram; **Save...** writes `<name>.csv`, `<name>_mean.tiff` and `<name>_frame0.tiff`. See [Noise analysis](noise.md) |
| Raw | raw bursts (16-bit TIFF in DN or DNG, plus a metadata JSON) and raw video recording. See [Raw data](raw-data.md) |
| Registers | named registers, read / write / poll every 500 ms (8-32 bit; bank and context for sensors whose profile has them), dump ranges and save them as CSV, load register sequences. See [Registers](registers.md) |

The remaining libcamera controls are in the ISP tab (the former Other tab had sliders for the same
controls).

Switching the tuning file restarts the viewer in a new process with `--tuning-file`, keeping the
other options.

The tuning file shown in the ISP tab is a best guess when `--tuning-file` is not given: the
`LIBCAMERA_RPI_TUNING_FILE` environment variable, else `<model>_mono.json` or `<model>.json` in
`/usr/local/share/libcamera/ipa/rpi/<platform>/` or `/usr/share/libcamera/ipa/rpi/<platform>/`.

Noise analysis, histograms, ROIs and raw TIFFs need an unpacked raw mode in the current
configuration.
