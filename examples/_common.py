"""Shared start-up of the examples: find picam_client and connect to the Raspberry Pi.

The address comes from the first command line argument, else the PICAM_URL environment variable,
else http://raspberrypi.local (the Pi over the USB-C cable).
"""

import os
import sys

# Use the installed picam_client (pip install), else the one in this repository
try:
    import picam_client
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    import picam_client

print(f"picam_client {picam_client.__version__} from {os.path.dirname(picam_client.__file__)}")

from picam_client import Camera, CameraError  # noqa: E402

__all__ = ["connect", "CameraError", "OUT_DIR"]

# Results of the examples go here, next to the scripts
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def connect():
    url = sys.argv[1] if len(sys.argv) > 1 and "://" in sys.argv[1] else os.environ.get("PICAM_URL", "http://raspberrypi.local")
    cam = Camera(url)
    try:
        h = cam.health()
    except OSError as e:
        sys.exit(f"Cannot reach the Picam-web service at {url}: {e}\n"
                 "Check the cable, or pass the address: python example.py http://<ip of the Pi>")
    if h["state"] != "streaming":
        print(f"Camera state: {h['state']} - {h['message']}")
    os.makedirs(OUT_DIR, exist_ok=True)
    return cam
