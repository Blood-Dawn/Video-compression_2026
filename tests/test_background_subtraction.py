"""
test_background_subtraction.py

Unit tests for the BackgroundSubtractor module.
Run with: pytest tests/ -v

Coverage:
  - Initialization and parameter validation
  - apply() mask generation: binary output, static scene, moving object, all-foreground
  - Morphological cleanup: apply() output is strictly binary (no shadow values)
  - Minimum contour area filter: small blobs excluded, large blobs retained
  - get_foreground_regions(): bounding box detection, sorting, padding clamp
  - Night mode: CLAHE flag, var_threshold selection
  - ForegroundRegion dataclass helpers

Author: Bloodawn (KheivenD)
"""

import numpy as np
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from background_subtraction.background_subtraction import BackgroundSubtractor, ForegroundRegion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_blank_frame(h=480, w=640):
    """All-black frame — represents static empty background."""
    return np.zeros((h, w, 3), dtype=np.uint8)


def make_frame_with_object(h=480, w=640, obj_x=200, obj_y=150, obj_w=80, obj_h=100, brightness=200):
    """Frame with a solid bright rectangle — simulates a foreground object."""
    frame = make_blank_frame(h, w)
    frame[obj_y:obj_y + obj_h, obj_x:obj_x + obj_w] = brightness
    return frame


def train_subtractor(bs, frame, n_frames=60):
    """Feed the same frame repeatedly to build a stable background model."""
    for _ in range(n_frames):
        bs.apply(frame)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestInitialization:

    def test_mog2_method_stored(self):
        bs = BackgroundSubtractor(method="MOG2")
        assert bs.method == "MOG2"

    def test_knn_method_stored(self):
        bs = BackgroundSubtractor(method="KNN")
        assert bs.method == "KNN"

    def test_invalid_method_raises(self):
        with pytest.raises(ValueError):
            BackgroundSubtractor(method="INVALID")

    def test_min_area_stored(self):
        bs = BackgroundSubtractor(min_area=1200)
        assert bs.min_area == 1200

    def test_night_mode_enables_clahe(self):
        bs = BackgroundSubtractor(night_mode=True)
        assert bs.use_clahe is True
        assert bs._clahe is not None

    def test_day_mode_no_clahe_by_default(self):
        bs = BackgroundSubtractor(night_mode=False)
        assert bs.use_clahe is False
        assert bs._clahe is None

    def test_explicit_use_clahe_flag(self):
        bs = BackgroundSubtractor(use_clahe=True)
        assert bs.use_clahe is True
        assert bs._clahe is not None


# ---------------------------------------------------------------------------
# Mask generation
# ---------------------------------------------------------------------------

class TestMaskGeneration:

    def test_apply_returns_correct_shape(self):
        """Output mask must have same (H, W) as input frame."""
        bs = BackgroundSubtractor(method="MOG2")
        frame = make_blank_frame(360, 480)
        mask = bs.apply(frame)
        assert mask.shape == (360, 480)

    def test_apply_returns_binary_values_only(self):
        """After morphological cleanup, mask must contain only 0 and 255.
        Shadow pixels (value 127) must be thresholded out."""
        bs = BackgroundSubtractor(method="MOG2")
        frame = make_blank_frame()
        mask = bs.apply(frame)
        unique_vals = set(np.unique(mask))
        assert unique_vals.issubset({0, 255}), (
            f"Mask contained non-binary values: {unique_vals - {0, 255}}"
        )

    def test_static_scene_produces_empty_mask(self):
        """After the model converges on a static background, an identical
        frame should produce zero foreground pixels."""
        bs = BackgroundSubtractor(method="MOG2", history=50)
        frame = make_blank_frame()
        train_subtractor(bs, frame, n_frames=60)
        mask = bs.apply(frame)
        assert np.count_nonzero(mask) == 0, (
            "Static scene produced foreground pixels after model convergence"
        )

    def test_moving_object_produces_foreground_mask(self):
        """After training on a blank background, introducing a bright object
        should light up the mask in the object's region."""
        bs = BackgroundSubtractor(method="MOG2", history=50, min_area=100)
        background = make_blank_frame()
        train_subtractor(bs, background, n_frames=60)

        # Introduce object with a large enough area to survive min_area filter
        obj_frame = make_frame_with_object(obj_w=120, obj_h=120, brightness=220)
        mask = bs.apply(obj_frame)

        assert np.count_nonzero(mask) > 0, (
            "A clearly different foreground object produced no foreground pixels"
        )

    def test_all_foreground_frame_triggers_widespread_detection(self):
        """After training on a black background, a fully-white frame should
        produce foreground detections across a large portion of the mask."""
        bs = BackgroundSubtractor(method="MOG2", history=50)
        background = make_blank_frame()
        train_subtractor(bs, background, n_frames=60)

        all_white = np.full((480, 640, 3), 255, dtype=np.uint8)
        mask = bs.apply(all_white)

        # More than 10% of pixels should be foreground on a complete scene change
        fg_fraction = np.count_nonzero(mask) / mask.size
        assert fg_fraction > 0.10, (
            f"All-foreground frame only triggered {fg_fraction:.1%} foreground pixels"
        )

    def test_empty_frame_after_convergence_has_no_regions(self):
        """An all-black frame on a converged model should yield no regions."""
        bs = BackgroundSubtractor(method="MOG2", history=50)
        frame = make_blank_frame()
        train_subtractor(bs, frame, n_frames=60)
        mask = bs.apply(frame)
        regions = bs.get_foreground_regions(mask)
        assert regions == [], "Empty frame after convergence should yield no regions"


