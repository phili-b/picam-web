"""The camera model: the sensor's dtoverlay= line in /boot/firmware/config.txt.

The list of models is every camera sensor overlay installed in /boot/firmware/overlays (the usual
sensor name prefixes, plus the names of sensor plugin profiles). Changing it runs the root helper
tools/picam-camera-overlay through sudo (install.sh installs it and the sudoers rule); the change
applies after a reboot.
"""

import os
import re
import subprocess

import sensor_regs

BOOT = os.environ.get("PICAM_BOOT_DIR", "/boot/firmware")
HELPER_CMD = ["sudo", "-n", "/usr/local/sbin/picam-camera-overlay"]
# Overlay names of camera sensors (Sony, OmniVision, ST, onsemi, ams OSRAM Mira); sensor plugins add their own
SENSOR_PREFIXES = ("imx", "ov", "vd", "ar0", "mira", "poncha")
LINE = re.compile(r"^\s*dtoverlay=([a-z0-9][a-z0-9_-]*)((?:,[^\s#]*)?)")


def _is_sensor(name):
    return name.startswith(SENSOR_PREFIXES) or any(name.startswith(p) for p in sensor_regs.PROFILES)


def overlays():
    """Names of the camera sensor overlays installed, sorted."""
    try:
        files = os.listdir(os.path.join(BOOT, "overlays"))
    except OSError:
        return []
    return sorted(f[:-5] for f in files if f.endswith(".dtbo") and _is_sensor(f[:-5]))


def current():
    """The camera overlay line of config.txt: {"overlay", "port", "mono", "line"}; overlay None if
    there is none (camera_auto_detect then picks the camera)."""
    installed = set(overlays())
    try:
        with open(os.path.join(BOOT, "config.txt")) as fh:
            text = fh.read()
    except OSError as e:
        raise RuntimeError(f"cannot read config.txt: {e}") from e
    auto = re.search(r"^\s*camera_auto_detect\s*=\s*(\d)", text, re.M)
    out = {"overlay": None, "port": "cam1", "mono": False, "line": None,
           "camera_auto_detect": bool(int(auto.group(1))) if auto else True}
    for line in text.splitlines():
        m = LINE.match(line)
        if m and m.group(1) in installed:
            params = [p for p in m.group(2).split(",") if p]
            out.update(overlay=m.group(1), port="cam0" if "cam0" in params else "cam1",
                       mono="mono" in params, line=line.strip())
    return out


def reboot_pending():
    """True if config.txt changed after the last boot."""
    try:
        with open("/proc/stat") as fh:
            btime = next(int(line.split()[1]) for line in fh if line.startswith("btime"))
        return os.path.getmtime(os.path.join(BOOT, "config.txt")) > btime
    except (OSError, StopIteration, ValueError):
        return False


def status():
    if not os.path.isfile(os.path.join(BOOT, "config.txt")):
        return {"available": False, "overlays": [], "current": None, "reboot_pending": False}
    return {"available": True, "overlays": overlays(), "current": current(), "reboot_pending": reboot_pending()}


def set_overlay(overlay, port="cam1", mono=False):
    """Write the camera overlay line with the root helper; returns the new status."""
    if overlay not in overlays():
        raise ValueError(f"no camera overlay {overlay!r} in {BOOT}/overlays")
    if port not in ("cam0", "cam1"):
        raise ValueError("port must be cam0 or cam1")
    old = current()["overlay"] or "-"
    try:
        r = subprocess.run([*HELPER_CMD, old, overlay, port, "1" if mono else "0"],
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"cannot run the camera overlay helper: {e}") from e
    if r.returncode:
        msg = (r.stderr or r.stdout).strip() or f"exit code {r.returncode}"
        if "password" in msg.lower() or "sudo" in msg.lower():
            msg += " (run install.sh to allow the service to change the camera)"
        raise RuntimeError(msg)
    return status()
