"""Fixed pattern noise (dark frame) correction of the ams-OSRAM libcamera fork, switched at runtime.

libcamera reads the dark frames from `<dir>/<sensor model>/gain_<code>.pgm`, where <dir> is the
`fpn_dark_frame_dir` of the pipeline config file (LIBCAMERA_RPI_CONFIG_FILE). The config file is read
once per process, but the directory is looked at again every time the camera is configured. So the
config names a symlink, and this module creates or removes it:

    PICAM_FPN_DIR   the calibration directory (the dark frames)
    PICAM_FPN_LINK  the path `fpn_dark_frame_dir` in the libcamera config file points to

On: LINK -> DIR. Off: no LINK, libcamera finds no dark frames and corrects nothing. The state is the
link itself, so it survives a restart. Without both variables the feature is not available.
"""

import os


def _paths():
    return os.environ.get("PICAM_FPN_DIR"), os.environ.get("PICAM_FPN_LINK")


def status():
    """{"available", "enabled"}; available needs both variables, the calibration directory, and a
    link path that is free or already a symlink (a real directory there is never touched)."""
    calibration, link = _paths()
    if not (calibration and link and os.path.isdir(calibration)) or (os.path.lexists(link) and not os.path.islink(link)):
        return {"available": False, "enabled": False}
    enabled = os.path.islink(link) and os.path.realpath(link) == os.path.realpath(calibration)
    return {"available": True, "enabled": enabled}


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
