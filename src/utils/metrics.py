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
    """PSNR in dB. Higher is better. >40 dB is considered very good."""
    return float(psnr_fn(original, compressed, data_range=255))


def compute_ssim(original: np.ndarray, compressed: np.ndarray) -> float:
    """SSIM in [0, 1]. Higher is better. >0.95 is considered very good."""
    gray_orig = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    gray_comp = cv2.cvtColor(compressed, cv2.COLOR_BGR2GRAY)
    return float(ssim_fn(gray_orig, gray_comp, data_range=255))


def compression_ratio(original_path: str, compressed_path: str) -> float:
    """Ratio of original size to compressed size. 6.0 means 6x smaller."""
    orig_size = Path(original_path).stat().st_size
    comp_size = Path(compressed_path).stat().st_size
    if comp_size == 0:
        return float("inf")
    return orig_size / comp_size


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
    ratio = original_size_bytes / max(compressed_size_bytes, 1)
    saved = original_size_bytes - compressed_size_bytes
    return {
        "original_mb": round(original_size_bytes / 1e6, 2),
        "compressed_mb": round(compressed_size_bytes / 1e6, 2),
        "saved_mb": round(saved / 1e6, 2),
        "compression_ratio": round(ratio, 2),
        "space_saved_pct": round((saved / max(original_size_bytes, 1)) * 100, 1),
    }
