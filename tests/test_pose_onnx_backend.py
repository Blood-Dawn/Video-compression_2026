"""
tests/test_pose_onnx_backend.py

Unit tests for src/detection/pose_onnx_backend.py (planner 6.11).

Mirrors test_onnx_detection_parity.py's shape: cheap, always-run checks for
the module's constants and its graceful-fallback behavior when the pose
ONNX model/runtime is unavailable, plus a skip-guarded test that only runs
when a real yolov8n-pose.onnx has been exported locally (it is a gitignored
build artifact, like yolov8n.onnx, so CI never has one).

Author: Bloodawn (KheivenD), 2026-10-07 (planner 6.11 - YOLO pose).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from detection.pose_onnx_backend import COCO_KEYPOINT_NAMES, YoloPoseOnnxDetector  # noqa: E402

_POSE_MODEL = REPO / "yolov8n-pose.onnx"


def test_coco_keypoint_names_has_17_entries():
    assert len(COCO_KEYPOINT_NAMES) == 17
    assert COCO_KEYPOINT_NAMES[0] == "nose"
    assert COCO_KEYPOINT_NAMES[5] == "left_shoulder"
    assert COCO_KEYPOINT_NAMES[-1] == "right_ankle"


def test_pose_detector_unavailable_is_graceful(tmp_path):
    """A missing model leaves the detector unavailable and infer()/
    person_confirmed_in() return empty/False rather than raising."""
    det = YoloPoseOnnxDetector(model_path=str(tmp_path / "nope.onnx"))
    assert det.available is False
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    assert det.infer(frame) == []
    assert det.person_confirmed_in(frame) is False


def test_pose_detector_unavailable_handles_empty_and_none_input():
    det = YoloPoseOnnxDetector(model_path="definitely-does-not-exist.onnx")
    assert det.infer(None) == []
    assert det.infer(np.zeros((0, 0, 3), dtype=np.uint8)) == []


@pytest.mark.skipif(not _POSE_MODEL.exists(),
                    reason="yolov8n-pose.onnx not exported (build artifact; gitignored)")
def test_pose_detector_loads_and_runs_on_real_model():
    pytest.importorskip("onnxruntime", reason="onnxruntime not installed")
    det = YoloPoseOnnxDetector(model_path=str(_POSE_MODEL), confidence=0.25)
    assert det.available
    # Inference on a blank frame must not crash (likely zero detections).
    out = det.infer(np.full((480, 640, 3), 128, dtype=np.uint8))
    assert isinstance(out, list)
    for det_result in out:
        assert len(det_result.keypoints) == 17
        for (x, y, v) in det_result.keypoints:
            assert isinstance(x, float) and isinstance(y, float) and isinstance(v, float)
    # Must not crash either way on a blank frame.
    assert det.person_confirmed_in(np.full((480, 640, 3), 128, dtype=np.uint8)) in (True, False)
