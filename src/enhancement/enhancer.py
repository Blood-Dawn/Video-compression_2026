"""
enhancer.py

CPU-compatible super-resolution enhancement using Real-ESRGAN.
Designed for post-capture use: sharpening ROI regions before encoding,
or offline enhancement of stored compressed footage.

If Real-ESRGAN weights / packages are not available, falls back silently
to bicubic interpolation so the pipeline never hard-crashes on setup issues.

Author: Victor Teixeira

Model download:
    See DEV.md → "Enhancement Module Setup" for instructions.
    TL;DR: download RealESRGAN_x4plus.pth and place it in models/
"""

import logging
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)

# Resolved relative to the project root (two levels up from this file)
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_MODELS_DIR = _PROJECT_ROOT / "models"
_DEFAULT_MODEL_PATH = _MODELS_DIR / "RealESRGAN_x4plus.pth"


class Enhancer:
    """
    Frame and ROI upscaler using Real-ESRGAN (CPU-safe).

    Usage:
        enhancer = Enhancer()                     # auto-detect model
        enhancer = Enhancer(model_path="models/RealESRGAN_x4plus.pth")

    If the model file or required packages are missing, all methods fall
    back to bicubic interpolation — behaviour is identical from the
    caller's perspective, just without AI-driven sharpening.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        scale: int = 4,
    ) -> None:
        """
        Args:
            model_path: Path to RealESRGAN .pth weights file.
                        Defaults to models/RealESRGAN_x4plus.pth.
            scale: Native upscale factor of the loaded model (2 or 4).
                   Must match the downloaded weights file.
        """
        self.scale = scale
        self.model_path = Path(model_path) if model_path else _DEFAULT_MODEL_PATH
        self._upsampler = None   # RealESRGANer instance if available
        self._using_nn = False
        self._load_model()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        """Attempt to load Real-ESRGAN. Swallows all failures gracefully."""
        try:
            from basicsr.archs.rrdbnet_arch import RRDBNet  # type: ignore
            from realesrgan import RealESRGANer              # type: ignore
        except ImportError:
            log.warning(
                "realesrgan / basicsr not installed — using bicubic fallback. "
                "To enable AI upscaling: pip install basicsr realesrgan"
            )
            return

        if not self.model_path.exists():
            log.warning(
                "Model weights not found at %s — using bicubic fallback. "
                "See DEV.md → 'Enhancement Module Setup' to download weights.",
                self.model_path,
            )
            return

        model = RRDBNet(
            num_in_ch=3,
            num_out_ch=3,
            num_feat=64,
            num_block=23,
            num_grow_ch=32,
            scale=self.scale,
        )
        self._upsampler = RealESRGANer(
            scale=self.scale,
            model_path=str(self.model_path),
            model=model,
            half=False,   # CPU mode — fp16 is GPU-only
        )
        self._using_nn = True
        log.info("Real-ESRGAN loaded: %s (x%d)", self.model_path.name, self.scale)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def backend(self) -> str:
        """Return 'realesrgan' or 'bicubic' depending on what is active."""
        return "realesrgan" if self._using_nn else "bicubic"

    def upscale_frame(
        self,
        frame: np.ndarray,
        scale: Optional[int] = None,
    ) -> np.ndarray:
        """
        Upscale an entire BGR frame.

        Args:
            frame: H × W × 3 BGR numpy array (as returned by cv2.VideoCapture).
            scale: Upscale factor override. If None, uses self.scale.
                   When using Real-ESRGAN this is passed as outscale, so the
                   model internally runs at its native 4× and is then resized
                   to the requested factor.

        Returns:
            Upscaled BGR numpy array of shape (H*scale × W*scale × 3).
        """
        if frame is None or frame.size == 0:
            raise ValueError("upscale_frame received an empty frame")

        target_scale = scale if scale is not None else self.scale

        if self._using_nn and self._upsampler is not None:
            # RealESRGANer.enhance() returns (output_bgr, _)
            out, _ = self._upsampler.enhance(frame, outscale=target_scale)
            return out

        # Bicubic fallback
        h, w = frame.shape[:2]
        return cv2.resize(
            frame,
            (w * target_scale, h * target_scale),
            interpolation=cv2.INTER_CUBIC,
        )

    def upscale_roi(
        self,
        frame: np.ndarray,
        bbox: Tuple[int, int, int, int],
        scale: Optional[int] = None,
    ) -> np.ndarray:
        """
        Enhance one bounding-box region and composite it back into the frame.

        The ROI is upscaled by `scale`, then resized back to the original
        bounding-box dimensions before being pasted. This applies a
        super-resolution sharpening pass in-place without changing frame size.

        Args:
            frame: H × W × 3 BGR numpy array.
            bbox:  (x, y, w, h) bounding box in pixel coordinates.
            scale: Upscale factor for the intermediate SR pass. Defaults to
                   self.scale.

        Returns:
            A copy of `frame` with the bbox region sharpened in-place.
        """
        if frame is None or frame.size == 0:
            raise ValueError("upscale_roi received an empty frame")

        x, y, w, h = bbox
        fh, fw = frame.shape[:2]

        # Clamp to frame bounds
        x = max(0, min(x, fw - 1))
        y = max(0, min(y, fh - 1))
        w = min(w, fw - x)
        h = min(h, fh - y)

        if w <= 0 or h <= 0:
            return frame.copy()

        roi = frame[y : y + h, x : x + w]
        upscaled = self.upscale_frame(roi, scale=scale)

        # Resize back to original bbox size and paste
        restored = cv2.resize(upscaled, (w, h), interpolation=cv2.INTER_CUBIC)
        result = frame.copy()
        result[y : y + h, x : x + w] = restored
        return result
