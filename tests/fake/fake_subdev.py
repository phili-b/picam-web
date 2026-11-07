"""Simulated sensor sub-device with driver register access controls (see sensor_regs).

Behaves like a driver with these controls: they select the bank and context, access the
(simulated, smbus2.py) sensor and select bank 0 / context A again; register values are only
accessible while "streaming". Sensors with contexts (duocam, quadcam) also get the
context controls.
"""

import errno
import threading

import sensor_regs as sr
import smbus2


class FakeSubdev:
    def __init__(self, info, streaming=True):
        self.info = info
        self.streaming = streaming
        self.bus = smbus2.SMBus(info.bus)
        self.lock = threading.Lock()
        self.values = {sr.CID_REG_ADDRESS: 0, sr.CID_REG_WIDTH: 1, sr.CID_REG_VALUE: 0}
        if info.banked:
            self.values.update({sr.CID_REG_BANK: 0, sr.CID_REG_CONTEXT: 0, sr.CID_CONTEXT: 0,
                                sr.CID_CURRENT_CONTEXT: 0, sr.CID_AUTO_CONTEXT_SWITCH: 0,
                                sr.CID_AUTO_SWITCH_CONTEXT: 0, sr.CID_CONTROLS_CONTEXT: 0})
        self.closed = False

    def close(self):
        self.closed = True

    def has(self, cid):
        return cid in self.values

    def _check(self, cid):
        if cid not in self.values:
            raise OSError(errno.EINVAL, "Invalid argument")

    def _raw(self, reg, n=None, data=None):
        a = self.info.addr
        w = smbus2.i2c_msg.write(a, [reg >> 8, reg & 0xFF, *(data or [])])
        if data is not None:
            self.bus.i2c_rdwr(w)
            return None
        r = smbus2.i2c_msg.read(a, n)
        self.bus.i2c_rdwr(w, r)
        return list(r)

    def _access(self, write, value=0):
        if not self.streaming:
            raise OSError(errno.EBUSY, "Device or resource busy")
        reg, n = self.values[sr.CID_REG_ADDRESS], self.values[sr.CID_REG_WIDTH]
        if reg + n - 1 > 0xFFFF:
            raise OSError(errno.EINVAL, "Invalid argument")
        if write and not 0 <= value < 1 << (8 * n):
            raise OSError(errno.ERANGE, "Numerical result out of range")
        banked = sr.is_banked(self.info, reg)
        if banked:
            self._raw(self.info.profile.rw_context_reg, data=[self.values[sr.CID_REG_CONTEXT]])
            self._raw(self.info.profile.bank_sel_reg, data=[self.values[sr.CID_REG_BANK]])
        if write:
            self._raw(reg, data=list(value.to_bytes(n, "big")))
            result = value
        else:
            result = int.from_bytes(bytes(self._raw(reg, n)), "big")
        if banked:
            self._raw(self.info.profile.rw_context_reg, data=[0])
            self._raw(self.info.profile.bank_sel_reg, data=[0])
        return result

    def get(self, *cids):
        with self.lock:
            out = []
            for cid in cids:
                self._check(cid)
                if cid == sr.CID_REG_VALUE:
                    out.append(self._access(False))
                elif cid == sr.CID_CURRENT_CONTEXT:
                    if not self.streaming:
                        raise OSError(errno.EBUSY, "Device or resource busy")
                    out.append(self.values[sr.CID_CONTEXT])  # switches at once in the simulation
                else:
                    out.append(self.values[cid])
            return out

    def set(self, *pairs):
        with self.lock:
            for cid, value in pairs:
                self._check(cid)
                if cid == sr.CID_CURRENT_CONTEXT:
                    raise OSError(errno.EACCES, "Permission denied")
                if cid == sr.CID_REG_VALUE:
                    self._access(True, value)
                else:
                    self.values[cid] = value
