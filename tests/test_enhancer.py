"""
tests/test_enhancer.py

Unit tests for src/enhancement/enhancer.py.

These tests are designed to run WITHOUT any model weight files or the
realesrgan/basicsr packages installed.  Every test that exercises inference
(upscale_frame, upscale_roi, enhance_batch) uses unittest.mock to inject a fake
backend so the test suite never requires GPU or large model downloads in CI.

Tests that validate error-handling paths (bad bbox, empty batch, etc.) run
against a real Enhancer instance with no model loaded — those code paths fire
before any model call, so no mocking is needed.

Author: Bloodawn (KheivenD)
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Ensure src/ is on the path when running from the project root.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from enhancement.enhancer import Enhancer


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_frame(h=64, w=64, fill=128):
    """Return a solid-color BGR uint8 frame."""
    return np.full((h, w, 3), fill, dtype=np.uint8)


def _make_enhancer_with_mock_dnnsuperres(scale=4):
    """
    Return an Enhancer instance whose dnn_superres backend is mocked.
    The mock sr.upsample() returns an upscaled frame filled with the value 200.
    """
    enhancer = Enhancer.__new__(Enhancer)
    enhancer.scale = scale
    enhancer.model = "espcn"
    enhancer.device = "cpu"
    enhancer.models_dir = Path("/nonexistent")
    enhancer._backend = "dnnsuperres"
    enhancer._available = True
    enhancer._realesrgan_upsampler = None

    mock_sr = MagicMock()
    def fake_upsample(frame):
        h, w = frame.shape[:2]
        return np.full((h * scale, w * scale, 3), 200, dtype=np.uint8)
    mock_sr.upsample.side_effect = fake_upsample
    enhancer._sr = mock_sr

    return enhancer


# ─── Initialization and availability ──────────────────────────────────────────

class TestEnhancerInit:
    def test_default_init_does_not_raise(self):
        e = Enhancer()
        assert e is not None

    def test_is_available_false_when_no_weights(self):
        e = Enhancer(scale=4, model="espcn", models_dir="/nonexistent/path")
        assert e.is_available() is False

    def test_repr_shows_available_false(self):
        e = Enhancer(scale=4, model="espcn", models_dir="/nonexistent/path")
        r = repr(e)
        assert "available=False" in r
        assert "espcn" in r

    def test_repr_shows_backend_empty_when_not_loaded(self):
        e = Enhancer(scale=4, model="espcn", models_dir="/nonexistent/path")
        assert "backend=''" in repr(e)

    def test_unknown_model_name_does_not_crash(self):
        e = Enhancer(model="this_model_does_not_exist")
        assert e.is_available() is False

    def test_scale_stored_correctly(self):
        e = Enhancer(scale=2, model="espcn", models_dir="/nonexistent")
        assert e.scale == 2

    def test_device_stored_correctly(self):
        e = Enhancer(scale=4, model="espcn", device="cpu", models_dir="/nonexistent")
        assert e.device == "cpu"


# ─── Error paths — no model needed ────────────────────────────────────────────

class TestUpscaleRoiBoundsCheck:
    """upscale_roi bounds validation fires before the availability check."""

    def setup_method(self):
        self.frame = _make_frame(100, 100)
        self.e_unavail = Enhancer(scale=4, model="espcn", models_dir="/nonexistent")

    def test_negative_x_raises_value_error(self):
        with pytest.raises(ValueError, match="out of bounds"):
            self.e_unavail.upscale_roi(self.frame, bbox=(-1, 0, 10, 10))

    def test_negative_y_raises_value_error(self):
        with pytest.raises(ValueError, match="out of bounds"):
            self.e_unavail.upscale_roi(self.frame, bbox=(0, -1, 10, 10))

    def test_bbox_extends_past_right_edge_raises(self):
        with pytest.raises(ValueError, match="out of bounds"):
            self.e_unavail.upscale_roi(self.frame, bbox=(95, 0, 10, 10))

    def test_bbox_extends_past_bottom_edge_raises(self):
        with pytest.raises(ValueError, match="out of bounds"):
            self.e_unavail.upscale_roi(self.frame, bbox=(0, 95, 10, 10))

    def test_zero_width_raises_value_error(self):
        with pytest.raises(ValueError):
            self.e_unavail.upscale_roi(self.frame, bbox=(0, 0, 0, 10))

    def test_zero_height_raises_value_error(self):
        with pytest.raises(ValueError):
            self.e_unavail.upscale_roi(self.frame, bbox=(0, 0, 10, 0))

    def test_exact_frame_size_bbox_is_valid_but_unavailable(self):
        """A bbox exactly equal to frame size is in-bounds — error is RuntimeError, not ValueError."""
        with pytest.raises(RuntimeError, match="not available"):
            self.e_unavail.upscale_roi(self.frame, bbox=(0, 0, 100, 100))


class TestRuntimeErrorWhenUnavailable:
    def setup_method(self):
        self.e = Enhancer(scale=4, model="espcn", models_dir="/nonexistent")
        self.frame = _make_frame()

    def test_upscale_frame_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="not available"):
            self.e.upscale_frame(self.frame)

    def test_enhance_batch_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="not available"):
            self.e.enhance_batch([self.frame])


class TestEnhanceBatchValidation:
    def setup_method(self):
        self.e = Enhancer(scale=4, model="espcn", models_dir="/nonexistent")

    def test_empty_list_raises_value_error(self):
        with pytest.raises(ValueError, match="empty"):
            self.e.enhance_batch([])

    def test_inconsistent_shapes_raises_value_error(self):
        f1 = _make_frame(64, 64)
        f2 = _make_frame(128, 128)
        with pytest.raises(ValueError, match="same shape"):
            self.e.enhance_batch([f1, f2])


class TestFrameValidation:
    def setup_method(self):
        self.e = _make_enhancer_with_mock_dnnsuperres()

    def test_non_numpy_raises_value_error(self):
        with pytest.raises(ValueError):
            self.e.upscale_frame([[1, 2, 3]])

    def test_2d_array_raises_value_error(self):
        with pytest.raises(ValueError):
            self.e.upscale_frame(np.zeros((64, 64), dtype=np.uint8))

    def test_wrong_channel_count_raises_value_error(self):
        with pytest.raises(ValueError):
            self.e.upscale_frame(np.zeros((64, 64, 1), dtype=np.uint8))


# ─── Functional tests (mocked backend) ────────────────────────────────────────

class TestUpscaleFrameMocked:
    def setup_method(self):
        self.scale = 4
        self.e = _make_enhancer_with_mock_dnnsuperres(scale=self.scale)

    def test_is_available_true(self):
        assert self.e.is_available() is True

    def test_output_dimensions_are_scaled(self):
        frame = _make_frame(32, 48)
        result = self.e.upscale_frame(frame)
        assert result.shape == (32 * self.scale, 48 * self.scale, 3)

    def test_output_dtype_is_uint8(self):
        result = self.e.upscale_frame(_make_frame())
        assert result.dtype == np.uint8

    def test_output_is_not_input(self):
        frame = _make_frame()
        result = self.e.upscale_frame(frame)
        assert result is not frame

    def test_float32_frame_is_coerced_to_uint8(self):
        frame = np.full((32, 32, 3), 200.0, dtype=np.float32)
        result = self.e.upscale_frame(frame)
        assert result.dtype == np.uint8

    def test_sr_upsample_called_once(self):
        self.e.upscale_frame(_make_frame())
        assert self.e._sr.upsample.call_count == 1


class TestUpscaleRoiMocked:
    def setup_method(self):
        self.scale = 4
        self.e = _make_enhancer_with_mock_dnnsuperres(scale=self.scale)

    def test_output_has_same_shape_as_input(self):
        frame = _make_frame(100, 100)
        result = self.e.upscale_roi(frame, bbox=(10, 10, 30, 30))
        assert result.shape == frame.shape

    def test_roi_region_is_changed(self):
        """The ROI region in the output should differ from the original fill."""
        frame = _make_frame(100, 100, fill=50)  # dark frame
        result = self.e.upscale_roi(frame, bbox=(10, 10, 30, 30))
        # Mock returns 200 in the upscaled region, which gets pasted back
        roi_region = result[10:40, 10:40]
        original_region = frame[10:40, 10:40]
        assert not np.array_equal(roi_region, original_region)

    def test_non_roi_region_is_unchanged(self):
        """Pixels outside the bbox must not be touched."""
        frame = _make_frame(100, 100, fill=50)
        result = self.e.upscale_roi(frame, bbox=(10, 10, 30, 30))
        # Top-left corner (outside bbox) should be unchanged
        assert np.array_equal(result[0:5, 0:5], frame[0:5, 0:5])

    def test_full_frame_bbox_runs_without_error(self):
        frame = _make_frame(64, 64)
        result = self.e.upscale_roi(frame, bbox=(0, 0, 64, 64))
        assert result.shape == frame.shape

    def test_single_pixel_bbox(self):
        frame = _make_frame(64, 64)
        result = self.e.upscale_roi(frame, bbox=(32, 32, 1, 1))
        assert result.shape == frame.shape


class TestEnhanceBatchMocked:
    def setup_method(self):
        self.scale = 4
        self.e = _make_enhancer_with_mock_dnnsuperres(scale=self.scale)

    def test_batch_returns_correct_count(self):
        frames = [_make_frame() for _ in range(5)]
        results = self.e.enhance_batch(frames)
        assert len(results) == 5

    def test_batch_output_dimensions(self):
        frames = [_make_frame(32, 48) for _ in range(3)]
        results = self.e.enhance_batch(frames)
        for r in results:
            assert r.shape == (32 * self.scale, 48 * self.scale, 3)

    def test_single_frame_batch(self):
        results = self.e.enhance_batch([_make_frame()])
        assert len(results) == 1

    def test_upsample_called_once_per_frame(self):
        n = 7
        self.e.enhance_batch([_make_frame() for _ in range(n)])
        assert self.e._sr.upsample.call_count == n


# ─── Repr ─────────────────────────────────────────────────────────────────────

class TestRepr:
    def test_repr_shows_model_name(self):
        e = Enhancer(scale=4, model="fsrcnn", models_dir="/nonexistent")
        assert "fsrcnn" in repr(e)

    def test_repr_shows_scale(self):
        e = Enhancer(scale=2, model="espcn", models_dir="/nonexistent")
        assert "scale=2" in repr(e)

    def test_repr_for_available_enhancer(self):
        e = _make_enhancer_with_mock_dnnsuperres()
        assert "available=True" in repr(e)
        assert "dnnsuperres" in repr(e)
