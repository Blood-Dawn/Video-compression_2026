"""
src/config.py

Central place for SVCS defaults that used to be scattered across the
codebase as in-place literals. The big wins of having this in one file:

  * one obvious place to tune defaults when a sponsor or paying customer
    asks for different behaviour
  * easy to override at install time (an installer can drop a sibling
    ``svcs_config_overrides.toml`` and we merge it on top)
  * keeps the rest of the code readable instead of full of unexplained
    integers

This module imports the existing per-module constants where they're
already well-named (e.g. ``PBKDF2_ITERS`` in encryption.py,
``VAR_THRESHOLD_DAY`` in background_subtraction.py) so we have one
import to reach for, even when the original definition lives next to
its use site.

Author: Bloodawn (KheivenD), 2026-05-14 (audit cleanup, code smell D).
"""

from __future__ import annotations

# ── Compression / encoder defaults ────────────────────────────────────────

# Foreground regions are encoded near-lossless. 18 is "visually
# indistinguishable from source" for libx264. AV1 / libsvtav1 uses
# the same scale but slightly different perceptual sweet spot.
FOREGROUND_CRF = 18

# Background is compressed hard. 40 on libx264 is recognisable but
# small. 45 was the original surveillance project default; we keep that
# as the floor for the consumer compressor too.
BACKGROUND_CRF = 45

# Mode 3 (object-only blackout) uses one CRF for the whole frame because
# everything outside the bounding boxes is solid black and compresses
# trivially. 38 keeps the bounding-box pixels at decent quality while
# letting the blackout regions compress to almost nothing.
MODE3_CRF = 38

# Default codec. libsvtav1 is the SVT-AV1 implementation, royalty-free,
# patent-clean for distribution, smaller files than H.264 at the same
# perceived quality. libx264 is the auto-fallback when FFmpeg lacks
# AV1 support (the encoder probe runs at startup).
DEFAULT_CODEC = "libsvtav1"
FALLBACK_CODEC = "libx264"


def default_codec_for_mode(mode: str) -> str:
    """Per-mode default codec (codec gate RESOLVED 2026-06-01).

    mode0 / mode1 -> H.264 (libx264): every frame is kept, so universal
    playback and patent safety matter more than the last few percent of
    size; H.264 plays everywhere and is the safest royalty position.
    mode2 / mode3 -> AV1 (libsvtav1): these drop idle background and keep
    only objects, so the surviving bytes should be squeezed hardest with
    the royalty-free AV1 codec.

    H.265/HEVC is deliberately NOT an option anywhere: its patent licensing
    is fragmented and not royalty-free, unlike H.264. Explicit user codec
    selection always wins over this default (see pipeline.run_pipeline).

    Author: Bloodawn (KheivenD), 2026-06-02 (TASK 1.6 - per-mode codec).
    """
    return "libsvtav1" if mode in ("mode2", "mode3") else "libx264"

# How many seconds of footage end up in a single .mp4 segment.
# 60 s was a sponsor requirement, kept for now. Mobile devs might
# prefer shorter segments for snappier seeking; we expose this as a
# CLI / GUI option in pipeline.py.
SEGMENT_SECONDS = 60


# ── Background subtraction ────────────────────────────────────────────────

# Frame count the background subtractor sees before it starts emitting
# foreground regions. Lets MOG2/KNN build a stable background model.
# 120 frames at 25 fps = ~5 seconds of warmup.
WARMUP_FRAMES = 120

# Minimum bounding-box area (px) to count as a detected region. Below
# this is leaves, shadows, raindrops. Sensitivity GUI slider scales
# this between MIN_AREA_FLOOR and MIN_AREA_CEILING.
MIN_AREA_PX = 500
MIN_AREA_FLOOR = 100
MIN_AREA_CEILING = 2000

# Re-export the day / night varThreshold values from the BG subtractor
# module so callers can `from src.config import VAR_THRESHOLD_DAY`.
try:
    from background_subtraction.background_subtraction import (
        BackgroundSubtractor as _BS,
    )
    VAR_THRESHOLD_DAY = _BS.VAR_THRESHOLD_DAY
    VAR_THRESHOLD_NIGHT = _BS.VAR_THRESHOLD_NIGHT
except ImportError:  # pragma: no cover  (the module is always importable in real runs)
    VAR_THRESHOLD_DAY = 50
    VAR_THRESHOLD_NIGHT = 60


# ── Enhancement (Real-ESRGAN / bicubic) ───────────────────────────────────

