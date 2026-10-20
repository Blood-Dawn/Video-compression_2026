"""
src/enhancement/enhancement_benchmark.py

Quantify whether super-resolution actually helps a given segment / mode /
ROI combination. Answers two questions the team has been guessing about:

  1. Does running Real-ESRGAN on a Mode 2 / Mode 3 segment increase ROI
     sharpness in any meaningful way? (Mode 2 stores a background keyframe
     plus per-frame ROI patches; Mode 3 blacks out everything outside the
     ROI. Both modes concentrate intelligence value inside small bboxes,
     so the SR gain there matters more than gain elsewhere.)

  2. Does cropping to the ROI before SR - instead of running SR on the
     whole frame and then looking inside the box - change the result?
     ROI-only SR is roughly 10x faster on a 1080p frame with a small
     plate-sized box. If the in-ROI sharpness is the same either way,
     ROI-only SR is the obvious choice.

For each sampled frame the harness measures three variants:

    no_enhancement    plain bicubic up-scale of the ROI (baseline)
    full_frame_sr     run SR on the entire frame, then crop the ROI back
    roi_only_sr       crop ROI from the original frame, then run SR on
                      just that crop

Metrics per variant:

    sharpness_roi     Laplacian variance of the upscaled ROI (proxy for
                      perceived edge sharpness - higher is sharper).
    psnr_vs_baseline  PSNR of the variant against the bicubic baseline
                      cropped+upscaled ROI. None when not comparable.
    ssim_vs_baseline  SSIM ditto.
    ocr_confidence    Mean per-frame OCR confidence on the upscaled ROI.
                      Optional - only computed when an OCR backend is
                      installed and run_ocr=True.
    ocr_text          Best read text per frame, for sanity-checking.

Honest caveats:

  * Sharpness gain is necessary but not sufficient for "more readable"  - 
    a hallucinated SR can score higher Laplacian variance while inventing
    detail. That is why we also report OCR confidence: it is the closest
    practical proxy for "an automated reader can act on this".
  * PSNR/SSIM here compare against bicubic, not against a true
    high-resolution ground truth (we don't have one for surveillance
    footage). They measure how much the SR variant DIVERGES from the
    bicubic upscale - high divergence + high sharpness suggests the SR
    is doing real work; high divergence + low OCR is a hallucination
    warning.

Author: Bloodawn (KheivenD)
Created: 2026-05-02 to answer the "does SR help on Mode 2 / 3?" question.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Public dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class VariantMetrics:
    """Per-variant metrics aggregated across all sampled frames.

    All numeric fields are means across `frames_examined`. ``ocr_*`` is
    None when OCR was not requested or no backend was available.

    Author: Bloodawn (KheivenD)
    """
    label: str                              # "no_enhancement" | "full_frame_sr" | "roi_only_sr"
    avg_sharpness_roi:    float = 0.0
    avg_sharpness_full:   float = 0.0       # full-frame variant only; 0 for the others
    avg_psnr_vs_baseline: float | None = None
    avg_ssim_vs_baseline: float | None = None
    avg_ocr_confidence:   float | None = None
    ocr_reads:            int | None = None
    sample_texts:         list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkResult:
    """Top-level benchmark output. Returned by ``benchmark_enhancement``."""
    video_path:        str
    frames_examined:   int
    frames_total:      int
    roi_box:           tuple[int, int, int, int]
    sr_backend:        str
    ocr_backend:       str | None
    variants:          dict[str, VariantMetrics]
    deltas:            dict[str, Any]
    verdict:           str
    warnings:          list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["variants"] = {k: v.to_dict() if isinstance(v, VariantMetrics) else v
                         for k, v in self.variants.items()}
        return d


# ─────────────────────────────────────────────────────────────────────────────
# Pure-image metric helpers
# ─────────────────────────────────────────────────────────────────────────────


def measure_sharpness(image: np.ndarray) -> float:
    """Laplacian variance - the standard "is it in focus?" proxy.

    Higher value = more high-frequency content = sharper-looking image.
    Returns 0.0 on empty or single-pixel inputs to keep callers safe.

    Author: Bloodawn (KheivenD)
    """
    if image is None or image.size == 0:
        return 0.0
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    if gray.shape[0] < 2 or gray.shape[1] < 2:
        return 0.0
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def measure_psnr(reference: np.ndarray, candidate: np.ndarray) -> float | None:
    """Peak-signal-to-noise ratio in dB. None when shapes don't match."""
    if reference is None or candidate is None:
        return None
    if reference.shape != candidate.shape:
        return None
    diff = reference.astype(np.float64) - candidate.astype(np.float64)
    mse = float(np.mean(diff * diff))
    if mse <= 1e-9:
        return 100.0  # identical-ish; cap so the caller doesn't see inf.
    return float(20.0 * np.log10(255.0 / np.sqrt(mse)))


