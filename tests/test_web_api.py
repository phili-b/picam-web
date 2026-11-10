"""Every HTTP endpoint of the web service against the simulated camera (tests/fake).

Needs fastapi and httpx (pip install fastapi httpx); skipped otherwise.
"""

import io
import json
import os
import sys
import time

import numpy as np
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fake"))
import run_fake  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "..", "picam_viewer"))
import sensor_regs  # noqa: E402

_find_sensor = sensor_regs.find_sensor
run_fake.setup()
_fake_find_sensor = sensor_regs.find_sensor
sensor_regs.find_sensor = _find_sensor  # only the service in this module sees the simulated sensor
import camera_service  # noqa: E402
import health  # noqa: E402
import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    state = tmp_path_factory.mktemp("state")
    saved = camera_service.SETTINGS_FILE, health.RECOVERY_FILE
    camera_service.SETTINGS_FILE = str(state / "picam_web.json")
    health.RECOVERY_FILE = str(state / "recovery.json")
    sensor_regs.find_sensor = _fake_find_sensor
    try:
        server.service = camera_service.CameraService()
    finally:
        sensor_regs.find_sensor = _find_sensor
    wait_for(lambda: server.service.health.state == "streaming")
    with TestClient(server.app) as c:
        yield c
    server.service.close()
    camera_service.SETTINGS_FILE, health.RECOVERY_FILE = saved


def wait_for(cond, timeout=10):
    t0 = time.time()
    while not cond():
        assert time.time() - t0 < timeout, "timed out"
        time.sleep(0.05)


def test_page_and_static(client):
    page = client.get("/")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"
    if os.path.isfile(os.path.join(server.WEB_DIST, "index.html")):  # the web UI is built
        assert '<div id="app">' in page.text
    assert "app.js" in client.get("/classic").text
    r = client.get("/static/app.js")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"


def test_info_controls_metadata(client):
    info = client.get("/api/info").json()
    assert info["properties"]["Model"] == "fakecam" and info["raw"]["size"] == [640, 480]
    assert info["instance"] and len(info["sensor_modes"]) == 2
    controls = client.get("/api/controls").json()
    assert {"ExposureTime", "AnalogueGain", "AeEnable"} <= set(controls)
    r = client.post("/api/controls", json={"AeEnable": False, "ExposureTime": 5000, "AnalogueGain": 2.0})
    assert r.json()["set"] == ["AeEnable", "ExposureTime", "AnalogueGain"]
    wait_for(lambda: client.get("/api/metadata").json()["ExposureTime"] == 5000)
    assert client.post("/api/controls", json={"NoSuchControl": 1}).status_code == 400


def test_remember_merges_and_forgets(client):
    client.post("/api/controls?remember=true", json={"ExposureTime": 7000})
    client.post("/api/controls?remember=true", json={"AnalogueGain": 3.0})
    assert camera_service.load_settings()["controls"] == {"ExposureTime": 7000, "AnalogueGain": 3.0}
    client.delete("/api/controls/remembered")
    assert "controls" not in camera_service.load_settings()


def test_controls_report_what_was_set_when_metadata_does_not(client):
    assert client.get("/api/controls").json()["HdrMode"]["value"] is None
    client.post("/api/controls", json={"HdrMode": 1})
    assert client.get("/api/controls").json()["HdrMode"]["value"] == 1
    client.post("/api/controls", json={"HdrMode": 0})


def test_a_new_white_balance_choice_replaces_the_kept_one(client):
    server.service.remember({"AwbEnable": False, "ColourGains": [2.0, 1.5], "ExposureTime": 7000})
    server.service.remember({"AwbEnable": True})
    assert camera_service.load_settings()["controls"] == {"AwbEnable": True, "ExposureTime": 7000}
    client.delete("/api/controls/remembered")


