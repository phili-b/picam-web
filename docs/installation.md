# Installation

## On a Raspberry Pi

Requirements: Raspberry Pi OS Trixie with the camera's driver and libcamera support installed
(the standard Raspberry Pi cameras work out of the box). `install.sh` also works inside an image
build chroot.

```bash
sudo mkdir -p /opt/picam_viewer
curl -fL https://github.com/phili-b/picam-web/releases/latest/download/picam-web.tar.gz   | sudo tar -xz -C /opt/picam_viewer --strip-components=1
sudo /opt/picam_viewer/install.sh
```

The release archive contains the built web UI (`web/dist`). For another version, replace
`latest/download` with `download/v1.0.0` (a tag). A `git clone` works too, but then the web UI
must be built first (`cd web && npm ci && npm run build`, needs Node.js), else `/` shows the
classic UI.

`install.sh` must run as root. It installs in place, from the directory it is in, and:

1. installs the apt packages listed in `requirements-apt.txt`;
2. installs `systemd/picam-web.service` as `/etc/systemd/system/picam-web.service`, enables it and,
   on a running system (not in a chroot), restarts it; installs `tools/picam-camera-overlay` as
   `/usr/local/sbin/picam-camera-overlay` (root-owned) and `/etc/sudoers.d/picam-web`, which lets the
   service user run only `systemctl reboot` and that helper (it rewrites the camera's `dtoverlay=`
   line in `config.txt`) with sudo;
3. installs two menu entries in `/usr/share/applications/`: `picam_web.desktop` (opens the web UI at
   `http://localhost/`) and `picam_viewer.desktop` (the desktop viewer through `run_desktop.sh`);
4. copies the web UI shortcut to the user's `~/Desktop` (and removes the desktop viewer shortcut
   older versions put there).

The user that runs the service and gets the shortcut is `$VIEWER_USER`, else `$SUDO_USER`, else `pi`.

At the end it prints the web UI address (`http://<hostname>.local/`) and the path of the desktop
viewer launcher.

### Apt dependencies

From `requirements-apt.txt`:

| Package | Used for |
|---------|----------|
| `python3-picamera2` | camera access |
| `python3-pyqt5`, `python3-pyqt5.qtopengl`, `python3-opengl` | desktop viewer |
| `python3-numpy` | analysis |
| `python3-opencv` | desktop viewer (optional import) |
| `python3-pil` | TIFF files, overlays |
| `python3-smbus2` | I2C register access |
| `python3-rpi-lgpio` | GPIO tools |
| `ffmpeg` | video recording in the desktop viewer |
| `python3-fastapi`, `python3-uvicorn` | web service |
| `python3-simplejpeg` | JPEG preview stream |

## The web service

The systemd unit `picam-web` runs:

```
/usr/bin/python3 <install dir>/picam_web/server.py --port 80
```

as the viewer user, with `CAP_NET_BIND_SERVICE` so it can use port 80 without root, and
`Restart=always` (2 s). The service exits with code 3 to restart itself with another tuning file.

```bash
sudo systemctl status picam-web
sudo systemctl restart picam-web
journalctl -u picam-web -f
```

`server.py` options:

| Option | Default | |
|--------|---------|-|
| `--host` | `0.0.0.0` | address to listen on |
| `--port` | `80` | HTTP port |
| `--camera` | `0` | camera index |
| `--tuning-file` | none | libcamera tuning file (JSON) |

The service remembers the sensor mode, the tuning file and (when asked) the controls in
`~/.config/picam_web.json`, and starts with them next time.

## Python API on a PC

Only the `picam_client` package is installed by pip; it needs only numpy (Python 3.9 or later):

```bash
pip install "git+https://github.com/phili-b/picam-web.git"
```

See [Python API](python-api.md).