def measure_ssim(reference: np.ndarray, candidate: np.ndarray) -> float | None:
    """SSIM via skimage; None when shapes don't match or skimage missing."""
    if reference is None or candidate is None or reference.shape != candidate.shape:
        return None
    try:
        from skimage.metrics import structural_similarity as _ssim  # type: ignore
    except ImportError:
        return None
    if reference.ndim == 3:
        ref_g = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
        cand_g = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY)
    else:
        ref_g, cand_g = reference, candidate
    # win_size must be <= min spatial dim and odd
    win = min(7, ref_g.shape[0] - 1 if ref_g.shape[0] % 2 == 0 else ref_g.shape[0],
                 ref_g.shape[1] - 1 if ref_g.shape[1] % 2 == 0 else ref_g.shape[1])
    if win < 3:
        return None
    if win % 2 == 0:
        win -= 1
    try:
        return float(_ssim(ref_g, cand_g, win_size=win, data_range=255))
    except Exception:  # noqa: BLE001 - skimage occasionally raises ValueError on tiny crops
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Variant production helpers
# ─────────────────────────────────────────────────────────────────────────────


def _safe_crop(frame: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray:
    """Clamp the bbox to the frame and return the cropped region (BGR)."""
    h, w = frame.shape[:2]
    x, y, bw, bh = bbox
    x1 = max(0, int(x))
    y1 = max(0, int(y))
    x2 = min(w, int(x + bw))
    y2 = min(h, int(y + bh))
    if x2 <= x1 or y2 <= y1:
        return np.zeros((1, 1, 3), dtype=frame.dtype)
    return frame[y1:y2, x1:x2]


def _bicubic_upscale(image: np.ndarray, scale: int) -> np.ndarray:
    h, w = image.shape[:2]
    return cv2.resize(image, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)


def _try_full_frame_sr(frame: np.ndarray, enhancer, scale: int) -> np.ndarray | None:
    """SR-upscale the whole frame, or None when there is no enhancer or it fails."""
    if enhancer is None:
        return None
    try:
        return enhancer.upscale_frame(frame, scale=scale)
    except Exception as exc:  # noqa: BLE001 - any SR backend failure degrades to bicubic
        log.debug("Full-frame SR failed (%s); falling back to bicubic.", exc)
        return None


def _crop_scaled_roi(
    upscaled: np.ndarray, bbox: tuple[int, int, int, int], scale: int
) -> np.ndarray | None:
    """The ROI cut out of an already-upscaled frame, or None if it falls outside."""
    x, y, bw, bh = bbox
    sx, sy, sw, sh = x * scale, y * scale, bw * scale, bh * scale
    h, w = upscaled.shape[:2]
    sx2, sy2 = min(w, sx + sw), min(h, sy + sh)
    if sx2 <= sx or sy2 <= sy:
        return None
    return upscaled[sy:sy2, sx:sx2]


def _full_frame_sr_then_crop(
    frame: np.ndarray, bbox: tuple[int, int, int, int], enhancer, scale: int
) -> np.ndarray:
    """Upscale the entire frame with SR, then crop the (scaled) ROI."""
    upscaled = _try_full_frame_sr(frame, enhancer, scale)
    roi = _crop_scaled_roi(upscaled, bbox, scale) if upscaled is not None else None
    if roi is None:
        return _bicubic_upscale(_safe_crop(frame, bbox), scale)
    return roi


def _roi_only_sr(
    frame: np.ndarray, bbox: tuple[int, int, int, int], enhancer, scale: int
) -> np.ndarray:
    """Crop the ROI from the original frame, then upscale just that crop."""
    crop = _safe_crop(frame, bbox)
    if enhancer is None:
        return _bicubic_upscale(crop, scale)
    try:
        return enhancer.upscale_frame(crop, scale=scale)
    except Exception as exc:  # noqa: BLE001
        log.debug("ROI-only SR failed (%s); falling back to bicubic.", exc)
        return _bicubic_upscale(crop, scale)


# ─────────────────────────────────────────────────────────────────────────────
# Top-level benchmark
# ─────────────────────────────────────────────────────────────────────────────


def _safe_ocr(ocr, image: np.ndarray) -> tuple[float | None, str | None]:
    """Run the OCR backend; return (best_confidence, best_text) or (None, None)."""
    if ocr is None or not getattr(ocr, "available", False):
        return None, None
    try:
        reads = ocr.ocr(image)
    except Exception:  # noqa: BLE001
        return None, None
    if not reads:
        return None, None
    text, conf, _bbox = max(reads, key=lambda r: r[1])
    return float(conf), str(text)


def _verdict(deltas: dict[str, Any]) -> str:
    """Plain-English summary the GUI can show."""
    full_gain = deltas.get("roi_sharpness_gain_full_sr_pct") or 0.0
    roi_gain  = deltas.get("roi_sharpness_gain_roi_sr_pct") or 0.0
    ocr_full  = deltas.get("ocr_confidence_gain_full_sr") or 0.0
    ocr_roi   = deltas.get("ocr_confidence_gain_roi_sr") or 0.0

    # Sharpness gain over bicubic of < ~10% means SR is barely helping.
    if max(full_gain, roi_gain) < 10:
        return "SR provides minimal sharpness gain on this segment."

    # If ROI-only SR matches full-frame SR within 5 % sharpness AND within
    # 0.05 OCR confidence, recommend ROI-only - it's far cheaper.
    if abs(full_gain - roi_gain) < 5 and abs(ocr_full - ocr_roi) < 0.05:
        return "ROI-only SR matches full-frame SR; use ROI-only for ~10x speedup."

    if full_gain > roi_gain + 5:
        return "Full-frame SR sharper than ROI-only - keep full-frame for this clip."

    return "ROI-only SR competitive; full-frame SR adds context but at higher cost."


def benchmark_enhancement(
    video_path,
    roi_box: tuple[int, int, int, int],
    enhancer: Any | None = None,
    sample_every_n_frames: int = 5,
    max_frames: int = 20,
    sr_scale: int = 4,
    run_ocr: bool = False,
    ocr_backend: str = "auto",
    device: str | None = None,
) -> BenchmarkResult:
    """Compare three SR strategies on a saved segment for a given ROI.

    Args:
        video_path:            Path to a saved .mp4 segment (any mode).
        roi_box:               (x, y, w, h) in original frame coordinates.
                               Use the bbox from segments DB for Mode 2/3
                               clips so the comparison targets the actual
                               foreground region.
        enhancer:              Reuse an existing ``Enhancer``; pass None to
                               lazily construct one with default settings.
        sample_every_n_frames: Stride between sampled frames (cost guard).
        max_frames:            Cap on total sampled frames.
        sr_scale:              SR scale factor (2 or 4). 4 is recommended.
        run_ocr:               When True and an OCR backend is installed,
                               also report per-variant OCR confidence.
        ocr_backend:           Forwarded to the plate reader's OCR
                               selection (see plate_reader._select_backend).
        device:                Forwarded to a freshly-constructed Enhancer.

    Returns:
        ``BenchmarkResult`` with per-variant metrics, deltas, and a
        plain-English verdict the operator can act on.

    Author: Bloodawn (KheivenD)
    """
    path = Path(video_path)
    warnings: list[str] = []

    if not path.exists():
        return BenchmarkResult(
            video_path=str(path), frames_examined=0, frames_total=0,
            roi_box=tuple(roi_box), sr_backend="unknown", ocr_backend=None,
            variants={}, deltas={}, verdict="Video file not found.",
            warnings=[f"Not found: {path}"],
        )

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return BenchmarkResult(
            video_path=str(path), frames_examined=0, frames_total=0,
            roi_box=tuple(roi_box), sr_backend="unknown", ocr_backend=None,
            variants={}, deltas={}, verdict="OpenCV could not open the file.",
            warnings=[f"OpenCV open failed: {path}"],
        )
    frames_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    if enhancer is None:
        try:
            try:
                from enhancement.enhancer import Enhancer  # type: ignore
            except ImportError:
                from src.enhancement.enhancer import Enhancer  # type: ignore
            enhancer = Enhancer(scale=sr_scale, device=device)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Enhancer construction failed: {exc}; using bicubic only")
            enhancer = None

    sr_backend = getattr(enhancer, "backend", "bicubic") if enhancer is not None else "bicubic"

    ocr = None
    ocr_backend_name: str | None = None
    if run_ocr:
        try:
            try:
                from enhancement.plate_reader import _select_backend  # type: ignore
            except ImportError:
                from src.enhancement.plate_reader import _select_backend  # type: ignore
            ocr = _select_backend(ocr_backend, use_gpu=(device or "").lower() in ("cuda", "mps"))
            ocr_backend_name = getattr(ocr, "name", "none")
            if not getattr(ocr, "available", False):
                warnings.append(
                    "OCR requested but no backend installed; "
                    "install via `uv sync --extra plates` or `--extra plates-fallback`"
                )
                ocr = None
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"OCR setup failed: {exc}")
            ocr = None

    variants = {
        "no_enhancement": VariantMetrics(label="no_enhancement"),
        "full_frame_sr":  VariantMetrics(label="full_frame_sr"),
        "roi_only_sr":    VariantMetrics(label="roi_only_sr"),
    }
    sums = {k: {"sharp_roi": 0.0, "sharp_full": 0.0,
                "psnr": 0.0, "ssim": 0.0, "ocr_conf": 0.0,
                "psnr_n": 0, "ssim_n": 0, "ocr_n": 0}
            for k in variants}

    frame_idx = 0
    examined = 0
    stride = max(1, int(sample_every_n_frames))
    cap_max = max(1, int(max_frames))

    while examined < cap_max:
        if frame_idx % stride != 0:
            # grab() skips a frame without decoding it into a BGR array.
            if not cap.grab():
                break
            frame_idx += 1
            continue
        ok, frame = cap.read()
        if not ok or frame is None:
            break

        # Build the three variants for this frame. Full-frame SR is by far
        # the most expensive step, so it runs once and feeds both the cropped
        # variant and the whole-frame sharpness figure.
        baseline_roi = _bicubic_upscale(_safe_crop(frame, roi_box), sr_scale)
        full_up = _try_full_frame_sr(frame, enhancer, sr_scale)
        full_sr_roi = _crop_scaled_roi(full_up, roi_box, sr_scale) if full_up is not None else None
        if full_sr_roi is None:
            full_sr_roi = baseline_roi
        roi_sr_roi = _roi_only_sr(frame, roi_box, enhancer, sr_scale)

        sums["no_enhancement"]["sharp_roi"] += measure_sharpness(baseline_roi)
        sums["full_frame_sr"]["sharp_roi"]  += measure_sharpness(full_sr_roi)
        sums["roi_only_sr"]["sharp_roi"]    += measure_sharpness(roi_sr_roi)
        if full_up is not None:
            sums["full_frame_sr"]["sharp_full"] += measure_sharpness(full_up)

        # PSNR / SSIM of the SR variants against the bicubic baseline; all
        # three are the same ROI at the same scaled size.
        for key, candidate in (("full_frame_sr", full_sr_roi),
                               ("roi_only_sr", roi_sr_roi)):
            psnr = measure_psnr(baseline_roi, candidate)
            ssim = measure_ssim(baseline_roi, candidate)
            if psnr is not None:
                sums[key]["psnr"] += psnr
                sums[key]["psnr_n"] += 1
            if ssim is not None:
                sums[key]["ssim"] += ssim
                sums[key]["ssim_n"] += 1

        # Optional OCR pass on each variant.
        if ocr is not None:
            for key, image in (("no_enhancement", baseline_roi),
                               ("full_frame_sr", full_sr_roi),
                               ("roi_only_sr",   roi_sr_roi)):
                conf, text = _safe_ocr(ocr, image)
                if conf is not None:
                    sums[key]["ocr_conf"] += conf
                    sums[key]["ocr_n"]    += 1
                    if text and len(variants[key].sample_texts) < 5:
                        variants[key].sample_texts.append(text)

        examined += 1
        frame_idx += 1

    cap.release()

    for key, v in variants.items():
        if examined > 0:
            v.avg_sharpness_roi = round(sums[key]["sharp_roi"] / examined, 2)
            if key == "full_frame_sr":
                v.avg_sharpness_full = round(sums[key]["sharp_full"] / examined, 2)
        if sums[key]["psnr_n"]:
            v.avg_psnr_vs_baseline = round(sums[key]["psnr"] / sums[key]["psnr_n"], 2)
        if sums[key]["ssim_n"]:
            v.avg_ssim_vs_baseline = round(sums[key]["ssim"] / sums[key]["ssim_n"], 4)
        if sums[key]["ocr_n"]:
            v.avg_ocr_confidence = round(sums[key]["ocr_conf"] / sums[key]["ocr_n"], 3)
            v.ocr_reads = sums[key]["ocr_n"]

    # Deltas - the actually-actionable numbers.
    base = variants["no_enhancement"].avg_sharpness_roi or 1e-6
    deltas: dict[str, Any] = {
        "roi_sharpness_gain_full_sr_pct": round(
            100.0 * (variants["full_frame_sr"].avg_sharpness_roi - base) / base, 1),
        "roi_sharpness_gain_roi_sr_pct": round(
            100.0 * (variants["roi_only_sr"].avg_sharpness_roi - base) / base, 1),
    }
    if variants["no_enhancement"].avg_ocr_confidence is not None:
        ocr_base = variants["no_enhancement"].avg_ocr_confidence
        if variants["full_frame_sr"].avg_ocr_confidence is not None:
            deltas["ocr_confidence_gain_full_sr"] = round(
                variants["full_frame_sr"].avg_ocr_confidence - ocr_base, 3)
        if variants["roi_only_sr"].avg_ocr_confidence is not None:
            deltas["ocr_confidence_gain_roi_sr"] = round(
                variants["roi_only_sr"].avg_ocr_confidence - ocr_base, 3)

    if examined == 0:
        warnings.append("No frames could be sampled from the segment.")

    return BenchmarkResult(
        video_path=str(path),
        frames_examined=examined,
        frames_total=frames_total,
        roi_box=tuple(int(v) for v in roi_box),
        sr_backend=sr_backend,
        ocr_backend=ocr_backend_name,
        variants=variants,
        deltas=deltas,
        verdict=_verdict(deltas) if examined > 0 else "No frames examined.",
        warnings=warnings,
    )


__all__ = [
    "benchmark_enhancement",
    "measure_sharpness",
    "measure_psnr",
    "measure_ssim",
    "BenchmarkResult",
    "VariantMetrics",
]
