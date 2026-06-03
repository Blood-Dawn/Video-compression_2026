"""
tests/test_config.py

Smoke + value tests for src/config.py. This module isn't logic, it's
constants, so the test surface is small but important: any one of these
defaults landing wrong silently changes pipeline behaviour.

Author: Bloodawn (KheivenD), 2026-05-14.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import config  # noqa: E402


# ── Compression defaults ──────────────────────────────────────────────────


class TestCompressionDefaults:

    def test_foreground_crf_is_lossless_zone(self):
        # CRF 18 is widely considered visually lossless for libx264.
        # If someone bumps it above 23 the project loses its forensic
        # promise, so guard the range.
        assert config.FOREGROUND_CRF == 18
        assert 0 <= config.FOREGROUND_CRF <= 23

    def test_background_crf_is_aggressive(self):
        assert config.BACKGROUND_CRF == 45
        assert 30 <= config.BACKGROUND_CRF <= 51

    def test_mode3_crf_in_range(self):
        assert config.MODE3_CRF == 38
        assert 18 <= config.MODE3_CRF <= 51

    def test_fg_lower_than_bg(self):
        """Foreground must always be encoded at higher quality (lower CRF)."""
        assert config.FOREGROUND_CRF < config.BACKGROUND_CRF

    def test_default_codec_is_av1(self):
        assert config.DEFAULT_CODEC == "libsvtav1"

    def test_fallback_codec_is_h264(self):
        assert config.FALLBACK_CODEC == "libx264"

    def test_default_codec_for_mode(self):
        """Per-mode codec policy (TASK 1.6, codec gate resolved 2026-06-01):
        mode0/mode1 -> H.264 (universal playback + patent safety),
        mode2/mode3 -> AV1 (max savings on the surviving object bytes).
        H.265 is never selected."""
        assert config.default_codec_for_mode("mode0") == "libx264"
        assert config.default_codec_for_mode("mode1") == "libx264"
        assert config.default_codec_for_mode("mode2") == "libsvtav1"
        assert config.default_codec_for_mode("mode3") == "libsvtav1"
        # No mapping ever yields an H.265/HEVC encoder.
        for m in ("mode0", "mode1", "mode2", "mode3"):
            assert "265" not in config.default_codec_for_mode(m)
            assert "hevc" not in config.default_codec_for_mode(m).lower()

    def test_segment_seconds_is_positive(self):
        assert config.SEGMENT_SECONDS == 60
        assert config.SEGMENT_SECONDS > 0


# ── Background subtraction re-exports ─────────────────────────────────────


class TestBgSubtractionReExports:

    def test_var_threshold_day(self):
        """The re-export should match the source class constant."""
        from background_subtraction.background_subtraction import (
            BackgroundSubtractor as BS,
        )
        assert config.VAR_THRESHOLD_DAY == BS.VAR_THRESHOLD_DAY

    def test_var_threshold_night(self):
        from background_subtraction.background_subtraction import (
            BackgroundSubtractor as BS,
        )
        assert config.VAR_THRESHOLD_NIGHT == BS.VAR_THRESHOLD_NIGHT

    def test_night_threshold_higher_than_day(self):
        """Night needs a higher threshold to reject sensor noise."""
        assert config.VAR_THRESHOLD_NIGHT > config.VAR_THRESHOLD_DAY


# ── Warmup, min area ──────────────────────────────────────────────────────


class TestDetectionDefaults:

    def test_warmup_frames_positive(self):
        assert config.WARMUP_FRAMES == 120
        assert config.WARMUP_FRAMES > 0

    def test_min_area_in_range(self):
        assert (
            config.MIN_AREA_FLOOR <= config.MIN_AREA_PX <= config.MIN_AREA_CEILING
        )


# ── Enhancement defaults ──────────────────────────────────────────────────


class TestEnhancementDefaults:

    def test_enhance_every_n_positive(self):
        assert config.ENHANCE_EVERY_N >= 1

    def test_enhance_scale_supported(self):
        # Real-ESRGAN ships x2 and x4 model variants
        assert config.ENHANCE_SCALE in (2, 4)

    def test_enhance_max_roi_px_reasonable(self):
        # Below ~100 you're not enhancing anything useful, above ~500
        # the model output saturates and wall-clock cost explodes.
        assert 100 < config.ENHANCE_MAX_ROI_PX < 1000


# ── Encryption re-export ──────────────────────────────────────────────────


class TestEncryptionReExport:

    def test_pbkdf2_iters_at_or_above_nist_2023(self):
        """NIST recommends >= 600,000 for PBKDF2-HMAC-SHA256 as of 2023."""
        assert config.PBKDF2_ITERS >= 600_000

    def test_re_export_matches_encryption_module(self):
        from utils import encryption
        assert config.PBKDF2_ITERS == encryption.PBKDF2_ITERS


# ── HLS streaming defaults ────────────────────────────────────────────────


class TestHLSDefaults:

    def test_hls_segment_seconds_positive(self):
        assert config.HLS_SEGMENT_SECONDS > 0

    def test_hls_list_size_positive(self):
        assert config.HLS_LIST_SIZE >= 3   # need a minimum buffer

    def test_hls_latency_target_within_normal_range(self):
        """Standard HLS lands in 4-10 seconds end-to-end."""
        assert 2 <= config.HLS_LATENCY_TARGET_S <= 30


# ── Timeouts ──────────────────────────────────────────────────────────────


class TestTimeouts:

    def test_pipeline_join_timeout(self):
        assert config.PIPELINE_JOIN_TIMEOUT_S > 0

    def test_ffmpeg_timeout(self):
        assert config.FFMPEG_TIMEOUT_S > 0

    def test_cpu_sampler_join_timeout(self):
        assert config.CPU_SAMPLER_JOIN_TIMEOUT_S > 0


# ── GUI defaults ──────────────────────────────────────────────────────────


class TestGuiDefaults:

    def test_default_host_is_all_interfaces(self):
        # 0.0.0.0 makes the dashboard accessible on LAN. Localhost-only
        # would silently break the teammate-sharing flow.
        assert config.DEFAULT_HOST == "0.0.0.0"

    def test_default_port_in_valid_range(self):
        assert 1024 <= config.DEFAULT_PORT <= 65535

    def test_log_buffer_size_positive(self):
        assert config.LOG_BUFFER_SIZE > 0


# ── Public surface ────────────────────────────────────────────────────────


class TestExports:
    """__all__ should match what's actually defined at the top level."""

    def test_all_listed_attrs_exist(self):
        missing = [name for name in config.__all__ if not hasattr(config, name)]
        assert not missing, f"declared in __all__ but missing: {missing}"

    def test_no_unintended_private_leaks(self):
        """Only names in __all__ should be exposed via star-import."""
        public = [name for name in dir(config)
                  if not name.startswith("_")
                  and name not in ("annotations",)]
        # All public names should appear in __all__
        # (exceptions: nothing right now)
        for name in public:
            if name in ("annotations",):  # __future__
                continue
            assert name in config.__all__, f"public name not in __all__: {name}"
