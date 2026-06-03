"""
tests/test_enhancement_benchmark.py

Validates ``src/enhancement/enhancement_benchmark.py``. Strategy:

* Test the pure metric helpers (sharpness, PSNR, SSIM) with synthetic
  images of known characteristics - a flat block has near-zero Laplacian
  variance, identical inputs give max PSNR, etc.
* Test the variant production (full-frame SR vs ROI-only SR) with a
  stub Enhancer so we don't need Real-ESRGAN weights in CI.
* Test the segment-level walk on a synthetic .mp4 with a stub Enhancer
  and confirm the returned ``BenchmarkResult`` shape, deltas, and
  verdict logic are correct.

Author: Bloodawn (KheivenD)
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

# Make sure src/ is importable
SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from enhancement.enhancement_benchmark import (  # noqa: E402
    BenchmarkResult,
    VariantMetrics,
    _bicubic_upscale,
    _full_frame_sr_then_crop,
    _roi_only_sr,
    _safe_crop,
    _verdict,
    benchmark_enhancement,
    measure_psnr,
    measure_sharpness,
    measure_ssim,
)


# ---------------------------------------------------------------------------
# Stub Enhancer used by the segment-walk tests
# ---------------------------------------------------------------------------


class _SharpenStubEnhancer:
    """Enhancer stand-in: bicubic upscale, then a mild sharpen.

    Exists so we can exercise the comparison logic without pulling in the
    real Real-ESRGAN. We pick a sharpen kernel that yields detectably more
    Laplacian variance than plain bicubic, but doesn't introduce wild
    hallucinations - exactly what the benchmark is supposed to detect.

    Author: Bloodawn (KheivenD)
    """

    backend = "stub-sharpen"
    _KERNEL = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)

    def upscale_frame(self, frame: np.ndarray, scale: int = 4) -> np.ndarray:
        h, w = frame.shape[:2]
        big = cv2.resize(frame, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
        return cv2.filter2D(big, -1, self._KERNEL)


def _write_synthetic_video(path: Path, n_frames: int = 30, w: int = 320, h: int = 180) -> None:
    """Synthesise an .mp4 with text + a moving gradient.

    The text is what gives Laplacian variance something to bite on. The
    moving gradient is just to keep the video non-static.
    """
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, 15.0, (w, h))
    try:
        for i in range(n_frames):
            frame = np.full((h, w, 3), (i * 5) % 256, dtype=np.uint8)
            # Hard high-frequency edges so sharpness numbers are non-trivial
            cv2.putText(frame, "PLATE", (40 + i, 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
            cv2.rectangle(frame, (30, 50), (260, 110), (0, 0, 0), 2)
            writer.write(frame)
    finally:
        writer.release()


# ---------------------------------------------------------------------------
# Pure metric helpers
# ---------------------------------------------------------------------------


class TestMeasureSharpness:
    def test_zero_for_empty_input(self):
        assert measure_sharpness(np.zeros((0, 0, 3), dtype=np.uint8)) == 0.0
        assert measure_sharpness(None) == 0.0  # type: ignore[arg-type]

    def test_zero_for_flat_block(self):
        flat = np.full((40, 40, 3), 128, dtype=np.uint8)
        # Tiny floating noise from cv2.Laplacian is OK; threshold below 1.
        assert measure_sharpness(flat) < 1.0

    def test_high_for_edge_image(self):
        edge = np.zeros((40, 40, 3), dtype=np.uint8)
        edge[:, 20:, :] = 255  # vertical step edge
        assert measure_sharpness(edge) > 100  # large Laplacian variance


class TestMeasurePsnr:
    def test_identical_images_score_max(self):
        img = np.random.randint(0, 255, (32, 32, 3), dtype=np.uint8)
        assert measure_psnr(img, img) == pytest.approx(100.0)

    def test_shape_mismatch_returns_none(self):
        a = np.zeros((10, 10, 3), dtype=np.uint8)
        b = np.zeros((20, 20, 3), dtype=np.uint8)
        assert measure_psnr(a, b) is None

    def test_noisy_image_lowers_psnr(self):
        ref = np.full((32, 32, 3), 128, dtype=np.uint8)
        noisy = ref + np.random.randint(-30, 30, ref.shape, dtype=np.int16)
        noisy = np.clip(noisy, 0, 255).astype(np.uint8)
        psnr = measure_psnr(ref, noisy)
        # Noise is loud enough that PSNR should land between 10 and 30 dB.
        assert psnr is not None
        assert 10 < psnr < 30


class TestMeasureSsim:
    def test_identical_images_score_one(self):
        img = np.full((40, 40, 3), 128, dtype=np.uint8) + \
              np.random.randint(0, 5, (40, 40, 3), dtype=np.uint8)
        ssim = measure_ssim(img, img)
        assert ssim == pytest.approx(1.0, abs=1e-6)

    def test_shape_mismatch_returns_none(self):
        a = np.zeros((10, 10, 3), dtype=np.uint8)
        b = np.zeros((20, 20, 3), dtype=np.uint8)
        assert measure_ssim(a, b) is None


# ---------------------------------------------------------------------------
# Variant production helpers
# ---------------------------------------------------------------------------


class TestVariantHelpers:
    def test_safe_crop_clamps_bbox(self):
        frame = np.zeros((50, 50, 3), dtype=np.uint8)
        crop = _safe_crop(frame, (-10, -10, 100, 100))
        assert crop.shape == (50, 50, 3)

    def test_safe_crop_returns_minimal_for_zero_box(self):
        frame = np.zeros((50, 50, 3), dtype=np.uint8)
        crop = _safe_crop(frame, (10, 10, 0, 0))
        assert crop.shape == (1, 1, 3)

    def test_full_frame_sr_then_crop_preserves_scaled_size(self):
        frame = np.full((40, 40, 3), 100, dtype=np.uint8)
        out = _full_frame_sr_then_crop(frame, (5, 5, 10, 10), _SharpenStubEnhancer(), scale=4)
        # ROI is 10x10 at 4x → 40x40
        assert out.shape == (40, 40, 3)

    def test_roi_only_sr_preserves_scaled_size(self):
        frame = np.full((40, 40, 3), 100, dtype=np.uint8)
        out = _roi_only_sr(frame, (5, 5, 10, 10), _SharpenStubEnhancer(), scale=4)
        assert out.shape == (40, 40, 3)

    def test_bicubic_upscale_doubles_dimensions(self):
        frame = np.zeros((20, 30, 3), dtype=np.uint8)
        out = _bicubic_upscale(frame, scale=4)
        assert out.shape == (80, 120, 3)


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------


class TestVerdict:
    def test_minimal_gain_calls_out_no_help(self):
        v = _verdict({"roi_sharpness_gain_full_sr_pct": 2.0,
                      "roi_sharpness_gain_roi_sr_pct": 1.5})
        assert "minimal" in v.lower()

    def test_roi_matches_full_recommends_roi_only(self):
        v = _verdict({"roi_sharpness_gain_full_sr_pct": 25.0,
                      "roi_sharpness_gain_roi_sr_pct": 24.0,
                      "ocr_confidence_gain_full_sr": 0.10,
                      "ocr_confidence_gain_roi_sr": 0.10})
        assert "ROI-only" in v and "speedup" in v.lower()

    def test_full_much_sharper_recommends_full(self):
        v = _verdict({"roi_sharpness_gain_full_sr_pct": 40.0,
                      "roi_sharpness_gain_roi_sr_pct": 15.0})
        assert "full-frame" in v.lower()


# ---------------------------------------------------------------------------
# End-to-end segment benchmark
# ---------------------------------------------------------------------------


class TestBenchmarkEnhancement:
    def test_missing_file_returns_warning(self, tmp_path):
        res = benchmark_enhancement(tmp_path / "no.mp4", roi_box=(0, 0, 10, 10))
        assert isinstance(res, BenchmarkResult)
        assert res.frames_examined == 0
        assert any("not found" in w.lower() for w in res.warnings)

    def test_walks_synthetic_clip_and_returns_metrics(self, tmp_path):
        clip = tmp_path / "synth.mp4"
        _write_synthetic_video(clip, n_frames=18, w=320, h=180)

        res = benchmark_enhancement(
            clip,
            roi_box=(20, 50, 240, 70),       # box that contains "PLATE"
            enhancer=_SharpenStubEnhancer(),
            sample_every_n_frames=2,
            max_frames=6,
        )

        assert res.frames_examined > 0
        assert res.roi_box == (20, 50, 240, 70)

        for key in ("no_enhancement", "full_frame_sr", "roi_only_sr"):
            assert key in res.variants
            assert isinstance(res.variants[key], VariantMetrics)
            assert res.variants[key].avg_sharpness_roi >= 0

        # The sharpen stub yields measurably higher Laplacian variance
        # than bicubic baseline. Both SR variants should beat baseline.
        base = res.variants["no_enhancement"].avg_sharpness_roi
        assert res.variants["full_frame_sr"].avg_sharpness_roi > base
        assert res.variants["roi_only_sr"].avg_sharpness_roi > base

    def test_deltas_are_populated_and_signed(self, tmp_path):
        clip = tmp_path / "synth.mp4"
        _write_synthetic_video(clip, n_frames=10, w=320, h=180)

        res = benchmark_enhancement(
            clip, roi_box=(20, 50, 240, 70),
            enhancer=_SharpenStubEnhancer(),
            sample_every_n_frames=2, max_frames=4,
        )
        assert "roi_sharpness_gain_full_sr_pct" in res.deltas
        assert "roi_sharpness_gain_roi_sr_pct" in res.deltas
        # Both must be > 0 with the sharpen stub.
        assert res.deltas["roi_sharpness_gain_full_sr_pct"] > 0
        assert res.deltas["roi_sharpness_gain_roi_sr_pct"] > 0

    def test_verdict_string_is_present(self, tmp_path):
        clip = tmp_path / "synth.mp4"
        _write_synthetic_video(clip, n_frames=10, w=320, h=180)

        res = benchmark_enhancement(
            clip, roi_box=(20, 50, 240, 70),
            enhancer=_SharpenStubEnhancer(),
            sample_every_n_frames=2, max_frames=4,
        )
        assert isinstance(res.verdict, str) and res.verdict

    def test_to_dict_is_jsonable(self, tmp_path):
        clip = tmp_path / "synth.mp4"
        _write_synthetic_video(clip, n_frames=8, w=320, h=180)

        res = benchmark_enhancement(
            clip, roi_box=(20, 50, 240, 70),
            enhancer=_SharpenStubEnhancer(),
            sample_every_n_frames=2, max_frames=3,
        )
        d = res.to_dict()
        # Round-trip via JSON to confirm Flask can serialise it.
        import json
        s = json.dumps(d)
        assert "variants" in s and "deltas" in s and "verdict" in s

    def test_no_enhancer_falls_back_to_bicubic(self, tmp_path):
        """When the Enhancer is unavailable, all SR variants degrade to
        bicubic, so the deltas should be ~0 and the verdict should call
        out the lack of gain."""
        clip = tmp_path / "synth.mp4"
        _write_synthetic_video(clip, n_frames=8, w=320, h=180)

        res = benchmark_enhancement(
            clip, roi_box=(20, 50, 240, 70),
            enhancer=None,                  # force bicubic everywhere
            sample_every_n_frames=2, max_frames=3,
            sr_scale=2,                     # smaller scale just for speed
        )
        # With bicubic on all three variants, deltas hover near zero.
        assert abs(res.deltas["roi_sharpness_gain_full_sr_pct"]) < 5
        assert abs(res.deltas["roi_sharpness_gain_roi_sr_pct"]) < 5
        # And the verdict should explicitly say "minimal".
        assert "minimal" in res.verdict.lower()
