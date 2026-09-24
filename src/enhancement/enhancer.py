"""
enhancer.py

Super-resolution enhancement with a real backend behind every option the GUI
offers: ESPCN, FSRCNN, EDSR and LapSRN via OpenCV's dnn_superres module, and
Real-ESRGAN / RealESRNet via basicsr's RRDBNet architecture. Supports CPU,
NVIDIA CUDA (GPU), and Apple Silicon MPS for the RRDBNet backends; the
dnn_superres backends run on CPU (the pip opencv-contrib-python wheels this
project depends on are not built with a CUDA DNN backend).

Device selection order (automatic, RRDBNet backends only):
  1. CUDA  (if an NVIDIA GPU with CUDA is available and torch is installed
  2. MPS   (if running on Apple Silicon (M1/M2/M3) with torch >= 2.0
  3. CPU   (universal fallback, always works (slowest)

The device can also be forced via the ``device`` constructor argument or the
``ENHANCER_DEVICE`` environment variable ("cuda", "mps", "cpu").

Falls back silently to bicubic interpolation when:
  - the requested model's weights file is missing from models/
  - realesrgan / basicsr packages are not installed (realesrgan/realesrnet only)
  - the selected device fails to initialise (e.g. CUDA out of memory)

Author: Victor Teixeira
GPU support added: Bloodawn / KheivenD
6-model registry (ESPCN/FSRCNN/EDSR/LapSRN/RealESRNet real code, basicsr/
torchvision compatibility shim): Bloodawn (KheivenD), 2026-09-24.

Model download:
    See DEV.md -> "Enhancement Module Setup" for instructions, or run
    scripts/download_enhance_models.py to fetch every weights file at once.
"""

import logging
import os
import sys
import types
from pathlib import Path
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)

# Default models directory.
#
# In a frozen PyInstaller build, resolve straight off sys._MEIPASS instead of
# walking up from __file__: this module can load under either the canonical
# name (enhancement.enhancer) or the src.* mirror (src.enhancement.enhancer -
# see installer/svcs.spec's dual-import-name comment for why both exist), and
# those two resolve __file__ at different depths under _MEIPASS. Walking
# __file__.parent.parent.parent lands in the right place for one of them and
# one level too high for the other, which would make a bundled models/ folder
# silently invisible depending on which name happened to win. sys._MEIPASS is
# unambiguous: PyInstaller sets it to the same place regardless of which
# import name resolved, and installer/svcs.spec bundles the AI-enhance model
# weights to "models" relative to that same COLLECT root.
if os.environ.get("ENHANCER_MODELS_DIR"):
    _DEFAULT_MODELS_DIR = Path(os.environ["ENHANCER_MODELS_DIR"])
elif getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _DEFAULT_MODELS_DIR = Path(sys._MEIPASS) / "models"
else:
    _DEFAULT_MODELS_DIR = Path(__file__).parent.parent.parent / "models"

_VALID_SCALES = {2, 3, 4, 8}

# ─────────────────────────────────────────────────────────────────────────────
# Model registry
#
# Every non-bicubic option the GUI can offer resolves through this table.
# "dnn_superres" models run through cv2.dnn_superres (OpenCV's contrib
# super-resolution module - requires opencv-contrib-python, NOT plain
# opencv-python/opencv-python-headless, which silently ship an empty
# cv2.dnn_superres namespace with no error). "rrdbnet" models share the
# existing Real-ESRGAN loading path, just with different checkpoint weights.
#
# Weight sources (all redistributed under permissive licenses - see
# DEV.md -> "Enhancement Module Setup" for the full attribution list):
#   ESPCN/LapSRN:  fannymonori/TF-ESPCN, fannymonori/TF-LapSRN (Apache-2.0)
#   FSRCNN/EDSR:   Saafke/FSRCNN_Tensorflow, Saafke/EDSR_Tensorflow (Apache-2.0)
#   RealESRGAN/RealESRNet: xinntao/Real-ESRGAN release assets (BSD-3-Clause)
# ─────────────────────────────────────────────────────────────────────────────

_DNN_SR_MODELS: Dict[str, Dict] = {
    "espcn":  {"algo": "espcn",  "scales": (2, 3, 4),    "filename": "ESPCN_x{s}.pb"},
    "fsrcnn": {"algo": "fsrcnn", "scales": (2, 3, 4),    "filename": "FSRCNN_x{s}.pb"},
    "edsr":   {"algo": "edsr",   "scales": (2, 3, 4),    "filename": "EDSR_x{s}.pb"},
    "lapsrn": {"algo": "lapsrn", "scales": (2, 4, 8),    "filename": "LapSRN_x{s}.pb"},
}

