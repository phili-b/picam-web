"""Sensor registers over I2C: list the named registers, read some, dump a range.

    python 06_registers.py [http://raspberrypi.local]

Reads only. Writing is shown commented out at the end: writes go straight to the sensor and the
driver does not know about them (it may overwrite them at a mode switch or stream start).
"""

from _common import CameraError, connect

cam = connect()
regs = cam.known_registers()
if not regs:
    raise SystemExit("No named registers: no sensor profile for this sensor (see docs/registers.md)")

print(f"{len(regs)} named registers; the first 10:")
for r in regs[:10]:
    try:
        value = cam.read_register(r["address"], nbytes=r["bytes"])
        print(f"  {r['name']:22s} 0x{r['address']:04x} = 0x{value:0{2 * r['bytes']}x} ({value})")
    except CameraError as e:
        print(f"  {r['name']:22s} 0x{r['address']:04x}: {e}")

start = regs[0]["address"] & ~0xF
print(f"\nDump of 32 registers from 0x{start:04x}:")
dump = cam.dump_registers(start, 32)
for i in range(0, len(dump), 16):
    print(f"  0x{dump[i][0]:04x}: " + " ".join(f"{v:02x}" for _, v in dump[i:i + 16]))

# Sensors with a banked register map: registers can depend on the bank and the context
#   cam.read_register(0x000E, nbytes=4, bank=0, context=1)
# Writing (bypasses the driver):
#   cam.write_register(0x2091, 0x01)          # e.g. a test pattern register
#   cam.write_register(0x000E, 5000, nbytes=4)
