"""Fixed pattern noise (dark frame) correction of the ams-OSRAM libcamera fork, switched at runtime.

libcamera reads the dark frames from `<dir>/<sensor model>/gain_<code>.pgm`, where <dir> is the
`fpn_dark_frame_dir` of the pipeline config file (LIBCAMERA_RPI_CONFIG_FILE). The config file is read
once per process, but the directory is looked at again every time the camera is configured. So the
config names a symlink, and this module creates or removes it:

    PICAM_FPN_DIR   the calibration directory (the dark frames)
    PICAM_FPN_LINK  the path `fpn_dark_frame_dir` in the libcamera config file points to

On: LINK -> DIR. Off: no LINK, libcamera finds no dark frames and corrects nothing. The state is the
link itself, so it survives a restart. Without both variables the feature is not available.

The mode is the file DIR/fpn_mode: "column" (libcamera subtracts the column pattern of the maps, the
default) or "full" (the whole map). libcamera reads it on every configure too.

Sensors with an electrical black readout (ELECTRICAL_BLACK) can be calibrated without covering the lens:
CameraService.calibrate_fpn captures the maps with it and write_maps stores them.
"""

import os
import shutil

import numpy as np


def _paths():
    return os.environ.get("PICAM_FPN_DIR"), os.environ.get("PICAM_FPN_LINK")


MODES = ("column", "full")


def status():
    """{"available", "enabled", "mode"}; available needs both variables, the calibration directory, and a
    link path that is free or already a symlink (a real directory there is never touched)."""
    calibration, link = _paths()
    if not (calibration and link and os.path.isdir(calibration)) or (os.path.lexists(link) and not os.path.islink(link)):
        return {"available": False, "enabled": False, "mode": "column"}
    enabled = os.path.islink(link) and os.path.realpath(link) == os.path.realpath(calibration)
    return {"available": True, "enabled": enabled, "mode": get_mode()}


def get_mode():
    """The correction mode in the calibration directory: "column" (also without the file) or "full"."""
    calibration, _ = _paths()
    try:
        with open(os.path.join(calibration, "fpn_mode")) as f:
            word = f.read().strip()
    except (OSError, TypeError):
        return "column"
    return word if word in MODES else "column"


def set_mode(mode):
    """Write the correction mode. The camera must be configured again afterwards."""
    if mode not in MODES:
        raise ValueError(f"FPN mode {mode!r}: one of {', '.join(MODES)}")
    if not status()["available"]:
        raise RuntimeError("FPN correction is not set up (see PICAM_FPN_DIR and PICAM_FPN_LINK)")
    calibration, _ = _paths()
    with open(os.path.join(calibration, "fpn_mode"), "w") as f:
        f.write(mode + "\n")


def set_enabled(enabled):
    """Create or remove the link. The camera must be configured again afterwards."""
    if not status()["available"]:
        raise RuntimeError("FPN correction is not set up (see PICAM_FPN_DIR and PICAM_FPN_LINK)")
    calibration, link = _paths()
    if enabled:
        tmp = link + ".tmp"
        if os.path.lexists(tmp):
            os.unlink(tmp)
        os.symlink(calibration, tmp)
        os.replace(tmp, link)  # atomic: libcamera never sees a missing link while switching it on
    elif os.path.lexists(link):
        os.unlink(link)


# Calibration ------------------------------------------------------------------------------------
# Sensors that can be calibrated: (electrical black register, value, {gain code: analogue gain}).
# Electrical black maps hold the column pattern only (the pixels are read without their charge), so they
# suit the column mode; for the full frame mode calibrate with dark frames (light off or lens covered).
# poncha110: PIX_CTRL_ELECTRICAL_BLACK, value 2 = PIX_TG low during readout. The photodiode charge is
# never transferred, so the frame does not see light, but it goes through the normal column readout and
# has the same column pattern as a dark frame. Values 1 and 3 (PIX_RST high) change the column pattern
# and cannot be used. The driver writes 0 at every stream start. Gain code = gain - 1 (libcamera helper).
ELECTRICAL_BLACK = {
    "poncha110": (0x0017, 2, {0: 1.0, 1: 2.0, 2: 3.0}),
}
MIN_FRAMES = 10
# The column offsets are means over the rows of many frames; their noise is the pixel noise divided by
# sqrt(frames x rows / 2): poncha110 at 1 ms, 30 frames: 0.55 / 0.9 / 1.3 DN at gain 1 / 2 / 3 (256 frames:
# 0.2 / 0.3 / 0.4). libcamera applies the offsets with their fractional part.
DEFAULT_FRAMES = 30
MAX_FRAMES = 1024


def electrical_black(model):
    """(register, value, {gain code: gain}) of the sensor model, or None if it has no electrical black."""
    return ELECTRICAL_BLACK.get(str(model).lower())


def can_calibrate(model):
    return status()["available"] and electrical_black(model) is not None


def maps_missing(model):
    """True if a gain code of the sensor's electrical black list has no map <dir>/<model>/gain_<code>.pgm."""
    calibration, _ = _paths()
    eb = electrical_black(model)
    return bool(calibration and eb) and not all(
        os.path.isfile(os.path.join(calibration, model, f"gain_{code}.pgm")) for code in eb[2])


def column_offsets(frame):
    """The correction libcamera derives from a map: per row parity, the mean of each column minus the
    mean of its CFA phase (2 x W). Its spread is the column FPN that is corrected."""
    cols = np.stack([frame[p::2].mean(0) for p in (0, 1)])
    for x in (0, 1):
        cols[:, x::2] -= cols[:, x::2].mean(1, keepdims=True)
    return cols


def offset_noise(half_a, half_b):
    """The noise of column_offsets() of the mean of two equal halves, from the half means: std(A - B) / 2.
    A calibration measures its own precision this way (16-bit DN)."""
    return float(column_offsets(half_a - half_b).std() / 2)


def write_maps(model, maps, comment):
    """Write the averaged frames {gain code: (H x W float array, gain)} as <dir>/<model>/gain_<code>.pgm
    (16-bit P5, big-endian). The maps there before are moved to <dir>/<model>.previous (replacing an
    older copy). Returns the paths written."""
    calibration, _ = _paths()
    folder = os.path.join(calibration, model)
    previous = folder + ".previous"
    if os.path.isdir(folder):
        if os.path.isdir(previous):
            shutil.rmtree(previous)
        os.replace(folder, previous)
    os.makedirs(folder)
    paths = []
    for code, (frame, gain) in sorted(maps.items()):
        h, w = frame.shape
        path = os.path.join(folder, f"gain_{code}.pgm")
        header = f"P5\n# sensor {model} gain_code {code} gain {gain:.3f} {comment}\n{w} {h}\n65535\n"
        with open(path, "wb") as f:
            f.write(header.encode())
            f.write(np.clip(np.rint(frame), 0, 65535).astype(">u2").tobytes())
        paths.append(path)
    return paths
