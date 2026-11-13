# Web viewer

Open `http://<pi>/` in a browser: <http://raspberrypi.local/> over the USB-C cable, or the Pi's
host name or IP address over Ethernet or Wi-Fi. On the Pi's desktop, the menu entry and the desktop
shortcut **Picam-web** open it in its own window (Chromium app mode; the default
browser when Chromium is not installed).

The page has the live preview on the left and six tabs on the right. The header shows the sensor
model and the raw stream, and links to this documentation (Docs) and the API docs (`/docs`). Under the preview: the measured frame
rate, frames received and dropped frames, or the reason why there are no frames. A banner above the
preview shows when the camera is starting, recovering or failed.

On a phone or any window narrower than 900 pixels the page is one column that scrolls: the preview
on top, the tabs under it as a row you swipe sideways, with larger buttons and fields. One finger
on the preview pans it, two fingers pinch to zoom (the page scrolls from the panel below).

## Preview

| Action | |
|--------|-|
| mouse wheel | zoom in or out around the cursor |
| drag | pan |
| double-click | fit the whole frame |
| Shift + drag | draw a new ROI |
| pinch (touch) | zoom in or out around the fingers; lift one finger to pan on |
| double-tap (touch) | fit the whole frame |

The preview is the ISP-processed image (MJPEG, at most 960 pixels wide, about 30 fps). Zoomed in to
6 or more screen pixels per raw pixel, the raw pixels themselves are drawn (grey, from the raw frame
in DN), from 14 with a pixel grid and from 34 with each pixel's value. The bar under the preview
shows the zoom and the raw position under the cursor, with its value in DN when zoomed in. The raw
values are those of the last analysed frame (4 per second).

## Tabs

### Controls

