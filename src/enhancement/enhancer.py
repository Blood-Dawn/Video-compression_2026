"""
enhancer.py

CPU-based super-resolution enhancement for post-offload footage analysis.

Supports two backends, selected automatically based on what is installed:
  1. OpenCV dnn_superres  (ESPCN / FSRCNN / EDSR / LapSRN)
       - Requires: opencv-contrib-python
       - Requires: model .pb file in models/ directory
       - Speed: 1–50 ms / frame at 480p (CPU)
       - Use for: bulk post-offload batch processing

  2. Real-ESRGAN  (RealESRGAN_x4plus / realesr-general-x4v3)
       - Requires: pip install realesrgan basicsr facexlib gfpgan
       - Requires: .pth weight file in models/ directory
       - Speed: 100–500 ms / frame at 480p (CPU, fp32)
       - Use for: high-value forensic targets (faces, license plates)
       - Note: use realesrnet (MSE loss) variant for fewer hallucinations

Model file locations (all gitignored — do not commit weights):
  models/ESPCN_x2.pb    models/ESPCN_x4.pb
  models/FSRCNN_x2.pb   models/FSRCNN_x4.pb
  models/EDSR_x2.pb     models/EDSR_x4.pb
  models/LapSRN_x2.pb   models/LapSRN_x4.pb   models/LapSRN_x8.pb
  models/RealESRGAN_x4plus.pth
  models/realesr-general-x4v3.pth

Setup instructions: see DEV.md → "Enhancement Module Setup"

Hallucination warning:
  Real-ESRGAN and other GAN-based models may fabricate details (faces,
  license plates, text) that look plausible but are not present in the
  original footage. Never use enhanced output as the sole evidence.
  Always retain the original compressed segment alongside any enhanced copy.
  Prefer RealESRNet (MSE loss) for forensic applications.

Author: Bloodawn (KheivenD)
"""

import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)

# Default path to look for model weight files.
# Resolved relative to this file's parent-of-parent (project root).
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_MODELS_DIR = _PROJECT_ROOT / "models"

# Supported OpenCV dnn_superres model names (lowercase).
_DNNSUPERRES_MODELS = {"espcn", "fsrcnn", "edsr", "lapsrn"}

# Dependency-free built-in backends (always available, no weight files needed).
_BUILTIN_MODELS = {"bicubic"}

# Supported Real-ESRGAN model filenames (stem → display name).
_REALESRGAN_MODELS = {
    "RealESRGAN_x4plus": "realesrgan",
    "realesr-general-x4v3": "realesr-general",
    "RealESRNet_x4plus": "realesrnet",  # MSE loss — fewer hallucinations
}


