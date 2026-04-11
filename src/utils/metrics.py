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
from pathlib import Path
from skimage.metrics import structural_similarity as ssim_fn
from skimage.metrics import peak_signal_noise_ratio as psnr_fn


def compute_psnr(original: np.ndarray, compressed: np.ndarray) -> float:
    """
    PSNR in dB. Higher is better. >40 dB is considered very good.

    Returns float('inf') for identical frames (no error signal).
    Raises ValueError if frames have different shapes.
    """
    if original.shape != compressed.shape:
        raise ValueError(
            f"original and compressed must have the same shape, "
            f"got {original.shape} vs {compressed.shape}"
        )
    if np.array_equal(original, compressed):
        return float("inf")
    return float(psnr_fn(original, compressed, data_range=255))


def compute_ssim(original: np.ndarray, compressed: np.ndarray) -> float:
    """
    SSIM in [0, 1]. Higher is better. >0.95 is considered very good.

    Converts to grayscale before comparison so color channel differences
    don't inflate or deflate the structural similarity score.
    Raises ValueError if frames have different shapes.
    """
    if original.shape != compressed.shape:
        raise ValueError(
            f"original and compressed must have the same shape, "
            f"got {original.shape} vs {compressed.shape}"
        )
    gray_orig = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    gray_comp = cv2.cvtColor(compressed, cv2.COLOR_BGR2GRAY)
    return float(ssim_fn(gray_orig, gray_comp, data_range=255))


def compute_compression_ratio(original_size_bytes: int, compressed_size_bytes: int) -> float:
    """
    Ratio of original size to compressed size. 6.0 means 6x smaller.

    Returns float('inf') if compressed_size_bytes is zero.
    Raises ValueError if either size is negative.
    """
    if original_size_bytes < 0 or compressed_size_bytes < 0:
        raise ValueError("file sizes must be non-negative")
    if compressed_size_bytes == 0:
        return float("inf")
    return float(original_size_bytes / compressed_size_bytes)


def compression_ratio(original_path: str, compressed_path: str) -> float:
    """
    Convenience wrapper: computes compression ratio from file paths.

    Raises FileNotFoundError if either path does not exist.
    """
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


def storage_savings_report(original_size_bytes: int, compressed_size_bytes: int) -> dict:
    """
    Summarise storage savings from a single encode.

    Uses compute_compression_ratio() for consistent handling of zero/negative
    inputs — same rules as the rest of this module.

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
        "space_saved_pct": round((saved / max(original_size_bytes, 1)) * 100, 1),
    }
