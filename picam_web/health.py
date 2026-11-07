"""Health of the camera service: state, recovery escalation, kernel log warnings, systemd watchdog.

States: starting -> streaming -> stalled -> recovering -> streaming | failed.

Escalation when frames stop (each level only if the previous one did not bring frames back):
  1. restart the stream (stop/start)                        in this process
  2. reopen the camera in a fresh process (2 s off time)    the level survives the restart in a file
  3. failed: the sensor needs a power cycle; reboot automatically if auto_reboot is set
Resetting the sensor driver (unbind/bind on I2C) is not used: with some drivers it crashes the
kernel (oops in the driver's bind).
"""

import json
import os
import re
import socket
import subprocess
import threading
import time

RECOVERY_FILE = os.path.expanduser("~/.config/picam_web_recovery.json")
RECOVERY_WINDOW = 120   # s: a camera reopen within this time of the previous one counts as the same incident
KERNEL_PATTERNS = re.compile(r"Error (writing|reading) reg|stream on failed|Unable to handle kernel|"
                             r"Failed to queue buffer|i2c.*(timeout|-121)", re.IGNORECASE)


def load_recovery():
    try:
        with open(RECOVERY_FILE) as fh:
            r = json.load(fh)
        return r if time.time() - r.get("at", 0) < RECOVERY_WINDOW else {}
    except (OSError, ValueError):
        return {}


def save_recovery(level):
    os.makedirs(os.path.dirname(RECOVERY_FILE), exist_ok=True)
    with open(RECOVERY_FILE, "w") as fh:
        json.dump({"level": level, "at": time.time()}, fh)


def clear_recovery():
    try:
        os.remove(RECOVERY_FILE)
    except OSError:
        pass


class Health:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = "starting"
        self.message = "Starting the camera"
        self.since = time.time()
        self.history = []          # [(time, text)]
        self.kernel = []           # recent kernel warnings about the sensor/camera
        self.level = 0             # recovery level reached in this incident

    def set(self, state, message):
        with self.lock:
            if state != self.state or message != self.message:
                self.state, self.message, self.since = state, message, time.time()
                self.history.append((time.strftime("%H:%M:%S"), f"{state}: {message}"))
                self.history = self.history[-20:]

    def as_dict(self):
        with self.lock:
            return {"state": self.state, "message": self.message, "since": self.since,
                    "recovery_level": self.level, "history": self.history[-10:], "kernel": self.kernel[-5:]}


class KernelLog(threading.Thread):
    """Follows new kernel messages (dmesg -W) and keeps those about the sensor or the camera interface."""

    def __init__(self, health):
        super().__init__(daemon=True)
        self.health = health

    def run(self):
        try:
            proc = subprocess.Popen(["dmesg", "-W", "--notime"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    text=True)
        except OSError:
            return
        for line in proc.stdout:
            if KERNEL_PATTERNS.search(line):
                with self.health.lock:
                    self.health.kernel.append(f"{time.strftime('%H:%M:%S')} {line.strip()[:160]}")
                    self.health.kernel = self.health.kernel[-20:]


def reboot():
    """Reboot the Raspberry Pi (sudoers rule from install.sh). Power-cycles the sensor."""
    clear_recovery()
    subprocess.run(["sudo", "-n", "/usr/bin/systemctl", "reboot"], check=False)


def sd_notify(message):
    """Send a message to systemd (Type=notify / WatchdogSec) if running under it."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(addr)
            s.sendall(message.encode())
        return True
    except OSError:
        return False


def watchdog_interval():
    """Half of systemd's WatchdogSec in seconds, or None when there is no watchdog."""
    usec = os.environ.get("WATCHDOG_USEC")
    return int(usec) / 2e6 if usec and usec.isdigit() else None
