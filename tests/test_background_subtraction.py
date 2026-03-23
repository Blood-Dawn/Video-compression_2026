"""
test_background_subtraction.py

Unit tests for the BackgroundSubtractor module.
Run with: pytest tests/ -v
"""

import numpy as np
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from background_subtraction.background_subtraction import BackgroundSubtractor, ForegroundRegion


def make_blank_frame(h=480, w=640):
    return np.zeros((h, w, 3), dtype=np.uint8)


def make_frame_with_object(h=480, w=640, obj_x=200, obj_y=150, obj_w=80, obj_h=100):
    frame = make_blank_frame(h, w)
    frame[obj_y:obj_y+obj_h, obj_x:obj_x+obj_w] = 200
    return frame


class TestBackgroundSubtractor:

    def test_initialization_mog2(self):
        bs = BackgroundSubtractor(method="MOG2")
        assert bs.method == "MOG2"

    def test_initialization_knn(self):
        bs = BackgroundSubtractor(method="KNN")
        assert bs.method == "KNN"

    def test_invalid_method_raises(self):
        with pytest.raises(ValueError):
            BackgroundSubtractor(method="INVALID")

    def test_apply_returns_binary_mask(self):
        bs = BackgroundSubtractor(method="MOG2")
        frame = make_blank_frame()
        mask = bs.apply(frame)
        assert mask.shape == (480, 640)
        unique_vals = set(np.unique(mask))
        assert unique_vals.issubset({0, 255})

    def test_static_scene_produces_no_foreground(self):
        bs = BackgroundSubtractor(method="MOG2", history=50)
        frame = make_blank_frame()
        # Feed the same frame many times to build background model
        for _ in range(60):
            mask = bs.apply(frame)
        regions = bs.get_foreground_regions(mask)
        assert len(regions) == 0, "Static scene should produce no foreground regions"

    def test_foreground_region_expand_clamps_to_frame(self):
        r = ForegroundRegion(x=5, y=5, w=10, h=10, area=100)
        expanded = r.expand(pad=20, frame_w=640, frame_h=480)
        assert expanded.x == 0
        assert expanded.y == 0

    def test_foreground_region_to_tuple(self):
        r = ForegroundRegion(x=10, y=20, w=30, h=40, area=1200)
        assert r.to_tuple() == (10, 20, 30, 40)


class TestForegroundRegion:

    def test_area_calculation(self):
        r = ForegroundRegion(0, 0, 100, 100, 10000)
        assert r.area == 10000
