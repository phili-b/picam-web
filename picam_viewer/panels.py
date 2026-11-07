"""Extra viewer tabs: registers, noise analysis, frame statistics and libcamera ISP controls."""

import csv
import json
import logging
import os
import threading
import time

import numpy as np
from PIL import Image
from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                             QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                             QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

import analysis
import live
import sensor_regs

log = logging.getLogger("picam_viewer")


def _hex(text):
    return sensor_regs.parse_int(text)


# ---------------------------------------------------------------------------
# Registers
# ---------------------------------------------------------------------------
class RegisterTab(QWidget):
    """Read, write, dump and watch sensor registers (through the driver's controls, else over I2C)."""

    def __init__(self, model=None):
        super().__init__()
        self.info = sensor_regs.find_sensor(names=[model] if model else ())
        self.regs = None
        error = None
        if self.info:
            try:
                self.regs = sensor_regs.SensorRegs(self.info)
            except (OSError, RuntimeError) as e:
                error = str(e)

        layout = QVBoxLayout(self)
        status = str(self.info) if self.info else "No sensor found on an I2C bus"
        if self.regs:
            status += " - " + ("through the driver" if self.regs.backend == "driver"
                               else "directly over I2C (driver without register controls)")
        if error:
            status += f"\n{error}"
        self.status = QLabel(status)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        warn = QLabel("The driver does not know about writes; it may overwrite them on a mode switch, stream "
                      "start or exposure change.")
        warn.setWordWrap(True)
        layout.addWidget(warn)

        # Single register access
        box = QGroupBox("Register")
        form = QFormLayout(box)
        self.known = QComboBox()
        self.known.addItem("(address below)")
        for name, addr, nbytes in (self.info.registers if self.info else []):
            self.known.addItem(f"{name}  0x{addr:04X}", (addr, nbytes))
        self.known.currentIndexChanged.connect(self.on_known)
        self.addr = QLineEdit("0x0000")
        self.width = QComboBox()
        self.width.addItems(["8 bit", "16 bit", "24 bit", "32 bit"])
        self.bank = QComboBox()
        self.bank.addItems(["current", "0", "1"])
        self.context = QComboBox()
        names = self.info.contexts if self.info else ""
        self.context.addItems(["current"] + [f"{n} ({i})" for i, n in enumerate(names)])
        self.value = QLineEdit("0x00")
        rw = QWidget()
        rw_layout = QHBoxLayout(rw)
        rw_layout.setContentsMargins(0, 0, 0, 0)
        read_btn = QPushButton("Read")
        read_btn.clicked.connect(self.on_read)
        write_btn = QPushButton("Write")
        write_btn.clicked.connect(self.on_write)
        rw_layout.addWidget(read_btn)
        rw_layout.addWidget(write_btn)
        if self.known.count() > 1:
            form.addRow("Known register", self.known)
        form.addRow("Address", self.addr)
        form.addRow("Width", self.width)
        if self.info and self.info.banked:
            form.addRow("Bank", self.bank)
            form.addRow("Context", self.context)
        form.addRow("Value", self.value)
        form.addRow(rw)
        self.watch = QCheckBox("Poll every 500 ms")
        self.watch.stateChanged.connect(self.on_watch)
        form.addRow(self.watch)
        layout.addWidget(box)

        # Dump and sequences
        box2 = QGroupBox("Dump / sequence")
        grid = QGridLayout(box2)
        self.dump_start = QLineEdit("0x0000")
        self.dump_count = QSpinBox()
        self.dump_count.setRange(1, 4096)
        self.dump_count.setValue(64)
        dump_btn = QPushButton("Dump")
        dump_btn.clicked.connect(self.on_dump)
        save_btn = QPushButton("Save dump...")
        save_btn.clicked.connect(self.on_save_dump)
        seq_btn = QPushButton("Load sequence...")
        seq_btn.clicked.connect(self.on_sequence)
        grid.addWidget(QLabel("Start"), 0, 0)
        grid.addWidget(self.dump_start, 0, 1)
        grid.addWidget(QLabel("Count"), 0, 2)
        grid.addWidget(self.dump_count, 0, 3)
        grid.addWidget(dump_btn, 1, 0, 1, 2)
        grid.addWidget(save_btn, 1, 2, 1, 2)
        grid.addWidget(seq_btn, 2, 0, 1, 4)
        layout.addWidget(box2)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        layout.addWidget(self.log, 1)

        self.last_dump = []
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_read)
        for w in (read_btn, write_btn, dump_btn, save_btn, seq_btn, self.watch):
            w.setEnabled(self.regs is not None)

    def on_known(self, index):
        data = self.known.itemData(index)
        if data:
            addr, nbytes = data
            self.addr.setText(f"0x{addr:04x}")
            self.width.setCurrentIndex(nbytes - 1)

    def _sel(self):
        bank = None if self.bank.currentIndex() == 0 else self.bank.currentIndex() - 1
        ctx = None if self.context.currentIndex() == 0 else self.context.currentIndex() - 1
        if not (self.info and self.info.banked):
            bank = ctx = None
        return bank, ctx

    def _nbytes(self):
        return self.width.currentIndex() + 1

    def _print(self, text):
        self.log.appendPlainText(f"{time.strftime('%H:%M:%S')} {text}")

    def _guard(self, fn):
        try:
            return fn()
        except (ValueError, OSError) as e:
            self._print(f"ERROR: {e}")
            if self.watch.isChecked():
                self.watch.setChecked(False)
            return None

    def on_read(self):
        def do():
            reg = _hex(self.addr.text())
            n = self._nbytes()
            bank, ctx = self._sel()
            v = self.regs.read(reg, n, bank, ctx)
            self.value.setText(f"0x{v:0{2 * n}x}")
            self._print(f"read  0x{reg:04x} = 0x{v:0{2 * n}x} ({v})" + self._bank_txt(bank, ctx))
        self._guard(do)

    def on_write(self):
        def do():
            reg = _hex(self.addr.text())
            n = self._nbytes()
            v = _hex(self.value.text())
            if v >= 1 << (8 * n):
                raise ValueError(f"0x{v:x} does not fit in {8 * n} bits")
            bank, ctx = self._sel()
            self.regs.write(reg, v, n, bank, ctx)
            self._print(f"write 0x{reg:04x} = 0x{v:0{2 * n}x}" + self._bank_txt(bank, ctx))
        self._guard(do)

    @staticmethod
    def _bank_txt(bank, ctx):
        parts = []
        if bank is not None:
            parts.append(f"bank {bank}")
        if ctx is not None:
            parts.append("context " + "AB"[ctx])
        return f"  [{', '.join(parts)}]" if parts else ""

    def on_watch(self, state):
        if state:
            self.timer.start(500)
        else:
            self.timer.stop()

    def on_dump(self):
        def do():
            start = _hex(self.dump_start.text())
            bank, ctx = self._sel()
            self.last_dump = self.regs.dump(start, self.dump_count.value(), bank, ctx)
            lines = []
            for i in range(0, len(self.last_dump), 16):
                row = self.last_dump[i:i + 16]
                lines.append(f"0x{row[0][0]:04x}: " + " ".join(f"{v:02x}" for _, v in row))
            self._print(f"dump 0x{start:04x} +{len(self.last_dump)}{self._bank_txt(bank, ctx)}\n" + "\n".join(lines))
        self._guard(do)

    def on_save_dump(self):
        if not self.last_dump:
            self._print("Nothing dumped yet")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save register dump", "register_dump.csv", "CSV (*.csv)")
        if path:
            with open(path, "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["addr", "value"])
                w.writerows([(f"0x{a:04x}", f"0x{v:02x}") for a, v in self.last_dump])
            self._print(f"saved {path}")

    def on_sequence(self):
        path, _ = QFileDialog.getOpenFileName(self, "Register sequence", "",
                                              "Sequences (*.txt *.csv);;All files (*)")
        if not path:
            return
        try:
            seq = sensor_regs.parse_sequence(path)
        except (OSError, ValueError) as e:
            self._print(f"ERROR: {e}")
            return
        if not seq:
            self._print(f"no 'write <value> to <addr>' or 'addr,value' lines in {path}")
            return
        if QMessageBox.question(self, "Write sequence",
                                f"Write {len(seq)} registers from {os.path.basename(path)}?") != QMessageBox.Yes:
            return
        n = self._guard(lambda: self.regs.write_sequence(seq))
        if n:
            self._print(f"wrote {n} registers from {path}")


# ---------------------------------------------------------------------------
# Noise analysis
# ---------------------------------------------------------------------------
class HistogramWidget(QWidget):
    """Histogram of one or more channels: a single array, or {name: counts} drawn as lines."""

    CHANNEL_COLOURS = {"R": QColor(255, 90, 90), "G": QColor(154, 205, 86), "B": QColor(80, 160, 255),
                       "Y": QColor(220, 222, 218)}

    def __init__(self, min_height=120):
        super().__init__()
        self.counts = None
        self.log = True
        self.setMinimumHeight(min_height)

    def set_data(self, counts):
        self.counts = counts if isinstance(counts, dict) else ({"Y": counts} if counts is not None else None)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(20, 22, 20))
        if not self.counts:
            return
        scaled = {k: (np.log1p(v.astype(np.float64)) if self.log else v.astype(np.float64))
                  for k, v in self.counts.items()}
        top = max(float(v.max()) for v in scaled.values())
        if top <= 0:
            return
        w, h = self.width(), self.height()
        p.setRenderHint(QPainter.Antialiasing)
        for name, v in scaled.items():
            p.setPen(self.CHANNEL_COLOURS.get(name, QColor(220, 222, 218)))
            n = len(v)
            prev = None
            for i, val in enumerate(v):
                pt = (int(i * (w - 1) / max(1, n - 1)), int(h - 1 - val / top * (h - 4)))
                if prev:
                    p.drawLine(prev[0], prev[1], pt[0], pt[1])
                prev = pt


