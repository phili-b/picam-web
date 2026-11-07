"""Connect to the Pi and print the camera, its sensor modes, the state and the latest frame's metadata.

    python 01_camera_info.py [http://raspberrypi.local]
"""

from _common import connect

cam = connect()
info = cam.info()
p = info["properties"]
print(f"Sensor      {p['Model']}  ({info['sensor']})")
print(f"Pipeline    {p['PipelineHandler']}, pixel array {p['PixelArraySize'][0]}x{p['PixelArraySize'][1]}")
print(f"Mono        {info['is_mono']}")
print(f"Tuning file {info['tuning_file'] or 'default'}")
print(f"Service     version {info['version']}")
print()
print("Sensor modes:")
for i, m in enumerate(info["sensor_modes"]):
    current = "  <- current" if i == info["mode"] else ""
    print(f"  {i}: {m['unpacked']:8s} {m['size'][0]}x{m['size'][1]} {m['bit_depth']:2d}-bit {m['fps']:6.1f} fps{current}")
print()

h = cam.health()
f = cam.frame_stats()
print(f"State       {h['state']}: {h['message']}")
print(f"Frames      {f['frames']} received, {f['fps']} fps (expected {f['expected_fps']}), {f['dropped']} dropped")
print()

md = cam.metadata()
for key in ("ExposureTime", "AnalogueGain", "DigitalGain", "FrameDuration", "SensorTemperature", "SensorBlackLevels"):
    if key in md:
        print(f"{key:18s} {md[key]}")
