"""Detector size choice: the setter, the file lookup with its fallback, and the status card."""
import sys
from pathlib import Path

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

from detection import onnx_backend as ob  # noqa: E402


@pytest.fixture(autouse=True)
def _reset():
    ob.set_detector_size(None)
    yield
    ob.set_detector_size(None)


def test_setter_accepts_known_sizes_and_strings():
    ob.set_detector_size(640)
    assert ob.get_detector_size() == 640
    ob.set_detector_size("416")
    assert ob.get_detector_size() == 416


@pytest.mark.parametrize("bad", [None, "", "abc", 100, 1281, 0])
def test_setter_ignores_unknown_values(bad):
    ob.set_detector_size(512)
    ob.set_detector_size(bad)
    assert ob.get_detector_size() is None


def test_missing_size_falls_back_to_the_default_file(tmp_path, monkeypatch):
    default = tmp_path / "yolov8n.onnx"
    default.write_bytes(b"x")
    monkeypatch.setattr(ob, "_default_model_path", lambda: default)
    assert ob.model_path_for_size(640) == default
    assert ob.model_path_for_size(None) == default


def test_installed_size_is_picked_up(tmp_path, monkeypatch):
    default = tmp_path / "yolov8n.onnx"
    big = tmp_path / "yolov8n_640.onnx"
    default.write_bytes(b"x")
    big.write_bytes(b"y")
    monkeypatch.setattr(ob, "_default_model_path", lambda: default)
    assert ob.model_path_for_size(640) == big
    assert ob.model_path_for_size(320) == default


def test_models_status_lists_every_size():
    from gui.services.models_status import models_status
    sizes = models_status()["detector_sizes"]
    assert [s["size"] for s in sizes] == [320, 416, 512, 640, 960, 1280]
    assert all({"label", "installed"} <= set(s) for s in sizes)