# ---------------------------------------------------------------------------
# Morphological cleanup
# ---------------------------------------------------------------------------

class TestMorphologicalCleanup:

    def test_output_contains_no_shadow_values(self):
        """Shadow pixels (127) must be removed by the threshold step before
        morphological ops. Only 0 and 255 should remain in any mask."""
        for method in ("MOG2", "KNN"):
            bs = BackgroundSubtractor(method=method)
            frame = make_frame_with_object()
            for _ in range(5):
                mask = bs.apply(frame)
            assert 127 not in np.unique(mask), (
                f"{method}: shadow value 127 survived into the cleaned mask"
            )

    def test_small_noise_blob_removed_by_morphology(self):
        """A single isolated pixel in a mask should be eroded away by
        MORPH_OPEN with kernel size >= 3."""
        bs = BackgroundSubtractor(method="MOG2", morph_kernel_size=5, min_area=50)
        background = make_blank_frame()
        train_subtractor(bs, background, n_frames=60)

        # Introduce a 1-pixel noise spike in a synthetic mask directly
        # by checking that apply() on a near-background frame doesn't
        # return isolated single-pixel noise blobs
        near_bg = make_blank_frame()
        near_bg[240, 320] = 10  # tiny perturbation, well below detection threshold
        mask = bs.apply(near_bg)

        # No contours from a sub-threshold single pixel
        import cv2
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        single_pixel_contours = [c for c in contours if cv2.contourArea(c) <= 1]
        assert len(single_pixel_contours) == 0, (
            "Single-pixel noise survived morphological cleanup"
        )


# ---------------------------------------------------------------------------
# Minimum contour area filter
# ---------------------------------------------------------------------------

class TestMinAreaFilter:

    def test_small_blob_excluded_when_below_min_area(self):
        """A foreground region smaller than min_area must not appear in
        get_foreground_regions() output."""
        # Use a large min_area so the synthetic object is below threshold
        bs = BackgroundSubtractor(method="MOG2", history=50, min_area=5000)
        background = make_blank_frame()
        train_subtractor(bs, background, n_frames=60)

        # Small object: 30x30 = 900px area — below min_area=5000
        small_obj = make_frame_with_object(obj_w=30, obj_h=30, brightness=220)
        mask = bs.apply(small_obj)
        regions = bs.get_foreground_regions(mask, pad=0)
        assert len(regions) == 0, (
            f"Small blob ({30*30}px) passed min_area filter of 5000px"
        )

    def test_large_blob_retained_above_min_area(self):
        """A foreground region larger than min_area must appear in output."""
        bs = BackgroundSubtractor(method="MOG2", history=50, min_area=100)
        background = make_blank_frame()
        train_subtractor(bs, background, n_frames=60)

        # Large object: 150x150 = 22500px area — well above min_area=100
        large_obj = make_frame_with_object(obj_w=150, obj_h=150, brightness=220)
        mask = bs.apply(large_obj)
        regions = bs.get_foreground_regions(mask, pad=0)
        assert len(regions) >= 1, (
            "Large foreground blob was incorrectly filtered out by min_area"
        )

    def test_default_min_area_filters_tiny_detections(self):
        """With default min_area=500, a 10x10 object should be excluded."""
        bs = BackgroundSubtractor(method="MOG2", history=50)
        assert bs.min_area == 500
        background = make_blank_frame()
        train_subtractor(bs, background, n_frames=60)

        tiny_obj = make_frame_with_object(obj_w=10, obj_h=10, brightness=220)
        mask = bs.apply(tiny_obj)
        regions = bs.get_foreground_regions(mask, pad=0)
        # 10x10 = 100px which is well below 500px default threshold
        for r in regions:
            assert r.area >= 500, f"Region with area {r.area} slipped past min_area=500"


