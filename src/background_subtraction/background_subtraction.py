"""
background_subtraction.py

Wraps OpenCV background subtraction algorithms for static surveillance cameras.
All algorithms are CPU-only and designed to run on legacy hardware.

Supported methods:
  - MOG2  (Mixture of Gaussians v2) -- best general-purpose choice
  - KNN   (K-Nearest Neighbors)     -- better for scenes with sudden illumination changes
  - GMG   (Godbehere-Matsukawa-Goldberg) -- slower but very clean masks

Night mode:
  Pass night_mode=True to enable two improvements for low-light footage:
    1. CLAHE preprocessing: normalizes local contrast before background subtraction,
       which significantly reduces bloom/halo effects from point light sources
       (streetlamps, vehicle headlights). Frames are converted to LAB colorspace,
       CLAHE is applied to the L (luminance) channel only, then converted back to BGR.
    2. Higher var_threshold: the default MOG2 varThreshold of 16 is calibrated for
       daytime pixel variance. At night, sensor noise and light flicker raise the
       baseline variance. Increasing this threshold to 30 reduces false positives
       from static noise without missing real objects.

Usage:
    # Daytime (default):
    from background_subtraction import BackgroundSubtractor
    bs = BackgroundSubtractor(method="MOG2")
    mask = bs.apply(frame)

    # Night mode:
    bs = BackgroundSubtractor(method="MOG2", night_mode=True)
    mask = bs.apply(frame)

    # Manual CLAHE only (no threshold change):
    bs = BackgroundSubtractor(method="MOG2", use_clahe=True)

Author: Bloodawn (KheivenD)
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

    Supports a night_mode flag that enables CLAHE preprocessing and a higher
    var_threshold to compensate for the increased pixel noise and light glare
    present in low-light footage.
    """

    SUPPORTED_METHODS = ("MOG2", "KNN", "GMG")

    # Default var_threshold values tuned per lighting condition.
    # MOG2's internal varThreshold controls how many standard deviations a pixel
    # must deviate from the background model to be classified as foreground.
    # At night, ambient noise raises this baseline, so we need a higher threshold
    # to avoid flagging sensor grain and light flicker as foreground objects.
    VAR_THRESHOLD_DAY = 16    # OpenCV default -- calibrated for daytime footage
    VAR_THRESHOLD_NIGHT = 30  # Raised to reduce false positives from night noise

    def __init__(
        self,
        method: str = "MOG2",
        history: int = 500,
        min_area: int = 500,
        learning_rate: float = -1,
        morph_kernel_size: int = 5,
        night_mode: bool = False,
        use_clahe: bool = False,
        clahe_clip_limit: float = 2.0,
        clahe_tile_size: int = 8,
        var_threshold: Optional[int] = None,
    ):
        """
        Args:
            method: One of MOG2, KNN, GMG.
            history: Number of frames used to build the background model.
                     Higher = more stable but slower to adapt to scene changes.
            min_area: Minimum contour area in pixels to count as a foreground object.
                      Filters out small noise blobs. 500px is good for 320x240 footage;
                      increase to 1500-2000 for HD footage.
            learning_rate: Background model update rate. -1 = automatic (recommended).
                           0 = never update (frozen background), 1 = replace every frame.
            morph_kernel_size: Size of the elliptical structuring element used for
                               morphological cleanup (opening and closing) of the mask.
                               Larger = smoother masks but may merge nearby objects.
            night_mode: If True, enables both CLAHE preprocessing and the higher
                        night-tuned var_threshold. This is the recommended way to
                        run the detector on low-light footage. Equivalent to setting
                        use_clahe=True and var_threshold=VAR_THRESHOLD_NIGHT.
            use_clahe: If True, applies CLAHE (Contrast Limited Adaptive Histogram
                       Equalization) to each frame before background subtraction.
                       Works in LAB colorspace so only luminance is equalized, leaving
                       color channels intact. Reduces halo/bloom from point light sources.
                       Can be used independently of night_mode.
            clahe_clip_limit: CLAHE contrast limit parameter. Higher = more aggressive
                              contrast enhancement. Default 2.0 is conservative and safe.
                              Values above 4.0 can introduce artifacts.
            clahe_tile_size: CLAHE tile grid size (applied as tile x tile grid).
                             Smaller tiles = more localized equalization, better for
                             scenes with extreme local contrast like streetlamps.
                             Default 8 means an 8x8 grid of tiles.
            var_threshold: Override the MOG2 varThreshold directly. If None, uses
                           VAR_THRESHOLD_NIGHT when night_mode=True, else VAR_THRESHOLD_DAY.
                           Only applies to MOG2 (KNN uses a different internal parameter).
        """
        if method not in self.SUPPORTED_METHODS:
            raise ValueError(f"method must be one of {self.SUPPORTED_METHODS}")

        self.method = method
        self.min_area = min_area
        self.learning_rate = learning_rate
        self.night_mode = night_mode

        # CLAHE is enabled either by night_mode or the explicit use_clahe flag
        self.use_clahe = use_clahe or night_mode
        if self.use_clahe:
            self._clahe = cv2.createCLAHE(
                clipLimit=clahe_clip_limit,
                tileGridSize=(clahe_tile_size, clahe_tile_size),
            )
        else:
            self._clahe = None

        # Resolve var_threshold: explicit arg > night_mode default > day default
        if var_threshold is not None:
            resolved_threshold = var_threshold
        elif night_mode:
            resolved_threshold = self.VAR_THRESHOLD_NIGHT
        else:
            resolved_threshold = self.VAR_THRESHOLD_DAY

        self._kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (morph_kernel_size, morph_kernel_size)
        )

        if method == "MOG2":
            self._subtractor = cv2.createBackgroundSubtractorMOG2(
                history=history, varThreshold=resolved_threshold, detectShadows=True
            )
        elif method == "KNN":
            self._subtractor = cv2.createBackgroundSubtractorKNN(
                history=history, detectShadows=True
            )
        elif method == "GMG":
            # GMG requires opencv-contrib-python (cv2.bgsegm module).
            # The default requirements.txt installs opencv-python only.
            # Raise a clear error rather than an AttributeError at apply() time.
            if not hasattr(cv2, "bgsegm"):
                raise ImportError(
                    "GMG requires 'opencv-contrib-python'. "
                    "Install it with: pip install opencv-contrib-python "
                    "(remove opencv-python first to avoid conflicts)."
                )
            self._subtractor = cv2.bgsegm.createBackgroundSubtractorGMG(
                initializationFrames=history
            )

    def _apply_clahe(self, frame: np.ndarray) -> np.ndarray:
        """
        Applies CLAHE to the luminance channel of a BGR frame.

        Converts to LAB colorspace so we equalize only brightness (L channel),
        not hue or saturation. This preserves color information for downstream
        processing while normalizing the contrast caused by point light sources.

        Without CLAHE, a streetlamp at night creates a bright halo around it that
        the background model may flag as foreground because the brightness varies
        slightly from frame to frame. After CLAHE, that halo is suppressed and
        the surrounding pixels become more uniform, reducing false positives.

        Args:
            frame: BGR image as uint8 numpy array.

        Returns:
            CLAHE-equalized BGR image, same shape and dtype as input.
        """
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        lab[:, :, 0] = self._clahe.apply(lab[:, :, 0])
        return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    def apply(self, frame: np.ndarray) -> np.ndarray:
        """
        Apply background subtraction to a frame, with optional CLAHE preprocessing.

        If use_clahe or night_mode is enabled, CLAHE equalization is applied to
        the frame before it is passed to the background model. This improves mask
        quality significantly in low-light footage with point light sources.

        The CLAHE-processed frame is only used for background model input; the
        original unprocessed frame is what gets encoded by the compression module.

        Args:
            frame: BGR image as uint8 numpy array, any resolution.

        Returns:
            Binary mask as uint8 array with same spatial dimensions as frame.
            255 = foreground pixel, 0 = background pixel.
        """
        # Preprocess if CLAHE is active -- use the enhanced frame for the model
        # but the calling code (pipeline, encoder) still receives the raw frame
        model_input = self._apply_clahe(frame) if self.use_clahe else frame

        raw_mask = self._subtractor.apply(model_input, learningRate=self.learning_rate)

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
            pad: Extra pixels to pad around each bounding box. Padding ensures
                 the full object is included even if the mask is slightly undersized.

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
