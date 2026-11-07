#!/usr/bin/python3

# This example adds multiple exposures together to create a much longer exposure
# image. It does this by adding raw images together, correcting the black level,
# and saving a DNG file. Currentl you need to use a raw converter to obtain the
# final result (e.g. "dcraw -w -W accumulated.dng").

import numpy as np
from picamera2 import Picamera2
from picamera2.sensor_format import SensorFormat

from PIL import Image

exposure_time = 600
num_frames = 60
framerate = 10
# Configure an unpacked raw format as these are easier to add.
picam2 = Picamera2()
# raw_format = SensorFormat(picam2.sensor_format)

raw_format = SensorFormat('SGRBG10_CSI2P')
print(raw_format)
raw_format.packing = None
config = picam2.create_still_configuration(raw={"format": raw_format.format}, buffer_count=2)
picam2.configure(config)
images = []
picam2.set_controls({"ExposureTime": exposure_time , "AnalogueGain": 1.0, "FrameRate":framerate})
picam2.start()
old = 0
new = 0
# The raw images can be added directly using 2-byte pixels.
for i in range(num_frames):
    images.append(picam2.capture_array("raw").view(np.uint16))
    metadata = picam2.capture_metadata()
    new = metadata['SensorTimestamp']
    diff = new - old 
    old = new
    print(metadata['SensorTimestamp'])
    print(diff/1000)

print(images[0].shape)
print(images[0])
for index, image in enumerate(images):
    pilim = Image.fromarray(image)
    pilim.save(f"imgraw{index}.tiff")
# accumulated = images.pop(0).astype(int)
# for image in images:
#     accumulated += image

# print(accumulated)

# # Fix the black level, and convert back to uint8 form for saving as a DNG.
# black_level = metadata["SensorBlackLevels"][0] / 2**(16 - raw_format.bit_depth)
# accumulated -= (num_frames - 1) * int(black_level)
# accumulated = accumulated.clip(0, 2 ** raw_format.bit_depth - 1).astype(np.uint16)
# accumulated = accumulated.view(np.uint8)
# metadata["ExposureTime"] = exposure_time
# picam2.helpers.save_dng(accumulated, metadata, config["raw"], "accumulated.dng")
