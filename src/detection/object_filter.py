"""
object_filter.py

YOLO-based classification gate for the surveillance pipeline.

Problem it solves:
    MOG2/KNN background subtraction detects ANY pixel change. Leaves blowing
    in wind, shadows shifting, light flickering as foreground regions. On
    videos with dynamic backgrounds (trees, flags, water) this produces
    thousands of false ROIs, making mode1/2/3 behave exactly like mode0
    (every frame has "detections").

Solution:
    After MOG2 produces bounding boxes, run each box crop through YOLOv8-nano.
    Only pass boxes through to the encoder if YOLO confirms a target class
    (person, vehicle, animal, etc.). Everything else (leaves, branches,
    shadows get discarded.

Architecture:
    - Uses YOLOv8-nano (yolov8n.pt, ~6 MB) (fast enough to run on CPU at
      real-time on small crops. On CUDA it's essentially free.
    - Crops each MOG2 bounding box from the frame and classifies it.
    - Boxes below a minimum size are skipped (YOLO gains nothing on tiny chips).
    - Results are cached per frame so multiple calls don't re-run inference.
    - Falls back transparently if ultralytics is not installed. All boxes pass.

Static suppression mask (optional):
    Regions that have ONLY ever produced false detections can be added to a
    suppression mask. Future frames skip those regions entirely, saving both
    MOG2 and YOLO work. The mask resets when a true target is seen in that
    region (so if a person walks into a previously-suppressed leaf area, they
    get detected).

Usage in pipeline.py:
    from detection.object_filter import ObjectFilter

    obj_filter = ObjectFilter(confidence=0.35, device="cuda")

    # In per-frame loop:
    regions = subtractor.get_foreground_regions(mask)
    regions = obj_filter.filter(frame, regions)   # drop leaves/shadows

Author: Bloodawn / KheivenD
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)

# ── Semantic groupings ────────────────────────────────────────────────────────
_VEHICLE_CLASSES = {"bicycle", "car", "motorcycle", "bus", "truck", "train", "boat", "airplane"}
_PERSON_CLASSES  = {"person"}
_ANIMAL_CLASSES  = {"bird", "cat", "dog", "horse", "sheep", "cow",
                    "elephant", "bear", "zebra", "giraffe"}
_CARRIED_CLASSES = {"backpack", "handbag", "suitcase"}


def _label_from_classes(classes: set) -> str:
    """Map a set of COCO class names to a human-readable segment type label."""
    has_vehicle = bool(classes & _VEHICLE_CLASSES)
    has_person  = bool(classes & (_PERSON_CLASSES | _CARRIED_CLASSES))
    has_animal  = bool(classes & _ANIMAL_CLASSES)

    if has_vehicle and has_person:
        return "person+vehicle"
    if has_vehicle and has_animal:
        return "vehicle+animal"
    if has_person and has_animal:
        return "person+animal"
    if has_vehicle:
        return "vehicle"
    if has_person:
        return "person"
    if has_animal:
        return "animal"
    if classes:
        return "other"
    return "unknown"


# ── Color detection ───────────────────────────────────────────────────────────
# HSV hue ranges for dominant-color labelling.
# Hue is 0-179 in OpenCV (half of 360°).
_HUE_RANGES = [
    ("red",    [(0, 10), (160, 179)]),   # wraps around
    ("orange", [(10, 22)]),
    ("yellow", [(22, 38)]),
    ("green",  [(38, 82)]),
    ("cyan",   [(82, 100)]),
    ("blue",   [(100, 130)]),
    ("purple", [(130, 160)]),
]


def detect_dominant_color(frame: np.ndarray, x: int, y: int, w: int, h: int) -> str:
    """Return the dominant color label for the center 50% of a bounding box.

    Uses Cody Hayashi's approach: crop the central region of the box to reduce
    road/background contamination, build an HSV histogram, and map the peak
    hue bin to a color name.

    Returns one of: red, orange, yellow, green, cyan, blue, purple,
                    white, black, gray, or unknown.
    """
    fh, fw = frame.shape[:2]

    # Center 50% crop
    cx, cy = x + w // 2, y + h // 2
    cw, ch = max(4, w // 2), max(4, h // 2)
    x1 = max(0, cx - cw // 2); y1 = max(0, cy - ch // 2)
    x2 = min(fw, cx + cw // 2); y2 = min(fh, cy + ch // 2)
    if x2 <= x1 or y2 <= y1:
        return "unknown"

    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return "unknown"

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h_ch, s_ch, v_ch = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

    # Achromatic check: pixels with low saturation or extreme brightness
    total = h_ch.size
    white_px = int(np.sum((s_ch < 40) & (v_ch > 200)))
    black_px = int(np.sum(v_ch < 50))
    gray_px  = int(np.sum((s_ch < 50) & (v_ch >= 50) & (v_ch <= 200)))

    achromatic = white_px + black_px + gray_px
    if achromatic > total * 0.55:
        if white_px >= black_px and white_px >= gray_px:
            return "white"
        if black_px >= gray_px:
            return "black"
        return "gray"

    # Only consider chromatic (saturated) pixels for hue analysis
    chromatic_mask = s_ch >= 50
    if not np.any(chromatic_mask):
        return "gray"

    h_vals = h_ch[chromatic_mask]
    hist, _ = np.histogram(h_vals, bins=180, range=(0, 180))

    # Score each named color
    best_label, best_score = "unknown", 0
    for label, ranges in _HUE_RANGES:
        score = sum(int(hist[lo:hi].sum()) for lo, hi in ranges)
        if score > best_score:
            best_score = score
            best_label = label

    return best_label


# ── Scene type detection ──────────────────────────────────────────────────────

def detect_scene_type(motion_vectors: list[tuple[float, float]], roi_count: int,
                      frame_area: int) -> str:
    """Heuristic scene-type classifier based on motion direction diversity.

    Args:
        motion_vectors: List of (dx, dy) displacement vectors for detected ROIs
                        across recent frames. Populated by the pipeline.
        roi_count:      Total ROI count for the segment.
        frame_area:     H * W of the frame in pixels.

    Returns one of: highway | intersection | parking | unknown
    """
    if not motion_vectors or roi_count < 3:
        return "unknown"

    import math
    angles = []
    for dx, dy in motion_vectors:
        mag = math.hypot(dx, dy)
        if mag > 1.0:          # ignore near-stationary blobs
            angles.append(math.degrees(math.atan2(dy, dx)) % 360)

    if len(angles) < 3:
        return "unknown"

    # Bin into 8 directional sectors (N, NE, E, SE, S, SW, W, NW)
    sectors = [0] * 8
    for a in angles:
        sectors[int(a // 45) % 8] += 1

    active_sectors = sum(1 for s in sectors if s > 0)
    dominant_share = max(sectors) / len(angles)

    if dominant_share > 0.70:
        # Most motion goes one way → highway / one-way street
        return "highway"
    if active_sectors >= 3 and dominant_share < 0.55:
        # Traffic crossing in multiple directions → intersection
        return "intersection"
    if dominant_share < 0.45 and roi_count < 20:
        # Scattered slow movement → parking lot
        return "parking"

    return "street"


# COCO classes that are considered "real targets" worth recording.
# Everything outside this set (potted plant, kite, sports ball, etc.) is
# treated as a false detection and discarded.
DEFAULT_TARGET_CLASSES = {
    # People
    "person",
    # Vehicles
    "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat",
    # Animals (relevant for perimeter security)
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear",
    "zebra", "giraffe",
    # Carried items that indicate a person
    "backpack", "handbag", "suitcase",
}

# Minimum bbox dimension (px) to bother running YOLO on.
# Boxes smaller than this are too small for meaningful classification.
# pass them through unfiltered so tiny but real targets aren't silently lost.
_MIN_CLASSIFY_PX = 20

# Minimum confidence for a YOLO detection to count as confirmed.
_DEFAULT_CONFIDENCE = 0.30


class ObjectFilter:
    """
    Classification gate: runs YOLOv8-nano on MOG2 bounding boxes and drops
    boxes that don't contain a target-class object.

    Falls back to pass-through (all boxes kept) if ultralytics is not installed
    or the model can't be loaded. The pipeline continues working without
    the leaf/shadow filtering.

    Args:
        confidence:      Minimum YOLO confidence to accept a detection (0–1).
        device:          "cuda", "cpu", or "auto" (auto-detects CUDA).
        target_classes:  Set of COCO class names to keep. Defaults to
                         DEFAULT_TARGET_CLASSES.
        min_box_px:      Minimum bbox side length (px) to run YOLO on.
                         Smaller boxes pass through unfiltered.
        use_suppression: If True, build a static suppression mask for regions
                         that have only ever produced false detections.
        suppress_after:  Number of consecutive false-only frames in a grid cell
                         before it gets suppressed.
    """

    def __init__(
        self,
        confidence: float = _DEFAULT_CONFIDENCE,
        device: str = "auto",
        target_classes: Optional[set] = None,
        min_box_px: int = _MIN_CLASSIFY_PX,
        use_suppression: bool = True,
        suppress_after: int = 30,
        backend: str = "auto",
    ) -> None:
        self.confidence = confidence
        self.target_classes = target_classes if target_classes is not None else DEFAULT_TARGET_CLASSES
        self.min_box_px = min_box_px
        self.use_suppression = use_suppression
        self.suppress_after = suppress_after
        # Inference backend selector (M2 TASK 2.1/2.2):
        #   "auto"  — DEFAULT (TASK 2.2): ONNX Runtime if its model+runtime are
        #             available, else PyTorch. The slim install has no torch, so
        #             this resolves to ONNX; a torch-only env resolves to torch.
        #   "onnx"  — force ONNX Runtime (slim install path).
        #   "torch" — force ultralytics/PyTorch.
        # The detector interface is backend-agnostic, so a future RT-DETR /
        # permissive detector slots in here without touching the pipeline.
        self.backend = str(backend or "torch").lower()

        # Resolve device
        if device == "auto":
            try:
                import torch
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                self._device = "cpu"
        else:
            self._device = device

        self._model = None        # ultralytics YOLO (torch backend)
        self._onnx = None         # YoloOnnxDetector (onnx backend)
        self._backend = "none"    # which backend actually loaded
        self._available = False
        self._load_model()

        # Suppression state: grid of counters, built lazily on first frame
        self._suppress_grid: Optional[np.ndarray] = None  # (rows, cols) int16
        self._suppress_mask: Optional[np.ndarray] = None  # (H, W) bool
        self._grid_cell = 32   # px per grid cell
        self._frame_shape: Optional[Tuple[int, int]] = None

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        # Try ONNX first when requested ("onnx" or "auto"). It falls through to
        # the torch backend if the runtime or the exported .onnx is missing.
        if self.backend in ("onnx", "auto") and self._load_onnx():
            return
        if self.backend == "onnx":
            # Explicit onnx request that couldn't load: stay in pass-through
            # rather than silently switching to torch (which TASK 2.2 removes).
            log.warning("ObjectFilter: ONNX backend requested but unavailable "
                        "(pass-through mode).")
            return
        self._load_torch()

    def _load_onnx(self) -> bool:
        try:
            from detection.onnx_backend import YoloOnnxDetector
        except ImportError:
            try:
                from src.detection.onnx_backend import YoloOnnxDetector  # type: ignore
            except ImportError:
                return False
        det = YoloOnnxDetector(confidence=self.confidence, device=self._device)
        if not det.available:
            return False
        self._onnx = det
        self._backend = "onnx"
        self._available = True
        log.info("ObjectFilter: YOLOv8-nano (ONNX Runtime) loaded on %s", self._device.upper())
        return True

    def _load_torch(self) -> None:
        try:
            from ultralytics import YOLO  # type: ignore
        except ImportError:
            log.warning(
                "ultralytics not installed. ObjectFilter disabled (all boxes pass). "
                "To enable: pip install ultralytics"
            )
            return

        try:
            self._model = YOLO("yolov8n.pt")   # downloads ~6 MB on first run
            # Run on the right device
            if self._device == "cuda":
                self._model.to("cuda")
            self._backend = "torch"
            self._available = True
            log.info("ObjectFilter: YOLOv8-nano (PyTorch) loaded on %s", self._device.upper())
        except Exception as exc:
            log.warning("ObjectFilter: failed to load YOLOv8-nano (%s) (pass-through mode).", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    # COCO class → semantic group mapping used for type labelling
    _VEHICLE_CLASSES  = {"bicycle", "car", "motorcycle", "bus", "truck", "train", "boat", "airplane"}
    _PERSON_CLASSES   = {"person"}
    _ANIMAL_CLASSES   = {"bird", "cat", "dog", "horse", "sheep", "cow", "elephant",
                         "bear", "zebra", "giraffe"}
    _CARRIED_CLASSES  = {"backpack", "handbag", "suitcase"}

    @property
    def active(self) -> bool:
        """True if YOLO is loaded and filtering is actually happening."""
        return self._available

    def filter(self, frame: np.ndarray, regions: list) -> list:
        """Filter regions, keeping only confirmed target-class objects.

        After this call, ``self.last_detected_classes`` contains a dict mapping
        each kept region's index (in the returned list) to the set of COCO
        class names YOLO found inside it.  Use ``classify_detected_objects()``
        to turn that into a human-readable segment type label.
        """
        # Reset per-frame label tracking
        self.last_detected_classes: dict[int, set[str]] = {}

        if not self._available or not regions:
            # Pass-through: annotate every region as "unknown"
            for i in range(len(regions)):
                self.last_detected_classes[i] = set()
            return regions

        if self.use_suppression:
            self._init_suppression(frame.shape)

        kept        : list = []
        false_regions: list = []

        for region in regions:
            x, y, w, h = region.x, region.y, region.w, region.h

            if self.use_suppression and self._is_suppressed(x, y, w, h):
                continue

            if w < self.min_box_px or h < self.min_box_px:
                # Too small to classify — pass through, label unknown
                self.last_detected_classes[len(kept)] = set()
                kept.append(region)
                continue

            labels = self._classify_box_labels(frame, x, y, w, h)
            if labels is not None:
                self.last_detected_classes[len(kept)] = labels
                kept.append(region)
                if self.use_suppression:
                    self._reset_suppression(x, y, w, h)
            else:
                false_regions.append(region)

        if self.use_suppression:
            for region in false_regions:
                self._increment_suppression(region.x, region.y, region.w, region.h)
            self._rebuild_suppress_mask()

        return kept

    def classify_detected_objects(self) -> str:
        """Return a segment-level type label from the last filter() call.

        Combines all detected class names across every kept region and maps
        them to one of:
          vehicle | person | person+vehicle | animal | mixed | unknown
        """
        all_classes: set[str] = set()
        for labels in self.last_detected_classes.values():
            all_classes |= labels
        return _label_from_classes(all_classes)

    def reset_suppression(self) -> None:
        """Clear the suppression mask. Call when the source changes."""
        self._suppress_grid = None
        self._suppress_mask = None
        self._frame_shape = None

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify_box_labels(
        self, frame: np.ndarray, x: int, y: int, w: int, h: int
    ) -> Optional[set]:
        """Run YOLO on the bbox crop.

        Returns the set of target-class names found (may be empty if only
        non-target classes appeared), or None if no target was found at all
        and the box should be discarded.
        """
        fh, fw = frame.shape[:2]
        x1 = max(0, x); y1 = max(0, y)
        x2 = min(fw, x + w); y2 = min(fh, y + h)
        if x2 <= x1 or y2 <= y1:
            return None

        crop = frame[y1:y2, x1:x2]
        found: set[str] = set()

        try:
            if self._backend == "onnx":
                # ONNX backend returns the set of detected COCO class names.
                for name in self._onnx.class_names_in(crop, conf=self.confidence):
                    if name in self.target_classes:
                        found.add(name)
            else:
                results = self._model(crop, verbose=False, conf=self.confidence, device=self._device)
                for result in results:
                    for box in result.boxes:
                        cls_id   = int(box.cls[0])
                        cls_name = result.names.get(cls_id, "")
                        if cls_name in self.target_classes:
                            found.add(cls_name)
        except Exception as exc:
            log.debug("YOLO classify error: %s", exc)
            return found  # on error pass through

        return found if found else None  # None → discard box

    # ------------------------------------------------------------------
    # Suppression grid helpers
    # ------------------------------------------------------------------

    def _init_suppression(self, shape: tuple) -> None:
        h, w = shape[:2]
        if self._frame_shape == (h, w):
            return
        self._frame_shape = (h, w)
        rows = (h + self._grid_cell - 1) // self._grid_cell
        cols = (w + self._grid_cell - 1) // self._grid_cell
        self._suppress_grid = np.zeros((rows, cols), dtype=np.int16)
        self._suppress_mask = np.zeros((h, w), dtype=bool)
        log.debug("Suppression grid initialised: %dx%d cells", rows, cols)

    def _grid_cells_for(self, x: int, y: int, w: int, h: int):
        """Yield (row, col) grid cell indices covered by the bbox."""
        c = self._grid_cell
        r0 = y // c; r1 = (y + h - 1) // c
        c0 = x // c; c1 = (x + w - 1) // c
        rows, cols = self._suppress_grid.shape
        for r in range(max(0, r0), min(rows, r1 + 1)):
            for cc in range(max(0, c0), min(cols, c1 + 1)):
                yield r, cc

    def _is_suppressed(self, x: int, y: int, w: int, h: int) -> bool:
        if self._suppress_mask is None:
            return False
        fh, fw = self._frame_shape
        cx = max(0, min(fw - 1, x + w // 2))
        cy = max(0, min(fh - 1, y + h // 2))
        return bool(self._suppress_mask[cy, cx])

    def _increment_suppression(self, x: int, y: int, w: int, h: int) -> None:
        if self._suppress_grid is None:
            return
        for r, c in self._grid_cells_for(x, y, w, h):
            if self._suppress_grid[r, c] < 32767:
                self._suppress_grid[r, c] += 1

    def _reset_suppression(self, x: int, y: int, w: int, h: int) -> None:
        if self._suppress_grid is None:
            return
        for r, c in self._grid_cells_for(x, y, w, h):
            self._suppress_grid[r, c] = 0

    def _rebuild_suppress_mask(self) -> None:
        if self._suppress_grid is None or self._suppress_mask is None:
            return
        c = self._grid_cell
        h, w = self._frame_shape
        rows, cols = self._suppress_grid.shape
        for r in range(rows):
            for cc in range(cols):
                y0 = r * c; y1 = min(h, y0 + c)
                x0 = cc * c; x1 = min(w, x0 + c)
                self._suppress_mask[y0:y1, x0:x1] = (
                    self._suppress_grid[r, cc] >= self.suppress_after
                )
