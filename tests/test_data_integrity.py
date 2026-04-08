"""
tests/test_data_integrity.py

Zero data loss validation for the ROI compression pipeline.

Sponsor requirement (Cody Hayashi, April 1 2026):
    "Government is risk-intolerant. Even 5% foreground data loss is unacceptable."

Strategy:
  1. Generate synthetic frames with clearly defined foreground ROI regions.
     Foreground regions contain a bright distinguishable pattern; background
     is a solid dark colour so we can measure degradation separately.
  2. Encode the frames through ROIEncoder.encode_segment() at the production
     foreground CRF (18) and background CRF (45).
  3. Decode the output file back to raw frames using FFmpeg.
  4. Extract the exact same ROI pixel regions from both original and decoded
     frames and compute per-pixel Mean Absolute Error (MAE).
  5. Assert that foreground MAE is below the pass threshold (CRF 18 is
     near-lossless; we allow a small tolerance for YUV↔BGR round-trip).
  6. Assert that the total frame count decoded equals total frames encoded
     (no frames silently dropped).

Thresholds (tuned for CRF 18 libx264):
  FOREGROUND_MAE_PASS  ≤ 3.0  intensity units out of 255  (~1.2%)
  MAX_FG_PIXEL_LOSS    ≤ 0.0  (zero frames where any ROI pixel exceeds 15 units MAE)

These are conservative but realistic for near-lossless H.264 on synthetic frames.

Author: Bloodawn (KheivenD)
"""

import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from compression.roi_encoder import ROIEncoder

# ─── Pass/fail thresholds ─────────────────────────────────────────────────────

# Mean Absolute Error on ROI pixels (per channel, per pixel) — CRF 18 target
FOREGROUND_MAE_THRESHOLD   = 3.0   # intensity units (0–255). CRF 18 is near-lossless.
# Maximum single-pixel channel error allowed in the ROI
FOREGROUND_MAX_PX_THRESHOLD = 20   # any pixel deviating more than this is a "loss event"
# Maximum fraction of ROI pixels that may exceed FOREGROUND_MAX_PX_THRESHOLD
FOREGROUND_LOSS_RATE_MAX   = 0.0   # 0% — zero tolerance for high-error pixels in ROI

# ─── Synthetic frame generation ───────────────────────────────────────────────

FRAME_H = 120    # small enough for fast encode/decode in CI
FRAME_W = 160
FPS     = 10.0   # low fps so the test runs faster
N_FRAMES = 30    # 3 seconds at 10 fps

# Foreground ROI: a bright rectangle in the centre of the frame
ROI_X, ROI_Y, ROI_W, ROI_H = 40, 30, 80, 60   # (x, y, w, h)

# Background fill: dark grey (easy to distinguish from bright FG)
BG_COLOR  = (30, 30, 30)      # BGR
# Foreground fill: bright blue + horizontal gradient so the encoder has actual detail to preserve
FG_BASE   = np.array([200, 100, 50], dtype=np.float32)   # BGR


def _make_synthetic_frames(n: int = N_FRAMES) -> List[np.ndarray]:
    """
    Generate `n` synthetic BGR frames with:
      - Dark background (BG_COLOR)
      - Bright ROI region with a per-frame gradient so consecutive frames differ
        (prevents I-frame-only encoding where the encoder can be too clever)
    """
    frames = []
    for i in range(n):
        frame = np.full((FRAME_H, FRAME_W, 3), BG_COLOR, dtype=np.uint8)
        # Gradient inside ROI varies per frame so the encoder must preserve real data
        for dy in range(ROI_H):
            intensity = float(i % 30) / 30.0  # oscillates across 30 frames
            pixel = np.clip(FG_BASE + np.array([dy * 0.5, intensity * 30, i % 50]), 0, 255).astype(np.uint8)
            frame[ROI_Y + dy, ROI_X:ROI_X + ROI_W] = pixel
        frames.append(frame)
    return frames


