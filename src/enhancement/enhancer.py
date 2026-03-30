"""
enhancer.py

Stub for Milestone 2 post-compression enhancement / super-resolution.

The Enhancer class defines the full interface that downstream code (pipeline,
notebooks, tests) can import and call against today.  Every method raises
NotImplementedError so integration wiring can be written and tested now,
with the real implementation filled in during Milestone 2.

Planned implementation notes (Milestone 2):
  - upscale_frame: apply a lightweight SR model (e.g. EDSR, Real-ESRGAN) to
    an entire decoded frame.  Useful for background segments that were encoded
    at high CRF and need perceptual quality restored before display.
  - upscale_roi: crop the ROI region, upscale it, and paste it back onto the
    full-resolution canvas. More efficient than upscaling the whole frame when
    the ROI is a small fraction of total pixels.
  - enhance_batch: process a list of frames in one call; allows the model to
    be loaded once and applied across many frames without repeated init cost.

Author: Bloodawn (KheivenD)
"""

import numpy as np
from typing import List, Tuple


class Enhancer:
    """
    Post-compression image enhancement / super-resolution interface.

    All methods are stubs that raise NotImplementedError.
    Implement during Milestone 2 by replacing the raise statements with
    a real model (EDSR, FSRCNN, Real-ESRGAN, etc.).

    Usage (Milestone 2+):
        enhancer = Enhancer(scale=2, model="edsr")
        upscaled = enhancer.upscale_frame(frame)
        roi_upscaled = enhancer.upscale_roi(frame, bbox=(x, y, w, h))
    """

    def __init__(
        self,
        scale: int = 2,
        model: str = "edsr",
        device: str = "cpu",
    ):
        """
        Args:
            scale: Upscale factor. Typically 2 or 4.
            model: Model architecture name. Supported values TBD (Milestone 2).
                   Suggested options: "edsr", "fsrcnn", "esrgan".
            device: Compute device. "cpu" for Raspberry Pi / legacy hardware.
                    "cuda" or "mps" if available.
        """
        self.scale = scale
        self.model = model
        self.device = device

    def upscale_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Upscale an entire decoded video frame by self.scale.

        Args:
            frame: BGR uint8 numpy array, shape (H, W, 3).

        Returns:
            Upscaled BGR uint8 numpy array, shape (H*scale, W*scale, 3).

        Raises:
            NotImplementedError: Until Milestone 2 implementation is complete.
        """
        raise NotImplementedError(
            "upscale_frame() is not yet implemented. "
            "Complete the super-resolution model integration in Milestone 2."
        )

    def upscale_roi(
        self,
        frame: np.ndarray,
        bbox: Tuple[int, int, int, int],
    ) -> np.ndarray:
        """
        Crop the ROI from frame, upscale it, and paste it back.

        More efficient than full-frame upscaling when the ROI covers only a
        small fraction of the total pixel area (typical for sparse surveillance
        footage with one or two small targets).

        Args:
            frame: Full-resolution BGR uint8 numpy array, shape (H, W, 3).
            bbox: Bounding box as (x, y, w, h) in pixel coordinates.

        Returns:
            A copy of frame with the ROI region replaced by its upscaled version.
            Output shape is identical to input shape.

        Raises:
            NotImplementedError: Until Milestone 2 implementation is complete.
            ValueError: If bbox is out of bounds (raised even before implementation).
        """
        x, y, w, h = bbox
        fh, fw = frame.shape[:2]
        if x < 0 or y < 0 or x + w > fw or y + h > fh:
            raise ValueError(
                f"bbox {bbox} is out of bounds for frame of size {fw}x{fh}"
            )
        raise NotImplementedError(
            "upscale_roi() is not yet implemented. "
            "Complete the super-resolution model integration in Milestone 2."
        )

    def enhance_batch(self, frames: List[np.ndarray]) -> List[np.ndarray]:
        """
        Upscale a list of frames in one call (model loaded once).

        Args:
            frames: List of BGR uint8 numpy arrays, all the same shape.

        Returns:
            List of upscaled BGR uint8 numpy arrays.

        Raises:
            NotImplementedError: Until Milestone 2 implementation is complete.
            ValueError: If frames is empty or frames have inconsistent shapes.
        """
        if not frames:
            raise ValueError("frames must not be empty")
        shape = frames[0].shape
        if any(f.shape != shape for f in frames):
            raise ValueError("All frames must have the same shape")
        raise NotImplementedError(
            "enhance_batch() is not yet implemented. "
            "Complete the super-resolution model integration in Milestone 2."
        )

    def is_available(self) -> bool:
        """
        Returns True when the enhancement backend is loaded and ready.

        Always returns False in the stub so callers can gate enhancement
        behind an availability check without crashing.
        """
        return False

    def __repr__(self) -> str:
        return (
            f"Enhancer(model={self.model!r}, scale={self.scale}, "
            f"device={self.device!r}, available={self.is_available()})"
        )
