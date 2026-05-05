"""
enhancer.py

Super-resolution enhancement using Real-ESRGAN.
Supports CPU, NVIDIA CUDA (GPU), and Apple Silicon MPS.

Device selection order (automatic):
  1. CUDA  (if an NVIDIA GPU with CUDA is available and torch is installed
  2. MPS   (if running on Apple Silicon (M1/M2/M3) with torch >= 2.0
  3. CPU   (universal fallback, always works (slowest)

The device can also be forced via the ``device`` constructor argument or the
``ENHANCER_DEVICE`` environment variable ("cuda", "mps", "cpu").

Falls back silently to bicubic interpolation when:
  - realesrgan / basicsr packages are not installed
  - model weights file is missing
  - the selected device fails to initialise (e.g. CUDA out of memory)

Author: Victor Teixeira
GPU support added: Bloodawn / KheivenD

Model download:
    See DEV.md → "Enhancement Module Setup" for instructions.
    TL;DR: download RealESRGAN_x4plus.pth and place it in models/
"""

import logging
import os
from pathlib import Path
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)

# Default models directory
_DEFAULT_MODELS_DIR = Path(
    os.environ.get("ENHANCER_MODELS_DIR", "")
) if os.environ.get("ENHANCER_MODELS_DIR") else Path(__file__).parent.parent.parent / "models"

_DEFAULT_MODEL_PATH = _DEFAULT_MODELS_DIR / "RealESRGAN_x4plus.pth"

_VALID_SCALES = {2, 4}


# ─────────────────────────────────────────────────────────────────────────────
# GPU / device detection helpers (importable by app.py for /api/gpu_info)
# ─────────────────────────────────────────────────────────────────────────────

def detect_gpu() -> Dict:
    """
    Probe the system for GPU acceleration support.

    Returns a dict with keys:
        available      bool  (True if any GPU backend can be used)
        backend        str   ("cuda", "mps", or "cpu")
        device_name    str   (human-readable GPU name, or "CPU only")
        cuda_available bool
        mps_available  bool
        cuda_version   str | None
        vram_mb        int | None   (CUDA VRAM in MB; None if unknown)
        torch_version  str | None
        will_work      bool  (True if SR will run faster than CPU)
        note           str   (human-readable summary)
        mobile_note    str   (warning about mobile / integrated GPU)
    """
    result: Dict = {
        "available": False,
        "backend": "cpu",
        "device_name": "CPU only",
        "cuda_available": False,
        "mps_available": False,
        "cuda_version": None,
        "vram_mb": None,
        "torch_version": None,
        "will_work": False,
        "note": "",
        "mobile_note": "",
    }

    try:
        import torch
        result["torch_version"] = torch.__version__

        # ── CUDA (NVIDIA) ────────────────────────────────────────────
        if torch.cuda.is_available():
            result["cuda_available"] = True
            idx = torch.cuda.current_device()
            name = torch.cuda.get_device_name(idx)
            props = torch.cuda.get_device_properties(idx)
            vram_mb = props.total_memory // (1024 * 1024)

            result["available"]   = True
            result["backend"]     = "cuda"
            result["device_name"] = name
            result["cuda_version"] = torch.version.cuda
            result["vram_mb"]     = vram_mb
            result["will_work"]   = vram_mb >= 2048  # Real-ESRGAN needs ~2 GB VRAM minimum

            # Warn on low-VRAM / integrated / mobile GPUs
            name_lower = name.lower()
            is_mobile = any(x in name_lower for x in [
                "mx", "gtx 9", "gtx 10", "rtx 20",  # older low-VRAM cards
                "1050", "1060", "1650", "1660",       # borderline VRAM
                "intel", "amd radeon", "vega",        # ROCm is unsupported here
                "iris", "uhd", "hd graphics",         # integrated
            ])
            if vram_mb < 2048:
                result["will_work"] = False
                result["note"] = (
                    f"{name}: only {vram_mb} MB VRAM detected. "
                    "Real-ESRGAN needs at least 2 GB. Will fall back to CPU."
                )
                result["mobile_note"] = "Low VRAM. GPU acceleration disabled for SR."
            elif is_mobile:
                result["note"] = (
                    f"{name}: mobile/older GPU detected ({vram_mb} MB VRAM). "
                    "SR will run but may be slow. Consider using every-N-frames sampling."
                )
                result["mobile_note"] = "Mobile GPU: SR will work but expect reduced speed."
            else:
                result["note"] = (
                    f"{name}: {vram_mb} MB VRAM. GPU acceleration active. "
                    "Expect 5–20× faster SR than CPU."
                )

        # ── MPS (Apple Silicon) ──────────────────────────────────────
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            result["mps_available"] = True
            result["available"]   = True
            result["backend"]     = "mps"
            result["device_name"] = "Apple Silicon (MPS)"
            result["will_work"]   = True
            result["note"] = (
                "Apple Silicon GPU (MPS) detected. Real-ESRGAN will run on the "
                "Neural Engine / GPU cores. Expect 2–5× faster than CPU."
            )
            result["mobile_note"] = (
                "MPS is Apple-only. Not supported on phones or Windows/Linux machines."
            )

        else:
            result["note"] = (
                "No CUDA or MPS GPU found. Real-ESRGAN will run on CPU. "
                "To enable GPU: install CUDA + torch with CUDA, or use Apple Silicon."
            )
            result["will_work"] = False  # GPU won't help, but CPU SR still works

    except ImportError:
        result["note"] = "PyTorch is not installed. GPU detection unavailable."

    return result