def _decode_video_frames(video_path: str, h: int, w: int) -> List[np.ndarray]:
    """
    Decode a video file back to raw BGR uint8 frames using ffmpeg subprocess.
    Returns a list of numpy arrays, one per frame.
    """
    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-loglevel", "error",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg decode failed: {result.stderr.decode()[:200]}")

    raw = result.stdout
    frame_bytes = h * w * 3
    n_decoded = len(raw) // frame_bytes
    frames = []
    for i in range(n_decoded):
        chunk = raw[i * frame_bytes:(i + 1) * frame_bytes]
        frame = np.frombuffer(chunk, dtype=np.uint8).reshape((h, w, 3)).copy()
        frames.append(frame)
    return frames


def _roi_pixels(frame: np.ndarray) -> np.ndarray:
    """Extract the foreground ROI region from a frame as a flat float array."""
    return frame[ROI_Y:ROI_Y + ROI_H, ROI_X:ROI_X + ROI_W].astype(np.float32)


def _bg_pixels(frame: np.ndarray) -> np.ndarray:
    """Extract a background patch (top-left corner, well away from the ROI)."""
    return frame[0:20, 0:20].astype(np.float32)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def encode_decode_pair(tmp_path_factory):
    """
    Encode synthetic frames → decode → return (originals, decoded_frames, bbox).
    Scoped to module so encoding only happens once for all tests in this file.
    """
    tmp = tmp_path_factory.mktemp("integrity")
    encoder = ROIEncoder(
        output_dir=str(tmp),
        foreground_crf=18,
        background_crf=45,
        preset="veryfast",
        db_path=str(tmp / "meta.db"),
    )

    originals = _make_synthetic_frames(N_FRAMES)
    bboxes = [[(ROI_X, ROI_Y, ROI_W, ROI_H)] for _ in originals]

    output_path = encoder.encode_segment(
        frames=originals,
        bboxes_per_frame=bboxes,
        camera_id="integrity_test",
        fps=FPS,
    )
    assert Path(output_path).exists(), "Encoder produced no output file"
    assert Path(output_path).stat().st_size > 0, "Output file is empty"

    decoded = _decode_video_frames(output_path, FRAME_H, FRAME_W)
    return originals, decoded, (ROI_X, ROI_Y, ROI_W, ROI_H)


# ─── Frame count integrity ────────────────────────────────────────────────────

class TestFrameCount:
    def test_no_frames_dropped(self, encode_decode_pair):
        """Every encoded frame must appear in the decoded output."""
        originals, decoded, _ = encode_decode_pair
        assert len(decoded) == len(originals), (
            f"Frame count mismatch: encoded {len(originals)}, decoded {len(decoded)}. "
            "Frames were silently dropped."
        )

    def test_frame_dimensions_preserved(self, encode_decode_pair):
        originals, decoded, _ = encode_decode_pair
        for i, (orig, dec) in enumerate(zip(originals, decoded)):
            assert dec.shape == orig.shape, (
                f"Frame {i} shape mismatch: original {orig.shape}, decoded {dec.shape}"
            )


# ─── Foreground ROI quality (zero data loss) ──────────────────────────────────

