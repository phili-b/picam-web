"""Simulated Qt preview: a QWidget that drives the simulated camera from a QTimer (GUI thread)."""

import numpy as np
from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtWidgets import QWidget


class QPicamera2(QWidget):
    done_signal = pyqtSignal(object)

    def __init__(self, picam2, parent=None, width=640, height=480, bg_colour=(20, 20, 20), keep_ar=True,
                 transform=None, preview_window=None):
        super().__init__(parent)
        self.picam2 = picam2
        picam2._qt = self
        self.bg_colour = QColor(*bg_colour[:3])
        self.keep_ar = keep_ar
        self.image = None
        self.overlay = None
        self.resize(width, height)
        self.timer = QTimer(self)
        self.timer.timeout.connect(picam2.tick)
        self.timer.start(33)

    def signal_done(self, job):
        self.done_signal.emit(job)

    def set_overlay(self, overlay):
        self.overlay = None if overlay is None else np.ascontiguousarray(overlay)
        self.update()

    def _show(self, request):
        a = request.make_array("main") if "main" in request.arrays else None
        if a is not None:
            rgb = np.ascontiguousarray(a[..., :3])
            self.image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], 3 * rgb.shape[1], QImage.Format_RGB888).copy()
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), self.bg_colour)
        if self.image is not None:
            p.drawImage(self.rect(), self.image)
        if self.overlay is not None:
            o = self.overlay
            img = QImage(o.data, o.shape[1], o.shape[0], 4 * o.shape[1], QImage.Format_RGBA8888)
            p.drawImage(self.rect(), img)


QGlPicamera2 = QPicamera2
