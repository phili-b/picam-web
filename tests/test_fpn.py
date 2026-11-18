"""The FPN switch: a symlink to the calibration directory, on a temporary folder."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "picam_web"))
import fpn  # noqa: E402


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    try:
        (tmp_path / "probe").symlink_to(tmp_path)
    except OSError:
        pytest.skip("no symlinks here (Windows without developer mode)")
    calibration, link = tmp_path / "fpn", tmp_path / "fpn-active"
    calibration.mkdir()
    monkeypatch.setenv("PICAM_FPN_DIR", str(calibration))
    monkeypatch.setenv("PICAM_FPN_LINK", str(link))
    return calibration, link


def test_not_available_without_setup(monkeypatch):
    monkeypatch.delenv("PICAM_FPN_DIR", raising=False)
    monkeypatch.delenv("PICAM_FPN_LINK", raising=False)
    assert fpn.status() == {"available": False, "enabled": False}
    with pytest.raises(RuntimeError):
        fpn.set_enabled(True)


def test_switch(dirs):
    calibration, link = dirs
    assert fpn.status() == {"available": True, "enabled": False}
    fpn.set_enabled(True)
    fpn.set_enabled(True)   # again: fine
    assert fpn.status()["enabled"] and link.resolve() == calibration.resolve()
    fpn.set_enabled(False)
    fpn.set_enabled(False)
    assert fpn.status() == {"available": True, "enabled": False} and not link.is_symlink()
    assert calibration.is_dir()


def test_link_to_something_else_is_off(dirs, tmp_path):
    _, link = dirs
    other = tmp_path / "other"
    other.mkdir()
    link.symlink_to(other)
    assert fpn.status()["enabled"] is False


def test_real_directory_at_the_link_is_left_alone(dirs):
    _, link = dirs
    link.mkdir()
    assert fpn.status()["available"] is False
    with pytest.raises(RuntimeError):
        fpn.set_enabled(False)
    assert link.is_dir()
