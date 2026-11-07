"""Register access to the camera sensor.

Two backends, chosen automatically:

- driver: register access controls of the sensor driver on its /dev/v4l-subdevN, for drivers
  that have them (described by a sensor profile, see below). The driver selects the bank and
  context, does the access and selects bank 0 / context A again, all under its own lock, so
  this cannot mix with the driver's own register writes. Only works while the sensor streams.
  Such drivers may also have context controls (active context, auto switching, the context the
  exposure and frame time controls go to); see `contexts()`.
- i2c: for other drivers, combined write/read transfers (I2C_RDWR) on the sensor's I2C bus.
  The kernel allows these even while the driver owns the address, but they can race with
  the driver's own bank selection.

Registers have 16-bit addresses and 8-bit values; multi-byte values are big-endian.
Writes are not known to the driver, which may overwrite them when it reconfigures the
sensor (mode switch, stream start, exposure change).

Sensor profiles (`SensorProfile`) add what is specific to a sensor: named registers, a register
map split in banks and contexts, and the driver's register access controls. They come from
plugins: every module in the `sensor_plugins` folder next to this file is imported at start and
calls `register_profile()`. Without a profile, a sensor is found by the camera's model name and
accessed by address over I2C.
"""

import csv
import ctypes
import errno
import glob
import importlib.util
import logging
import os
import pkgutil
import re
import threading
from dataclasses import dataclass, field

try:
    import fcntl
except ImportError:  # not on Windows; only needed on the Pi
    fcntl = None

try:
    from smbus2 import SMBus, i2c_msg
except ImportError:  # allows importing (and testing the parsers) without smbus2
    SMBus = i2c_msg = None

@dataclass
class SensorProfile:
    """What is specific to a sensor (registered by a plugin, see the module docstring)."""
    name: str                                       # as found in the I2C device or driver name
    registers: list = field(default_factory=list)   # named registers: (name, address, bytes)
    contexts: str = ""            # context names of a map split in banks and contexts; "" = flat map
    bank_sel_reg: int = 0xE000    # banked maps: the bank select register
    rw_context_reg: int = 0xE004  # ... the register that selects the context accessed in bank 1
    bankless_regs: int = 0x006    # ... offsets below this in each 4 KiB block are not banked
    driver_cid_base: int | None = None  # first id of the driver's register access controls (None: none)


PROFILES = {}


def register_profile(profile):
    """Add or replace a sensor profile (called by plugins)."""
    PROFILES[profile.name] = profile


def is_banked(info, reg):
    """True if reg depends on the bank select register (and, in bank 1, on the context)."""
    return info.banked and (reg & 0x0FFF) >= info.profile.bankless_regs


# Driver controls: offsets from the profile's driver_cid_base ---------------------------------
CID_CONTEXT = 0
CID_CURRENT_CONTEXT = 1
CID_AUTO_CONTEXT_SWITCH = 2
CID_AUTO_SWITCH_CONTEXT = 3
CID_CONTROLS_CONTEXT = 4
CID_REG_ADDRESS = 8
CID_REG_BANK = 9
CID_REG_CONTEXT = 10
CID_REG_WIDTH = 11
CID_REG_VALUE = 12


class _ExtControl(ctypes.Structure):
    _pack_ = 1  # struct v4l2_ext_control is packed
    _fields_ = [("id", ctypes.c_uint32), ("size", ctypes.c_uint32), ("reserved2", ctypes.c_uint32),
                ("value64", ctypes.c_int64)]


class _ExtControls(ctypes.Structure):
    _fields_ = [("which", ctypes.c_uint32), ("count", ctypes.c_uint32), ("error_idx", ctypes.c_uint32),
                ("request_fd", ctypes.c_int32), ("reserved", ctypes.c_uint32), ("controls", ctypes.c_void_p)]


def _iowr(nr, size):
    return (3 << 30) | (size << 16) | (ord("V") << 8) | nr


VIDIOC_G_EXT_CTRLS = _iowr(71, ctypes.sizeof(_ExtControls))
VIDIOC_S_EXT_CTRLS = _iowr(72, ctypes.sizeof(_ExtControls))


