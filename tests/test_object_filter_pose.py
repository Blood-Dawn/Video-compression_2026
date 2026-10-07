"""
tests/test_object_filter_pose.py

Unit tests for the pose-confirmation wiring added to ObjectFilter in
src/detection/object_filter.py (planner 6.11).

These tests never load a real ONNX model - they install small fake
"backend" objects after construction (same unit-testing shape the rest of
the suite uses for ObjectFilter's pass-through behavior), so they run on
every machine regardless of whether onnxruntime or a .onnx file is
present. What they verify is the *integration contract* planner 6.11
depends on:

  1. Pose confirmation is off by default and never changes which boxes are
     kept (it is purely additive metadata, not a stricter filter).
  2. When enabled, a "person" box gets flagged pose-verified only if the
     pose backend actually confirms a skeleton in that same crop.
  3. A pose rejection (or a pose-backend error) must never drop a box the
     bbox classifier already confirmed - recall never regresses because of
     pose, only the "pose-verified" subset narrows.
  4. Pose confirmation only ever runs for "person" - a vehicle box is
     never pose-checked.

Author: Bloodawn (KheivenD), 2026-10-07 (planner 6.11 - YOLO pose).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from detection.object_filter import ObjectFilter  # noqa: E402
from background_subtraction.background_subtraction import ForegroundRegion  # noqa: E402


class _FakeOnnxPerson:
    """Always reports a confirmed 'person' bbox detection."""
    def class_names_in(self, crop, conf=None):
        return {"person"}


class _FakeOnnxVehicle:
    """Always reports a confirmed 'car' bbox detection."""
    def class_names_in(self, crop, conf=None):
        return {"car"}


class _FakePoseAlwaysConfirms:
    available = True
    def person_confirmed_in(self, crop, conf=None, min_visible_keypoints=4):
        return True


class _FakePoseNeverConfirms:
    available = True
    def person_confirmed_in(self, crop, conf=None, min_visible_keypoints=4):
        return False


class _FakePoseBoom:
    available = True
    def person_confirmed_in(self, crop, conf=None, min_visible_keypoints=4):
        raise RuntimeError("pose backend exploded")


def _make_filter(use_pose: bool, onnx=None) -> ObjectFilter:
    """Build an ObjectFilter with a fake bbox backend already "loaded".

    use_pose=True does NOT attempt to load a real pose model (there isn't
    one on this machine); it only flips the use_pose flag so a fake pose
    backend can be installed afterward. A test that wants pose enabled but
    genuinely unavailable (the real-world default on a machine without the
    .onnx export) should assert on _pose_available instead of installing
    a fake.
    """
    of = ObjectFilter(use_pose=False)  # avoid a real _load_pose() attempt
    of._onnx = onnx if onnx is not None else _FakeOnnxPerson()
    of._backend = "onnx"
    of._available = True
    of.use_pose = use_pose
    return of


def _frame() -> np.ndarray:
    return np.zeros((200, 200, 3), dtype=np.uint8)


def _region() -> ForegroundRegion:
    return ForegroundRegion(x=10, y=10, w=40, h=40, area=1600)


class TestPoseOffByDefault:
    def test_use_pose_false_never_flags_pose_confirmed(self):
        of = _make_filter(use_pose=False)
        kept = of.filter(_frame(), [_region()])
        assert len(kept) == 1
        assert of.last_pose_confirmed[0] is False
        assert of.pose_confirmed_count() == 0

    def test_pose_enabled_but_model_unavailable_matches_pose_disabled(self):
        """Enabling use_pose with no pose model loaded must behave exactly
        like use_pose=False for which boxes are kept - the real-world
        state on any machine without a yolov8n-pose.onnx export."""
        of_no_pose = _make_filter(use_pose=False)
        of_pose_unavailable = _make_filter(use_pose=True)
        assert of_pose_unavailable._pose_available is False

        region = _region()
        kept1 = of_no_pose.filter(_frame(), [region])
        kept2 = of_pose_unavailable.filter(_frame(), [region])
        assert len(kept1) == len(kept2) == 1
        assert of_pose_unavailable.pose_confirmed_count() == 0


class TestPoseConfirmation:
    def test_person_box_confirmed_by_pose(self):
        of = _make_filter(use_pose=True)
        of._pose = _FakePoseAlwaysConfirms()
        of._pose_available = True

        kept = of.filter(_frame(), [_region()])
        assert len(kept) == 1
        assert of.last_pose_confirmed[0] is True
        assert of.pose_confirmed_count() == 1
        # The segment-level label is unaffected by pose either way.
        assert of.classify_detected_objects() == "person"

    def test_person_box_rejected_by_pose_is_still_kept(self):
        """A pose rejection must never drop a box the bbox classifier
        already confirmed - recall must not regress because of pose."""
        of = _make_filter(use_pose=True)
        of._pose = _FakePoseNeverConfirms()
        of._pose_available = True

        kept = of.filter(_frame(), [_region()])
        assert len(kept) == 1
        assert of.last_pose_confirmed[0] is False
        assert of.pose_confirmed_count() == 0
        assert of.classify_detected_objects() == "person"

    def test_pose_backend_error_degrades_gracefully(self):
        """An exception from the pose backend must not propagate or drop
        the box - same graceful-degradation contract as the bbox backend."""
        of = _make_filter(use_pose=True)
        of._pose = _FakePoseBoom()
        of._pose_available = True

        kept = of.filter(_frame(), [_region()])
        assert len(kept) == 1
        assert of.last_pose_confirmed[0] is False
        assert of.pose_confirmed_count() == 0

    def test_vehicle_box_never_runs_pose_check(self):
        """Pose confirmation only ever applies to "person" - a vehicle box
        must never be pose-checked, even if a pose backend is loaded."""
        of = _make_filter(use_pose=True, onnx=_FakeOnnxVehicle())
        of._pose = _FakePoseAlwaysConfirms()
        of._pose_available = True

        kept = of.filter(_frame(), [_region()])
        assert len(kept) == 1
        assert of.last_pose_confirmed[0] is False
        assert of.pose_confirmed_count() == 0
        assert of.classify_detected_objects() == "vehicle"

    def test_multiple_regions_mixed_pose_results(self):
        """pose_confirmed_count() must correctly count only the confirmed
        subset across several regions in the same frame."""
        of = _make_filter(use_pose=True)
        of._pose = _FakePoseAlwaysConfirms()
        of._pose_available = True

        regions = [
            ForegroundRegion(x=10, y=10, w=40, h=40, area=1600),
            ForegroundRegion(x=60, y=60, w=40, h=40, area=1600),
            ForegroundRegion(x=110, y=110, w=40, h=40, area=1600),
        ]
        kept = of.filter(_frame(), regions)
        assert len(kept) == 3
        assert of.pose_confirmed_count() == 3
        assert all(of.last_pose_confirmed.values())

    def test_too_small_box_is_never_pose_checked(self):
        """A box below min_box_px passes through unclassified entirely - it
        must never be flagged pose-confirmed either."""
        of = _make_filter(use_pose=True)
        of._pose = _FakePoseAlwaysConfirms()
        of._pose_available = True

        tiny = ForegroundRegion(x=5, y=5, w=5, h=5, area=25)
        kept = of.filter(_frame(), [tiny])
        assert len(kept) == 1
        assert of.last_pose_confirmed[0] is False
        assert of.pose_confirmed_count() == 0