def best_device() -> str:
    """Return the best available torch device string: 'cuda', 'mps', or 'cpu'."""
    env = os.environ.get("ENHANCER_DEVICE", "").strip().lower()
    if env in ("cuda", "mps", "cpu"):
        return env
    info = detect_gpu()
    return info["backend"]


# ─────────────────────────────────────────────────────────────────────────────
# Enhancer class
# ─────────────────────────────────────────────────────────────────────────────

class Enhancer:
    """
    Frame and ROI upscaler using Real-ESRGAN (CPU / CUDA / MPS).

    Usage:
        enhancer = Enhancer()                             # auto-detect device
        enhancer = Enhancer(device="cuda")                # force NVIDIA GPU
        enhancer = Enhancer(device="cpu")                 # force CPU
        enhancer = Enhancer(model_path="models/RealESRGAN_x4plus.pth")
        enhancer = Enhancer(models_dir="/data/weights")

    Device resolution order:
      1. ``device`` argument
      2. ``ENHANCER_DEVICE`` environment variable
      3. Auto-detect: CUDA → MPS → CPU

    If the model or required packages are missing, all methods fall back to
    bicubic interpolation transparently.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        models_dir: Optional[str] = None,
        scale: int = 4,
        device: Optional[str] = None,
    ) -> None:
        """
        Args:
            model_path: Explicit path to a RealESRGAN .pth weights file.
            models_dir: Directory containing RealESRGAN_x4plus.pth.
            scale:      Model upscale factor (2 or 4).
            device:     "cuda" | "mps" | "cpu" | None (auto-detect).
        """
        if scale not in _VALID_SCALES:
            raise ValueError(f"scale must be one of {_VALID_SCALES}, got {scale}")
        self.scale = scale

        if model_path:
            self.model_path = Path(model_path)
        elif models_dir:
            self.model_path = Path(models_dir) / "RealESRGAN_x4plus.pth"
        else:
            self.model_path = _DEFAULT_MODEL_PATH

        # Resolve device
        if device:
            self._device = device.strip().lower()
        else:
            env = os.environ.get("ENHANCER_DEVICE", "").strip().lower()
            self._device = env if env in ("cuda", "mps", "cpu") else best_device()

        self._upsampler = None
        self._using_nn  = False
        self._load_model()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        """Attempt to load Real-ESRGAN on the selected device."""
        try:
            from basicsr.archs.rrdbnet_arch import RRDBNet  # type: ignore
            from realesrgan import RealESRGANer              # type: ignore
        except ImportError:
            log.warning(
                "realesrgan / basicsr not installed. Using bicubic fallback. "
                "To enable AI upscaling: pip install basicsr realesrgan"
            )
            return

        if not self.model_path.exists():
            log.warning(
                "Model weights not found at %s. Using bicubic fallback. "
                "See DEV.md → 'Enhancement Module Setup' to download weights.",
                self.model_path,
            )
            return

        # Validate device availability and downgrade if necessary
        resolved_device = self._resolve_device()

        try:
            model = RRDBNet(
                num_in_ch=3,
                num_out_ch=3,
                num_feat=64,
                num_block=23,
                num_grow_ch=32,
                scale=self.scale,
            )
            use_half = (resolved_device == "cuda")  # fp16 only on CUDA
            self._upsampler = RealESRGANer(
                scale=self.scale,
                model_path=str(self.model_path),
                model=model,
                device=resolved_device,
                half=use_half,
            )
            self._using_nn  = True
            self._device    = resolved_device
            log.info(
                "Real-ESRGAN loaded: %s (x%d) on %s",
                self.model_path.name, self.scale, resolved_device.upper()
            )
        except Exception as exc:
            if resolved_device != "cpu":
                # Try again on CPU before giving up entirely
                log.warning(
                    "Real-ESRGAN failed on %s (%s: %s). Retrying on CPU.",
                    resolved_device.upper(), type(exc).__name__, exc,
                )
                try:
                    model2 = RRDBNet(
                        num_in_ch=3, num_out_ch=3,
                        num_feat=64, num_block=23, num_grow_ch=32,
                        scale=self.scale,
                    )
                    self._upsampler = RealESRGANer(
                        scale=self.scale,
                        model_path=str(self.model_path),
                        model=model2,
                        device="cpu",
                        half=False,
                    )
                    self._using_nn = True
                    self._device   = "cpu"
                    log.info("Real-ESRGAN loaded on CPU (GPU fallback).")
                    return
                except Exception as exc2:
                    log.warning("CPU fallback also failed (%s). Using bicubic.", exc2)
            else:
                log.warning(
                    "Real-ESRGAN failed to initialise (%s: %s). Using bicubic fallback.",
                    type(exc).__name__, exc,
                )
            self._upsampler = None
            self._using_nn  = False

    def _resolve_device(self) -> str:
        """Validate the requested device and downgrade if unavailable."""
        requested = self._device
        try:
            import torch
            if requested == "cuda":
                if torch.cuda.is_available():
                    # Check VRAM (Real-ESRGAN needs ~2 GB)
                    vram = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
                    if vram < 2048:
                        log.warning(
                            "CUDA GPU has only %d MB VRAM (need 2048 MB). Falling back to CPU.", vram
                        )
                        return "cpu"
                    return "cuda"
                log.warning("CUDA requested but not available. Falling back to CPU.")
                return "cpu"
            if requested == "mps":
                if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    return "mps"
                log.warning("MPS requested but not available. Falling back to CPU.")
                return "cpu"
        except ImportError:
            log.warning("torch not installed. Cannot use GPU, falling back to CPU.")
        return "cpu"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def backend(self) -> str:
        """Return 'realesrgan-cuda', 'realesrgan-mps', 'realesrgan-cpu', or 'bicubic'."""
        if self._using_nn:
            return f"realesrgan-{self._device}"
        return "bicubic"

    @property
    def device(self) -> str:
        """Return the active compute device string."""
        return self._device

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

        Returns:
            Upscaled BGR numpy array.
        """
        if frame is None or frame.size == 0:
            raise ValueError("upscale_frame received an empty frame")

        target_scale = scale if scale is not None else self.scale

        if self._using_nn and self._upsampler is not None:
            out, _ = self._upsampler.enhance(frame, outscale=target_scale)
            return out

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
        measure_quality: bool = False,
    ) -> np.ndarray:
        """
        Enhance one bounding-box region and composite it back into the frame.

        Args:
            frame:           H × W × 3 BGR numpy array.
            bbox:            (x, y, w, h) bounding box in pixel coordinates.
            scale:           Upscale factor for the intermediate SR pass.
            measure_quality: Log before/after sharpness. Avoid in hot paths.

        Returns:
            Copy of ``frame`` with the bbox region sharpened in-place.
        """
        if frame is None or frame.size == 0:
            raise ValueError("upscale_roi received an empty frame")

        x, y, w, h = bbox
        fh, fw = frame.shape[:2]

        x = max(0, min(x, fw - 1))
        y = max(0, min(y, fh - 1))
        w = min(w, fw - x)
        h = min(h, fh - y)

        if w <= 0 or h <= 0:
            return frame.copy()

        roi      = frame[y : y + h, x : x + w]
        upscaled = self.upscale_frame(roi, scale=scale)
        sharpened = cv2.resize(upscaled, (w, h), interpolation=cv2.INTER_CUBIC)
        out = frame.copy()
        out[y : y + h, x : x + w] = sharpened

        if measure_quality:
            try:
                from utils.metrics import compute_enhancement_gain  # type: ignore
            except ImportError:
                try:
                    from src.utils.metrics import compute_enhancement_gain  # type: ignore
                except ImportError:
                    compute_enhancement_gain = None

            if compute_enhancement_gain is not None:
                gain = compute_enhancement_gain(roi, sharpened)
                if gain["improved"]:
                    log.info(
                        "Enhancement gain: %s → %s  (+%.1f%%)  [backend: %s]",
                        gain["before_label"], gain["after_label"],
                        gain["gain_pct"], self.backend,
                    )
                else:
                    log.debug(
                        "Enhancement no gain: %.1f → %.1f  (%.1f%%)  [backend: %s]",
                        gain["sharpness_before"], gain["sharpness_after"],
                        gain["gain_pct"], self.backend,
                    )

        return out