# Run the enhancer every N foreground ROIs to keep the pipeline real-time
# on CPU. 5 means roughly 1 in 5 detected regions get a fresh SR pass;
# the rest reuse the most recent upscale. Lower number = sharper output,
# higher CPU. Higher number = faster, occasionally stale frames.
ENHANCE_EVERY_N = 5

# Skip the enhancer on regions bigger than this many pixels in either
# dimension. The model output saturates around 200 px on x4 upscale and
# the wall-clock cost climbs fast above that.
ENHANCE_MAX_ROI_PX = 200

# Default super-resolution scale factor. 4x is Real-ESRGAN's strongest
# point. 2x is faster but less dramatic.
ENHANCE_SCALE = 4


# ── Encryption ────────────────────────────────────────────────────────────
# Re-export PBKDF2_ITERS so callers don't have to remember which module
# owns it. NIST 2023 recommendation for PBKDF2-HMAC-SHA256.
try:
    from utils.encryption import PBKDF2_ITERS  # noqa: F401
except ImportError:  # pragma: no cover
    PBKDF2_ITERS = 600_000


# ── HLS streaming ─────────────────────────────────────────────────────────

# Target end-to-end latency for the live preview (ingest → browser).
# 4 to 6 seconds is normal HLS; lower needs LL-HLS or WebRTC which we
# don't ship.
HLS_LATENCY_TARGET_S = 5

# Number of .ts segments to keep in the rolling playlist.
HLS_LIST_SIZE = 5

# Length of each .ts segment in seconds.
HLS_SEGMENT_SECONDS = 2


# ── CPU sampler ───────────────────────────────────────────────────────────

# How often the background CPU/RAM/battery sampler ticks. 1 s is enough
# resolution for the dashboard chart without burning meaningful CPU on
# the measurement itself.
CPU_SAMPLER_INTERVAL_S = 1


# ── Concurrency / timeouts ────────────────────────────────────────────────

# Max time to wait for the pipeline thread to drain cleanly after the
# stop button is pressed. After this we just leave the daemon thread
# running and trust process exit to clean up.
PIPELINE_JOIN_TIMEOUT_S = 4

# FFmpeg subprocess timeout before we kill it. Sanity bound so a hung
# encoder doesn't hang the dashboard forever.
FFMPEG_TIMEOUT_S = 60

# CPU sampler thread join timeout.
CPU_SAMPLER_JOIN_TIMEOUT_S = 4


# ── Storage / database ────────────────────────────────────────────────────

# Max number of segments to return from /api/segments. The dashboard
# does its own client-side filtering once it has the list.
DEFAULT_SEGMENT_LIMIT = 50

# SQLite busy timeout in milliseconds. WAL mode means readers and
# writers rarely collide, but a slow shutdown can still hit a brief
# lock and we want it to wait rather than raise OperationalError.
SQLITE_BUSY_TIMEOUT_MS = 5_000


# ── GUI / dashboard ───────────────────────────────────────────────────────

# Server-sent events log buffer size. Older messages roll off when the
# dashboard reconnects after a network blip.
LOG_BUFFER_SIZE = 300

# Default Flask host and port. Overridable from the run_gui.py CLI.
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5000


__all__ = [
    "FOREGROUND_CRF",
    "BACKGROUND_CRF",
    "MODE3_CRF",
    "DEFAULT_CODEC",
    "FALLBACK_CODEC",
    "default_codec_for_mode",
    "SEGMENT_SECONDS",
    "WARMUP_FRAMES",
    "MIN_AREA_PX",
    "MIN_AREA_FLOOR",
    "MIN_AREA_CEILING",
    "VAR_THRESHOLD_DAY",
    "VAR_THRESHOLD_NIGHT",
    "ENHANCE_EVERY_N",
    "ENHANCE_MAX_ROI_PX",
    "ENHANCE_SCALE",
    "PBKDF2_ITERS",
    "HLS_LATENCY_TARGET_S",
    "HLS_LIST_SIZE",
    "HLS_SEGMENT_SECONDS",
    "CPU_SAMPLER_INTERVAL_S",
    "PIPELINE_JOIN_TIMEOUT_S",
    "FFMPEG_TIMEOUT_S",
    "CPU_SAMPLER_JOIN_TIMEOUT_S",
    "DEFAULT_SEGMENT_LIMIT",
    "SQLITE_BUSY_TIMEOUT_MS",
    "LOG_BUFFER_SIZE",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
]
