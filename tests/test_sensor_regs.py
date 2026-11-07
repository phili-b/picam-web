"""Register and context access through the driver controls and over I2C (simulated, tests/fake)."""

import ctypes
import importlib
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fake"))
sys.path.insert(0, os.path.join(HERE, "..", "picam_viewer"))
importlib.import_module("fake_profiles")  # registers the fakecam profiles
import fake_subdev  # noqa: E402
import sensor_regs as sr  # noqa: E402
import smbus2  # noqa: E402  (the simulated one)

sr.SMBus, sr.i2c_msg = smbus2.SMBus, smbus2.i2c_msg


def regs(model, driver=True, streaming=True):
    info = sr.SensorInfo(model, 1, 0x36)
    return sr.SensorRegs(info, driver=fake_subdev.FakeSubdev(info, streaming) if driver else None) \
        if driver else _i2c(info)


def _i2c(info):
    saved = sr.open_driver_controls
    sr.open_driver_controls = lambda info: None
    try:
        return sr.SensorRegs(info)
    finally:
        sr.open_driver_controls = saved


def test_ioctl_layout_matches_the_kernel():
    assert ctypes.sizeof(sr._ExtControl) == 20
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert sr.VIDIOC_G_EXT_CTRLS == 0xC0205647 and sr.VIDIOC_S_EXT_CTRLS == 0xC0205648


def test_backend():
    assert regs("duocam").backend == "driver"
    assert regs("duocam", driver=False).backend == "i2c"


@pytest.mark.parametrize("driver", [True, False])
def test_contexts_are_separate(driver):
    r = regs("quadcam", driver)
    for ctx in range(4):
        r.write(0x000E, 1000 + ctx, 4, bank=1, context=ctx)
    assert [r.read(0x000E, 4, bank=1, context=c) for c in range(4)] == [1000, 1001, 1002, 1003]
    r.write(0x000E, 7, 4, bank=0)
    assert r.read(0x000E, 4, bank=0) == 7 and r.read(0x000E, 4, bank=1, context=0) == 1000
    with pytest.raises(ValueError):
        r.read(0x000E, 4, bank=1, context=4)
    with pytest.raises(ValueError):
        regs("duocam", driver).read(0x000E, 4, bank=1, context=2)  # duocam has A and B only


def test_driver_restores_bank_0_and_context_a():
    r = regs("duocam")
    r.write(0x0020, 0x55, bank=1, context=1)
    assert r.driver._raw(0xE000, 1) == [0] and r.driver._raw(0xE004, 1) == [0]


def test_dump_through_the_driver():
    r = regs("fakecam")
    r.write(0x1000, 0x0102030405 & 0xFFFFFFFF, 4)
    r.write(0x1004, 0x06, 1)
    assert [v for _, v in r.dump(0x1000, 5)] == [0x02, 0x03, 0x04, 0x05, 0x06]


def test_sequence_banks_are_tracked_through_the_driver():
    r = regs("duocam")
    r.write_sequence([(0xE004, 1), (0xE000, 1), (0x0030, 0xAA), (0xE000, 0), (0x0030, 0xBB)])
    assert r.read(0x0030, bank=1, context=1) == 0xAA
    assert r.read(0x0030, bank=0) == 0xBB


def test_not_streaming():
    r = regs("duocam", streaming=False)
    with pytest.raises(RuntimeError, match="streams"):
        r.read(0x0010)
    assert r.contexts()["current"] is None


def test_contexts():
    r = regs("quadcam")
    c = r.contexts()
    assert c == {"contexts": "ABCD", "context": "A", "current": "A", "auto_switch": False,
                 "auto_switch_to": "A", "controls_context": "all"}
    c = r.set_contexts(context="C", auto_switch=True, auto_switch_to="B", controls_context="D")
    assert (c["context"], c["current"], c["auto_switch"], c["auto_switch_to"], c["controls_context"]) == \
        ("C", "C", True, "B", "D")
    assert r.set_contexts(controls_context="all")["controls_context"] == "all"
    with pytest.raises(ValueError):
        regs("duocam").set_contexts(context="C")


def test_no_contexts():
    assert regs("fakecam").contexts() is None
    assert regs("duocam", driver=False).contexts() is None
    with pytest.raises(RuntimeError):
        regs("fakecam").set_contexts(context="A")


def test_find_subdev(tmp_path):
    d = tmp_path / "v4l-subdev3"
    d.mkdir()
    (d / "name").write_text("duocam 10-0036\n")
    (tmp_path / "v4l-subdev0").mkdir()
    (tmp_path / "v4l-subdev0" / "name").write_text("rp1-cfe-csi2\n")
    assert sr.find_subdev(sr.SensorInfo("duocam", 10, 0x36), str(tmp_path)) == "/dev/v4l-subdev3"
    assert sr.find_subdev(sr.SensorInfo("fakecam", 4, 0x54), str(tmp_path)) is None
