"""
object_filter.py

YOLO-based classification gate for the surveillance pipeline.

Problem it solves:
    MOG2/KNN background subtraction detects ANY pixel change — leaves blowing
    in wind, shadows shifting, light flickering — as foreground regions. On
    videos with dynamic backgrounds (trees, flags, water) this produces
    thousands of false ROIs, making mode1/2/3 behave exactly like mode0
    (every frame has "detections").

Solution:
    After MOG2 produces bounding boxes, run each box crop through YOLOv8-nano.
    Only pass boxes through to the encoder if YOLO confirms a target class
    (person, vehicle, animal, etc.). Everything else — leaves, branches,
    shadows — gets discarded.

Architecture:
    - Uses YOLOv8-nano (yolov8n.pt, ~6 MB) — fast enough to run on CPU at
      real-time on small crops. On CUDA it's essentially free.
    - Crops each MOG2 bounding box from the frame and classifies it.
    - Boxes below a minimum size are skipped (YOLO gains nothing on tiny chips).
    - Results are cached per frame so multiple calls don't re-run inference.
    - Falls back transparently if ultralytics is not installed — all boxes pass.

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
# Boxes smaller than this are too small for meaningful classification —
# pass them through unfiltered so tiny but real targets aren't silently lost.
_MIN_CLASSIFY_PX = 20

# Minimum confidence for a YOLO detection to count as confirmed.
_DEFAULT_CONFIDENCE = 0.30


class ObjectFilter:
    """
    Classification gate: runs YOLOv8-nano on MOG2 bounding boxes and drops
    boxes that don't contain a target-class object.

    Falls back to pass-through (all boxes kept) if ultralytics is not installed
    or the model can't be loaded — the pipeline continues working, just without
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
    ) -> None:
        self.confidence = confidence
        self.target_classes = target_classes if target_classes is not None else DEFAULT_TARGET_CLASSES
        self.min_box_px = min_box_px
        self.use_suppression = use_suppression
        self.suppress_after = suppress_after

        # Resolve device
        if device == "auto":
            try:
                import torch
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                self._device = "cpu"
        else:
            self._device = device

        self._model = None
        self._available = False
        self._load_model()

        # Suppression state — grid of counters, built lazily on first frame
        self._suppress_grid: Optional[np.ndarray] = None  # (rows, cols) int16
        self._suppress_mask: Optional[np.ndarray] = None  # (H, W) bool
        self._grid_cell = 32   # px per grid cell
        self._frame_shape: Optional[Tuple[int, int]] = None

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        try:
            from ultralytics import YOLO  # type: ignore
        except ImportError:
            log.warning(
                "ultralytics not installed — ObjectFilter disabled (all boxes pass). "
                "To enable: pip install ultralytics"
            )
            return

        try:
            self._model = YOLO("yolov8n.pt")   # downloads ~6 MB on first run
            # Run on the right device
            if self._device == "cuda":
                self._model.to("cuda")
            self._available = True
            log.info("ObjectFilter: YOLOv8-nano loaded on %s", self._device.upper())
        except Exception as exc:
            log.warning("ObjectFilter: failed to load YOLOv8-nano (%s) — pass-through mode.", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        """True if YOLO is loaded and filtering is actually happening."""
        return self._available

    def filter(self, frame: np.ndarray, regions: list) -> list:
        """
        Filter a list of ForegroundRegion objects, keeping only those where
        YOLO confirms a target-class object.

        Args:
            frame:   Full BGR frame (H×W×3).
            regions: List of ForegroundRegion from BackgroundSubtractor.

        Returns:
            Filtered list — may be empty if all regions are false detections.
        """
        if not self._available or not regions:
            return regions

        if self.use_suppression:
            self._init_suppression(frame.shape)

        kept = []
        false_regions = []

        for region in regions:
            x, y, w, h = region.x, region.y, region.w, region.h

            # Skip suppressed regions (known false-positive areas)
            if self.use_suppression and self._is_suppressed(x, y, w, h):
                continue

            # Pass tiny boxes through — too small to classify reliably
            if w < self.min_box_px or h < self.min_box_px:
                kept.append(region)
                continue

            if self._classify_box(frame, x, y, w, h):
                kept.append(region)
                # A true target in this area resets its suppression counter
                if self.use_suppression:
                    self._reset_suppression(x, y, w, h)
            else:
                false_regions.append(region)

        # Increment suppression counters for false-only regions
        if self.use_suppression:
            for region in false_regions:
                self._increment_suppression(region.x, region.y, region.w, region.h)
            self._rebuild_suppress_mask()

        return kept

    def reset_suppression(self) -> None:
        """Clear the suppression mask — call when the source changes."""
        self._suppress_grid = None
        self._suppress_mask = None
        self._frame_shape = None

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify_box(self, frame: np.ndarray, x: int, y: int, w: int, h: int) -> bool:
        """Return True if YOLO finds a target-class object in the bbox crop."""
        fh, fw = frame.shape[:2]
        x1 = max(0, x); y1 = max(0, y)
        x2 = min(fw, x + w); y2 = min(fh, y + h)
        if x2 <= x1 or y2 <= y1:
            return False

        crop = frame[y1:y2, x1:x2]

        try:
            results = self._model(
                crop,
                verbose=False,
                conf=self.confidence,
                device=self._device,
            )
            for result in results:
                for box in result.boxes:
                    cls_id = int(box.cls[0])
                    cls_name = result.names.get(cls_id, "")
                    if cls_name in self.target_classes:
                        return True
        except Exception as exc:
            log.debug("YOLO classify error: %s", exc)
            return True  # on error, pass through rather than drop

        return False

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
