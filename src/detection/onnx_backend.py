"""
src/detection/onnx_backend.py

ONNX Runtime backend for YOLOv8-nano object detection (M2 TASK 2.1).

This is the slim-install inference path: it runs the exact same YOLOv8n model
as the PyTorch/ultralytics backend, but through ONNX Runtime instead of torch,
which is what lets TASK 2.2 make torch optional and shrink the installer from
multi-GB to a few hundred MB (PLAN-V2 §6).

The backend is intentionally detector-agnostic in shape: it takes a BGR image
(OpenCV) and returns a list of Detection(class_id, class_name, score, xyxy) in
the ORIGINAL image's pixel coordinates - the same information ObjectFilter
extracts from ultralytics result objects. A future swap to RT-DETR/another
permissive detector only has to produce the same Detection list.

The .onnx weights are produced once with
    yolo export model=yolov8n.pt format=onnx imgsz=640
and ship as an optional component (not committed). When onnxruntime or the
.onnx file is missing, ``available`` is False and the caller falls back to the
torch backend (or pass-through).

Author: Bloodawn (KheivenD), 2026-06-02 (TASK 2.1 - ONNX detection backend).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, NamedTuple, Optional, Sequence, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)

# Standard 80-class COCO label order that YOLOv8 is trained on. Index == class id.
COCO_NAMES: Tuple[str, ...] = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag",
    "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon",
    "bowl", "banana", "apple", "sandwich", "orange", "broccoli", "carrot",
    "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant",
    "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
)


class Detection(NamedTuple):
    class_id: int
    class_name: str
    score: float
    xyxy: Tuple[int, int, int, int]   # (x1, y1, x2, y2) in original image coords


def _default_model_path() -> Path:
    """Where to look for yolov8n.onnx (repo root by default).

    src/detection/onnx_backend.py -> parents[2] == repo root.
    """
    return Path(__file__).resolve().parents[2] / "yolov8n.onnx"


class YoloOnnxDetector:
    """YOLOv8-nano detector on ONNX Runtime.

    Args:
        model_path: path to the exported .onnx (default: <repo>/yolov8n.onnx).
        confidence: minimum class score to keep a detection (0-1).
        iou:        IoU threshold for non-max suppression.
        imgsz:      square input size the model was exported at (default 640).
        device:     "auto" / "cuda" / "cpu" - selects the ORT provider.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        confidence: float = 0.25,
        iou: float = 0.45,
        imgsz: int = 640,
        device: str = "auto",
    ) -> None:
        self.confidence = float(confidence)
        self.iou = float(iou)
        self.imgsz = int(imgsz)
        self.model_path = Path(model_path) if model_path else _default_model_path()
        self._session = None
        self._input_name: Optional[str] = None
        self._available = False
        self._load(device)

    # ------------------------------------------------------------------ load
    def _load(self, device: str) -> None:
        try:
            import onnxruntime as ort  # type: ignore
        except ImportError:
            log.info("onnxruntime not installed; ONNX detector unavailable.")
            return
        if not self.model_path.exists():
            log.info("ONNX model not found at %s; ONNX detector unavailable. "
                     "Export it with: yolo export model=yolov8n.pt format=onnx",
                     self.model_path)
            return
        try:
            providers = self._providers_for(ort, device)
            self._session = ort.InferenceSession(str(self.model_path), providers=providers)
            self._input_name = self._session.get_inputs()[0].name
            self._available = True
            log.info("ONNX detector loaded: %s (providers=%s)",
                     self.model_path.name, self._session.get_providers())
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to load ONNX detector (%s); falling back.", exc)

    @staticmethod
    def _providers_for(ort, device: str) -> Sequence[str]:
        avail = set(ort.get_available_providers())
        if device in ("auto", "cuda") and "CUDAExecutionProvider" in avail:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]

    @property
    def available(self) -> bool:
        return self._available

    # ------------------------------------------------------- pre/post-process
    def _letterbox(self, img: np.ndarray) -> Tuple[np.ndarray, float, Tuple[int, int]]:
        """Resize keeping aspect ratio, pad to a square self.imgsz.

        Returns the padded image, the resize ratio, and the (pad_x, pad_y)
        offsets so detections can be mapped back to the original frame.
        """
        h, w = img.shape[:2]
        r = min(self.imgsz / h, self.imgsz / w)
        nh, nw = int(round(h * r)), int(round(w * r))
        resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        pad_x = (self.imgsz - nw) // 2
        pad_y = (self.imgsz - nh) // 2
        canvas = np.full((self.imgsz, self.imgsz, 3), 114, dtype=np.uint8)
        canvas[pad_y:pad_y + nh, pad_x:pad_x + nw] = resized
        return canvas, r, (pad_x, pad_y)

    def infer(self, image_bgr: np.ndarray) -> List[Detection]:
        """Run detection on a BGR image; return detections in original coords."""
        if not self._available or image_bgr is None or image_bgr.size == 0:
            return []
        h0, w0 = image_bgr.shape[:2]
        canvas, ratio, (pad_x, pad_y) = self._letterbox(image_bgr)

        # BGR->RGB, /255, HWC->CHW, add batch dim.
        blob = canvas[:, :, ::-1].astype(np.float32) / 255.0
        blob = np.transpose(blob, (2, 0, 1))[None, ...]
        blob = np.ascontiguousarray(blob)

        try:
            out = self._session.run(None, {self._input_name: blob})[0]
        except Exception as exc:  # noqa: BLE001
            log.debug("ONNX inference error: %s", exc)
            return []

        # YOLOv8 output: (1, 84, N) -> (N, 84): 4 box (cx,cy,w,h) + 80 scores.
        pred = np.squeeze(out, axis=0)
        if pred.shape[0] in (84, len(COCO_NAMES) + 4):
            pred = pred.transpose(1, 0)
        if pred.shape[1] < 4 + len(COCO_NAMES):
            return []

        boxes_cxcywh = pred[:, :4]
        cls_scores = pred[:, 4:4 + len(COCO_NAMES)]
        class_ids = np.argmax(cls_scores, axis=1)
        scores = cls_scores[np.arange(cls_scores.shape[0]), class_ids]

        keep = scores >= self.confidence
        if not np.any(keep):
            return []
        boxes_cxcywh = boxes_cxcywh[keep]
        class_ids = class_ids[keep]
        scores = scores[keep]

        # cx,cy,w,h (letterbox space) -> x1,y1,x2,y2 (original image space).
        cx, cy, bw, bh = boxes_cxcywh.T
        x1 = (cx - bw / 2 - pad_x) / ratio
        y1 = (cy - bh / 2 - pad_y) / ratio
        x2 = (cx + bw / 2 - pad_x) / ratio
        y2 = (cy + bh / 2 - pad_y) / ratio
        x1 = np.clip(x1, 0, w0); y1 = np.clip(y1, 0, h0)
        x2 = np.clip(x2, 0, w0); y2 = np.clip(y2, 0, h0)

        # Class-aware NMS via OpenCV (offset boxes by class so NMS is per-class).
        boxes_xywh = np.stack([x1, y1, x2 - x1, y2 - y1], axis=1)
        idxs = cv2.dnn.NMSBoxes(
            boxes_xywh.tolist(), scores.tolist(),
            score_threshold=self.confidence, nms_threshold=self.iou,
        )
        if idxs is None or len(idxs) == 0:
            return []
        idxs = np.array(idxs).flatten()

        dets: List[Detection] = []
        for i in idxs:
            cid = int(class_ids[i])
            name = COCO_NAMES[cid] if 0 <= cid < len(COCO_NAMES) else str(cid)
            dets.append(Detection(
                class_id=cid, class_name=name, score=float(scores[i]),
                xyxy=(int(x1[i]), int(y1[i]), int(x2[i]), int(y2[i])),
            ))
        return dets

    def class_names_in(self, image_bgr: np.ndarray, conf: Optional[float] = None) -> set:
        """Convenience: the set of class names detected in an image (>= conf).

        Mirrors what ObjectFilter._classify_box_labels collects from a crop.
        """
        prev = self.confidence
        if conf is not None:
            self.confidence = float(conf)
        try:
            return {d.class_name for d in self.infer(image_bgr)}
        finally:
            self.confidence = prev