class Subdev:
    """V4L2 controls of a sub-device node, through VIDIOC_G/S_EXT_CTRLS. Control ids are offsets
    from base (the profile's driver_cid_base)."""

    def __init__(self, path, base=0):
        self.path = path
        self.base = base
        self.fd = os.open(path, os.O_RDWR)

    def close(self):
        os.close(self.fd)

    def _ioctl(self, request, pairs):
        arr = (_ExtControl * len(pairs))()
        for c, (cid, value) in zip(arr, pairs):
            c.id, c.value64 = self.base + cid, int(value)
        ctrls = _ExtControls(which=0, count=len(pairs), controls=ctypes.addressof(arr))
        fcntl.ioctl(self.fd, request, ctrls)
        return [c.value64 for c in arr]

    def get(self, *cids):
        """Values of the controls (one ioctl)."""
        return self._ioctl(VIDIOC_G_EXT_CTRLS, [(c, 0) for c in cids])

    def set(self, *pairs):
        """Set (cid, value) pairs, in this order, in one ioctl."""
        self._ioctl(VIDIOC_S_EXT_CTRLS, pairs)

    def has(self, cid):
        try:
            self.get(cid)
        except OSError as e:
            # EBUSY: the control exists but the sensor is not streaming
            return e.errno == errno.EBUSY
        return True


def find_subdev(info, sysfs="/sys/class/video4linux"):
    """/dev/v4l-subdevN of the sensor, or None."""
    for d in sorted(glob.glob(os.path.join(sysfs, "v4l-subdev*"))):
        try:
            with open(os.path.join(d, "name")) as fh:
                name = fh.read().strip().lower()
        except OSError:
            continue
        # the subdev name is "<driver> <bus>-<addr>", e.g. "imx219 10-0010"
        if name.startswith(info.name) or f"{info.bus}-{info.addr:04x}" in name:
            return "/dev/" + os.path.basename(d)
    return None


def open_driver_controls(info):
    """The sensor's Subdev if its profile names driver register access controls and the driver
    has them, else None."""
    base = info.profile.driver_cid_base
    path = find_subdev(info) if base is not None else None
    if not path:
        return None
    try:
        sd = Subdev(path, base)
    except OSError:
        return None
    if sd.has(CID_REG_ADDRESS):
        return sd
    sd.close()
    return None


@dataclass
class SensorInfo:
    name: str
    bus: int
    addr: int

    @property
    def profile(self):
        """The registered SensorProfile, or a plain one (no named registers, flat map)."""
        return PROFILES.get(self.name) or SensorProfile(self.name)

    @property
    def banked(self):
        return bool(self.profile.contexts)

    @property
    def contexts(self):
        """Names of the contexts of the bank 1 registers, e.g. "AB"; "" if not banked."""
        return self.profile.contexts

    @property
    def registers(self):
        """Named registers: [(name, address, bytes)]."""
        return list(self.profile.registers)

    def __str__(self):
        return f"{self.name} on /dev/i2c-{self.bus} at 0x{self.addr:02x}"


def find_sensor(sysfs="/sys/bus/i2c/devices", names=()):
    """Return the SensorInfo of the first sensor bound on an I2C bus whose device or driver name
    contains a profile name or one of names (e.g. the camera's model), or None."""
    wanted = [n.lower() for n in (*PROFILES, *names) if n]
    for dev in sorted(glob.glob(os.path.join(sysfs, "*-00[0-9a-f][0-9a-f]"))):
        m = re.match(r"(\d+)-([0-9a-f]{4})$", os.path.basename(dev))
        if not m:
            continue
        found = []
        for f in ("name", "driver"):
            p = os.path.join(dev, f)
            if f == "driver" and os.path.islink(p):
                found.append(os.path.basename(os.path.realpath(p)))
            elif os.path.isfile(p):
                with open(p) as fh:
                    found.append(fh.read().strip())
        # the device name first: one driver can serve several sensors (its name is then less exact)
        for n in found:
            for name in wanted:
                if name in n.lower():
                    return SensorInfo(name, int(m.group(1)), int(m.group(2), 16))
    return None


def parse_int(text):
    """Parse '0x1A', '1Ah' or '26' style numbers."""
    text = text.strip().lower()
    if text.endswith("h"):
        return int(text[:-1], 16)
    return int(text, 0)


def parse_sequence(path):
    """Parse a register sequence file into a list of (addr, value).

    Supported formats (as used by the lab scripts):
      write <value> to <addr>     one per line, '#' starts a comment
      <addr>,<value>              CSV
    """
    seq = []
    with open(path, newline="") as fh:
        lines = fh.read().splitlines()
    if path.lower().endswith(".csv"):
        for row in csv.reader(lines):
            if len(row) >= 2 and row[0].strip() and not row[0].strip().startswith("#"):
                try:
                    seq.append((parse_int(row[0]), parse_int(row[1])))
                except ValueError:
                    continue  # header line
        return seq
    for line in lines:
        words = line.split("#", 1)[0].split()
        lower = [w.lower() for w in words]
        if "write" in lower:
            i = lower.index("write")
            if len(words) >= i + 4 and lower[i + 2] == "to":
                seq.append((parse_int(words[i + 3]), parse_int(words[i + 1])))
    return seq


