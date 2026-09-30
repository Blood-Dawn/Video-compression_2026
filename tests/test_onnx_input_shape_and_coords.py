"""
tests/test_onnx_input_shape_and_coords.py

Regression tests for two bugs found while investigating "generic metrics" /
object_type always being "unknown" (see docs/METRICS-*.md if present):

1. YoloOnnxDetector hardcoded imgsz=640 for letterboxing, but a .onnx export
   can bake in a different fixed input size (e.g. `yolo export imgsz=320`).
   When the two disagree, EVERY session.run() call raises an ONNX Runtime
   shape-mismatch error, which infer()'s broad except swallows into a
   silently-empty detection list -- no crash, no visible symptom, just
   permanently empty object_type/vehicle_count/person_count.

2. Some ONNX export toolchains emit box coordinates normalized to [0, 1] of
   the letterboxed canvas rather than absolute pixels in that canvas. Fed
   through the pixel-space unletterbox math unmodified, every box collapses
   to ~(0, 0, 0, 0) -- detections "work" (right class, right confidence) but
   are geometrically useless.

These tests use a lightweight fake onnxruntime session (no real .onnx
weights needed) so they run everywhere, including CI, unlike the real-model
parity test in test_onnx_detection_parity.py.

Author: Bloodawn (KheivenD), 2026-09-30.
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

pytest.importorskip("cv2", reason="opencv not installed")

from detection.onnx_backend import COCO_NAMES, YoloOnnxDetector  # noqa: E402

_N_CLASSES = len(COCO_NAMES)
_N_ANCHORS = 100


class _FakeInput:
    def __init__(self, shape):
        self.name = "images"
        self.shape = shape


class _FakeSession:
    """Stands in for onnxruntime.InferenceSession without needing real weights."""

    def __init__(self, input_shape, run_result=None):
        self._input_shape = input_shape
        self._run_result = run_result

    def get_inputs(self):
        return [_FakeInput(self._input_shape)]

    def get_providers(self):
        return ["CPUExecutionProvider"]

    def run(self, output_names, input_feed):
        if self._run_result is None:
            raise RuntimeError("no fake result configured")
        return [self._run_result]


def _bare_detector(imgsz=640, confidence=0.25) -> YoloOnnxDetector:
    """A YoloOnnxDetector with __init__ skipped, for unit-testing internals
    in isolation without touching the filesystem or onnxruntime."""
    det = YoloOnnxDetector.__new__(YoloOnnxDetector)
    det.confidence = confidence
    det.iou = 0.45
    det.imgsz = imgsz
    det.model_path = Path("fake_yolov8n.onnx")
    det._session = None
    det._input_name = "images"
    det._available = True
    det._inference_error_logged = False
    return det


def _make_pred(class_id: int, score: float, cx, cy, w, h) -> np.ndarray:
    """Build a synthetic (1, 84, N) YOLOv8-style raw model output with a
    single confident detection at index 0 and near-zero noise elsewhere."""
    pred = np.zeros((4 + _N_CLASSES, _N_ANCHORS), dtype=np.float32)
    pred[0, 0], pred[1, 0], pred[2, 0], pred[3, 0] = cx, cy, w, h
    pred[4 + class_id, 0] = score
    return pred[None, ...]


# --------------------------------------------------------------- imgsz auto-align

def test_align_imgsz_to_model_uses_the_models_fixed_input_size():
    det = _bare_detector(imgsz=640)
    det._session = _FakeSession(input_shape=[1, 3, 320, 320])
    det._align_imgsz_to_model()
    assert det.imgsz == 320


def test_align_imgsz_to_model_keeps_configured_default_when_dynamic():
    det = _bare_detector(imgsz=640)
    det._session = _FakeSession(input_shape=[1, 3, "height", "width"])
    det._align_imgsz_to_model()
    assert det.imgsz == 640


def test_align_imgsz_to_model_keeps_configured_default_for_non_square_input():
    det = _bare_detector(imgsz=640)
    det._session = _FakeSession(input_shape=[1, 3, 320, 640])
    det._align_imgsz_to_model()
    assert det.imgsz == 640


def test_align_imgsz_to_model_noop_when_already_matching():
    det = _bare_detector(imgsz=320)
    det._session = _FakeSession(input_shape=[1, 3, 320, 320])
    det._align_imgsz_to_model()
    assert det.imgsz == 320


# ------------------------------------------------------- infer(): shape mismatch

def test_infer_returns_empty_list_instead_of_raising_on_shape_mismatch():
    """A leftover mismatch (e.g. _align_imgsz_to_model never ran) must degrade
    to "no detections", never crash the caller mid-pipeline."""
    det = _bare_detector(imgsz=640)

    class _RaisingSession(_FakeSession):
        def run(self, output_names, input_feed):
            raise RuntimeError(
                "INVALID_ARGUMENT: Got invalid dimensions for input: images"
            )

    det._session = _RaisingSession(input_shape=[1, 3, 320, 320])
    frame = np.full((240, 320, 3), 128, dtype=np.uint8)
    assert det.infer(frame) == []
    assert det._inference_error_logged is True


# --------------------------------------------------- infer(): coordinate scaling

def test_infer_scales_normalized_box_coordinates_before_unletterboxing():
    """A box reported as fractions of the canvas (cx=cy=0.5, w=h=0.5 -> the
    center half of the frame) must land near the center of the ORIGINAL
    image, not collapse to a ~0-area box near the origin."""
    det = _bare_detector(imgsz=320, confidence=0.25)
    class_id = COCO_NAMES.index("car")
    pred = _make_pred(class_id, score=0.9, cx=0.5, cy=0.5, w=0.5, h=0.5)
    det._session = _FakeSession(input_shape=[1, 3, 320, 320], run_result=pred)

    # Square 320x320 source -> letterbox ratio 1.0, no padding, so canvas
    # space and original-image space are identical here.
    frame = np.full((320, 320, 3), 128, dtype=np.uint8)
    dets = det.infer(frame)

    assert len(dets) == 1
    d = dets[0]
    assert d.class_name == "car"
    x1, y1, x2, y2 = d.xyxy
    w, h = x2 - x1, y2 - y1
    # Expected: a box roughly spanning [80,240] in both axes (160px wide/tall,
    # centered). Degenerate output before the fix was ~(0,0,0,0).
    assert w > 100 and h > 100, f"box collapsed to near-zero size: {d.xyxy}"
    assert 60 <= x1 <= 100 and 60 <= y1 <= 100


def test_infer_leaves_pixel_space_box_coordinates_unchanged():
    """A box already in absolute canvas pixels (values >> 1.5) must NOT be
    re-scaled by imgsz a second time, or it would blow up off-frame."""
    det = _bare_detector(imgsz=320, confidence=0.25)
    class_id = COCO_NAMES.index("car")
    # Pixel-space: centered box, 160x160, in a 320x320 canvas.
    pred = _make_pred(class_id, score=0.9, cx=160.0, cy=160.0, w=160.0, h=160.0)
    det._session = _FakeSession(input_shape=[1, 3, 320, 320], run_result=pred)

    frame = np.full((320, 320, 3), 128, dtype=np.uint8)
    dets = det.infer(frame)

    assert len(dets) == 1
    x1, y1, x2, y2 = dets[0].xyxy
    w, h = x2 - x1, y2 - y1
    assert 100 <= w <= 320 and 100 <= h <= 320
    assert 60 <= x1 <= 100 and 60 <= y1 <= 100