def test_mode_switch(client):
    r = client.post("/api/mode", json={"index": 1})
    assert r.status_code == 200 and r.json()["mode"] == 1
    assert client.get("/api/info").json()["raw"]["size"] == [320, 240]
    assert client.post("/api/mode", json={"index": 5}).status_code == 400
    client.post("/api/mode", json={"index": 0})
    wait_for(lambda: client.get("/api/health").json()["state"] == "streaming")


def test_frames_and_reset(client):
    wait_for(lambda: client.get("/api/frames").json()["frames"] > 3)
    f = client.post("/api/frames/reset").json()
    assert f["frames"] <= 2 and f["error"] is None


def test_captures(client):
    r = client.get("/api/capture/raw?count=3")
    with np.load(io.BytesIO(r.content)) as z:
        assert z["frames"].shape == (3, 480, 640) and z["frames"].dtype == np.uint16
        assert z["frames"].max() < 4096  # 12-bit DN, not the left-aligned 16-bit stream
        assert len(json.loads(str(z["metadata"]))) == 3
    assert client.get("/api/capture/raw?format=tiff").headers["content-type"] == "image/tiff"
    assert client.get("/api/capture/raw?format=dng").status_code == 200
    assert client.get("/api/capture/raw?format=png").status_code == 422
    assert client.get("/api/snapshot.jpg").content[:2] == b"\xff\xd8"


def test_capture_size_limit(client, monkeypatch):
    monkeypatch.setattr(camera_service, "MAX_CAPTURE_BYTES", 640 * 480 * 2 * 2)
    r = client.get("/api/capture/raw?count=3")
    assert r.status_code == 400 and "at most 2 frames" in r.json()["detail"]


def test_noise(client):
    r = client.post("/api/noise", json={"frames": 8, "roi": [10, 10, 64, 64]}).json()
    assert r["frames"] == 8 and r["pixels"] == 64 * 64 and 0 < r["temporal_noise"] < 20
    assert client.post("/api/noise", json={"frames": 4, "roi": [10, 10]}).status_code == 400
    assert client.post("/api/noise", json={"frames": 4, "roi": [9999, 0, 4, 4]}).status_code == 400


def test_histogram_rois(client):
    wait_for(lambda: "channels" in client.get("/api/histogram").json())
    assert client.get("/api/histogram").json()["bits"] == 12
    rois = client.put("/api/rois", json=[{"name": "A", "x": 600, "y": 10, "w": 500, "h": 20}]).json()
    assert rois[0]["w"] == 40  # clipped to the frame
    wait_for(lambda: client.get("/api/rois").json()[0]["mean"] == client.get("/api/rois").json()[0]["mean"])
    assert client.put("/api/rois", json=[{"x": -1, "y": 0, "w": 4, "h": 4}]).status_code == 400
    assert client.put("/api/rois", json=[{"x": 0}]).status_code == 400
    client.put("/api/rois", json=[])


def test_raw_crop_and_view(client):
    wait_for(lambda: client.get("/api/raw/crop?x=0&y=0&w=1&h=1").status_code == 200)
    c = client.get("/api/raw/crop?x=630&y=10&w=20&h=4").json()
    assert (c["x"], c["w"], c["h"], c["bits"]) == (630, 10, 4, 12)  # clipped at the right edge
    assert len(c["values"]) == 40 and max(c["values"]) < 4096
    assert client.get("/api/raw/crop?x=0&y=0&w=129&h=1").status_code == 422
    assert client.get("/api/raw/crop?x=9999&y=0&w=4&h=4").status_code == 400
    assert client.get("/api/frames").json()["view"] == [0, 0, 640, 480]


def test_isp_stats(client):
    assert client.get("/api/isp_stats").json()["enabled"] is False
    client.post("/api/isp_stats/enable", json={"enabled": True})
    wait_for(lambda: "zones_mean" in client.get("/api/isp_stats").json())
    s = client.get("/api/isp_stats").json()
    assert len(s["histogram"]) == 1024 and len(s["zones_mean"]) == 32
    client.post("/api/isp_stats/enable", json={"enabled": False})
    assert client.get("/api/isp_stats").json()["enabled"] is False