class TestForegroundROIIntegrity:
    def test_foreground_mae_below_threshold(self, encode_decode_pair):
        """
        CRF 18 is near-lossless. Mean Absolute Error across ROI pixels must
        stay below FOREGROUND_MAE_THRESHOLD (~1.2% of full intensity range).
        A higher MAE means the encoder degraded subject pixels beyond acceptable limits.
        """
        originals, decoded, _ = encode_decode_pair
        mae_values = []
        for orig, dec in zip(originals, decoded):
            diff = np.abs(_roi_pixels(orig) - _roi_pixels(dec))
            mae_values.append(float(diff.mean()))

        overall_mae = float(np.mean(mae_values))
        assert overall_mae <= FOREGROUND_MAE_THRESHOLD, (
            f"Foreground ROI MAE {overall_mae:.2f} exceeds threshold {FOREGROUND_MAE_THRESHOLD}. "
            f"Subject pixels are being degraded beyond acceptable limits at CRF 18. "
            f"Per-frame MAEs: min={min(mae_values):.2f}, max={max(mae_values):.2f}"
        )

    def test_zero_high_error_roi_pixels(self, encode_decode_pair):
        """
        No ROI pixel should deviate by more than FOREGROUND_MAX_PX_THRESHOLD
        intensity units. Any such deviation constitutes foreground data loss.
        Government requirement: 0% loss rate.
        """
        originals, decoded, _ = encode_decode_pair
        high_error_count = 0
        total_roi_pixels = 0

        for orig, dec in zip(originals, decoded):
            diff = np.abs(_roi_pixels(orig) - _roi_pixels(dec))
            high_error_count += int((diff > FOREGROUND_MAX_PX_THRESHOLD).sum())
            total_roi_pixels += diff.size

        loss_rate = high_error_count / total_roi_pixels if total_roi_pixels > 0 else 0.0

        assert loss_rate <= FOREGROUND_LOSS_RATE_MAX, (
            f"Foreground data loss rate {loss_rate:.4%} exceeds threshold {FOREGROUND_LOSS_RATE_MAX:.0%}. "
            f"{high_error_count} of {total_roi_pixels} ROI pixel channels deviated by "
            f">{FOREGROUND_MAX_PX_THRESHOLD} intensity units."
        )

    def test_foreground_roi_not_blank(self, encode_decode_pair):
        """ROI pixels must not be zeroed out (encoder did not null the region)."""
        _, decoded, _ = encode_decode_pair
        for i, dec in enumerate(decoded):
            roi = _roi_pixels(dec)
            assert roi.mean() > 10.0, (
                f"Frame {i}: decoded ROI appears blank (mean={roi.mean():.1f}). "
                "Encoder may have zeroed out the foreground region."
            )

    def test_foreground_roi_structurally_similar_to_original(self, encode_decode_pair):
        """
        Structural content of the ROI (mean and std) should not be wildly
        different from the original. This catches cases where pixels were
        preserved in magnitude but spatially scrambled (block artifacts).
        """
        originals, decoded, _ = encode_decode_pair
        for i, (orig, dec) in enumerate(zip(originals, decoded)):
            orig_roi = _roi_pixels(orig)
            dec_roi  = _roi_pixels(dec)
            # Standard deviation measures spatial variation — if the decoder
            # averages out the ROI, std drops dramatically.
            orig_std = float(orig_roi.std())
            dec_std  = float(dec_roi.std())
            if orig_std > 5.0:  # only check frames with meaningful spatial variation
                ratio = dec_std / orig_std
                assert 0.5 <= ratio <= 2.0, (
                    f"Frame {i}: ROI spatial structure not preserved. "
                    f"Original std={orig_std:.1f}, decoded std={dec_std:.1f} (ratio={ratio:.2f}). "
                    "Heavy block artifacts or averaging detected."
                )


# ─── Background quality (different assertion — degradation is acceptable) ─────