_RRDBNET_MODELS: Dict[str, str] = {
    "realesrgan": "RealESRGAN_x4plus.pth",
    "realesrnet": "RealESRNet_x4plus.pth",
}

# Every recognised non-bicubic model id, for GUI/route validation.
ALL_MODEL_IDS = frozenset({"bicubic", *_DNN_SR_MODELS, *_RRDBNET_MODELS})


def _nearest_supported_scale(model_id: str, requested: int) -> int:
    """Snap ``requested`` to a scale the given dnn_superres model actually ships.

    LapSRN only has x2/x4/x8 weights (no x3); ESPCN/FSRCNN/EDSR have x2/x3/x4.
    Picking the closest available scale keeps a slightly-off request working
    instead of failing outright, and is logged so it's never a silent lie
    about what scale actually ran.
    """
    scales = _DNN_SR_MODELS[model_id]["scales"]
    if requested in scales:
        return requested
    nearest = min(scales, key=lambda s: abs(s - requested))
    log.info(
        "%s has no x%d weights (available: %s). Using x%d instead.",
        model_id.upper(), requested, sorted(scales), nearest,
    )
    return nearest


def _ensure_torchvision_functional_tensor_shim() -> None:
    """Patch around a real, currently-live basicsr/torchvision incompatibility.

    basicsr.data.degradations imports
    ``torchvision.transforms.functional_tensor.rgb_to_grayscale``, a module
    torchvision removed in 0.17+ (the function moved to
    ``torchvision.transforms.functional``, unchanged). Without this shim,
    ``from basicsr.archs.rrdbnet_arch import RRDBNet`` raises
    ModuleNotFoundError on any current torchvision - which the existing
    ``except ImportError`` in _load_model_rrdbnet() already caught, so this
    was never a crash, just Real-ESRGAN/RealESRNet silently never activating
    and every run quietly using bicubic instead, no matter how correctly it
    was configured. Discovered and fixed 2026-09-24 while wiring up
    RealESRNet - it also explains why Real-ESRGAN itself was inert.
    """
    mod_name = "torchvision.transforms.functional_tensor"
    if mod_name in sys.modules:
        return
    try:
        from torchvision.transforms import functional as _tv_functional
    except ImportError:
        return  # torchvision itself isn't installed; the caller's import will fail normally
    shim = types.ModuleType(mod_name)
    shim.rgb_to_grayscale = _tv_functional.rgb_to_grayscale
    sys.modules[mod_name] = shim


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
                    "Expect 5-20× faster SR than CPU."
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
                "Neural Engine / GPU cores. Expect 2-5× faster than CPU."
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
    Frame and ROI upscaler backed by a real model for every option the GUI
    offers: bicubic, espcn, fsrcnn, edsr, lapsrn, realesrgan, realesrnet.

    Usage:
        enhancer = Enhancer()                             # bicubic (no model requested)
        enhancer = Enhancer(model="realesrgan")            # AI, auto-detect device
        enhancer = Enhancer(model="espcn", device="cpu")   # fast, lightweight AI
        enhancer = Enhancer(model="edsr", scale=3)
        enhancer = Enhancer(models_dir="/data/weights")

    Device resolution order (realesrgan/realesrnet only; the dnn_superres
    models always run on CPU):
      1. ``device`` argument
      2. ``ENHANCER_DEVICE`` environment variable
      3. Auto-detect: CUDA → MPS → CPU

    If the model or required packages/weights are missing, all methods fall
    back to bicubic interpolation transparently, and ``backend`` reports
    "bicubic" so callers can tell the difference between "AI ran" and
    "AI was requested but silently didn't run" (see pipeline.py's check
    against ``enhancer.backend`` after construction).
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        models_dir: Optional[str] = None,
        scale: int = 4,
        device: Optional[str] = None,
        use_nn: bool = True,
        model: str = "realesrgan",
    ) -> None:
        """
        Args:
            model_path: Explicit path to a weights file, overriding the
                        registry lookup for ``model``.
            models_dir: Directory containing the model weight files.
            scale:      Requested upscale factor. dnn_superres models snap
                        this to their nearest shipped scale (see
                        _nearest_supported_scale); realesrgan/realesrnet are
                        always x4 regardless of this value (that's the only
                        scale either ships weights for).
            device:     "cuda" | "mps" | "cpu" | None (auto-detect). Only
                        meaningful for realesrgan/realesrnet.
            use_nn:     False skips loading any model entirely and always
                        uses bicubic, even if ``model`` names one whose
                        weights are present. This is what an explicit
                        "bicubic" choice in the GUI maps to.
            model:      One of ALL_MODEL_IDS: "bicubic", "espcn", "fsrcnn",
                        "edsr", "lapsrn", "realesrgan", "realesrnet".
                        Unrecognised values behave like "bicubic".
        """
        if scale not in _VALID_SCALES:
            raise ValueError(f"scale must be one of {sorted(_VALID_SCALES)}, got {scale}")
        self.scale = scale
        self.model_id = (model or "bicubic").strip().lower()
        if self.model_id not in ALL_MODEL_IDS:
            log.warning("Unknown enhance model %r requested; treating as bicubic.", model)
            self.model_id = "bicubic"

        self._models_dir = Path(models_dir) if models_dir else _DEFAULT_MODELS_DIR
        self._explicit_model_path = Path(model_path) if model_path else None

        # Resolve device (realesrgan/realesrnet only - dnn_superres is CPU-only
        # with the pip opencv-contrib-python wheels this project ships).
        if device:
            self._device = device.strip().lower()
        else:
            env = os.environ.get("ENHANCER_DEVICE", "").strip().lower()
            self._device = env if env in ("cuda", "mps", "cpu") else best_device()

        self._upsampler = None      # cv2.dnn_superres.DnnSuperResImpl, when active
        self._rrdb_upsampler = None  # RealESRGANer, when active
        self._using_nn  = False
        self._active_scale = scale

        if not use_nn or self.model_id == "bicubic":
            if use_nn and self.model_id == "bicubic":
                log.info("Enhancer: bicubic explicitly selected, skipping model load.")
            self.model_id = "bicubic"
        elif self.model_id in _DNN_SR_MODELS:
            self._load_dnn_superres()
        elif self.model_id in _RRDBNET_MODELS:
            self._load_rrdbnet()

    # ------------------------------------------------------------------
    # Internal: dnn_superres backends (ESPCN / FSRCNN / EDSR / LapSRN)
    # ------------------------------------------------------------------

    def _load_dnn_superres(self) -> None:
        spec = _DNN_SR_MODELS[self.model_id]
        target_scale = _nearest_supported_scale(self.model_id, self.scale)

        weights_path = self._explicit_model_path or (
            self._models_dir / spec["filename"].format(s=target_scale)
        )
        if not weights_path.exists():
            log.warning(
                "%s weights not found at %s. Using bicubic fallback. Run "
                "scripts/download_enhance_models.py or see DEV.md -> "
                "'Enhancement Module Setup'.",
                self.model_id.upper(), weights_path,
            )
            return

        if not hasattr(cv2, "dnn_superres") or not hasattr(cv2.dnn_superres, "DnnSuperResImpl_create"):
            log.warning(
                "cv2.dnn_superres has no implementation in this OpenCV build "
                "(got plain opencv-python/opencv-python-headless instead of "
                "opencv-contrib-python, or the two are installed together and "
                "the non-contrib one's files won overwrote the contrib "
                "build's). Using bicubic fallback. Fix: `pip uninstall "
                "opencv-python opencv-python-headless && pip install --force-"
                "reinstall opencv-contrib-python`."
            )
            return

        try:
            sr = cv2.dnn_superres.DnnSuperResImpl_create()
            sr.readModel(str(weights_path))
            sr.setModel(spec["algo"], target_scale)
            self._upsampler = sr
            self._using_nn = True
            self._active_scale = target_scale
            self._device = "cpu"  # dnn_superres has no GPU backend in these wheels
            log.info(
                "%s loaded: %s (x%d) on CPU",
                self.model_id.upper(), weights_path.name, target_scale,
            )
        except Exception as exc:
            log.warning(
                "%s failed to initialise (%s: %s). Using bicubic fallback.",
                self.model_id.upper(), type(exc).__name__, exc,
            )
            self._upsampler = None
            self._using_nn = False

    # ------------------------------------------------------------------
    # Internal: RRDBNet backends (Real-ESRGAN / RealESRNet)
    # ------------------------------------------------------------------

    def _load_rrdbnet(self) -> None:
        """Attempt to load an RRDBNet checkpoint (Real-ESRGAN or RealESRNet)."""
        _ensure_torchvision_functional_tensor_shim()
        try:
            from basicsr.archs.rrdbnet_arch import RRDBNet  # type: ignore
            from realesrgan import RealESRGANer              # type: ignore
        except ImportError:
            log.warning(
                "realesrgan / basicsr not installed. Using bicubic fallback. "
                "To enable AI upscaling: pip install basicsr realesrgan"
            )
            return

        weights_path = self._explicit_model_path or (
            self._models_dir / _RRDBNET_MODELS[self.model_id]
        )
        if not weights_path.exists():
            log.warning(
                "%s weights not found at %s. Using bicubic fallback. Run "
                "scripts/download_enhance_models.py or see DEV.md -> "
                "'Enhancement Module Setup'.",
                self.model_id, weights_path,
            )
            return

        # RRDBNet checkpoints here are only shipped at x4; report it plainly
        # rather than silently ignoring a different requested scale.
        if self.scale != 4:
            log.info(
                "%s only has x4 weights; ignoring requested scale x%d.",
                self.model_id, self.scale,
            )
        self._active_scale = 4

        # Validate device availability and downgrade if necessary
        resolved_device = self._resolve_device()

        try:
            model = RRDBNet(
                num_in_ch=3,
                num_out_ch=3,
                num_feat=64,
                num_block=23,
                num_grow_ch=32,
                scale=4,
            )
            use_half = (resolved_device == "cuda")  # fp16 only on CUDA
            self._rrdb_upsampler = RealESRGANer(
                scale=4,
                model_path=str(weights_path),
                model=model,
                device=resolved_device,
                half=use_half,
            )
            self._using_nn  = True
            self._device    = resolved_device
            log.info(
                "%s loaded: %s (x4) on %s",
                self.model_id, weights_path.name, resolved_device.upper()
            )
        except Exception as exc:
            if resolved_device != "cpu":
                # Try again on CPU before giving up entirely
                log.warning(
                    "%s failed on %s (%s: %s). Retrying on CPU.",
                    self.model_id, resolved_device.upper(), type(exc).__name__, exc,
                )
                try:
                    model2 = RRDBNet(
                        num_in_ch=3, num_out_ch=3,
                        num_feat=64, num_block=23, num_grow_ch=32,
                        scale=4,
                    )
                    self._rrdb_upsampler = RealESRGANer(
                        scale=4,
                        model_path=str(weights_path),
                        model=model2,
                        device="cpu",
                        half=False,
                    )
                    self._using_nn = True
                    self._device   = "cpu"
                    log.info("%s loaded on CPU (GPU fallback).", self.model_id)
                    return
                except Exception as exc2:
                    log.warning("CPU fallback also failed (%s). Using bicubic.", exc2)
            else:
                log.warning(
                    "%s failed to initialise (%s: %s). Using bicubic fallback.",
                    self.model_id, type(exc).__name__, exc,
                )
            self._rrdb_upsampler = None
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
        """Return e.g. 'realesrgan-cuda', 'espcn-cpu', 'edsr-cpu', or 'bicubic'."""
        if self._using_nn:
            return f"{self.model_id}-{self._device}"
        return "bicubic"

    @property
    def device(self) -> str:
        """Return the active compute device string."""
        return self._device

    @property
    def active_scale(self) -> int:
        """Return the scale actually in effect (may differ from the requested
        one: dnn_superres models snap to their nearest shipped scale, and
        RRDBNet models are always x4)."""
        return self._active_scale

    def upscale_frame(
        self,
        frame: np.ndarray,
        scale: Optional[int] = None,
    ) -> np.ndarray:
        """
        Upscale an entire BGR frame.

        Args:
            frame: H × W × 3 BGR numpy array (as returned by cv2.VideoCapture).
            scale: Upscale factor override. Only honoured for the bicubic
                   fallback path; an active model always runs at the scale it
                   was loaded for (self.active_scale) since dnn_superres and
                   RRDBNet models are fixed-scale once loaded.

        Returns:
            Upscaled BGR numpy array.
        """
        if frame is None or frame.size == 0:
            raise ValueError("upscale_frame received an empty frame")

        if self._using_nn and self._upsampler is not None:
            return self._upsampler.upsample(frame)

        if self._using_nn and self._rrdb_upsampler is not None:
            out, _ = self._rrdb_upsampler.enhance(frame, outscale=self._active_scale)
            return out

        target_scale = scale if scale is not None else self.scale
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
            scale:           Upscale factor for the intermediate SR pass
                             (bicubic fallback only - see upscale_frame).
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
