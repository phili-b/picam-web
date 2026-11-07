import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "picam_web"))
import health  # noqa: E402


def test_state_history():
    h = health.Health()
    h.set("streaming", "ok")
    h.set("streaming", "ok")  # unchanged: no new history entry
    h.set("stalled", "no frames")
    d = h.as_dict()
    assert d["state"] == "stalled" and len(d["history"]) == 2


def test_recovery_file_window(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "RECOVERY_FILE", str(tmp_path / "r.json"))
    assert health.load_recovery() == {}
    health.save_recovery(2)
    assert health.load_recovery()["level"] == 2
    monkeypatch.setattr(health, "RECOVERY_WINDOW", 0)
    time.sleep(0.01)
    assert health.load_recovery() == {}  # too old: a new incident
    health.clear_recovery()
    health.clear_recovery()  # no error when already gone


def test_kernel_patterns():
    assert health.KERNEL_PATTERNS.search("imx219 10-0010: Error writing reg 0x01e4: -121")
    assert health.KERNEL_PATTERNS.search("rp1-cfe 1f00110000.csi: stream on failed in subdev")
    assert not health.KERNEL_PATTERNS.search("rp1-cfe 1f00110000.csi: Using a link rate of 1500 Mbps")


def test_watchdog_interval(monkeypatch):
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)
    assert health.watchdog_interval() is None
    monkeypatch.setenv("WATCHDOG_USEC", "30000000")
    assert health.watchdog_interval() == 15
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert health.sd_notify("READY=1") is False
