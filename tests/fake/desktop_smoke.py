#!/usr/bin/env python3
"""Click every button and toggle every check box of the desktop viewer with the simulated camera.

    python tests/fake/desktop_smoke.py            (needs PyQt5; runs off-screen)

File dialogs answer with files in a temporary folder, message boxes with Yes. Fails on any
exception in a Qt slot, and when the viewer stops showing frames or ends with disabled
capture buttons. Exit code 0 = passed.
"""

import os
import runpy
import sys
import tempfile
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_fake  # noqa: E402

run_fake.setup()
OUT = tempfile.mkdtemp(prefix="picam_desktop_")
os.chdir(OUT)  # photos and videos without a folder go here

from PyQt5.QtWidgets import (QAbstractButton, QCheckBox, QComboBox, QFileDialog, QMessageBox,  # noqa: E402
                             QPushButton, QTabWidget)

errors = []
sys.excepthook = lambda *exc: errors.append("".join(traceback.format_exception(*exc)))

seq = os.path.join(OUT, "seq.txt")
with open(seq, "w") as fh:
    fh.write("write 0x12 to 0x1000\n")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (os.path.join(OUT, "saved.csv"), ""))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (seq, ""))
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: OUT)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

sys.argv = [os.path.join(run_fake.ROOT, "picam_viewer", "app_full.py")]
g = runpy.run_path(sys.argv[0], run_name="desktop_smoke")   # builds the window, does not run app.exec()
app, window, tabs, mode_tabs = g["app"], g["main_window"], g["tabs"], g["mode_tabs"]
picam2 = g["picam2"]
window.show()
g["raw_tab"].folder.setText(OUT)

# Buttons that restart or quit the process, or need user input that the harness cannot give
SKIP = {"Restart with this tuning file", "Browse..."}


def pump(seconds=0.3):
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.01)


def wait_enabled(widget, seconds=20):
    t0 = time.time()
    while not widget.isEnabled() and time.time() - t0 < seconds:
        pump(0.1)
    return widget.isEnabled()


clicked = []


def click_all(container, label):
    for w in container.findChildren(QAbstractButton):
        text = w.text() or w.toolTip() or type(w).__name__
        if not w.isEnabled() or text in SKIP or isinstance(w, QTabWidget):
            continue
        w.click()
        pump(0.4)
        if isinstance(w, QPushButton):
            wait_enabled(w)   # worker-thread buttons (noise, burst) come back when done
        if isinstance(w, QCheckBox):
            w.click()  # back to how it was
            pump(0.2)
        clicked.append(f"{label}: {text}")


for i in range(tabs.count()):
    tabs.setCurrentIndex(i)
    pump(0.5)
    page = tabs.widget(i)
    if tabs.tabText(i) == "ROI":
        page.findChildren(QPushButton)[0].click()  # Add a ROI so the noise ROI chooser has one
        pump(0.5)
    for combo in page.findChildren(QComboBox):
        if combo.count() > 1:
            combo.setCurrentIndex(1)
            pump(0.2)
            combo.setCurrentIndex(0)
    click_all(page, tabs.tabText(i))

# Still capture in every file type, then video
for i in range(mode_tabs.count()):
    mode_tabs.setCurrentIndex(i)
    pump(1.0)
pic_tab, vid_tab, rec = g["pic_tab"], g["vid_tab"], g["rec_button"]
mode_tabs.setCurrentIndex(0)
pump(1.0)
for ftype in [pic_tab.filetype.itemText(k) for k in range(pic_tab.filetype.count())]:
    pic_tab.filetype.setCurrentText(ftype)
    pic_tab.filename.setText(os.path.join(OUT, f"photo_{ftype}"))
    rec.click()
    if not wait_enabled(rec, 10):
        errors.append(f"photo {ftype}: the capture button stayed disabled")
    clicked.append(f"Take photo: {ftype}")
# A save that fails (folder does not exist): reported, and the button must work again
pic_tab.filetype.setCurrentText("png")
pic_tab.filename.setText(os.path.join(OUT, "no_such_folder", "photo"))
rec.click()
if not wait_enabled(rec, 10):
    errors.append("after a failed save the capture button stayed disabled")
if "failed" not in g["capture_msg"].text():
    errors.append(f"a failed save was not reported: {g['capture_msg'].text()!r}")
clicked.append("Take photo: failing save")
click_all(pic_tab, "Still Capture")
mode_tabs.setCurrentIndex(1)
pump(1.0)
vid_tab.filename.setText(os.path.join(OUT, "video"))
click_all(vid_tab, "Video")
rec.click()
pump(1.0)
rec.click()
pump(0.5)
clicked.append("Video: start/stop recording")
mode_tabs.setCurrentIndex(0)
pump(1.0)
g["hide_button"].click()
g["hide_button"].click()

frames_before = g["frame_tab"].stats.frames
pump(1.5)
alive = g["frame_tab"].stats.frames > frames_before
files = sorted(os.listdir(OUT))
print(f"{len(clicked)} buttons/check boxes clicked; files written: {', '.join(files)}")
for e in errors:
    print("ERROR", e)
ok = not errors and alive and rec.isEnabled() and mode_tabs.isEnabled()
print(f"{'PASS' if ok else 'FAIL'}: frames still coming: {alive}, capture button enabled: {rec.isEnabled()}, "
      f"{len(errors)} errors")
picam2.stop()
sys.stdout.flush()
sys.stderr.flush()
os._exit(0 if ok else 1)   # skips Qt's teardown of the simulated preview