def test_registers(client):
    k = client.get("/api/registers/known").json()
    assert k["name"] == "fakecam" and k["registers"]
    assert client.put("/api/registers/4096", json={"value": 0xBEEF, "nbytes": 2}).status_code == 200
    assert client.get("/api/registers/4096?nbytes=2").json()["value"] == 0xBEEF
    d = client.get("/api/registers/dump?start=4096&count=2").json()
    assert [x["value"] for x in d] == [0xBE, 0xEF]
    assert client.put("/api/registers/4096", json={"value": 0x1FFFF, "nbytes": 2}).status_code == 400
    assert client.get("/api/registers/70000").status_code == 400
    assert k["backend"] == "driver" and k["contexts"] == ""


def test_contexts(client, monkeypatch):
    assert client.get("/api/sensor/contexts").json() == {"available": False}
    assert client.put("/api/sensor/contexts", json={"context": "A"}).status_code == 400
    # a sensor with four contexts and the context controls of its driver
    import fake_subdev
    info = sensor_regs.SensorInfo("quadcam", 1, 0x36)
    monkeypatch.setattr(server.service, "sensor_info", info)
    monkeypatch.setattr(server.service, "_regs", sensor_regs.SensorRegs(info, fake_subdev.FakeSubdev(info)))
    c = client.get("/api/sensor/contexts").json()
    assert c["available"] and c["contexts"] == "ABCD" and c["controls_context"] == "all"
    c = client.put("/api/sensor/contexts", json={"context": "B", "auto_switch": True}).json()
    assert c["context"] == "B" and c["current"] == "B" and c["auto_switch"] and c["auto_switch_to"] == "A"
    assert client.put("/api/sensor/contexts", json={"controls_context": "E"}).status_code == 400
    for ctx in (2, 3):
        assert client.put("/api/registers/14", json={"value": 50 + ctx, "nbytes": 4, "bank": 1,
                                                     "context": ctx}).status_code == 200
    assert client.get("/api/registers/14?nbytes=4&bank=1&context=3").json()["value"] == 53
    assert client.get("/api/registers/14?nbytes=4&bank=1&context=2").json()["value"] == 52
    assert client.get("/api/registers/known").json()["contexts"] == "ABCD"


def test_tuning(client, monkeypatch, tmp_path):
    assert client.get("/api/tuning").json()["current"] is None
    assert client.post("/api/tuning", json={"path": "/no/such.json"}).status_code == 400
    restarts = []
    monkeypatch.setattr(camera_service, "restart_process", lambda: restarts.append(1))
    monkeypatch.setattr(server.service, "close", lambda: None)
    monkeypatch.setattr(camera_service, "probe_tuning", lambda path: None)
    f = tmp_path / "fakecam.json"
    f.write_text("{}")
    assert client.post("/api/tuning", json={"path": str(f)}).status_code == 202
    assert camera_service.load_settings()["tuning_file"] == str(f)
    assert client.post("/api/tuning", json={"path": None}).status_code == 202  # back to the default
    assert "tuning_file" not in camera_service.load_settings()
    wait_for(lambda: len(restarts) == 2)


def test_health_auto_reboot(client):
    h = client.get("/api/health").json()
    assert h["state"] == "streaming" and h["instance"]
    assert client.post("/api/auto_reboot", json={"enabled": True}).json() == {"auto_reboot": True}
    assert client.get("/api/health").json()["auto_reboot"] is True
    client.post("/api/auto_reboot", json={"enabled": False})
    assert client.post("/api/reset", json={"action": "nonsense"}).status_code == 400


def test_manual_stream_reset(client):
    svc = server.service
    assert client.post("/api/reset", json={"action": "stream"}).status_code == 202
    wait_for(lambda: svc.health.state == "streaming")
    assert any("restarting the stream" in text for _, text in svc.health.history)


