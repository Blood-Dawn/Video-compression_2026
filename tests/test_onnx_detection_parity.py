"""
tests/test_onnx_detection_parity.py

Parity test for the ONNX detection backend (M2 TASK 2.1).

Asserts that the ONNX Runtime YOLOv8n backend produces detections that agree
with the PyTorch/ultralytics backend within an agreed tolerance on a real
CDnet surveillance clip. This is what gives us confidence to make ONNX the
default and drop torch from the installer (TASK 2.2).

Heavily skip-guarded so it runs locally (where yolov8n.onnx is exported and the
CDnet clips are present) but skips cleanly on CI, where:
  * yolov8n.onnx is a build artifact (*.onnx is gitignored), and
  * the CDnet clips are git-LFS and not pulled.

Export the model once with:  yolo export model=yolov8n.pt format=onnx imgsz=640

Author: Bloodawn (KheivenD), 2026-06-02 (TASK 2.1 - ONNX/torch parity).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

pytest.importorskip("onnxruntime", reason="onnxruntime not installed")
pytest.importorskip("cv2", reason="opencv not installed")

import cv2  # noqa: E402

from detection.onnx_backend import COCO_NAMES, YoloOnnxDetector  # noqa: E402

_ONNX_MODEL = REPO / "yolov8n.onnx"
_CLIP = REPO / "data" / "samples" / "cdnet_mp4" / "baseline" / "baseline_highway.mp4"
_CONF = 0.25
_N_FRAMES = 6


def test_coco_names_has_80_classes():
    assert len(COCO_NAMES) == 80
    assert COCO_NAMES[0] == "person"
    assert COCO_NAMES[2] == "car"


def test_onnx_backend_unavailable_is_graceful(tmp_path):
    """A missing model leaves the backend unavailable and infer() returns []."""
    det = YoloOnnxDetector(model_path=str(tmp_path / "nope.onnx"))
    assert det.available is False
    import numpy as np
    assert det.infer(np.zeros((64, 64, 3), dtype=np.uint8)) == []


@pytest.mark.skipif(not _ONNX_MODEL.exists(),
                    reason="yolov8n.onnx not exported (build artifact; *.onnx gitignored)")
def test_onnx_backend_loads_and_runs():
    det = YoloOnnxDetector(model_path=str(_ONNX_MODEL), confidence=_CONF)
    assert det.available
    import numpy as np
    # Inference on a blank frame must not crash (likely zero detections).
    out = det.infer(np.full((480, 640, 3), 128, dtype=np.uint8))
    assert isinstance(out, list)


@pytest.mark.skipif(not _ONNX_MODEL.exists(),
                    reason="yolov8n.onnx not exported (build artifact)")
@pytest.mark.skipif(not _CLIP.exists(),
                    reason="CDnet clip not present (git-LFS not pulled, e.g. on CI)")
def test_onnx_matches_torch_on_cdnet_clip():
    """ONNX and torch agree on detection class-sets and counts within tolerance."""
    ultralytics = pytest.importorskip("ultralytics", reason="ultralytics not installed")
    YOLO = ultralytics.YOLO

    onnx_det = YoloOnnxDetector(model_path=str(_ONNX_MODEL), confidence=_CONF)
    assert onnx_det.available
    torch_model = YOLO(str(REPO / "yolov8n.pt"))

    cap = cv2.VideoCapture(str(_CLIP))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    # Sample evenly across the clip, skipping the first few frames.
    if total > 0:
        idxs = [int(total * f) for f in (0.1, 0.25, 0.4, 0.55, 0.7, 0.85)][:_N_FRAMES]
    else:
        idxs = list(range(30, 30 + _N_FRAMES * 10, 10))

    frames_compared = 0
    class_set_matches = 0
    count_close = 0
    for fi in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        frames_compared += 1

        onnx_names = {d.class_name for d in onnx_det.infer(frame)}
        onnx_n = len([d for d in onnx_det.infer(frame)])

        r = torch_model(frame, verbose=False, conf=_CONF)[0]
        torch_names = {r.names[int(b.cls[0])] for b in r.boxes}
        torch_n = len(r.boxes)

        if onnx_names == torch_names:
            class_set_matches += 1
        # Count within max(1, 30% of torch count).
        if abs(onnx_n - torch_n) <= max(1, int(round(0.3 * torch_n))):
            count_close += 1
    cap.release()

    assert frames_compared >= 3, "could not read enough frames from the clip"
    # Same weights -> the two backends should agree on most frames. Allow one
    # frame of slack for NMS / preprocessing rounding differences.
    assert class_set_matches >= frames_compared - 1, (
        f"class-set parity {class_set_matches}/{frames_compared} too low"
    )
    assert count_close >= frames_compared - 1, (
        f"detection-count parity {count_close}/{frames_compared} too low"
    )
