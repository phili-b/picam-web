#!/usr/bin/env python3
"""Run the web service or the desktop viewer on a PC with a simulated camera and sensor.

    python tests/fake/run_fake.py web [--port 8080]       # web UI at http://localhost:8080/
    python tests/fake/run_fake.py desktop                 # Qt desktop viewer (needs PyQt5)

Environment: FAKE_CAMERA_COLOUR=1 for an RGGB sensor, FAKE_CAMERA_MODEL=duocam (or quadcam)
for a sensor with register banks and two (four) contexts, FAKE_DRIVER_CONTROLS=0 for register
access over I2C instead of the simulated driver controls. Settings go to a temporary folder,
not to ~/.config. For development and tests only; see docs/development.md.
"""

import importlib
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def setup():
    """Put the simulated picamera2/smbus2 first on the path and point the sensor lookup at them."""
    sys.path.insert(0, HERE)
    sys.path.insert(1, os.path.join(ROOT, "picam_viewer"))
    sys.path.insert(1, os.path.join(ROOT, "picam_web"))
    import sensor_regs
    importlib.import_module("fake_profiles")  # registers the fakecam profiles
    import smbus2  # the simulated one (HERE is first on the path)
    sensor_regs.SMBus, sensor_regs.i2c_msg = smbus2.SMBus, smbus2.i2c_msg
    model = os.environ.get("FAKE_CAMERA_MODEL", "fakecam")
    sensor_regs.find_sensor = lambda sysfs=None, names=(): sensor_regs.SensorInfo(model, 1, 0x36)
    # Driver register and context controls; FAKE_DRIVER_CONTROLS=0 for direct I2C
    if os.environ.get("FAKE_DRIVER_CONTROLS", "1") != "0":
        import fake_subdev
        sensor_regs.open_driver_controls = fake_subdev.FakeSubdev
    state = os.environ.setdefault("FAKE_CAMERA_STATE", os.path.join(tempfile.gettempdir(), "picam_fake"))
    os.makedirs(state, exist_ok=True)
    try:
        import camera_service
        import health
        camera_service.SETTINGS_FILE = os.path.join(state, "picam_web.json")
        health.RECOVERY_FILE = os.path.join(state, "picam_web_recovery.json")
    except ImportError:  # the desktop viewer does not need the web service modules
        pass


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "web"
    setup()
    if what == "web":
        sys.argv = [os.path.join(ROOT, "picam_web", "server.py"), *sys.argv[2:]]
        if "--port" not in sys.argv:
            sys.argv += ["--port", "8080"]
        if "--host" not in sys.argv:
            sys.argv += ["--host", "127.0.0.1"]
        import server
        # restart_process starts this launcher again (not server.py) so the simulator stays in use
        import camera_service
        camera_service.LAUNCHER = [os.path.abspath(__file__), "web"]
        server.main()
    elif what == "desktop":
        sys.argv = [os.path.join(ROOT, "picam_viewer", "app_full.py"), *sys.argv[2:]]
        import runpy
        runpy.run_path(sys.argv[0], run_name="__main__")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