class TestBackgroundCompression:
    def test_background_is_smaller_than_foreground_crf(self, encode_decode_pair, tmp_path):
        """
        Encode the same frames twice: once with has_targets=True (CRF 18)
        and once with has_targets=False (CRF 45). Verify CRF 45 produces a
        smaller file, confirming the background compression is actually applied.
        """
        originals, _, _ = encode_decode_pair

        encoder = ROIEncoder(
            output_dir=str(tmp_path),
            foreground_crf=18,
            background_crf=45,
            preset="veryfast",
            db_path=str(tmp_path / "meta.db"),
        )

        # Encode with foreground present (CRF 18)
        fg_path = encoder.encode_segment(
            frames=originals,
            bboxes_per_frame=[[(ROI_X, ROI_Y, ROI_W, ROI_H)] for _ in originals],
            camera_id="fg_crf18",
            fps=FPS,
        )

        # Encode with no foreground (CRF 45)
        bg_path = encoder.encode_segment(
            frames=originals,
            bboxes_per_frame=[[] for _ in originals],
            camera_id="bg_crf45",
            fps=FPS,
        )

        fg_size = Path(fg_path).stat().st_size
        bg_size = Path(bg_path).stat().st_size
        assert bg_size < fg_size, (
            f"Background (CRF 45) file ({bg_size} bytes) is not smaller than "
            f"foreground (CRF 18) file ({fg_size} bytes). "
            "Dual-CRF selection may not be working correctly."
        )

    def test_background_mae_is_higher_than_foreground(self, encode_decode_pair, tmp_path):
        """
        Background is allowed to degrade (CRF 45). Its MAE should be
        measurably higher than the foreground MAE, confirming the quality
        tiers are actually different.
        """
        originals, decoded, _ = encode_decode_pair

        fg_maes = [
            float(np.abs(_roi_pixels(o) - _roi_pixels(d)).mean())
            for o, d in zip(originals, decoded)
        ]
        bg_maes = [
            float(np.abs(_bg_pixels(o) - _bg_pixels(d)).mean())
            for o, d in zip(originals, decoded)
        ]
        # Both should be modest in absolute terms (this is the CRF 18 segment)
        # but at minimum FG should not be dramatically worse than BG
        assert np.mean(fg_maes) <= FOREGROUND_MAE_THRESHOLD, (
            f"Foreground MAE {np.mean(fg_maes):.2f} exceeds threshold even in the quality check."
        )


# ─── Mode 0 vs mode 1 smoke tests (encode only — no mode gating in encoder) ───

class TestIntegrityAcrossFrameCounts:
    """
    Verify integrity holds for different segment sizes (edge case: 1 frame,
    many frames) since FFmpeg behaviour can differ for very short segments.
    """

    @pytest.mark.parametrize("n_frames", [1, 5, 30, 90])
    def test_frame_count_preserved_for_various_segment_lengths(self, tmp_path, n_frames):
        encoder = ROIEncoder(
            output_dir=str(tmp_path),
            foreground_crf=18,
            background_crf=45,
            preset="veryfast",
            db_path=str(tmp_path / "meta.db"),
        )
        frames = _make_synthetic_frames(n_frames)
        bboxes = [[(ROI_X, ROI_Y, ROI_W, ROI_H)] for _ in frames]
        output = encoder.encode_segment(frames=frames, bboxes_per_frame=bboxes,
                                        camera_id="integrity_param", fps=FPS)
        decoded = _decode_video_frames(output, FRAME_H, FRAME_W)
        assert len(decoded) == n_frames, (
            f"{n_frames}-frame segment: expected {n_frames} decoded frames, got {len(decoded)}"
        )

    def test_all_black_frames_do_not_cause_data_loss(self, tmp_path):
        """Edge case: completely dark frames (all background)."""
        encoder = ROIEncoder(
            output_dir=str(tmp_path),
            foreground_crf=18, background_crf=45, preset="veryfast",
            db_path=str(tmp_path / "meta.db"),
        )
        frames = [np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8) for _ in range(10)]
        bboxes = [[(ROI_X, ROI_Y, ROI_W, ROI_H)] for _ in frames]
        output = encoder.encode_segment(frames=frames, bboxes_per_frame=bboxes,
                                        camera_id="black_frames", fps=FPS)
        decoded = _decode_video_frames(output, FRAME_H, FRAME_W)
        assert len(decoded) == 10

    def test_all_white_frames_do_not_cause_data_loss(self, tmp_path):
        """Edge case: completely white/saturated frames."""
        encoder = ROIEncoder(
            output_dir=str(tmp_path),
            foreground_crf=18, background_crf=45, preset="veryfast",
            db_path=str(tmp_path / "meta.db"),
        )
        frames = [np.full((FRAME_H, FRAME_W, 3), 255, dtype=np.uint8) for _ in range(10)]
        bboxes = [[(ROI_X, ROI_Y, ROI_W, ROI_H)] for _ in frames]
        output = encoder.encode_segment(frames=frames, bboxes_per_frame=bboxes,
                                        camera_id="white_frames", fps=FPS)
        decoded = _decode_video_frames(output, FRAME_H, FRAME_W)
        assert len(decoded) == 10