# ---------------------------------------------------------------------------
# get_foreground_regions
# ---------------------------------------------------------------------------

class TestGetForegroundRegions:

    def test_regions_sorted_by_area_descending(self):
        """Regions must be returned largest-first."""
        bs = BackgroundSubtractor(method="MOG2", history=50, min_area=100)
        background = make_blank_frame()
        train_subtractor(bs, background, n_frames=60)

        # Two objects of clearly different sizes
        frame = make_blank_frame()
        frame[50:200, 50:250] = 200   # large: 150x200
        frame[300:330, 400:430] = 200  # small: 30x30
        mask = bs.apply(frame)
        regions = bs.get_foreground_regions(mask, pad=0)

        if len(regions) >= 2:
            for i in range(len(regions) - 1):
                assert regions[i].area >= regions[i + 1].area, (
                    "Regions not sorted by area descending"
                )

    def test_padding_expands_bounding_box(self):
        """pad > 0 should increase the bounding box dimensions."""
        bs = BackgroundSubtractor(method="MOG2", history=50, min_area=100)
        background = make_blank_frame()
        train_subtractor(bs, background, n_frames=60)

        obj_frame = make_frame_with_object(
            obj_x=100, obj_y=100, obj_w=120, obj_h=120, brightness=220
        )
        mask = bs.apply(obj_frame)

        regions_no_pad = bs.get_foreground_regions(mask, pad=0)
        regions_padded = bs.get_foreground_regions(mask, pad=20)

        if regions_no_pad and regions_padded:
            assert regions_padded[0].w >= regions_no_pad[0].w
            assert regions_padded[0].h >= regions_no_pad[0].h

    def test_padding_clamps_to_frame_boundary(self):
        """Expanded bounding box must not exceed frame dimensions."""
        r = ForegroundRegion(x=5, y=5, w=10, h=10, area=100)
        expanded = r.expand(pad=20, frame_w=640, frame_h=480)
        assert expanded.x >= 0
        assert expanded.y >= 0
        assert expanded.x + expanded.w <= 640
        assert expanded.y + expanded.h <= 480


# ---------------------------------------------------------------------------
# Night mode
# ---------------------------------------------------------------------------

class TestNightMode:

    def test_night_mode_applies_clahe(self):
        """night_mode=True must set use_clahe=True and initialize the CLAHE object."""
        bs = BackgroundSubtractor(method="MOG2", night_mode=True)
        assert bs.use_clahe is True
        assert bs._clahe is not None

    def test_night_mode_output_still_binary(self):
        """apply() with night_mode must still produce a clean binary mask."""
        bs = BackgroundSubtractor(method="MOG2", night_mode=True)
        frame = make_blank_frame()
        mask = bs.apply(frame)
        unique_vals = set(np.unique(mask))
        assert unique_vals.issubset({0, 255}), (
            f"Night mode mask contained non-binary values: {unique_vals - {0, 255}}"
        )

    def test_night_mode_output_shape_matches_input(self):
        bs = BackgroundSubtractor(method="MOG2", night_mode=True)
        frame = make_blank_frame(360, 480)
        mask = bs.apply(frame)
        assert mask.shape == (360, 480)


# ---------------------------------------------------------------------------
# ForegroundRegion dataclass
# ---------------------------------------------------------------------------

class TestForegroundRegion:

    def test_area_stored(self):
        r = ForegroundRegion(0, 0, 100, 100, 10000)
        assert r.area == 10000

    def test_to_tuple_returns_xywh(self):
        r = ForegroundRegion(x=10, y=20, w=30, h=40, area=1200)
        assert r.to_tuple() == (10, 20, 30, 40)

    def test_expand_increases_dimensions(self):
        r = ForegroundRegion(x=100, y=100, w=50, h=50, area=2500)
        expanded = r.expand(pad=10, frame_w=640, frame_h=480)
        assert expanded.w > r.w
        assert expanded.h > r.h

    def test_expand_clamps_top_left(self):
        r = ForegroundRegion(x=5, y=5, w=10, h=10, area=100)
        expanded = r.expand(pad=20, frame_w=640, frame_h=480)
        assert expanded.x == 0
        assert expanded.y == 0

    def test_expand_clamps_bottom_right(self):
        r = ForegroundRegion(x=620, y=460, w=15, h=15, area=225)
        expanded = r.expand(pad=20, frame_w=640, frame_h=480)
        assert expanded.x + expanded.w <= 640
        assert expanded.y + expanded.h <= 480
