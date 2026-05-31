"""
metrics.py

Evaluation utilities for benchmarking compression performance.

Metrics:
  - PSNR  (Peak Signal-to-Noise Ratio)
  - SSIM  (Structural Similarity Index)
  - Compression ratio
  - Storage savings vs. naive full-frame encode
  - Foreground pixel coverage ratio (what fraction of pixels were "kept")
"""

import cv2
import numpy as np
import os
import sqlite3
import time
from pathlib import Path
from typing import Callable, TypeVar
from skimage.metrics import structural_similarity as ssim_fn
from skimage.metrics import peak_signal_noise_ratio as psnr_fn

T = TypeVar("T")

"""
Enhancement metrics
-------------------
Note on "resolution" equivalence:
  The enhancer does NOT change frame resolution. upscale_roi() runs SR then
  downsamples back to the original bbox dimensions. So we measure *sharpness*
  (Laplacian variance) instead of pixel count, and map it to a rough
  perceptual label so log output reads like "480p → 720p".

Laplacian variance thresholds were tuned against CDnet clips at various blur
levels. Treat the labels as approximate. They convey trend, not ground truth.
"""


def compute_psnr(original: np.ndarray, compressed: np.ndarray) -> float:
    """PSNR in dB. Higher is better. >40 dB is considered very good."""
    if original.shape != compressed.shape:
        raise ValueError("original and compressed must have the same shape")

    if np.array_equal(original, compressed):
        return float("inf")

    return float(psnr_fn(original, compressed, data_range=255))


def compute_ssim(original: np.ndarray, compressed: np.ndarray) -> float:
    """SSIM in [0, 1]. Higher is better. >0.95 is considered very good."""
    if original.shape != compressed.shape:
        raise ValueError("original and compressed must have the same shape")
    gray_orig = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    gray_comp = cv2.cvtColor(compressed, cv2.COLOR_BGR2GRAY)
    return float(ssim_fn(gray_orig, gray_comp, data_range=255))


def compute_compression_ratio(original_size_bytes: int, compressed_size_bytes: int) -> float:
    """Ratio of original size to compressed size. 6.0 means 6x smaller."""
    if original_size_bytes < 0 or compressed_size_bytes < 0:
        raise ValueError("file sizes must be non-negative")
    if compressed_size_bytes == 0:
        return float("inf")
    return float(original_size_bytes / compressed_size_bytes)


def compression_ratio(original_path: str, compressed_path: str) -> float:
    """Convenience wrapper that computes compression ratio from file paths."""
    orig_size = Path(original_path).stat().st_size
    comp_size = Path(compressed_path).stat().st_size
    return compute_compression_ratio(orig_size, comp_size)


def foreground_coverage(mask: np.ndarray) -> float:
    """
    Fraction of pixels in the frame that are foreground.
    A value of 0.02 means only 2% of pixels are targets -- the rest can be
    heavily compressed or discarded.
    """
    total = mask.size
    fg = int(np.count_nonzero(mask))
    return fg / total if total > 0 else 0.0


def compute_sharpness(frame: np.ndarray) -> float:
    """
    Laplacian variance (a measure of perceived sharpness).

    Higher values mean sharper / more detailed. A blurry 480p clip typically
    scores < 200; a sharp 1080p clip typically scores > 800.

    Args:
        frame: BGR or grayscale numpy array.

    Returns:
        Float ≥ 0. Returns 0.0 on an empty or single-pixel input.
    """
    if frame is None or frame.size == 0:
        return 0.0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def estimate_perceptual_resolution(sharpness: float) -> str:
    """
    Map a Laplacian variance score to a rough perceptual resolution label.

    These thresholds are empirical. They give a human-readable sense of
    whether a region looks blurry or crisp, not a true resolution measurement.
    """
    if sharpness < 50:
        return "~240p (very blurry)"
    if sharpness < 150:
        return "~360p (blurry)"
    if sharpness < 400:
        return "~480p (moderate)"
    if sharpness < 900:
        return "~720p (sharp)"
    if sharpness < 2000:
        return "~1080p (very sharp)"
    return "~4K (ultra sharp)"