class Enhancer:
    """
    Post-compression super-resolution enhancement for static surveillance footage.

    Automatically selects the best available backend:
      - opencv dnn_superres (fast, good quality, easy to set up)
      - Real-ESRGAN (slower, best quality, requires extra pip packages)

    The class is safe to instantiate even when no backend is available.
    is_available() returns False and all processing methods raise RuntimeError
    until a model is loaded.

    Usage:
        # With OpenCV dnn_superres (ESPCN — fast CPU mode):
        enhancer = Enhancer(scale=4, model="espcn")
        if enhancer.is_available():
            upscaled = enhancer.upscale_frame(frame)
            roi_enhanced = enhancer.upscale_roi(frame, bbox=(x, y, w, h))

        # With Real-ESRGAN (higher quality, slower):
        enhancer = Enhancer(scale=4, model="realesrgan")

        # Batch processing (model loaded once):
        results = enhancer.enhance_batch(frames)
    """

    def __init__(
        self,
        scale: int = 4,
        model: str = "espcn",
        models_dir: Optional[str] = None,
        device: str = "cpu",
    ):
        """
        Initialize the enhancer and attempt to load the requested model.

        Args:
            scale: Upscale factor. Typically 2 or 4. LapSRN also supports 8.
            model: Backend model name. One of:
                   OpenCV dnn_superres: "espcn", "fsrcnn", "edsr", "lapsrn"
                   Real-ESRGAN:        "realesrgan", "realesrnet", "realesr-general"
            models_dir: Directory containing weight files. Defaults to
                        <project_root>/models/.
            device: Compute device. "cpu" always used in production.
                    "cuda" / "mps" accepted but not tested on target hardware.
        """
        self.scale = scale
        self.model = model.lower()
        self.device = device
        self.models_dir = Path(models_dir) if models_dir else _DEFAULT_MODELS_DIR

        self._available: bool = False
        self._backend: str = ""           # "dnnsuperres", "realesrgan", or "bicubic"
        self._sr = None                   # loaded model object (backend-specific)
        self._realesrgan_upsampler = None # Real-ESRGAN RealESRGANer instance

        self._load_model()

    # ─── Public API ────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True when a model is loaded and ready for inference."""
        return self._available

    def upscale_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Upscale an entire decoded video frame by self.scale.

        Args:
            frame: BGR uint8 numpy array, shape (H, W, 3).

        Returns:
            Upscaled BGR uint8 numpy array, shape (H*scale, W*scale, 3).

        Raises:
            RuntimeError: If no backend is loaded (is_available() is False).
            ValueError: If frame is not a valid 3-channel uint8 BGR array.
        """
        self._require_available()
        frame = self._validate_frame(frame)

        if self._backend == "dnnsuperres":
            return self._sr.upsample(frame)

        if self._backend == "realesrgan":
            return self._realesrgan_upscale(frame)

        if self._backend == "bicubic":
            h, w = frame.shape[:2]
            return cv2.resize(
                frame,
                (w * self.scale, h * self.scale),
                interpolation=cv2.INTER_CUBIC,
            )

        raise RuntimeError(f"Unknown backend: {self._backend!r}")

    def upscale_roi(
        self,
        frame: np.ndarray,
        bbox: Tuple[int, int, int, int],
    ) -> np.ndarray:
        """
        Crop the ROI from frame, upscale it, resize back to original ROI
        dimensions, and paste it back onto the frame canvas.

        Upscaling only the ROI is significantly faster than full-frame upscaling
        when the subject occupies a small fraction of total pixels (typical for
        sparse surveillance footage).

        The result has the SAME shape as the input frame — the ROI region is
        enhanced in-place, the rest of the frame is unchanged.

        Args:
            frame: Full-resolution BGR uint8 numpy array, shape (H, W, 3).
            bbox: Bounding box as (x, y, w, h) in pixel coordinates.

        Returns:
            A copy of frame with the ROI region replaced by its enhanced version.
            Output shape is identical to input shape.

        Raises:
            RuntimeError: If no backend is loaded.
            ValueError: If bbox is out of bounds for the given frame.
        """
        x, y, w, h = bbox
        fh, fw = frame.shape[:2]
        if x < 0 or y < 0 or x + w > fw or y + h > fh:
            raise ValueError(
                f"bbox {bbox} is out of bounds for frame of size {fw}x{fh}"
            )
        if w <= 0 or h <= 0:
            raise ValueError(f"bbox has non-positive dimensions: w={w}, h={h}")

        self._require_available()
        frame = self._validate_frame(frame)

        # Crop the region.
        roi = frame[y:y + h, x:x + w].copy()

        # Upscale the crop.
        upscaled_roi = self.upscale_frame(roi)

        # Resize the upscaled crop back to the original bbox dimensions
        # so it fits back onto the canvas without changing overall frame size.
        restored = cv2.resize(
            upscaled_roi,
            (w, h),
            interpolation=cv2.INTER_LANCZOS4,
        )

        # Paste back.
        result = frame.copy()
        result[y:y + h, x:x + w] = restored
        return result

    def enhance_batch(self, frames: List[np.ndarray]) -> List[np.ndarray]:
        """
        Upscale a list of frames in one call.

        The model is already loaded at __init__ time, so calling this method
        avoids repeated model initialization compared to calling upscale_frame()
        in a manual loop.

        Args:
            frames: List of BGR uint8 numpy arrays, all the same shape.

        Returns:
            List of upscaled BGR uint8 numpy arrays (scale times larger in H and W).

        Raises:
            RuntimeError: If no backend is loaded.
            ValueError: If frames is empty or frames have inconsistent shapes.
        """
        if not frames:
            raise ValueError("frames must not be empty")
        shape = frames[0].shape
        if any(f.shape != shape for f in frames[1:]):
            raise ValueError("All frames must have the same shape")

        self._require_available()
        return [self.upscale_frame(f) for f in frames]

    # ─── Model Loading ─────────────────────────────────────────────────────────

    def _load_model(self) -> None:
        """
        Attempt to load the requested model. Sets self._available = True on
        success. Logs a warning and returns quietly on failure (missing weights,
        missing package) so callers can gate behind is_available().
        """
        if self.model in _BUILTIN_MODELS:
            self._try_load_builtin()
        elif self.model in _DNNSUPERRES_MODELS:
            self._try_load_dnnsuperres()
        elif self.model in {"realesrgan", "realesrnet", "realesr-general"}:
            self._try_load_realesrgan()
        else:
            log.warning(
                f"Enhancer: unknown model {self.model!r}. "
                f"Supported: {sorted(_DNNSUPERRES_MODELS | {'realesrgan', 'realesrnet', 'realesr-general'} | _BUILTIN_MODELS)}. "
                "Enhancement disabled."
            )

    def _try_load_builtin(self) -> None:
        """Activate the dependency-free bicubic upscale backend.

        Always succeeds — no weight files or extra packages required.
        Use as a safe fallback when dnn_superres / Real-ESRGAN are not available.
        """
        self._backend = "bicubic"
        self._available = True
        log.info(
            f"Enhancer: using built-in bicubic x{self.scale} fallback backend "
            "(no weight files required)"
        )

    def _try_load_dnnsuperres(self) -> None:
        """Load an OpenCV dnn_superres model from the models/ directory."""
        # Check for the dnn_superres module (requires opencv-contrib-python).
        if not hasattr(cv2, "dnn_superres"):
            log.warning(
                "Enhancer: cv2.dnn_superres is not available. "
                "Install opencv-contrib-python to enable enhancement.\n"
                "  pip install opencv-contrib-python"
            )
            return

        # Find the model weight file.
        model_upper = self.model.upper()
        candidates = [
            self.models_dir / f"{model_upper}_x{self.scale}.pb",
            self.models_dir / f"{model_upper}_{self.scale}.pb",
        ]
        model_path = next((p for p in candidates if p.exists()), None)

        if model_path is None:
            searched = ", ".join(str(p) for p in candidates)
            log.warning(
                f"Enhancer: model weight file not found. Searched: {searched}\n"
                f"Download {model_upper}_x{self.scale}.pb from the OpenCV extra "
                "models repo and place it in models/.\n"
                "  See: https://github.com/opencv/opencv_contrib/tree/master/modules/dnn_superres"
            )
            return

        try:
            sr = cv2.dnn_superres.DnnSuperResImpl_create()
            sr.readModel(str(model_path))
            sr.setModel(self.model, self.scale)
            if self.device.lower() in ("cuda", "gpu"):
                sr.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
                sr.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
            self._sr = sr
            self._backend = "dnnsuperres"
            self._available = True
            log.info(
                f"Enhancer: loaded {self.model.upper()} x{self.scale} "
                f"from {model_path}"
            )
        except Exception as exc:
            log.warning(f"Enhancer: failed to load dnn_superres model: {exc}")

    def _try_load_realesrgan(self) -> None:
        """Load Real-ESRGAN using the realesrgan Python package."""
        try:
            from basicsr.archs.rrdbnet_arch import RRDBNet
            from realesrgan import RealESRGANer
        except ImportError:
            log.warning(
                "Enhancer: realesrgan package not installed. "
                "Install with:\n"
                "  pip install realesrgan basicsr facexlib gfpgan"
            )
            return

        # Map model alias to weight filename.
        model_stem_map = {
            "realesrgan": f"RealESRGAN_x{self.scale}plus",
            "realesrnet": f"RealESRNet_x{self.scale}plus",
            "realesr-general": "realesr-general-x4v3",
        }
        stem = model_stem_map.get(self.model, f"RealESRGAN_x{self.scale}plus")
        model_path = self.models_dir / f"{stem}.pth"

        if not model_path.exists():
            log.warning(
                f"Enhancer: Real-ESRGAN weight file not found: {model_path}\n"
                f"Download {stem}.pth from https://github.com/xinntao/Real-ESRGAN "
                "and place it in models/."
            )
            return

        try:
            # All government deployments run CPU-only (fp32).
            # half=False forces fp32 instead of fp16 (fp16 requires CUDA).
            rrdbnet_model = RRDBNet(
                num_in_ch=3, num_out_ch=3,
                num_feat=64, num_block=23, num_grow_ch=32,
                scale=self.scale,
            )
            upsampler = RealESRGANer(
                scale=self.scale,
                model_path=str(model_path),
                model=rrdbnet_model,
                tile=0,           # 0 = no tiling (use full frame)
                tile_pad=10,
                pre_pad=0,
                half=False,       # fp32 for CPU
                device=self.device,
            )
            self._realesrgan_upsampler = upsampler
            self._backend = "realesrgan"
            self._available = True
            log.info(
                f"Enhancer: loaded Real-ESRGAN ({stem}) x{self.scale} "
                f"[fp32, CPU] from {model_path}"
            )
        except Exception as exc:
            log.warning(f"Enhancer: failed to load Real-ESRGAN: {exc}")

    # ─── Backend-Specific Inference ────────────────────────────────────────────

    def _realesrgan_upscale(self, frame: np.ndarray) -> np.ndarray:
        """Run Real-ESRGAN inference on a single BGR frame."""
        # RealESRGANer.enhance() expects BGR uint8, returns BGR uint8.
        output, _ = self._realesrgan_upsampler.enhance(frame, outscale=self.scale)
        return output

    # ─── Validation Helpers ────────────────────────────────────────────────────

    def _require_available(self) -> None:
        if not self._available:
            raise RuntimeError(
                "Enhancer is not available. "
                "Check that the model weight file exists in models/ and that "
                "the required Python packages are installed. "
                "See DEV.md → Enhancement Module Setup."
            )

    @staticmethod
    def _validate_frame(frame: np.ndarray) -> np.ndarray:
        if not isinstance(frame, np.ndarray):
            raise ValueError(f"frame must be a numpy array, got {type(frame)}")
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError(
                f"frame must be shape (H, W, 3), got {frame.shape}"
            )
        if frame.dtype != np.uint8:
            frame = np.clip(frame, 0, 255).astype(np.uint8)
        return frame

    # ─── Repr ─────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"Enhancer(model={self.model!r}, scale={self.scale}, "
            f"device={self.device!r}, backend={self._backend!r}, "
            f"available={self._available})"
        )
