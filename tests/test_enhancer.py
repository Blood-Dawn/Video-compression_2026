"""
test_enhancer.py

Unit tests for src/enhancement/enhancer.py.

These tests are designed to pass even without Real-ESRGAN installed or
model weights downloaded. The bicubic fallback is exercised in all cases
so CI can run the full test suite without extra setup.

Author: Victor Teixeira
"""

import numpy as np
import pytest
from src.enhancement.enhancer import Enhancer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def enhancer():
    """Enhancer with no model path — always uses bicubic fallback."""
    return Enhancer(model_path="nonexistent_model.pth", scale=4)


@pytest.fixture
def small_frame():
    """32 × 32 BGR frame filled with a gradient."""
    frame = np.zeros((32, 32, 3), dtype=np.uint8)
    for i in range(32):
        frame[i, :, :] = i * 8   # horizontal gradient
    return frame


# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------

def test_backend_is_bicubic_without_weights(enhancer):
    assert enhancer.backend == "bicubic"


def test_backend_is_realesrgan_or_bicubic_with_default_path():
    """
    Instantiating with the default path should never raise — it should
    either load the model (if weights exist) or fall back gracefully.
    """
    e = Enhancer()
    assert e.backend in ("realesrgan", "bicubic")


# ---------------------------------------------------------------------------
# upscale_frame — output shape
# ---------------------------------------------------------------------------

def test_upscale_frame_output_shape_x4(enhancer, small_frame):
    out = enhancer.upscale_frame(small_frame, scale=4)
    expected_h = small_frame.shape[0] * 4
    expected_w = small_frame.shape[1] * 4
    assert out.shape == (expected_h, expected_w, 3)


def test_upscale_frame_output_shape_x2(enhancer, small_frame):
    out = enhancer.upscale_frame(small_frame, scale=2)
    assert out.shape == (small_frame.shape[0] * 2, small_frame.shape[1] * 2, 3)


def test_upscale_frame_uses_instance_scale_when_no_override(small_frame):
    e = Enhancer(model_path="nonexistent.pth", scale=2)
    out = e.upscale_frame(small_frame)   # no scale arg
    assert out.shape == (small_frame.shape[0] * 2, small_frame.shape[1] * 2, 3)


def test_upscale_frame_output_dtype(enhancer, small_frame):
    out = enhancer.upscale_frame(small_frame)
    assert out.dtype == np.uint8


def test_upscale_frame_is_not_all_zeros(enhancer, small_frame):
    out = enhancer.upscale_frame(small_frame)
    assert out.sum() > 0


# ---------------------------------------------------------------------------
# upscale_frame — error handling
# ---------------------------------------------------------------------------

def test_upscale_frame_raises_on_empty_array(enhancer):
    with pytest.raises(ValueError, match="empty frame"):
        enhancer.upscale_frame(np.array([]))


# ---------------------------------------------------------------------------
# upscale_roi — output shape equals input shape
# ---------------------------------------------------------------------------

def test_upscale_roi_output_shape_matches_input(enhancer, small_frame):
    bbox = (4, 4, 16, 16)
    out = enhancer.upscale_roi(small_frame, bbox)
    assert out.shape == small_frame.shape


def test_upscale_roi_does_not_mutate_original(enhancer, small_frame):
    original = small_frame.copy()
    bbox = (0, 0, 16, 16)
    enhancer.upscale_roi(small_frame, bbox)
    np.testing.assert_array_equal(small_frame, original)


def test_upscale_roi_outside_frame_returns_copy(enhancer, small_frame):
    """A bbox entirely outside the frame should return a clean copy."""
    bbox = (100, 100, 10, 10)   # beyond 32 × 32 frame
    out = enhancer.upscale_roi(small_frame, bbox)
    assert out.shape == small_frame.shape


def test_upscale_roi_full_frame_bbox(enhancer, small_frame):
    h, w = small_frame.shape[:2]
    bbox = (0, 0, w, h)
    out = enhancer.upscale_roi(small_frame, bbox)
    assert out.shape == small_frame.shape


def test_upscale_roi_clamped_negative_coords(enhancer, small_frame):
    """Negative x/y should be clamped, not raise."""
    bbox = (-5, -5, 20, 20)
    out = enhancer.upscale_roi(small_frame, bbox)
    assert out.shape == small_frame.shape


# ---------------------------------------------------------------------------
# upscale_roi — error handling
# ---------------------------------------------------------------------------

def test_upscale_roi_raises_on_empty_frame(enhancer):
    with pytest.raises(ValueError, match="empty frame"):
        enhancer.upscale_roi(np.array([]), (0, 0, 10, 10))


# ---------------------------------------------------------------------------
# scale attribute
# ---------------------------------------------------------------------------

def test_custom_scale_stored(small_frame):
    e = Enhancer(model_path="nonexistent.pth", scale=2)
    assert e.scale == 2


def test_default_scale_is_four():
    e = Enhancer(model_path="nonexistent.pth")
    assert e.scale == 4