def compute_enhancement_gain(
    before_roi: np.ndarray,
    after_roi: np.ndarray,
) -> dict:
    """
    Measure the sharpness improvement from a super-resolution pass.

    Call this with the ROI crop *before* and *after* enhancement (both at the
    same spatial dimensions (the enhancer resizes back to original bbox size).

    Returns a dict with:
        sharpness_before  – Laplacian variance of the input crop
        sharpness_after   – Laplacian variance of the enhanced crop
        gain_pct          – percentage change (positive = improvement)
        before_label      – human-readable resolution equivalent e.g. "~480p"
        after_label       – human-readable resolution equivalent e.g. "~720p"
        improved          – True if after > before
    """
    before = compute_sharpness(before_roi)
    after = compute_sharpness(after_roi)
    gain_pct = ((after - before) / max(before, 1e-6)) * 100
    return {
        "sharpness_before": round(before, 1),
        "sharpness_after": round(after, 1),
        "gain_pct": round(gain_pct, 1),
        "before_label": estimate_perceptual_resolution(before),
        "after_label": estimate_perceptual_resolution(after),
        "improved": after > before,
    }


def storage_savings_report(original_size_bytes: int, compressed_size_bytes: int) -> dict:
    """
    Summarise storage savings from a single encode.

    Uses compute_compression_ratio() for consistent handling of zero/negative
    inputs. Same rules as the rest of this module.

    Raises ValueError if either size is negative (delegated to
    compute_compression_ratio).

    Returns:
        Dict with keys: original_mb, compressed_mb, saved_mb,
        compression_ratio, space_saved_pct.
    """
    if original_size_bytes < 0 or compressed_size_bytes < 0:
        raise ValueError("file sizes must be non-negative")
    ratio = compute_compression_ratio(original_size_bytes, compressed_size_bytes)
    saved = original_size_bytes - compressed_size_bytes
    return {
        "original_mb": round(original_size_bytes / 1e6, 2),
        "compressed_mb": round(compressed_size_bytes / 1e6, 2),
        "saved_mb": round(saved / 1e6, 2),
        "compression_ratio": round(ratio, 2) if ratio != float("inf") else ratio,
        "space_saved_pct": round((saved / original_size_bytes) * 100, 2) if original_size_bytes > 0 else 0.0,
    }


def measure_cpu_usage(func: Callable[[], T]) -> tuple[T, dict]:
    """
    Run a callable and measure CPU cost for the current process plus completed
    child processes.

    The percentage is normalized to one CPU core, so CPU-heavy subprocesses can
    exceed 100% on multi-core systems.
    """
    start_wall = time.perf_counter()
    start_times = os.times()
    result = func()
    end_times = os.times()
    wall_seconds = max(time.perf_counter() - start_wall, 1e-9)

    cpu_seconds = (
        (end_times.user - start_times.user)
        + (end_times.system - start_times.system)
        + (end_times.children_user - start_times.children_user)
        + (end_times.children_system - start_times.children_system)
    )

    return result, {
        "wall_seconds": round(wall_seconds, 3),
        "cpu_seconds": round(cpu_seconds, 3),
        "cpu_percent": round((cpu_seconds / wall_seconds) * 100.0, 1),
        "cpu_core_equivalent": round(cpu_seconds / wall_seconds, 2),
    }


def summarize_mode_storage(input_path: str | Path, db_path: str | Path) -> dict:
    """
    Compute storage metrics for one demo mode from its metadata database.

    The compressed size is the sum of the segment file sizes recorded by the
    pipeline, not the stitched demo video size. Demo videos include overlays and
    are only for presentation.
    """
    original_size = Path(input_path).stat().st_size
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(file_size), 0),
                COALESCE(SUM(duration), 0.0),
                COUNT(*),
                COALESCE(SUM(target_detected), 0),
                COALESCE(SUM(roi_count), 0)
            FROM segments
            """
        ).fetchone()

    compressed_size = int(row[0] or 0)
    report = storage_savings_report(original_size, compressed_size)
    report.update(
        {
            "original_bytes": int(original_size),
            "compressed_bytes": compressed_size,
            "total_duration_seconds": round(float(row[1] or 0.0), 3),
            "segment_count": int(row[2] or 0),
            "segments_with_targets": int(row[3] or 0),
            "roi_count": int(row[4] or 0),
        }
    )
    return report


def build_demo_metrics(
    *,
    mode: str,
    input_path: str | Path,
    db_path: str | Path,
    cpu_metrics: dict | None = None,
    latency_ms: float | None = None,
) -> dict:
    """
    Build the metrics payload shown on the demo end card and written to the
    manifest.

    latency_ms is intentionally optional because file demos do not have camera
    capture/display latency. Live paths can populate it when frame arrival and
    display/write timestamps are available.
    """
    metrics = summarize_mode_storage(input_path, db_path)
    metrics["mode"] = mode
    metrics["cpu"] = cpu_metrics or {}
    metrics["latency_ms"] = round(float(latency_ms), 1) if latency_ms is not None else None
    return metrics
