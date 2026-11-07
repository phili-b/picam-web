"""Tabs built on what libcamera and picamera2 already provide: camera properties, ISP
statistics, tuning file switching, raw bursts and raw video recording."""

import glob
import json
import logging
import os
import sys
import threading
import time

import numpy as np
from PIL import Image
from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

import analysis
import isp_stats
import live
from panels import HistogramWidget

log = logging.getLogger("picam_viewer")

CFA_NAMES = {0: "RGGB", 1: "GRBG", 2: "GBRG", 3: "BGGR", 4: "RGB", 5: "mono"}


def _jsonable(value):
    """Metadata values as JSON: tuples/lists stay lists, numpy and libcamera types become numbers or text."""
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(value)} bytes>"
    return str(value)


def metadata_json(metadata):
    return {k: _jsonable(v) for k, v in metadata.items() if k not in ("PispStatsOutput", "Bcm2835StatsOutput")}


# ---------------------------------------------------------------------------
# Camera properties
# ---------------------------------------------------------------------------
class CameraTab(QWidget):
    """libcamera camera properties, the sensor modes and live values from the metadata."""

    def __init__(self, picam2, tuning_path=None):
        super().__init__()
        self.picam2 = picam2
        self.black_levels = None
        layout = QVBoxLayout(self)

        props = QGroupBox("Camera properties (libcamera)")
        form = QFormLayout(props)
        p = picam2.camera_properties
        rows = [
            ("Model", p.get("Model")),
            ("Pipeline", p.get("PipelineHandler")),
            ("Pixel array", "x".join(map(str, p.get("PixelArraySize", ())))),
            ("Active area", p.get("PixelArrayActiveAreas")),
            ("Unit cell size", f"{p['UnitCellSize'][0]} x {p['UnitCellSize'][1]} nm" if "UnitCellSize" in p else None),
            ("Colour filter", CFA_NAMES.get(p.get("ColorFilterArrangement"), p.get("ColorFilterArrangement"))),
            ("Rotation", p.get("Rotation")),
            ("Sensor sensitivity", p.get("SensorSensitivity")),
            ("Tuning file", tuning_path or "default (see ISP tab)"),
        ]
        for name, value in rows:
            if value is not None:
                lbl = QLabel(str(value))
                lbl.setWordWrap(True)
                lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
                form.addRow(name, lbl)
        layout.addWidget(props)

        modes = QGroupBox("Sensor modes")
        ml = QVBoxLayout(modes)
        cols = ["Format", "Size", "Bits", "Max fps", "Crop", "Exposure [us]"]
        table = QTableWidget(len(picam2.sensor_modes), len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        for r, m in enumerate(picam2.sensor_modes):
            exp = m.get("exposure_limits") or ()
            values = [m["unpacked"], f"{m['size'][0]}x{m['size'][1]}", m["bit_depth"], f"{m['fps']:.1f}",
                      m.get("crop_limits"), f"{exp[0]}-{exp[1]}" if len(exp) >= 2 else ""]
            for c, v in enumerate(values):
                table.setItem(r, c, QTableWidgetItem(str(v)))
        ml.addWidget(table)
        layout.addWidget(modes)

        self.live = QLabel()
        self.live.setWordWrap(True)
        self.live.setTextInteractionFlags(Qt.TextSelectableByMouse)
        live_box = QGroupBox("Current")
        QVBoxLayout(live_box).addWidget(self.live)
        layout.addWidget(live_box)
        layout.addStretch(1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)

    def update_metadata(self, metadata):
        self.black_levels = metadata.get("SensorBlackLevels")

    def refresh(self):
        if not self.isVisible():
            return
        cfg = self.picam2.camera_config or {}
        lines = []
        raw = cfg.get("raw")
        if raw:
            lines.append(f"Raw stream: {raw['format']} {raw['size'][0]}x{raw['size'][1]}, stride {raw.get('stride')}")
        main = cfg.get("main")
        if main:
            lines.append(f"Main stream: {main['format']} {main['size'][0]}x{main['size'][1]}")
        if self.black_levels:
            try:
                _, _, bits, _ = live.raw_info(self.picam2)
                in_dn = [v >> (16 - bits) for v in self.black_levels] if bits else None
            except ValueError:
                in_dn = None
            lines.append("SensorBlackLevels: " + ", ".join(map(str, self.black_levels)) + " (16-bit scale)"
                         + (f" = {', '.join(map(str, in_dn))} DN" if in_dn else ""))
        self.live.setText("\n".join(lines))


# ---------------------------------------------------------------------------
# ISP statistics
# ---------------------------------------------------------------------------
class HeatMap(QWidget):
    """A small 2D array drawn as a grey-scale (or RGB) image, scaled to the widget."""

    def __init__(self, title, min_height=140):
        super().__init__()
        self.title = title
        self.data = None
        self.setMinimumHeight(min_height)

    def set_data(self, data):
        self.data = data
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(20, 22, 20))
        if self.data is not None and self.data.size:
            d = self.data.astype(np.float64)
            top = d.max()
            img = np.zeros(d.shape[:2] + (3,), np.uint8)
            if top > 0:
                scaled = np.clip(d / top * 255, 0, 255).astype(np.uint8)
                img[:] = scaled[..., None] if scaled.ndim == 2 else scaled
            h, w = img.shape[:2]
            qimg = QImage(np.ascontiguousarray(img).data, w, h, 3 * w, QImage.Format_RGB888)
            side = min(self.width(), self.height() - 16)
            p.drawPixmap(0, 16, QPixmap.fromImage(qimg).scaled(side * w // max(w, h), side * h // max(w, h)))
        p.setPen(QColor(145, 150, 157))
        p.drawText(0, 12, self.title)


class IspStatsTab(QWidget):
    """The ISP's own statistics (libcamera StatsOutputEnable): AGC histogram, zone means, focus."""

    def __init__(self, picam2):
        super().__init__()
        self.picam2 = picam2
        self.latest = None
        self.error = None
        self.received = 0
        layout = QVBoxLayout(self)
        self.enable = QCheckBox("Enable ISP statistics output (StatsOutputEnable)")
        self.enable.stateChanged.connect(self.on_enable)
        layout.addWidget(self.enable)
        layout.addWidget(QLabel("AGC histogram (ISP front end, 1024 bins)"))
        self.hist = HistogramWidget(min_height=150)
        layout.addWidget(self.hist)
        maps = QHBoxLayout()
        self.zones = HeatMap("Zone means 32x32")
        self.focus = HeatMap("Focus FoM 8x8")
        maps.addWidget(self.zones)
        maps.addWidget(self.focus)
        layout.addLayout(maps, 1)
        self.label = QLabel("Statistics are off.")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(300)

    def on_enable(self, state):
        try:
            self.picam2.set_controls({"StatsOutputEnable": bool(state)})
            self.label.setText("Waiting for statistics..." if state else "Statistics are off.")
        except (KeyError, RuntimeError) as e:
            self.label.setText(f"StatsOutputEnable is not supported: {e}")

    def update_metadata(self, metadata):
        if not self.enable.isChecked():
            return
        try:
            stats = isp_stats.decode(metadata)
        except ValueError as e:
            self.error = str(e)
            return
        if stats:
            self.latest = stats
            self.received += 1

    def refresh(self):
        if not self.isVisible() or not self.enable.isChecked():
            return
        if self.error:
            self.label.setText(self.error)
            return
        s = self.latest
        if not s:
            return
        if s["platform"] != "pisp":
            self.label.setText("This Raspberry Pi returns VC4 (Pi 4) statistics, which are not decoded.")
            return
        self.hist.set_data(s["histogram"])
        self.zones.set_data(s["zones_rgb"] if not self.picam2.is_mono else s["zones_mean"])
        self.focus.set_data(s["focus"])
        self.label.setText(f"{self.received} statistics frames received (the ISP does not produce them "
                           f"for every frame). Zone mean range {s['zones_mean'].min():.0f}-{s['zones_mean'].max():.0f}.")


# ---------------------------------------------------------------------------
# Tuning files
# ---------------------------------------------------------------------------
def tuning_files():
    """Installed tuning files for this platform: /usr/local (the fork) first, then /usr."""
    try:
        with open("/proc/device-tree/model") as fh:
            platform = "pisp" if "Raspberry Pi 5" in fh.read() else "vc4"
    except OSError:
        platform = "vc4"
    found = []
    for prefix in ("/usr/local/share/libcamera/ipa/rpi", "/usr/share/libcamera/ipa/rpi"):
        found += sorted(glob.glob(os.path.join(prefix, platform, "*.json")))
    return found


def restart_with_tuning(picam2, path):
    """Close the camera and restart the viewer with --tuning-file path (other options kept)."""
    argv, skip = [], False
    for a in sys.argv[1:]:
        if skip:
            skip = False
            continue
        if a == "--tuning-file":
            skip = True
            continue
        if a.startswith("--tuning-file="):
            continue
        argv.append(a)
    import subprocess
    try:
        picam2.stop()
    finally:
        picam2.close()
    # A fresh process, not os.execv: execv keeps libcamera's media device handles open and the new
    # image then finds no camera. The new viewer waits a moment for this one to exit.
    subprocess.Popen([sys.executable, "-c", "import time, subprocess, sys; time.sleep(2); "
                      "subprocess.run(sys.argv[1:])", sys.executable, os.path.abspath(sys.argv[0]), *argv,
                      "--tuning-file", path], start_new_session=True, close_fds=True)
    os._exit(0)


class TuningBox(QGroupBox):
    def __init__(self, picam2, current):
        super().__init__("Switch tuning file")
        self.picam2 = picam2
        layout = QVBoxLayout(self)
        self.combo = QComboBox()
        for f in tuning_files():
            self.combo.addItem(f)
        if current:
            i = self.combo.findText(current)
            if i < 0:
                self.combo.addItem(current)
                i = self.combo.count() - 1
            self.combo.setCurrentIndex(i)
        row = QHBoxLayout()
        browse = QPushButton("Browse...")
        browse.clicked.connect(self.browse)
        apply_btn = QPushButton("Restart with this tuning file")
        apply_btn.clicked.connect(self.apply)
        row.addWidget(browse)
        row.addWidget(apply_btn)
        layout.addWidget(self.combo)
        layout.addLayout(row)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Tuning file", os.path.dirname(self.combo.currentText() or "/"),
                                              "Tuning files (*.json)")
        if path:
            self.combo.addItem(path)
            self.combo.setCurrentIndex(self.combo.count() - 1)

    def apply(self):
        path = self.combo.currentText()
        if path and os.path.isfile(path):
            restart_with_tuning(self.picam2, path)


# ---------------------------------------------------------------------------
# Raw burst and raw video
# ---------------------------------------------------------------------------
class _Signals(QObject):
    done = pyqtSignal(str)
    progress = pyqtSignal(str)


class RawTab(QWidget):
    """Raw bursts (TIFF/DNG + metadata JSON) and raw video recording."""

    def __init__(self, picam2):
        super().__init__()
        self.picam2 = picam2
        self.sig = _Signals()
        self.sig.done.connect(self.on_done)
        self.sig.progress.connect(lambda t: self.status.setText(t))
        self.recording = None
        layout = QVBoxLayout(self)

        out = QGroupBox("Output")
        of = QFormLayout(out)
        self.folder = QLineEdit(os.path.expanduser("~/captures"))
        pick = QPushButton("...")
        pick.setFixedWidth(30)
        pick.clicked.connect(self.pick_folder)
        fr = QHBoxLayout()
        fr.addWidget(self.folder)
        fr.addWidget(pick)
        self.prefix = QLineEdit("raw")
        of.addRow("Folder", fr)
        of.addRow("Name prefix", self.prefix)
        layout.addWidget(out)

        burst = QGroupBox("Raw burst")
        bf = QFormLayout(burst)
        self.count = QSpinBox()
        self.count.setRange(1, 500)
        self.count.setValue(10)
        self.fmt = QComboBox()
        self.fmt.addItems(["tiff (16-bit, DN)", "dng"])
        self.burst_btn = QPushButton("Capture burst")
        burst_note = QLabel("Frames can be skipped at high frame rates; their timestamps are in the JSON. "
                            "For every consecutive frame, use raw video.")
        burst_note.setWordWrap(True)
        self.burst_btn.clicked.connect(self.on_burst)
        bf.addRow("Frames", self.count)
        bf.addRow("Format", self.fmt)
        bf.addRow(self.burst_btn)
        bf.addRow(burst_note)
        layout.addWidget(burst)

        video = QGroupBox("Raw video")
        vl = QVBoxLayout(video)
        self.video_btn = QPushButton("Start raw recording")
        self.video_btn.clicked.connect(self.on_video)
        vl.addWidget(self.video_btn)
        vl.addWidget(QLabel("Writes <prefix>.raw (frames as the raw stream delivers them), <prefix>_pts.txt "
                            "(timestamps) and <prefix>.json (format to read it back: "
                            "analysis.read_raw_video)."))
        for w in vl.parentWidget().findChildren(QLabel):
            w.setWordWrap(True)
        layout.addWidget(video)

        self.status = QLabel("Needs a raw stream (Still Capture tab).")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch(1)

    def pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Output folder", self.folder.text())
        if path:
            self.folder.setText(path)

    def _base(self):
        folder = os.path.expanduser(self.folder.text())
        os.makedirs(folder, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        return os.path.join(folder, f"{self.prefix.text() or 'raw'}_{stamp}")

    # Burst --------------------------------------------------------------------------------
    def on_burst(self):
        try:
            fmt, size, bits, _ = live.raw_info(self.picam2)
            base = self._base()
        except (ValueError, OSError) as e:
            self.status.setText(str(e))
            return
        self.burst_btn.setEnabled(False)
        threading.Thread(target=self._burst, args=(base, self.count.value(), self.fmt.currentIndex() == 1,
                                                   fmt, size, bits), daemon=True).start()

    def _burst(self, base, n, dng, fmt, size, bits):
        # Worker thread: frames go to memory first so they are consecutive, then to disk.
        try:
            frames = []
            for i in range(n):
                self.sig.progress.emit(f"Capturing {i + 1}/{n}...")
                # Only copy the buffer here: anything slower makes the burst skip frames
                request = self.picam2.capture_request()
                try:
                    frames.append((request.make_buffer("raw").copy(), request.get_metadata()))
                finally:
                    request.release()
            raw_cfg = self.picam2.camera_config["raw"]
            meta = []
            for i, (data, md) in enumerate(frames):
                self.sig.progress.emit(f"Saving {i + 1}/{n}...")
                name = f"{base}_{i:04d}.{'dng' if dng else 'tiff'}"
                if dng:
                    self.picam2.helpers.save_dng(data, md, raw_cfg, name)
                else:
                    arr = np.asarray(data, dtype=np.uint8).reshape(size[1], raw_cfg["stride"])
                    img, _ = analysis.raw_to_image(arr, fmt, size, bits)
                    Image.fromarray(img.astype(np.uint16)).save(name)
                meta.append({"file": os.path.basename(name), **metadata_json(md)})
            with open(base + "_metadata.json", "w") as fh:
                json.dump({"format": fmt, "size": list(size), "bit_depth": bits,
                           "values": "DN" if not dng else "DNG", "frames": meta}, fh, indent=1)
            ts = [m.get("SensorTimestamp") for m in meta if m.get("SensorTimestamp")]
            gaps = np.diff(ts) / 1e6 if len(ts) > 1 else []
            gap_txt = f", frame gaps {min(gaps):.2f}-{max(gaps):.2f} ms" if len(gaps) else ""
            self.sig.done.emit(f"Saved {n} frames to {base}_*{gap_txt}")
        except Exception as e:
            log.exception("raw burst failed")
            self.sig.done.emit(f"Error: {e}")

    def on_done(self, text):
        self.status.setText(text)
        self.burst_btn.setEnabled(True)

    # Raw video ----------------------------------------------------------------------------
    def on_video(self):
        from picamera2.encoders import Encoder
        from picamera2.outputs import FileOutput
        if self.recording:
            self.picam2.stop_encoder(self.recording["encoder"])
            self.video_btn.setText("Start raw recording")
            self.burst_btn.setEnabled(True)
            size = os.path.getsize(self.recording["path"]) if os.path.exists(self.recording["path"]) else 0
            frames = size // self.recording["frame_bytes"] if self.recording["frame_bytes"] else 0
            self.status.setText(f"Recorded {frames} frames ({size / 1e6:.1f} MB) to {self.recording['path']}")
            self.recording = None
            return
        try:
            fmt, size, bits, _ = live.raw_info(self.picam2)
            base = self._base()
        except (ValueError, OSError) as e:
            self.status.setText(str(e))
            return
        raw_cfg = self.picam2.camera_config["raw"]
        frame_bytes = raw_cfg["stride"] * raw_cfg["size"][1]
        with open(base + ".json", "w") as fh:
            json.dump({"format": fmt, "size": list(size), "stride": raw_cfg["stride"], "bit_depth": bits,
                       "frame_bytes": frame_bytes, "pts": os.path.basename(base) + "_pts.txt"}, fh, indent=1)
        encoder = Encoder()
        self.picam2.start_encoder(encoder, FileOutput(base + ".raw", pts=base + "_pts.txt"), name="raw")
        self.recording = {"encoder": encoder, "path": base + ".raw", "frame_bytes": frame_bytes}
        self.video_btn.setText("Stop raw recording")
        self.burst_btn.setEnabled(False)
        self.status.setText(f"Recording to {base}.raw ...")