| Item | |
|------|-|
| Sensor mode | format, size, bit depth and maximum fps; switching restarts the camera |
| Auto exposure | on: exposure and gain follow the camera; off: set them by hand. The tab shows what you set again when you come back to it (the service remembers the values you set) |
| Exposure [µs], Analogue gain | slider (exposure on a log scale) or number; applied when released. The limits are those of the current sensor mode (its exposure range, narrowed to what libcamera reports) and follow a mode switch; a typed value outside them is brought back into range. The limits in force are printed under the fields. A mode with a fixed gain (minimum equals maximum, e.g. the 12-bit modes of some sensors) disables the gain slider |
| Digital gain | 1x to 4x on top of the analogue gain; the total gain is sent and libcamera uses analogue gain first, up to the mode maximum, then digital gain in the ISP. It only scales the processed preview and JPEG, not the raw frames, DNG/TIFF or noise figures. The gains the camera actually applies are shown under the sliders. The 4x maximum is libcamera's `max_digital_gain` (tuning file default) |
| keep after restart | also store the controls, so the service starts with them next time |
| Forget kept controls | the next start uses the defaults again |
| White balance (colour cameras) | **Auto white balance** (on at start): the camera estimates the light, and **Illuminant** limits its search to one kind of light. Off: the current gains are kept and can be changed with **Red gain** and **Blue gain** (green stays at 1x). The values the camera applies are shown underneath. Applied in the ISP: raw frames are not changed |
| Advanced controls (libcamera) | every other control, grouped, with a plain explanation, its range and default, and its libcamera name; modes are lists. Edit values, then **Apply changed** sends only the changed ones. Lists of numbers are comma-separated |
| Tuning file | **default** (libcamera's file for the sensor) or an installed file; files for another sensor or the other colour type are marked. **Restart with this file** checks it, restarts the camera and reloads the page |
| Camera model (dtoverlay) | the sensor overlay in `/boot/firmware/config.txt`: every camera sensor overlay installed (`imx*`, `ov*`, `vd*`, `ar0*` and the sensors of [sensor plugins](registers.md#sensor-plugins)), the connector (CAM1, the default, or CAM0) and the mono option. **Save** rewrites the camera's `dtoverlay=` line under `[all]` (keeping a copy in `config.txt.picam-web.bak`); **Reboot now** loads it. Opens by itself when the camera cannot be opened, since a wrong model is the usual reason, and works without a camera |

### Capture

Downloads to the browser's download folder; errors (a packed sensor mode, too many frames) show
under the buttons.

| Button | File |
|--------|------|
| Download .npz | the given number of raw frames (1-1000, at most 1 GiB) in DN, with the metadata of each frame |
| Raw .tiff | one 16-bit TIFF in DN |
| Raw .dng | one DNG |
| Preview .jpg | the latest preview frame |

See [Raw data](raw-data.md) for the formats.

### Histograms

The live histogram of the raw frame (R, G and B for Bayer sensors, one line for mono sensors), with
mean, min and max in DN. Drag over the plot to zoom into a range, double-click to zoom out;
logarithmic or linear counts. The service only analyses the frames for the histogram while this
tab is open (about 3 s after the last request), and the counts come from every 4th pixel in x and
y, scaled to the whole frame.

**ISP statistics** (Raspberry Pi 5): switch them on to see the ISP's own AGC histogram, its 32x32
zone means and its 8x8 focus figure of merit.

### ROIs & Noise

**ROIs**: named rectangles in raw pixels with their live mean in DN, also drawn on the preview.
**Add** puts one near the centre, Shift+drag on the preview draws one, **✕** removes one, **Apply
edits** sends changed names and positions. ROIs must start inside the frame; width and height are
clipped to it. They are not kept when the service restarts.

**Noise**: captures the given number of raw frames (1-1000) and shows mean, temporal noise, total
FPN, row and column FPN, row and column temporal noise, min and max in DN, for the full frame or a
ROI. See [Noise analysis](noise.md).

### Registers

Direct register access over I2C. Shows the sensor found (name, bus, address).

- **Named register**: registers from the driver; picking one fills in address and size.
- **Address**, **Bytes** (1-4), **Value**: hex (`0x...`) or decimal.
- **Bank** and **Context** (A/B/...): sensors with a banked register map only; "current" leaves them as they are.
- **Read**, **Write**, **Dump** (start address and number of 8-bit registers, up to 4096).

Results go to the log below. Writes bypass the driver; see [Registers](registers.md).

### Status

| Item | |
|------|-|
| Health | the camera state and message |
| Restart stream | stop and start the stream (about 1 s) |
| Reset camera | reopen the camera in a new service process (about 5 s); the page reconnects by itself |
| Reboot Pi | reboot the Raspberry Pi, which power-cycles the sensor |
| Reboot automatically ... | reboot by itself when the camera cannot be recovered |
| History | state changes and recent kernel warnings about the sensor |
| Frames | received, dropped, measured and expected fps, last and maximum gap; **Reset counters**. Drops are gaps in `SensorTimestamp` longer than 1.5 frame durations |
| Camera | model, I2C address, pipeline, pixel array, unit cell, colour filter, raw and preview streams, tuning file, version; the sensor modes; the latest frame's metadata |

The service also recovers by itself when frames stop for 10 s (so exposures up to the sensor
maximum, about 6.6 s, are not cut off): it restarts the stream, then reopens the
camera, then reports *failed* with **Reset camera** and **Reboot Pi** buttons in the banner.

## Performance on small Pis

The UI is meant to stay light for a Raspberry Pi 3 or a Pi Zero 2 W, where the service shares the
CPU with the camera:

- one poll a second for health, frame counters and ROI means; the open tab adds at most one more
  request a second (two for the histogram)
- a page that is not visible (background tab, locked phone) makes no requests and drops the MJPEG
  stream; it connects again when it is shown
- the Histograms tab, with its plot library, is loaded when it is first opened; the service
  computes the histogram, and keeps a copy of the raw frame for the zoomed-in pixel values, only
  for about 3 s after a client asked for them
- the ROIs are drawn by the browser, the service makes no overlay image
- the MJPEG preview is 960 px wide at up to 30 fps (`STREAM_WIDTH`, `STREAM_FPS` in
  `picam_web/camera_service.py`): lower them if a small Pi cannot keep up

## Classic UI

The previous, plain JavaScript UI is still at `http://<pi>/classic` while the new one is tried out.
`/` shows it as well when the new UI is not built (see [Development](development.md#web-ui)).
