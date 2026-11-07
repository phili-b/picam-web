"""Sensor profiles of the simulated sensors (tests and run_fake.py), as a plugin would register them.

fakecam: flat register map; duocam / quadcam: register map in banks (BANK_SEL 0xE000) and,
in bank 1, two or four contexts (RW_CONTEXT 0xE004). All have driver register access controls.
"""

import sensor_regs as sr

FAKE_CID_BASE = 0x00980900 + 0x2000  # V4L2_CID_USER_BASE + 0x2000

REGISTERS = [
    ("BANK_SEL", 0xE000, 1),
    ("RW_CONTEXT", 0xE004, 1),
    ("CHIP_ID", 0x011B, 1),
    ("EXP_TIME", 0x000E, 4),
    ("FRAME_TIME", 0x0008, 4),
    ("TEST_PATTERN", 0x2091, 1),
]

sr.register_profile(sr.SensorProfile("fakecam", REGISTERS[2:], driver_cid_base=FAKE_CID_BASE))
sr.register_profile(sr.SensorProfile("duocam", REGISTERS, contexts="AB", driver_cid_base=FAKE_CID_BASE))
sr.register_profile(sr.SensorProfile("quadcam", REGISTERS, contexts="ABCD", driver_cid_base=FAKE_CID_BASE))
