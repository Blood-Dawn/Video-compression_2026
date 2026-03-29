import numpy as np
import pytest

from src.utils.metrics import (
    compute_psnr,
    compute_ssim,
    compute_compression_ratio,
)


def test_compute_psnr_identical_frames():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    value = compute_psnr(frame, frame)
    assert value == float("inf") or value > 100


def test_compute_ssim_identical_frames():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    value = compute_ssim(frame, frame)
    assert value == pytest.approx(1.0, rel=1e-6)


def test_compute_psnr_different_frames():
    frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
    frame2 = np.full((100, 100, 3), 255, dtype=np.uint8)
    value = compute_psnr(frame1, frame2)
    assert value < 10


def test_compute_ssim_different_frames():
    frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
    frame2 = np.full((100, 100, 3), 255, dtype=np.uint8)
    value = compute_ssim(frame1, frame2)
    assert 0.0 <= value < 0.1


def test_compute_compression_ratio():
    assert compute_compression_ratio(6000, 1000) == 6.0


def test_compute_compression_ratio_zero_compressed():
    assert compute_compression_ratio(6000, 0) == float("inf")


def test_compute_compression_ratio_negative_raises():
    with pytest.raises(ValueError):
        compute_compression_ratio(-1, 100)


def test_compute_psnr_shape_mismatch_raises():
    frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
    frame2 = np.zeros((50, 50, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        compute_psnr(frame1, frame2)


def test_compute_ssim_shape_mismatch_raises():
    frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
    frame2 = np.zeros((50, 50, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        compute_ssim(frame1, frame2)