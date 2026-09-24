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
    """Enhancer with no model path - always uses bicubic fallback."""
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
    Instantiating with the default path should never raise - it should
    either load the model (if weights exist) or fall back gracefully.

    backend is "realesrgan-<device>" (e.g. "realesrgan-cuda", "realesrgan-cpu")
    when the model actually loaded, never bare "realesrgan" - that bare form
    would mean the honesty check in pipeline.py silently regressed to
    ignoring the device suffix. On a machine with weights present and a
    working basicsr/torchvision install (see
    enhancer._ensure_torchvision_functional_tensor_shim) this really does
    load, so "always falls back to bicubic in tests" is not a safe
    assumption to bake in here.
    """
    e = Enhancer()
    assert e.backend == "bicubic" or e.backend.startswith("realesrgan-")


# ---------------------------------------------------------------------------
# upscale_frame - output shape
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
# upscale_frame - error handling
# ---------------------------------------------------------------------------

def test_upscale_frame_raises_on_empty_array(enhancer):
    with pytest.raises(ValueError, match="empty frame"):
        enhancer.upscale_frame(np.array([]))


# ---------------------------------------------------------------------------
# upscale_roi - output shape equals input shape
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
# upscale_roi - error handling
# ---------------------------------------------------------------------------

def test_upscale_roi_raises_on_empty_frame(enhancer):
    with pytest.raises(ValueError, match="empty frame"):
        enhancer.upscale_roi(np.array([]), (0, 0, 10, 10))


# ---------------------------------------------------------------------------
# 6-model registry (ESPCN/FSRCNN/EDSR/LapSRN via cv2.dnn_superres,
# RealESRGAN/RealESRNet via basicsr RRDBNet) - added 2026-09-24 when these
# were given real code after being briefly offered with none at all.
# ---------------------------------------------------------------------------

from src.enhancement.enhancer import ALL_MODEL_IDS, _nearest_supported_scale  # noqa: E402


def test_all_model_ids_matches_gui_dropdown():
    """Keeps enhancer.py's registry and gui/state.py's _VALID_MODELS from
    silently drifting apart - a model missing from either side would make
    the GUI offer something the backend rejects, or accept something the
    GUI never lets you pick."""
    try:
        from src.gui.state import _VALID_MODELS
    except ModuleNotFoundError:
        from gui.state import _VALID_MODELS  # pragma: no cover - import path shim
    assert ALL_MODEL_IDS == _VALID_MODELS


def test_nearest_supported_scale_exact_match():
    assert _nearest_supported_scale("espcn", 3) == 3
    assert _nearest_supported_scale("edsr", 2) == 2


def test_nearest_supported_scale_snaps_lapsrn_x3_to_something_it_ships():
    """LapSRN's real weights are only x2/x4/x8 - there is no x3 file, so a
    scale=3 request must snap to whichever of those is closest rather than
    trying (and failing) to read a LapSRN_x3.pb that doesn't exist."""
    snapped = _nearest_supported_scale("lapsrn", 3)
    assert snapped in (2, 4)


def test_unrecognised_model_falls_back_to_bicubic():
    e = Enhancer(model="not_a_real_model")
    assert e.backend == "bicubic"
    assert e.model_id == "bicubic"


def test_bicubic_explicit_never_loads_a_model_even_if_weights_exist():
    """The explicit 'bicubic' choice must skip model loading entirely, not
    just prefer bicubic - this is the exact bug class that made the old
    dropdown dishonest (a model silently running despite being told not to)."""
    e = Enhancer(model="realesrgan", use_nn=False)
    assert e.backend == "bicubic"


@pytest.mark.parametrize("model_id,algo", [
    ("espcn", "espcn"),
    ("fsrcnn", "fsrcnn"),
    ("edsr", "edsr"),
    ("lapsrn", "lapsrn"),
])
def test_dnn_superres_model_loads_and_upscales_when_weights_present(model_id, algo, small_frame):
    """Live-loads the real weights file when present on this machine (CI
    without the weights present still passes: absence is exactly the
    documented bicubic-fallback path, already covered above)."""
    e = Enhancer(model=model_id, scale=4)
    if e.backend == "bicubic":
        pytest.skip(f"{model_id} weights not present in models/ on this machine")
    assert e.backend.startswith(f"{model_id}-")
    out = e.upscale_frame(small_frame)
    assert out.shape[0] > small_frame.shape[0]
    assert out.shape[1] > small_frame.shape[1]
    assert out.dtype == np.uint8


def test_realesrnet_loads_and_upscales_when_weights_present(small_frame):
    e = Enhancer(model="realesrnet", scale=4)
    if e.backend == "bicubic":
        pytest.skip("RealESRNet_x4plus.pth not present in models/ on this machine")
    assert e.backend.startswith("realesrnet-")
    out = e.upscale_frame(small_frame)
    assert out.shape == (small_frame.shape[0] * 4, small_frame.shape[1] * 4, 3)


# ---------------------------------------------------------------------------
# scale attribute
# ---------------------------------------------------------------------------

def test_custom_scale_stored(small_frame):
    e = Enhancer(model_path="nonexistent.pth", scale=2)
    assert e.scale == 2