"""The camera model (dtoverlay) helper and module, on a temporary boot folder."""

import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
HELPER = os.path.join(ROOT, "tools", "picam-camera-overlay")
sys.path.insert(0, os.path.join(ROOT, "picam_viewer"))
sys.path.insert(0, os.path.join(ROOT, "picam_web"))
import camera_overlay  # noqa: E402

CONFIG = """# comment
camera_auto_detect=1
dtoverlay=vc4-kms-v3d

[pi5]
dtoverlay=nospi10

[all]
dtoverlay=imx219,cam0
"""


@pytest.fixture
def boot(tmp_path, monkeypatch):
    (tmp_path / "overlays").mkdir()
    for name in ("imx219", "imx477", "ov5647", "vc4-kms-v3d", "nospi10", "dwc2"):
        (tmp_path / "overlays" / f"{name}.dtbo").write_bytes(b"")
    (tmp_path / "config.txt").write_text(CONFIG)
    monkeypatch.setenv("PICAM_BOOT_DIR", str(tmp_path))
    monkeypatch.setattr(camera_overlay, "BOOT", str(tmp_path))
    monkeypatch.setattr(camera_overlay, "HELPER_CMD", [sys.executable, HELPER])
    return tmp_path


def helper(*args):
    return subprocess.run([sys.executable, HELPER, *args], capture_output=True, text=True)


def test_overlays_are_camera_sensors_only(boot):
    assert camera_overlay.overlays() == ["imx219", "imx477", "ov5647"]


def test_current(boot):
    c = camera_overlay.current()
    assert (c["overlay"], c["port"], c["mono"], c["line"], c["camera_auto_detect"]) == \
        ("imx219", "cam0", False, "dtoverlay=imx219,cam0", True)


def test_set_replaces_the_line_and_keeps_the_rest(boot):
    s = camera_overlay.set_overlay("imx477", "cam1", True)
    assert s["current"]["overlay"] == "imx477" and s["current"]["mono"] and s["current"]["port"] == "cam1"
    text = (boot / "config.txt").read_text()
    assert "imx219" not in text and text.endswith("[all]\ndtoverlay=imx477,mono\n")
    assert "dtoverlay=vc4-kms-v3d" in text and "dtoverlay=nospi10" in text  # other overlays stay
    assert (boot / "config.txt.picam-web.bak").read_text() == CONFIG
    camera_overlay.set_overlay("imx477", "cam0", False)  # same model again: one line, updated
    assert (boot / "config.txt").read_text().count("dtoverlay=imx477") == 1


def test_section_header_added_when_the_file_ends_elsewhere(boot):
    (boot / "config.txt").write_text("[pi5]\ndtoverlay=nospi10\n")
    camera_overlay.set_overlay("ov5647")
    assert (boot / "config.txt").read_text() == "[pi5]\ndtoverlay=nospi10\n\n[all]\ndtoverlay=ov5647\n"


def test_helper_rejects_bad_input(boot):
    for args in (("-", "../etc", "cam1", "0"), ("-", "nosuch", "cam1", "0"), ("-", "imx219", "cam2", "0"),
                 ("-", "imx219", "cam1", "2"), ("nosuch", "imx219", "cam1", "0"), ("-", "imx219")):
        r = helper(*args)
        assert r.returncode != 0, args
    assert (boot / "config.txt").read_text() == CONFIG
    with pytest.raises(ValueError):
        camera_overlay.set_overlay("vc4-kms-v3d")  # not a camera sensor
