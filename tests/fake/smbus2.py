"""Simulated smbus2 for sensor_regs: one sensor with 16-bit addresses and a 64 KiB register space.

Register banks and contexts (duocam, quadcam) are simulated: registers other than the bankless ones (offsets 0-5 of a
block) are stored per bank (BANK_SEL 0xE000) and, in bank 1, per context (RW_CONTEXT 0xE004), so reads and
writes with another bank or context see other values.
"""

import threading

_REGS = {}
_LOCK = threading.Lock()
BANK_SEL, RW_CONTEXT = 0xE000, 0xE004
_REGS[(0, 0, 0x011B)] = 0x50   # CHIP_ID


def _key(reg):
    if (reg & 0x0FFF) < 0x006:  # bankless: BANK_SEL, RW_CONTEXT, ...
        return (0, 0, reg)
    bank = _REGS.get((0, 0, BANK_SEL), 0) & 1
    # only bank 1 has a copy per context
    return (bank, _REGS.get((0, 0, RW_CONTEXT), 0) if bank else 0, reg)


class i2c_msg:
    def __init__(self, addr, flags, data):
        self.addr, self.flags, self.buf = addr, flags, list(data)

    @classmethod
    def write(cls, addr, data):
        return cls(addr, 0, data)

    @classmethod
    def read(cls, addr, length):
        return cls(addr, 1, [0] * length)

    def __iter__(self):
        return iter(self.buf)


class SMBus:
    def __init__(self, bus=None):
        self.bus = bus

    def close(self):
        pass

    def i2c_rdwr(self, *msgs):
        with _LOCK:
            reg = None
            for m in msgs:
                if m.flags == 0:
                    reg = (m.buf[0] << 8) | m.buf[1]
                    for i, v in enumerate(m.buf[2:]):
                        _REGS[_key(reg + i)] = v & 0xFF
                else:
                    if reg is None:
                        raise OSError(121, "Remote I/O error")
                    m.buf = [_REGS.get(_key(reg + i), 0) for i in range(len(m.buf))]