def test_stall_is_recovered(client, monkeypatch):
    """A camera that stops delivering frames: captures fail fast (no hang), the monitor escalates
    (restart the stream, then reopen the camera in a new process), and frames come back."""
    svc = server.service
    reopened = []
    monkeypatch.setattr(camera_service, "restart_process", lambda: reopened.append(1))
    monkeypatch.setattr(svc, "close", lambda: None)
    svc.health.level = 0
    svc.picam2.frozen = True
    t0 = time.time()
    r = client.get("/api/capture/raw?count=1")
    assert r.status_code == 503 and time.time() - t0 < 15
    # The timed-out capture must not block the camera: a mode switch (stop/start) still works.
    # (Found on a Pi 5: the queued capture made stop() wait forever.)
    t0 = time.time()
    assert client.post("/api/mode", json={"index": 0}).status_code == 200
    assert time.time() - t0 < 5
    wait_for(lambda: svc.health.level >= 1, 15)
    wait_for(lambda: reopened, 20)  # still no frames after the stream restart: level 2
    assert svc.health.level == 2
    # The new process would start the camera again; here the same one comes back
    svc.picam2.frozen = False
    svc.health.set("starting", "reopened")
    svc.started = time.monotonic()
    wait_for(lambda: svc.health.state == "streaming", 15)
    assert client.get("/api/capture/raw?count=1").status_code == 200


def test_unavailable_service():
    """Camera that cannot be opened: the UI and /api/health still answer, the rest is 503."""
    saved = server.service
    server.service = server.Unavailable("no camera")
    try:
        with TestClient(server.app) as c:
            assert c.get("/").status_code == 200
            assert c.get("/api/health").json()["state"] == "failed"
            assert c.get("/api/info").status_code == 503
            # a wrong camera model can still be fixed
            assert c.get("/api/camera_overlay").status_code == 200
    finally:
        server.service = saved


def test_unavailable_names_the_camera_model(tmp_path, monkeypatch):
    import camera_overlay
    (tmp_path / "overlays").mkdir()
    (tmp_path / "overlays" / "imx477.dtbo").write_bytes(b"")
    (tmp_path / "config.txt").write_text("[all]\ndtoverlay=imx477,cam0\n")
    monkeypatch.setattr(camera_overlay, "BOOT", str(tmp_path))
    monkeypatch.setattr(camera_overlay, "reboot_pending", lambda: False)
    message = server.Unavailable("No camera number 0 found").health.message
    assert "imx477 on CAM0" in message and "Camera model (dtoverlay)" in message
    monkeypatch.setattr(camera_overlay, "reboot_pending", lambda: True)
    assert "reboot the Raspberry Pi to load it" in server.Unavailable("x").health.message


def test_camera_overlay(client, tmp_path, monkeypatch):
    import camera_overlay
    (tmp_path / "overlays").mkdir()
    for name in ("fakecam", "imx477", "vc4-kms-v3d"):
        (tmp_path / "overlays" / f"{name}.dtbo").write_bytes(b"")
    (tmp_path / "config.txt").write_text("[all]\ndtoverlay=fakecam\n")
    monkeypatch.setattr(camera_overlay, "BOOT", str(tmp_path))
    monkeypatch.setenv("PICAM_BOOT_DIR", str(tmp_path))
    s = client.get("/api/camera_overlay").json()
    assert s["overlays"] == ["fakecam", "imx477"] and s["current"]["overlay"] == "fakecam"
    s = client.put("/api/camera_overlay", json={"overlay": "imx477", "port": "cam0", "mono": True}).json()
    assert s["current"]["line"] == "dtoverlay=imx477,cam0,mono"
    assert client.put("/api/camera_overlay", json={"overlay": "vc4-kms-v3d"}).status_code == 400
    assert client.put("/api/camera_overlay", json={"overlay": "imx477", "port": "cam2"}).status_code == 400
