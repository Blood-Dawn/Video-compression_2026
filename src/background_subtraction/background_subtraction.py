"""
background_subtraction.py

Wraps OpenCV background subtraction algorithms for static surveillance cameras.
All algorithms are CPU-only and designed to run on legacy hardware.

Supported methods:
  - MOG2  (Mixture of Gaussians v2) -- best general-purpose choice
  - KNN   (K-Nearest Neighbors)     -- better for scenes with sudden illumination changes
  - GMG   (Godbehere-Matsukawa-Goldberg) -- slower but very clean masks

Usage:
    from background_subtraction import BackgroundSubtractor
    bs = BackgroundSubtractor(method="MOG2")
    mask = bs.apply(frame)
    regions = bs.get_foreground_regions(mask)
"""

import cv2
import numpy as np
from dataclasses import dataclass
from typing import List, Tuple, Optional


@dataclass
class ForegroundRegion:
    """Bounding box of a detected foreground object."""
    x: int
    y: int
    w: int
    h: int
    area: int

    def to_tuple(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)

    def expand(self, pad: int, frame_w: int, frame_h: int) -> "ForegroundRegion":
        """Expand bounding box by pad pixels, clamped to frame bounds."""
        x = max(0, self.x - pad)
        y = max(0, self.y - pad)
        x2 = min(frame_w, self.x + self.w + pad)
        y2 = min(frame_h, self.y + self.h + pad)
        return ForegroundRegion(x, y, x2 - x, y2 - y, (x2 - x) * (y2 - y))


class BackgroundSubtractor:
    """
    Wraps OpenCV background subtraction for surveillance use.
    Designed for static cameras with slow-moving or infrequent targets.
    """

    SUPPORTED_METHODS = ("MOG2", "KNN", "GMG")

    def __init__(
        self,
        method: str = "MOG2",
        history: int = 500,
        min_area: int = 500,
        learning_rate: float = -1,
        morph_kernel_size: int = 5,
    ):
        """
        Args:
            method: One of MOG2, KNN, GMG.
            history: Number of frames used to build the background model.
            min_area: Minimum contour area in pixels to count as a foreground object.
                      Filters out noise and small artifacts.
            learning_rate: Background model update rate. -1 = automatic.
            morph_kernel_size: Size of morphological kernel used to clean the mask.
        """
        if method not in self.SUPPORTED_METHODS:
            raise ValueError(f"method must be one of {self.SUPPORTED_METHODS}")

        self.method = method
        self.min_area = min_area
        self.learning_rate = learning_rate
        self._kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (morph_kernel_size, morph_kernel_size)
        )

        if method == "MOG2":
            self._subtractor = cv2.createBackgroundSubtractorMOG2(
                history=history, detectShadows=True
            )
        elif method == "KNN":
            self._subtractor = cv2.createBackgroundSubtractorKNN(
                history=history, detectShadows=True
            )
        elif method == "GMG":
            self._subtractor = cv2.bgsegm.createBackgroundSubtractorGMG(
                initializationFrames=history
            )

    def apply(self, frame: np.ndarray) -> np.ndarray:
        """
        Apply background subtraction to a frame.

        Returns:
            Binary mask (255 = foreground, 0 = background).
        """
        raw_mask = self._subtractor.apply(frame, learningRate=self.learning_rate)

        # Threshold: remove shadows (127) and keep only hard foreground (255)
        _, binary = cv2.threshold(raw_mask, 200, 255, cv2.THRESH_BINARY)

        # Morphological cleanup: close gaps, remove noise
        cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, self._kernel)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, self._kernel)

        return cleaned

    def get_foreground_regions(
        self,
        mask: np.ndarray,
        pad: int = 20,
    ) -> List[ForegroundRegion]:
        """
        Find bounding boxes of foreground objects in the mask.

        Args:
            mask: Binary mask from apply().
            pad: Extra pixels to pad around each bounding box.

        Returns:
            List of ForegroundRegion objects sorted by area descending.
        """
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        h, w = mask.shape[:2]
        regions = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self.min_area:
                continue
            x, y, bw, bh = cv2.boundingRect(cnt)
            region = ForegroundRegion(x, y, bw, bh, int(area))
            regions.append(region.expand(pad, w, h))

        return sorted(regions, key=lambda r: r.area, reverse=True)

    def draw_regions(
        self,
        frame: np.ndarray,
        regions: List[ForegroundRegion],
        color: Tuple[int, int, int] = (0, 255, 0),
        thickness: int = 2,
    ) -> np.ndarray:
        """Draw bounding boxes on a copy of the frame for visualization."""
        vis = frame.copy()
        for r in regions:
            cv2.rectangle(vis, (r.x, r.y), (r.x + r.w, r.y + r.h), color, thickness)
        return vis
