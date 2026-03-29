"""
test_metrics.py

Unit tests for src/utils/metrics.py.
Run with: pytest tests/ -v

Coverage:
  - compute_psnr(): identical frames, different frames, shape mismatch
  - compute_ssim(): identical frames, different frames, shape mismatch
  - compute_compression_ratio(): basic, zero compressed, negative raises
  - compression_ratio(): path-based wrapper
  - foreground_coverage(): full foreground, empty mask, partial
  - storage_savings_report(): correct keys, correct values, zero compressed

Author: Victor De Souza Teixeira — fixed imports/added tests: Bloodawn (KheivenD)
"""

import sys
import tempfile
import numpy as np
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.metrics import (
    compute_psnr,
    compute_ssim,
    compute_compression_ratio,
    compression_ratio,
    foreground_coverage,
    storage_savings_report,
)


# ---------------------------------------------------------------------------
# compute_psnr
# ---------------------------------------------------------------------------

def test_compute_psnr_identical_frames():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    value = compute_psnr(frame, frame)
    assert value == float("inf") or value > 100


def test_compute_psnr_different_frames():
    frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
    frame2 = np.full((100, 100, 3), 255, dtype=np.uint8)
    value = compute_psnr(frame1, frame2)
    assert value < 10


def test_compute_psnr_shape_mismatch_raises():
    frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
    frame2 = np.zeros((50, 50, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="same shape"):
        compute_psnr(frame1, frame2)


def test_compute_psnr_returns_float():
    frame1 = np.zeros((50, 50, 3), dtype=np.uint8)
    frame2 = np.full((50, 50, 3), 128, dtype=np.uint8)
    assert isinstance(compute_psnr(frame1, frame2), float)


# ---------------------------------------------------------------------------
# compute_ssim
# ---------------------------------------------------------------------------

def test_compute_ssim_identical_frames():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    value = compute_ssim(frame, frame)
    assert value == pytest.approx(1.0, rel=1e-6)


def test_compute_ssim_different_frames():
    frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
    frame2 = np.full((100, 100, 3), 255, dtype=np.uint8)
    value = compute_ssim(frame1, frame2)
    assert 0.0 <= value < 0.1


def test_compute_ssim_shape_mismatch_raises():
    frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
    frame2 = np.zeros((50, 50, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="same shape"):
        compute_ssim(frame1, frame2)


def test_compute_ssim_returns_float():
    frame = np.zeros((50, 50, 3), dtype=np.uint8)
    assert isinstance(compute_ssim(frame, frame), float)


# ---------------------------------------------------------------------------
# compute_compression_ratio
# ---------------------------------------------------------------------------

def test_compute_compression_ratio_basic():
    assert compute_compression_ratio(6000, 1000) == pytest.approx(6.0)


def test_compute_compression_ratio_zero_compressed():
    assert compute_compression_ratio(6000, 0) == float("inf")


def test_compute_compression_ratio_negative_raises():
    with pytest.raises(ValueError, match="non-negative"):
        compute_compression_ratio(-1, 100)


def test_compute_compression_ratio_negative_compressed_raises():
    with pytest.raises(ValueError, match="non-negative"):
        compute_compression_ratio(100, -1)


def test_compute_compression_ratio_equal_sizes():
    assert compute_compression_ratio(1000, 1000) == pytest.approx(1.0)


def test_compute_compression_ratio_returns_float():
    assert isinstance(compute_compression_ratio(500, 100), float)


# ---------------------------------------------------------------------------
# compression_ratio (path-based wrapper)
# ---------------------------------------------------------------------------

def test_compression_ratio_from_paths():
    """Path-based wrapper must return same result as compute_compression_ratio."""
    with tempfile.TemporaryDirectory() as tmpdir:
        orig = Path(tmpdir) / "original.bin"
        comp = Path(tmpdir) / "compressed.bin"

        orig.write_bytes(b"x" * 6000)
        comp.write_bytes(b"x" * 1000)

        result = compression_ratio(str(orig), str(comp))
        assert result == pytest.approx(6.0)


def test_compression_ratio_missing_file_raises():
    """Missing file should raise FileNotFoundError (from stat())."""
    with pytest.raises(FileNotFoundError):
        compression_ratio("/nonexistent/original.bin", "/nonexistent/compressed.bin")


# ---------------------------------------------------------------------------
# foreground_coverage
# ---------------------------------------------------------------------------

def test_foreground_coverage_all_foreground():
    mask = np.full((100, 100), 255, dtype=np.uint8)
    assert foreground_coverage(mask) == pytest.approx(1.0)


def test_foreground_coverage_empty_mask():
    mask = np.zeros((100, 100), dtype=np.uint8)
    assert foreground_coverage(mask) == pytest.approx(0.0)


def test_foreground_coverage_partial():
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[:50, :] = 255  # top half foreground = 50%
    assert foreground_coverage(mask) == pytest.approx(0.5)


def test_foreground_coverage_zero_size_mask():
    mask = np.zeros((0, 0), dtype=np.uint8)
    assert foreground_coverage(mask) == 0.0


def test_foreground_coverage_returns_float():
    mask = np.zeros((100, 100), dtype=np.uint8)
    assert isinstance(foreground_coverage(mask), float)


# ---------------------------------------------------------------------------
# storage_savings_report
# ---------------------------------------------------------------------------

def test_storage_savings_report_keys():
    report = storage_savings_report(10_000_000, 2_000_000)
    expected_keys = {"original_mb", "compressed_mb", "saved_mb", "compression_ratio", "space_saved_pct"}
    assert set(report.keys()) == expected_keys


def test_storage_savings_report_values():
    report = storage_savings_report(10_000_000, 2_000_000)
    assert report["original_mb"] == pytest.approx(10.0)
    assert report["compressed_mb"] == pytest.approx(2.0)
    assert report["saved_mb"] == pytest.approx(8.0)
    assert report["compression_ratio"] == pytest.approx(5.0)
    assert report["space_saved_pct"] == pytest.approx(80.0)


def test_storage_savings_report_zero_compressed():
    """Zero compressed size should not raise — uses max(..., 1) guard."""
    report = storage_savings_report(1_000_000, 0)
    assert report["compression_ratio"] > 0


def test_storage_savings_report_no_savings():
    report = storage_savings_report(1_000_000, 1_000_000)
    assert report["compression_ratio"] == pytest.approx(1.0)
    assert report["space_saved_pct"] == pytest.approx(0.0)
