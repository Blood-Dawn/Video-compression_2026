"""
src/detection/pose_onnx_backend.py

ONNX Runtime backend for YOLOv8-nano POSE estimation (planner 6.11).

Context (see src/detection/object_filter.py and onnx_backend.py): the
existing classification gate already runs YOLOv8-nano bounding-box detection
on every MOG2 foreground region and keeps only boxes YOLO confirms as a
target COCO class (person, vehicle, animal, ...). That is bounding-box
classification, not pose - it answers "is there probably a person-shaped
object in this box" from a single class score, with no notion of body
structure. A mannequin, a cardboard cutout, a reflection, or a sign with a
printed figure can all score as "person" under that test.

This module adds a second, independent signal: does the box actually
contain a coherent human skeleton? YOLOv8n-pose predicts 17 COCO keypoints
(nose, eyes, ears, shoulders, elbows, wrists, hips, knees, ankles) per
detection. A real person walking through a scene produces several visible,
spatially-consistent keypoints; a false positive generally does not. Pose
confirmation is used to *upgrade confidence*, not to *replace* the existing
bbox classifier - a "person" box with no pose confirmation is still kept
(never silently dropped, so recall does not regress), it is just not
counted as pose-verified in the segment metadata exposed to search/metrics.

Mirrors onnx_backend.py's shape and conventions on purpose (letterbox
preprocessing, graceful fallback when onnxruntime or the .onnx file is
missing, same provider-selection logic) so the two backends are easy to
read side by side. yolov8n-pose.onnx is a gitignored build artifact, like
yolov8n.onnx, produced once with:

    yolo export model=yolov8n-pose.pt format=onnx imgsz=640

Author: Bloodawn (KheivenD), 2026-10-07 (planner 6.11 - YOLO pose).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, NamedTuple, Optional, Sequence, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)

# The 17 COCO keypoints, in the order YOLOv8-pose emits them.
COCO_KEYPOINT_NAMES: Tuple[str, ...] = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
)
_NUM_KEYPOINTS = len(COCO_KEYPOINT_NAMES)  # 17


class PoseDetection(NamedTuple):
    score: float
    xyxy: Tuple[int, int, int, int]                  # original image coords
    keypoints: Tuple[Tuple[float, float, float], ...]  # (x, y, vis) x 17, original coords


def _default_model_path() -> Path:
    """Where to look for yolov8n-pose.onnx (repo root by default).

    src/detection/pose_onnx_backend.py -> parents[2] == repo root.
    """
    return Path(__file__).resolve().parents[2] / "yolov8n-pose.onnx"


class YoloPoseOnnxDetector:
    """YOLOv8-nano pose detector on ONNX Runtime.

    Args:
        model_path: path to the exported .onnx (default: <repo>/yolov8n-pose.onnx).
        confidence: minimum person-score to keep a detection (0-1).
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
        self._inference_error_logged = False
        self._load(device)

    # ------------------------------------------------------------------ load
    def _load(self, device: str) -> None:
        try:
            import onnxruntime as ort  # type: ignore
        except ImportError:
            log.info("onnxruntime not installed; pose detector unavailable.")
            return
        if not self.model_path.exists():
            log.info("Pose ONNX model not found at %s; pose detector unavailable. "
                     "Export it with: yolo export model=yolov8n-pose.pt format=onnx",
                     self.model_path)
            return
        try:
            providers = self._providers_for(ort, device)
            self._session = ort.InferenceSession(str(self.model_path), providers=providers)
            self._input_name = self._session.get_inputs()[0].name
            self._align_imgsz_to_model()
            self._available = True
            log.info("Pose detector loaded: %s (providers=%s, imgsz=%s)",
                     self.model_path.name, self._session.get_providers(), self.imgsz)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to load pose detector (%s); falling back.", exc)

    def _align_imgsz_to_model(self) -> None:
        """Trust the model's own fixed input dims over the constructor default.

        Same reasoning as YoloOnnxDetector._align_imgsz_to_model(): an export
        at a different imgsz than this class defaults to would otherwise fail
        every inference call with a silent shape mismatch.
        """
        try:
            dims = list(self._session.get_inputs()[0].shape)
        except Exception:  # noqa: BLE001
            return
        if len(dims) != 4:
            return
        h, w = dims[2], dims[3]
        if not (isinstance(h, int) and isinstance(w, int) and h > 0 and w > 0):
            return  # dynamic axes - keep the default
        if h != w:
            log.warning("Pose model has a non-square input (%sx%s); letterboxing "
                        "assumes square and may misbehave.", w, h)
            return
        if h != self.imgsz:
            log.warning("Pose model %s expects %dx%d input, not the configured "
                        "imgsz=%d; using %d to match the model.",
                        self.model_path.name, w, h, self.imgsz, h)
            self.imgsz = h

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

        Identical approach to YoloOnnxDetector._letterbox - kept as a
        separate copy (rather than a shared import) so this module stays a
        single, self-contained read, matching onnx_backend.py's own style.
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

    def infer(self, image_bgr: np.ndarray) -> List[PoseDetection]:
        """Run pose estimation on a BGR image; return detections in original coords."""
        if not self._available or image_bgr is None or image_bgr.size == 0:
            return []
        h0, w0 = image_bgr.shape[:2]
        canvas, ratio, (pad_x, pad_y) = self._letterbox(image_bgr)

        blob = canvas[:, :, ::-1].astype(np.float32) / 255.0
        blob = np.transpose(blob, (2, 0, 1))[None, ...]
        blob = np.ascontiguousarray(blob)

        try:
            out = self._session.run(None, {self._input_name: blob})[0]
        except Exception as exc:  # noqa: BLE001
            if not self._inference_error_logged:
                log.warning("Pose ONNX inference failed (%s); pose confirmation will "
                            "return no results until this is fixed. Further "
                            "occurrences are logged at debug level.", exc)
                self._inference_error_logged = True
            else:
                log.debug("Pose ONNX inference error: %s", exc)
            return []

        # YOLOv8-pose output: (1, 56, N) -> (N, 56):
        #   4 box (cx,cy,w,h) + 1 person-conf + 17*3 keypoints (x,y,vis).
        pred = np.squeeze(out, axis=0)
        _expected = 4 + 1 + _NUM_KEYPOINTS * 3  # 56
        if pred.shape[0] == _expected:
            pred = pred.transpose(1, 0)
        if pred.ndim != 2 or pred.shape[1] < _expected:
            return []

        boxes_cxcywh = pred[:, :4]
        scores = pred[:, 4]
        kpts = pred[:, 5:5 + _NUM_KEYPOINTS * 3].reshape(-1, _NUM_KEYPOINTS, 3)

        keep = scores >= self.confidence
        if not np.any(keep):
            return []
        boxes_cxcywh = boxes_cxcywh[keep]
        scores = scores[keep]
        kpts = kpts[keep]

        # Same normalized-vs-pixel safety check as the box detector: some
        # export toolchains emit [0,1]-normalized coordinates instead of
        # letterbox-canvas pixels.
        if boxes_cxcywh.size and np.all(boxes_cxcywh <= 1.5):
            boxes_cxcywh = boxes_cxcywh * self.imgsz
        if kpts.size and np.all(kpts[:, :, :2] <= 1.5):
            kpts = kpts.copy()
            kpts[:, :, :2] = kpts[:, :, :2] * self.imgsz

        cx, cy, bw, bh = boxes_cxcywh.T
        x1 = (cx - bw / 2 - pad_x) / ratio
        y1 = (cy - bh / 2 - pad_y) / ratio
        x2 = (cx + bw / 2 - pad_x) / ratio
        y2 = (cy + bh / 2 - pad_y) / ratio
        x1 = np.clip(x1, 0, w0); y1 = np.clip(y1, 0, h0)
        x2 = np.clip(x2, 0, w0); y2 = np.clip(y2, 0, h0)

        # Single class ("person") - plain NMS, no per-class offsetting needed.
        boxes_xywh = np.stack([x1, y1, x2 - x1, y2 - y1], axis=1)
        idxs = cv2.dnn.NMSBoxes(
            boxes_xywh.tolist(), scores.tolist(),
            score_threshold=self.confidence, nms_threshold=self.iou,
        )
        if idxs is None or len(idxs) == 0:
            return []
        idxs = np.array(idxs).flatten()

        dets: List[PoseDetection] = []
        for i in idxs:
            kx = (kpts[i, :, 0] - pad_x) / ratio
            ky = (kpts[i, :, 1] - pad_y) / ratio
            kx = np.clip(kx, 0, w0)
            ky = np.clip(ky, 0, h0)
            kv = kpts[i, :, 2]
            keypoints = tuple(
                (float(kx[j]), float(ky[j]), float(kv[j])) for j in range(_NUM_KEYPOINTS)
            )
            dets.append(PoseDetection(
                score=float(scores[i]),
                xyxy=(int(x1[i]), int(y1[i]), int(x2[i]), int(y2[i])),
                keypoints=keypoints,
            ))
        return dets

    def person_confirmed_in(
        self,
        image_bgr: np.ndarray,
        conf: Optional[float] = None,
        min_visible_keypoints: int = 4,
        keypoint_conf: float = 0.3,
    ) -> bool:
        """True if a coherent human skeleton is found in this crop.

        A keypoint counts as "visible" when its own confidence/visibility
        score is >= keypoint_conf. Requiring several (not just one) visible
        keypoints is what rejects a stray high-confidence box over a mostly
        occluded or ambiguous region - a single bright blob should not read
        as a confirmed person.

        Mirrors the convenience shape of YoloOnnxDetector.class_names_in().
        """
        prev = self.confidence
        if conf is not None:
            self.confidence = float(conf)
        try:
            for det in self.infer(image_bgr):
                visible = sum(1 for (_, _, v) in det.keypoints if v >= keypoint_conf)
                if visible >= min_visible_keypoints:
                    return True
            return False
        finally:
            self.confidence = prev
