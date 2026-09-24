"""
test_object_filter.py

Unit tests for src/detection/object_filter.py's detect_scene_type().

Covers the "TikTok clip tagged intersection at night" bug: a vertical/
handheld-shaped frame used to be run through the same motion-direction
heuristic built for fixed, wide-angle surveillance cameras, and multi-
directional camera shake/pan could misclassify it as "intersection" with
zero real cross-traffic. It now short-circuits to "handheld" for portrait
frames, and (see test_pipeline.py's TestCompensateCameraMotion) camera pan
is subtracted out of the vectors before they even get here.
"""

from detection.object_filter import detect_scene_type


class TestPortraitFrameIsHandheld:
    def test_portrait_frame_short_circuits_to_handheld(self):
        # Motion vectors here are deliberately the same "multi-directional
        # traffic" shape that would otherwise trigger "intersection" -
        # orientation must win regardless of what the motion looks like.
        vectors = [(5, 5), (-5, 5), (5, -5), (-5, -5), (0, 6)]
        result = detect_scene_type(vectors, roi_count=5, frame_w=1080, frame_h=1920)
        assert result == "handheld"

    def test_square_frame_is_not_treated_as_portrait(self):
        vectors = [(10, 0), (10, 0), (11, 0), (9, 0)]
        result = detect_scene_type(vectors, roi_count=4, frame_w=1080, frame_h=1080)
        assert result != "handheld"

    def test_unknown_dimensions_fall_back_to_motion_heuristic(self):
        # frame_w/frame_h default to 0 (unknown, e.g. an older caller) -
        # must not accidentally trip the portrait shortcut.
        vectors = [(10, 0), (10, 0), (11, 0), (9, 0)]
        result = detect_scene_type(vectors, roi_count=4)
        assert result != "handheld"


class TestLandscapeMotionHeuristicUnchanged:
    """The pre-existing fixed-camera behaviour must still hold for real
    landscape/CCTV-shaped frames - this fix should not regress it."""

    def test_dominant_single_direction_is_highway(self):
        vectors = [(10, 0)] * 8 + [(9, 1)]
        result = detect_scene_type(vectors, roi_count=9, frame_w=1920, frame_h=1080)
        assert result == "highway"

    def test_diverse_directions_is_intersection(self):
        vectors = [(10, 0), (0, 10), (-10, 0), (0, -10), (7, 7)]
        result = detect_scene_type(vectors, roi_count=5, frame_w=1920, frame_h=1080)
        assert result == "intersection"

    def test_too_few_rois_is_unknown(self):
        vectors = [(10, 0), (0, 10)]
        result = detect_scene_type(vectors, roi_count=2, frame_w=1920, frame_h=1080)
        assert result == "unknown"

    def test_no_vectors_is_unknown(self):
        result = detect_scene_type([], roi_count=10, frame_w=1920, frame_h=1080)
        assert result == "unknown"
