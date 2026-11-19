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
    assert fpn.status() == {"available": False, "enabled": False, "mode": "column"}
    with pytest.raises(RuntimeError):
        fpn.set_enabled(True)


def test_switch(dirs):
    calibration, link = dirs
    assert fpn.status() == {"available": True, "enabled": False, "mode": "column"}
    fpn.set_enabled(True)
    fpn.set_enabled(True)   # again: fine
    assert fpn.status()["enabled"] and link.resolve() == calibration.resolve()
    fpn.set_enabled(False)
    fpn.set_enabled(False)
    assert fpn.status() == {"available": True, "enabled": False, "mode": "column"} and not link.is_symlink()
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


def test_column_offsets_keep_the_phase_means():
    """Like libcamera: per row parity, column mean minus the mean of its CFA phase."""
    import numpy as np
    frame = np.full((4, 6), 100.0)
    frame[:, 2] += 6          # one even column higher
    frame[1::2, :] += 50      # odd rows: another black level, no column pattern
    off = fpn.column_offsets(frame)
    assert off.shape == (2, 6)
    assert np.allclose(off[:, 2], 4) and np.allclose(off[:, [0, 4]], -2) and np.allclose(off[:, 1::2], 0)


def test_mode_file(tmp_path, monkeypatch):
    """The mode is DIR/fpn_mode; no file (or an unknown word) means column."""
    calibration = tmp_path / "fpn"
    calibration.mkdir()
    monkeypatch.setenv("PICAM_FPN_DIR", str(calibration))
    monkeypatch.setenv("PICAM_FPN_LINK", str(tmp_path / "fpn-active"))
    assert fpn.get_mode() == "column"
    fpn.set_mode("full")
    assert (calibration / "fpn_mode").read_text() == "full\n" and fpn.status()["mode"] == "full"
    with pytest.raises(ValueError):
        fpn.set_mode("rows")
    (calibration / "fpn_mode").write_text("nonsense\n")
    assert fpn.get_mode() == "column"
