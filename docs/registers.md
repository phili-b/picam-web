# Registers

`picam_viewer/sensor_regs.py` reads and writes the sensor registers in one of two ways, chosen
automatically and shown in the Registers tab:

- **Through the driver**, for drivers with register access controls on the sensor's
  `/dev/v4l-subdevN` (described by a [sensor plugin](#sensor-plugins)). The driver selects the bank
  and context, does the access and selects bank 0 / context A again, under its own lock, so this
  does not interfere with the driver's own register writes. It only works while the camera streams.
- **Directly over I2C**, for all other drivers: combined write/read transfers (`I2C_RDWR`) on
  `/dev/i2c-N`, which the kernel allows while the driver owns the address. Bank and context
  selection can then race with the driver.

!!! warning "The driver does not know about your writes"
    The driver may overwrite register writes made here when it reconfigures the sensor, for
    example on a mode switch, at stream start or when the exposure changes. Writing the wrong
    register can also stop the sensor from streaming.

## Finding the sensor

`find_sensor()` looks through `/sys/bus/i2c/devices/<bus>-<addr>` for a device whose `name` or bound
driver contains the name of a sensor plugin profile, or the camera's model name (the libcamera
`Model` property, e.g. `imx477`). It returns the first one found (name, bus, 7-bit address), shown as
e.g. `imx477 on /dev/i2c-10 at 0x1a`. So any sensor with 16-bit register addresses works without a
plugin, by address.

## Register format

- 16-bit addresses, sent big-endian;
- 8-bit registers; multi-byte values (1-4 bytes) are read and written big-endian from consecutive
  addresses;
- dumps read 8-bit registers, 32 at a time.

## Sensor plugins

A sensor plugin adds what is specific to a sensor: named registers, a register map split in banks
and contexts, and the driver's register access and context controls. Every `.py` file in
`picam_viewer/sensor_plugins/` is imported at start (that folder is ignored by git, apart from its
README); a plugin calls `register_profile()`:

```python
# picam_viewer/sensor_plugins/mysensor.py
import sensor_regs as sr

sr.register_profile(sr.SensorProfile(
    "mysensor",                         # as found in the I2C device or driver name
    registers=[("CHIP_ID", 0x0000, 2), ("EXPOSURE", 0x0202, 2)],   # (name, address, bytes)
    contexts="AB",                      # optional: banked register map with contexts A and B
    driver_cid_base=0x00980900 + 0x2000,  # optional: the driver's register access controls
))
```

| Field | Default | |
|-------|---------|-|
| `name` | | matched against the I2C device and driver names |
| `registers` | `[]` | named registers `(name, address, bytes)`, listed in the UI and by `GET /api/registers/known` |
| `contexts` | `""` | context names of a banked register map; `""` = flat map |
| `bank_sel_reg`, `rw_context_reg` | `0xE000`, `0xE004` | banked maps: the bank select register and the register that selects the context accessed in bank 1 |
| `bankless_regs` | `0x006` | banked maps: offsets below this in each 4 KiB block are not banked |
| `driver_cid_base` | `None` | first V4L2 control id of the driver's register access controls (see below); `None` = I2C only |

A broken plugin is logged and skipped.

### Banks and contexts

In a banked register map, every register at an offset of `bankless_regs` or more in its 4 KiB block
exists in bank 0 and bank 1, and those of bank 1 once per context. Through the driver, bank and
context default to bank 0 and context A. Over I2C, when a bank or context is given, the access saves
the current bank select / context register value, selects the requested one, does the read, write
or dump, and restores the previous values; without them ("current"), the registers are left as they
are. Sensors with a flat map ignore bank and context.

### Driver controls

A driver with register access controls has these V4L2 controls on the sensor sub-device, at
`driver_cid_base` + the offset:

| Offset | Control | |
|-------:|---------|-|
| 8 | register address | address of the next access |
| 11 | register width | 1-4 bytes, big-endian |
| 9 | register bank | bank 0 or 1 (banked maps) |
| 10 | register context | context of bank 1 registers (banked maps) |
| 12 | register value | reading it reads the register, setting it writes the register |
| 0 | context | the context the sensor switches to |
| 1 | current context | the context in use, read-only |
| 2, 3 | auto context switch, auto switch to context | automatic context switching |
| 4 | controls context | where exposure and frame time go: all contexts (0) or one (1 = A, ...) |

The context controls (offsets 0-4) are only used for profiles with `contexts`. The web UI has them
under **Registers → Contexts**, the HTTP API under `/api/sensor/contexts` and the Python API as
`contexts()` / `set_contexts()`.

## Register sequences

The desktop viewer's Registers tab can load a sequence file and write it after a confirmation.
`parse_sequence()` reads two formats:

**Text** (any extension other than `.csv`): one write per line, `#` starts a comment.

```
# set the exposure
write 0x01 to 0xE000
write 0x10 to 0x000E
write 27h to 0x000F
```

**CSV** (`.csv`): `<addr>,<value>` per row; a header row and rows starting with `#` are skipped.

```
addr,value
0xE000,0x01
0x000E,0x10
```

Numbers can be hex (`0x1A` or `1Ah`) or decimal (`26`). Every entry is an 8-bit write, in the given
order: banks and contexts are not selected for you, so put the bank select / context writes in the
sequence itself. Through the driver, these writes are tracked and the writes that follow go to that
bank and context.

Sequences are not available in the web UI or the HTTP API.

## From Python on the Pi

`sensor_regs.py` can be used on its own (needs `python3-smbus2` without driver controls):

```python
import sys
sys.path.insert(0, "/opt/picam_viewer/picam_viewer")
import sensor_regs

info = sensor_regs.find_sensor(names=["imx477"])   # profile names are always searched
regs = sensor_regs.SensorRegs(info)
print(regs.backend)                      # "driver" or "i2c"
print(hex(regs.read(0x0202, nbytes=2)))
print(regs.contexts())                   # drivers with context controls, else None
regs.write(0x0202, 1000, nbytes=2)
for addr, value in regs.dump(0x0000, 32):
    print(f"0x{addr:04x} 0x{value:02x}")
regs.write_sequence(sensor_regs.parse_sequence("sequence.txt"))
regs.close()
```

`SensorRegs` serialises its own calls with a lock. While the web service runs, prefer the
[HTTP API](http-api.md) or the [Python API](python-api.md).