class SensorRegs:
    """Read and write sensor registers, through the driver if it can, else over I2C.

    Thread-safe: each call runs under one lock, so concurrent callers cannot mix up each
    other's bank, context or register address selection.

    bank / context None: bank 0 and context A through the driver (the driver always returns
    to those); over I2C, leave BANK_SEL / RW_CONTEXT as they are.
    """

    def __init__(self, info: "SensorInfo", driver=None):
        self.info = info
        self.lock = threading.RLock()
        self.bus = None
        self.driver = driver if driver is not None else open_driver_controls(info)
        if self.driver is None:
            if SMBus is None:
                raise RuntimeError("smbus2 is not installed (apt install python3-smbus2)")
            self.bus = SMBus(info.bus)
        self._has_bank = self.driver is not None and self.driver.has(CID_REG_BANK)

    @property
    def backend(self):
        return "driver" if self.driver is not None else "i2c"

    def close(self):
        if self.driver is not None:
            self.driver.close()
        if self.bus is not None:
            self.bus.close()

    # I2C access -----------------------------------------------------------
    def _read(self, reg, n=1):
        w = i2c_msg.write(self.info.addr, [reg >> 8, reg & 0xFF])
        r = i2c_msg.read(self.info.addr, n)
        self.bus.i2c_rdwr(w, r)
        return list(r)

    def _write(self, reg, values):
        self.bus.i2c_rdwr(i2c_msg.write(self.info.addr, [reg >> 8, reg & 0xFF, *values]))

    def _select(self, bank, context):
        """Select bank/context over I2C, return the previous values to restore."""
        saved = []
        if not self.info.banked:
            return saved
        p = self.info.profile
        if bank is not None:
            saved.append((p.bank_sel_reg, self._read(p.bank_sel_reg)[0]))
            self._write(p.bank_sel_reg, [bank])
        if context is not None:
            saved.append((p.rw_context_reg, self._read(p.rw_context_reg)[0]))
            self._write(p.rw_context_reg, [context])
        return saved

    def _restore(self, saved):
        for reg, value in reversed(saved):
            self._write(reg, [value])

    # Driver access --------------------------------------------------------
    def _driver_select(self, reg, nbytes, bank, context):
        pairs = [(CID_REG_ADDRESS, reg), (CID_REG_WIDTH, nbytes)]
        if self._has_bank:
            pairs += [(CID_REG_BANK, bank or 0), (CID_REG_CONTEXT, context or 0)]
        return pairs

    @staticmethod
    def _driver_error(e):
        if e.errno == errno.EBUSY:
            return RuntimeError("the driver accesses registers only while the camera streams")
        return e

    def _driver_read(self, reg, nbytes, bank, context):
        try:
            self.driver.set(*self._driver_select(reg, nbytes, bank, context))
            return self.driver.get(CID_REG_VALUE)[0]
        except OSError as e:
            raise self._driver_error(e) from e

    def _driver_write(self, reg, value, nbytes, bank, context):
        try:
            self.driver.set(*self._driver_select(reg, nbytes, bank, context), (CID_REG_VALUE, value))
        except OSError as e:
            raise self._driver_error(e) from e

    # Public API -----------------------------------------------------------
    @staticmethod
    def _check(reg, nbytes=1):
        if not 0 <= reg <= 0xFFFF or reg + nbytes - 1 > 0xFFFF:
            raise ValueError(f"register address 0x{reg:x} (+{nbytes} bytes) is outside 0x0000-0xFFFF")
        if not 1 <= nbytes <= 4:
            raise ValueError(f"{nbytes} bytes: 1 to 4 bytes per access")

    def _check_select(self, bank, context):
        if bank is not None and bank not in (0, 1):
            raise ValueError(f"bank {bank}: the banks are 0 and 1")
        if context is not None and not 0 <= context < len(self.info.contexts or "A"):
            raise ValueError(f"context {context}: {self.info.name} has contexts {self.info.contexts or 'A'}")

    def read(self, reg, nbytes=1, bank=None, context=None):
        """Read nbytes from reg; returns the big-endian integer value."""
        self._check(reg, nbytes)
        self._check_select(bank, context)
        with self.lock:
            if self.driver is not None:
                return self._driver_read(reg, nbytes, bank, context)
            saved = self._select(bank, context)
            try:
                data = self._read(reg, nbytes)
            finally:
                self._restore(saved)
        return int.from_bytes(bytes(data), "big")

    def write(self, reg, value, nbytes=1, bank=None, context=None):
        """Write value (big-endian, nbytes) to reg."""
        self._check(reg, nbytes)
        self._check_select(bank, context)
        if not 0 <= value < 1 << (8 * nbytes):
            raise ValueError(f"value {value} (0x{value:x}) does not fit in {nbytes} byte(s)")
        with self.lock:
            if self.driver is not None:
                return self._driver_write(reg, value, nbytes, bank, context)
            saved = self._select(bank, context)
            try:
                self._write(reg, list(value.to_bytes(nbytes, "big")))
            finally:
                self._restore(saved)

    def dump(self, start, count, bank=None, context=None):
        """Read count consecutive 8-bit registers; returns a list of (addr, value)."""
        if count < 1 or not 0 <= start <= 0xFFFF or start + count - 1 > 0xFFFF:
            raise ValueError(f"dump 0x{start:x} +{count} is outside 0x0000-0xFFFF")
        self._check_select(bank, context)
        out = []
        with self.lock:
            if self.driver is not None:
                for base in range(start, start + count, 4):
                    n = min(4, start + count - base)
                    v = self._driver_read(base, n, bank, context)
                    out.extend(zip(range(base, base + n), v.to_bytes(n, "big")))
                return out
            saved = self._select(bank, context)
            try:
                for base in range(start, start + count, 32):
                    n = min(32, start + count - base)
                    out.extend(zip(range(base, base + n), self._read(base, n)))
            finally:
                self._restore(saved)
        return out

    def write_sequence(self, seq):
        """Write a list of (addr, value) 8-bit writes in order. Banks and contexts are part of
        the sequence (writes to BANK_SEL and RW_CONTEXT); through the driver they are tracked
        and applied to the writes that follow."""
        for reg, _ in seq:
            self._check(reg)
        with self.lock:
            if self.driver is None:
                for reg, value in seq:
                    self._write(reg, [value & 0xFF])
                return len(seq)
            bank = context = 0
            p = self.info.profile
            for reg, value in seq:
                value &= 0xFF
                if self.info.banked and reg & 0x0FFF == p.bank_sel_reg & 0x0FFF:
                    bank = value & 1
                elif self.info.banked and reg & 0x0FFF == p.rw_context_reg & 0x0FFF:
                    context = value
                self._driver_write(reg, value, 1, bank, context)
        return len(seq)

    # Contexts (driver controls) -------------------------------------------
    def has_contexts(self):
        return self.driver is not None and bool(self.info.contexts) and self.driver.has(CID_CONTEXT)

    def contexts(self):
        """The context controls of the driver, or None if it has none:
        {"contexts": "AB", "context", "current" (None if not streaming), "auto_switch",
        "auto_switch_to", "controls_context" ("all" or a context)}"""
        if not self.has_contexts():
            return None
        names = self.info.contexts
        with self.lock:
            ctx, auto, auto_to, controls = self.driver.get(
                CID_CONTEXT, CID_AUTO_CONTEXT_SWITCH, CID_AUTO_SWITCH_CONTEXT, CID_CONTROLS_CONTEXT)
            try:
                current = names[self.driver.get(CID_CURRENT_CONTEXT)[0]]
            except (OSError, IndexError):
                current = None
        return {"contexts": names, "context": names[ctx], "current": current, "auto_switch": bool(auto),
                "auto_switch_to": names[auto_to], "controls_context": "all" if controls == 0 else names[controls - 1]}

    def set_contexts(self, context=None, auto_switch=None, auto_switch_to=None, controls_context=None):
        """Set the given context controls (None: leave as it is). Contexts by name ("A", "B", ...),
        controls_context also "all"."""
        if not self.has_contexts():
            raise RuntimeError(f"the {self.info.name} driver has no context controls")
        names = self.info.contexts

        def index(name, what):
            if name not in names:
                raise ValueError(f"{what} {name!r}: {self.info.name} has contexts {', '.join(names)}")
            return names.index(name)

        pairs = []
        if controls_context is not None:
            pairs.append((CID_CONTROLS_CONTEXT, 0 if controls_context == "all"
                          else index(controls_context, "controls context") + 1))
        if auto_switch_to is not None:
            pairs.append((CID_AUTO_SWITCH_CONTEXT, index(auto_switch_to, "auto switch context")))
        if auto_switch is not None:
            pairs.append((CID_AUTO_CONTEXT_SWITCH, int(bool(auto_switch))))
        if context is not None:
            pairs.append((CID_CONTEXT, index(context, "context")))
        if pairs:
            with self.lock:
                self.driver.set(*pairs)
        return self.contexts()


# Plugins -------------------------------------------------------------------------------------
PLUGIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sensor_plugins")


def load_plugins(folder=PLUGIN_DIR):
    """Import every module in folder; plugins call register_profile(). A broken plugin is
    logged and skipped."""
    for m in pkgutil.iter_modules([folder]):
        try:
            spec = importlib.util.spec_from_file_location(f"sensor_plugins.{m.name}",
                                                          os.path.join(folder, m.name + ".py"))
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("sensor plugin %s", m.name)


load_plugins()