class _Signals(QObject):
    done = pyqtSignal(object)
    progress = pyqtSignal(str)


class NoiseTab(QWidget):
    """Capture N raw frames and compute noise figures for an ROI."""

    def __init__(self, picam2, live_view=None):
        super().__init__()
        self.picam2 = picam2
        self.live_view = live_view
        self.sig = _Signals()
        self.sig.done.connect(self.on_done)
        self.sig.progress.connect(lambda t: self.status.setText(t))
        self.frames = None
        self.result = None

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.n_frames = QSpinBox()
        self.n_frames.setRange(1, 200)
        self.n_frames.setValue(16)
        self.roi_x = QSpinBox()
        self.roi_y = QSpinBox()
        self.roi_w = QSpinBox()
        self.roi_h = QSpinBox()
        for s in (self.roi_x, self.roi_y, self.roi_w, self.roi_h):
            s.setRange(0, 20000)
        self.full = QCheckBox("Full frame")
        self.full.setChecked(True)
        self.full.stateChanged.connect(self._roi_enable)
        roi = QWidget()
        rl = QHBoxLayout(roi)
        rl.setContentsMargins(0, 0, 0, 0)
        for lbl, s in (("x", self.roi_x), ("y", self.roi_y), ("w", self.roi_w), ("h", self.roi_h)):
            rl.addWidget(QLabel(lbl))
            rl.addWidget(s)
        form.addRow("Frames", self.n_frames)
        self.roi_pick = QComboBox()
        self.roi_pick.addItem("(enter below)")
        self.roi_pick.activated.connect(self.on_roi_pick)
        form.addRow(self.full)
        form.addRow("Use ROI", self.roi_pick)
        form.addRow("ROI", roi)
        layout.addLayout(form)

        btns = QHBoxLayout()
        self.run_btn = QPushButton("Capture && analyse")
        self.run_btn.clicked.connect(self.on_run)
        self.save_btn = QPushButton("Save...")
        self.save_btn.clicked.connect(self.on_save)
        self.save_btn.setEnabled(False)
        btns.addWidget(self.run_btn)
        btns.addWidget(self.save_btn)
        layout.addLayout(btns)

        self.status = QLabel("Uses the raw stream of the current sensor mode (needs an unpacked mode).")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.hist = HistogramWidget()
        layout.addWidget(self.hist)
        self.table = QLabel()
        self.table.setTextFormat(Qt.RichText)
        self.table.setAlignment(Qt.AlignTop)
        self.table.setTextInteractionFlags(Qt.TextSelectableByMouse)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.table)
        layout.addWidget(scroll, 1)
        self._roi_enable()

    def refresh_rois(self):
        """Fill the ROI chooser with the ROIs of the ROI tab."""
        self.roi_pick.clear()
        self.roi_pick.addItem("(enter below)")
        for r in (self.live_view.rois if self.live_view else []):
            self.roi_pick.addItem(f"{r.name} ({r.x}, {r.y}, {r.w}x{r.h})", r.rect)

    def on_roi_pick(self, index):
        rect = self.roi_pick.itemData(index)
        if rect:
            self.full.setChecked(False)
            for s, v in zip((self.roi_x, self.roi_y, self.roi_w, self.roi_h), rect):
                s.setValue(v)

    def _roi_enable(self):
        for s in (self.roi_x, self.roi_y, self.roi_w, self.roi_h):
            s.setEnabled(not self.full.isChecked())

    def _raw_info(self):
        fmt, size, bits, _ = live.raw_info(self.picam2)
        return fmt, size, bits

    def on_run(self):
        try:
            fmt, size, bits = self._raw_info()
        except ValueError as e:
            self.status.setText(str(e))
            return
        if self.full.isChecked():
            self.roi_x.setValue(0)
            self.roi_y.setValue(0)
            self.roi_w.setValue(size[0])
            self.roi_h.setValue(size[1])
        n = self.n_frames.value()
        roi = None if self.full.isChecked() else (self.roi_x.value(), self.roi_y.value(),
                                                  self.roi_w.value(), self.roi_h.value())
        self.run_btn.setEnabled(False)
        threading.Thread(target=self._capture, args=(fmt, size, bits, n, roi), daemon=True).start()

    def _capture(self, fmt, size, bits, n, roi):
        # Runs in a worker thread: capture_array waits for requests that the
        # Qt preview processes in the GUI thread, so it must not block that thread.
        try:
            frames = []
            for i in range(n):
                self.sig.progress.emit(f"Capturing frame {i + 1}/{n}...")
                arr = self.picam2.capture_array("raw")
                img, depth = analysis.raw_to_image(arr, fmt, size, bits)
                frames.append(img.copy())
            result = analysis.noise_stats(frames, roi)
            counts, _ = analysis.histogram(analysis.crop(frames[0], roi), depth)
            self.sig.done.emit({"frames": frames, "result": result, "counts": counts, "fmt": fmt,
                                "bits": depth, "roi": roi, "size": size})
        except Exception as e:  # report anything to the GUI instead of losing the thread
            log.exception("noise capture failed")
            self.sig.done.emit({"error": str(e)})

    def on_done(self, out):
        self.run_btn.setEnabled(True)
        if "error" in out:
            self.status.setText(f"Error: {out['error']}")
            return
        self.frames = out["frames"]
        self.result = out
        self.hist.set_data(out["counts"])
        self.save_btn.setEnabled(True)
        roi = out["roi"] or (0, 0, *out["size"])
        self.status.setText(f"{len(self.frames)} frames, {out['fmt']} {out['bits']}-bit, "
                            f"ROI {roi[2]}x{roi[3]} at ({roi[0]},{roi[1]})")
        self.table.setText(self._html(out["result"]))

    ROWS = [("mean", "Mean"), ("min", "Min"), ("max", "Max"), ("temporal_noise", "Temporal noise"),
            ("fpn", "Total FPN"), ("row_fpn", "Row FPN"), ("col_fpn", "Column FPN"),
            ("row_temporal_noise", "Row temporal noise"), ("col_temporal_noise", "Column temporal noise")]

    @classmethod
    def _html(cls, result):
        html = "<table cellspacing=6>"
        for key, name in cls.ROWS:
            value = "-" if result[key] != result[key] else f"{result[key]:.3f}"  # NaN -> "-"
            html += f"<tr><td>{name} [DN]</td><td align=right>{value}</td></tr>"
        return html + "</table>"

    def on_save(self):
        if not self.result:
            return
        base, _ = QFileDialog.getSaveFileName(self, "Save noise results (CSV + mean frame TIFF)",
                                              "noise.csv", "CSV (*.csv)")
        if not base:
            return
        stem = base[:-4] if base.lower().endswith(".csv") else base
        res = self.result["result"]
        with open(stem + ".csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["quantity", "value"])
            w.writerows(sorted(res.items()))
        mean = np.mean(np.asarray(self.frames, dtype=np.float32), axis=0)
        Image.fromarray(np.clip(mean, 0, 65535).astype(np.uint16)).save(stem + "_mean.tiff")
        Image.fromarray(self.frames[0].astype(np.uint16)).save(stem + "_frame0.tiff")
        self.status.setText(f"Saved {stem}.csv, {stem}_mean.tiff and {stem}_frame0.tiff")


# ---------------------------------------------------------------------------
# Frame statistics
# ---------------------------------------------------------------------------
class FrameTab(QWidget):
    """Frame counter, measured vs expected fps and dropped frames."""

    def __init__(self):
        super().__init__()
        self.stats = analysis.FrameStats()
        layout = QVBoxLayout(self)
        self.label = QLabel()
        self.label.setTextFormat(Qt.RichText)
        self.label.setAlignment(Qt.AlignTop)
        layout.addWidget(self.label)
        reset = QPushButton("Reset counters")
        reset.clicked.connect(self.stats.reset)
        layout.addWidget(reset)
        note = QLabel("Drops are gaps in SensorTimestamp longer than 1.5 frame durations. "
                      "Counts reset when the camera configuration changes.")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(250)

    def update_metadata(self, metadata):
        self.stats.update(metadata)

    def refresh(self):
        s = self.stats
        elapsed = time.monotonic() - s.started
        self.label.setText(
            "<table cellspacing=6>"
            f"<tr><td>Frames received</td><td align=right><b>{s.frames}</b></td></tr>"
            f"<tr><td>Dropped frames</td><td align=right><b>{s.dropped}</b></td></tr>"
            f"<tr><td>Measured fps</td><td align=right>{s.fps:.2f}</td></tr>"
            f"<tr><td>Expected fps (FrameDuration)</td><td align=right>{s.expected_fps:.2f}</td></tr>"
            f"<tr><td>Last frame gap</td><td align=right>{s.last_gap_ms:.2f} ms</td></tr>"
            f"<tr><td>Max frame gap</td><td align=right>{s.max_gap_ms:.2f} ms</td></tr>"
            f"<tr><td>Running for</td><td align=right>{elapsed:.0f} s</td></tr>"
            "</table>")


# ---------------------------------------------------------------------------
# libcamera ISP controls
# ---------------------------------------------------------------------------
class IspTab(QWidget):
    """Every libcamera control not handled by the other tabs, plus the tuning file in use."""

    def __init__(self, picam2, implemented, ignored, tuning_path=None):
        super().__init__()
        self.picam2 = picam2
        self.widgets = {}
        outer = QVBoxLayout(self)

        box = QGroupBox("libcamera controls")
        form = QFormLayout(box)
        for name in sorted(picam2.camera_controls):
            if name in implemented or name in ignored:
                continue
            lo, hi, default = picam2.camera_controls[name]
            w = self._make_widget(lo, hi, default)
            if w is None:
                continue
            w.setToolTip(f"min {lo}, max {hi}, default {default}")
            self.widgets[name] = (w, default)
            form.addRow(name, w)
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self.apply)
        reset_btn = QPushButton("Defaults")
        reset_btn.clicked.connect(self.defaults)
        row = QHBoxLayout()
        row.addWidget(apply_btn)
        row.addWidget(reset_btn)
        form.addRow(row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(box)
        outer.addWidget(scroll, 2)

        raw_box = QGroupBox("Set controls (Name=value, one per line)")
        rl = QVBoxLayout(raw_box)
        self.raw = QPlainTextEdit()
        self.raw.setPlaceholderText("e.g.\nExposureTime=10000\nFrameDurationLimits=33333,33333")
        self.raw.setMaximumHeight(90)
        raw_btn = QPushButton("Set")
        raw_btn.clicked.connect(self.apply_raw)
        rl.addWidget(self.raw)
        rl.addWidget(raw_btn)
        outer.addWidget(raw_box)

        self.msg = QLabel()
        self.msg.setWordWrap(True)
        outer.addWidget(self.msg)

        tune_box = QGroupBox("Tuning file")
        tl = QVBoxLayout(tune_box)
        path = tuning_path or find_tuning_file(picam2)
        self.tuning = QLabel(self._tuning_text(path))
        self.tuning.setWordWrap(True)
        self.tuning.setTextInteractionFlags(Qt.TextSelectableByMouse)
        tl.addWidget(self.tuning)
        outer.addWidget(tune_box, 1)

    @staticmethod
    def _make_widget(lo, hi, default):
        sample = default if default is not None else lo
        if isinstance(sample, bool):
            w = QCheckBox()
            w.setChecked(bool(default))
            return w
        if isinstance(sample, int) and isinstance(lo, int) and isinstance(hi, int):
            w = QSpinBox()
            w.setRange(max(lo, -2**31), min(hi, 2**31 - 1))
            w.setValue(int(default) if default is not None else lo)
            return w
        if isinstance(sample, (int, float)) and isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
            w = QDoubleSpinBox()
            w.setDecimals(3)
            w.setRange(float(lo), float(hi))
            w.setValue(float(default) if default is not None else float(lo))
            return w
        if isinstance(sample, (tuple, list)):
            w = QLineEdit(", ".join(str(v) for v in sample))
            return w
        return None

    @staticmethod
    def _value(w, default):
        if isinstance(w, QCheckBox):
            return w.isChecked()
        if isinstance(w, (QSpinBox, QDoubleSpinBox)):
            return w.value()
        parts = [p.strip() for p in w.text().split(",") if p.strip()]
        conv = float if any(isinstance(v, float) for v in (default or [])) else int
        return tuple(conv(p) for p in parts)

    def apply(self):
        controls = {}
        try:
            for name, (w, default) in self.widgets.items():
                controls[name] = self._value(w, default)
            self.picam2.set_controls(controls)
            self.msg.setText(f"Set {len(controls)} controls")
        except (ValueError, RuntimeError, TypeError) as e:
            self.msg.setText(f"Error: {e}")

    def defaults(self):
        for name, (w, default) in self.widgets.items():
            if default is None:
                continue
            if isinstance(w, QCheckBox):
                w.setChecked(bool(default))
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                w.setValue(default)
            else:
                w.setText(", ".join(str(v) for v in default))

    def apply_raw(self):
        controls = {}
        try:
            for line in self.raw.toPlainText().splitlines():
                if "=" not in line:
                    continue
                name, value = (p.strip() for p in line.split("=", 1))
                if name not in self.picam2.camera_controls:
                    raise ValueError(f"unknown control {name}")
                vals = [float(v) if "." in v else int(v, 0) for v in value.split(",") if v.strip()]
                if isinstance(self.picam2.camera_controls[name][2], bool):
                    controls[name] = bool(vals[0])
                else:
                    controls[name] = vals[0] if len(vals) == 1 else tuple(vals)
            self.picam2.set_controls(controls)
            self.msg.setText(f"Set {', '.join(controls) or 'nothing'}")
        except (ValueError, RuntimeError, TypeError, IndexError) as e:
            self.msg.setText(f"Error: {e}")

    @staticmethod
    def _tuning_text(path):
        if not path:
            return "Tuning file not found. Start the viewer with --tuning-file FILE to choose one."
        try:
            with open(path) as fh:
                data = json.load(fh)
            algos = [next(iter(a)) for a in data.get("algorithms", [])]
            return (f"{path}\nversion {data.get('version', '?')}, target {data.get('target', '?')}\n"
                    f"algorithms: {', '.join(algos)}\n\n"
                    "Start the viewer with --tuning-file FILE to use another tuning file.")
        except (OSError, ValueError) as e:
            return f"{path}\n(could not read: {e})"


def find_tuning_file(picam2):
    """Best guess of the tuning file libcamera loaded for this camera."""
    env = os.environ.get("LIBCAMERA_RPI_TUNING_FILE")
    if env:
        return env
    model = str(picam2.camera_properties.get("Model", "")).lower()
    try:
        with open("/proc/device-tree/model") as fh:
            platform = "pisp" if "Raspberry Pi 5" in fh.read() else "vc4"
    except OSError:
        platform = "vc4"
    names = [f"{model}_mono.json", f"{model}.json"] if picam2.is_mono else [f"{model}.json"]
    for prefix in ("/usr/local/share/libcamera/ipa/rpi", "/usr/share/libcamera/ipa/rpi"):
        for name in names:
            path = os.path.join(prefix, platform, name)
            if os.path.isfile(path):
                return path
    return None


# ---------------------------------------------------------------------------
# Live histogram
# ---------------------------------------------------------------------------
class HistogramTab(QWidget):
    """Live histogram of the raw image (per colour channel for Bayer sensors)."""

    def __init__(self, live_view):
        super().__init__()
        self.live_view = live_view
        layout = QVBoxLayout(self)
        self.hist = HistogramWidget(min_height=260)
        layout.addWidget(self.hist, 1)
        self.log = QCheckBox("Logarithmic counts")
        self.log.setChecked(True)
        self.log.stateChanged.connect(self._set_log)
        layout.addWidget(self.log)
        self.label = QLabel()
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(250)

    def _set_log(self, state):
        self.hist.log = bool(state)
        self.hist.update()

    def showEvent(self, event):
        self.live_view.histogram_enabled = True
        super().showEvent(event)

    def hideEvent(self, event):
        self.live_view.histogram_enabled = False
        super().hideEvent(event)

    def refresh(self):
        if not self.isVisible():
            return
        lv = self.live_view
        if lv.error:
            self.label.setText(lv.error)
            return
        if lv.histogram:
            counts, bits = lv.histogram
            self.hist.set_data(counts)
            st = lv.stats
            self.label.setText(f"Raw {bits}-bit, range 0-{(1 << bits) - 1} DN. "
                               f"Mean {st['mean']:.1f}, min {st['min']}, max {st['max']}")


# ---------------------------------------------------------------------------
# ROI rectangles
# ---------------------------------------------------------------------------
class RoiTab(QWidget):
    """Named rectangles in raw pixels, drawn on the preview with their live mean."""

    COLUMNS = ["Name", "x", "y", "w", "h", "Mean [DN]"]
    FIELDS = [None, "x", "y", "w", "h"]

    def __init__(self, live_view, on_change=None):
        super().__init__()
        self.live_view = live_view
        self.on_change = on_change
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._edited)
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        add = QPushButton("Add")
        add.clicked.connect(self.add)
        remove = QPushButton("Remove")
        remove.clicked.connect(self.remove)
        row.addWidget(add)
        row.addWidget(remove)
        layout.addLayout(row)

        self.show_rois = QCheckBox("Show ROIs on the preview")
        self.show_rois.setChecked(True)
        self.show_rois.stateChanged.connect(lambda s: setattr(live_view, "show_rois", bool(s)))
        self.show_pixels = QCheckBox("Show pixel values when zoomed in")
        self.show_pixels.setToolTip(f"Drawn when at most {live.PIXEL_VALUES_MAX} raw pixels span the view "
                                    "(zoom in with Pan/Zoom)")
        self.show_pixels.setChecked(True)
        self.show_pixels.stateChanged.connect(lambda s: setattr(live_view, "show_pixels", bool(s)))
        layout.addWidget(self.show_rois)
        layout.addWidget(self.show_pixels)
        note = QLabel("Coordinates are raw pixels of the current sensor mode. Edit a cell to move a ROI.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self._updating = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_means)
        self.timer.start(250)

    def _raw_size(self):
        try:
            return live.raw_info(self.live_view.picam2)[1]
        except ValueError:
            return (640, 480)

    def add(self):
        w, h = self._raw_size()
        n = len(self.live_view.rois)
        size = max(16, min(w, h) // 8)
        # New ROIs go along the diagonal so they do not overlap
        x = max(0, min(w - size, w // 2 - size // 2 + (n % 4) * size))
        y = max(0, min(h - size, h // 2 - size // 2 + (n % 4) * size))
        self.live_view.rois.append(live.Roi(f"ROI{n + 1}", x, y, size, size))
        self._rebuild()

    def remove(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows and self.live_view.rois:
            rows = [len(self.live_view.rois) - 1]
        for r in rows:
            del self.live_view.rois[r]
        self._rebuild()

    def _rebuild(self):
        self._updating = True
        self.table.setRowCount(len(self.live_view.rois))
        for r, roi in enumerate(self.live_view.rois):
            for c, v in enumerate((roi.name, roi.x, roi.y, roi.w, roi.h, "")):
                item = QTableWidgetItem(str(v))
                if c == 5:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, item)
        self._updating = False
        if self.on_change:
            self.on_change()

    def _edited(self, item):
        if self._updating or item.column() == 5:
            return
        roi = self.live_view.rois[item.row()]
        try:
            if item.column() == 0:
                roi.name = item.text().strip() or roi.name
            else:
                w, h = self._raw_size()
                setattr(roi, self.FIELDS[item.column()], max(0, int(item.text())))
                roi.x, roi.y = min(roi.x, w - 1), min(roi.y, h - 1)
                roi.w, roi.h = max(1, min(roi.w, w - roi.x)), max(1, min(roi.h, h - roi.y))
            self.status.setText("")
        except ValueError:
            self.status.setText(f"'{item.text()}' is not a number")
        self._rebuild()

    def refresh_means(self):
        if self.live_view.error:
            self.status.setText(self.live_view.error)
        self._updating = True
        for r, roi in enumerate(self.live_view.rois):
            item = self.table.item(r, 5)
            if item is not None:
                item.setText("-" if roi.mean != roi.mean else f"{roi.mean:.2f}")
        self._updating = False
