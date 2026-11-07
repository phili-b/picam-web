"""Sensor modes, ISP statistics and health: switch modes, read ISP statistics, restart the stream.

    python 08_modes_and_recovery.py [http://raspberrypi.local]

Leaves the camera in the mode it was in. A script that runs for a long time can call
cam.health() to see whether the camera still streams, and cam.reset() to recover it.
"""

import time

from _common import CameraError, connect

cam = connect()
info = cam.info()
start_mode = info["mode"]

for i, m in enumerate(info["sensor_modes"]):
    try:
        cam.set_mode(i)
    except CameraError as e:
        print(f"mode {i}: {e}")
        continue
    cam.wait_streaming(30)
    time.sleep(1)
    f = cam.frame_stats()
    print(f"mode {i}: {m['unpacked']} {m['size'][0]}x{m['size'][1]} -> {f['fps']} fps "
          f"(expected {f['expected_fps']}), raw {cam.info()['raw']['size']}")
cam.set_mode(start_mode)
cam.wait_streaming(30)

# ISP statistics (Raspberry Pi 5)
try:
    cam.isp_stats(enable=True)
    time.sleep(1)
    s = cam.isp_stats()
    if "error" in s:
        print("ISP statistics:", s["error"])
    else:
        print(f"ISP statistics: {s['count']} frames, zone means {s['zones_mean'].shape}, "
              f"focus {s['focus'].shape}, histogram {s['histogram'].shape}")
    cam.isp_stats(enable=False)
except CameraError as e:
    print("ISP statistics:", e)

# Health and a manual stream restart (about 1 s)
h = cam.health()
print(f"health: {h['state']}, recovery level {h['recovery_level']}")
print("restarting the stream...")
h = cam.reset("stream")
print(f"health: {h['state']} - {h['message']}")
