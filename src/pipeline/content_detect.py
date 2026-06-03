"""
src/pipeline/content_detect.py

Rule-based content auto-detection (M3 TASK 3.2).

Given a clip, sample its first ~30 seconds and extract cheap, explainable
signals — how much of the frame moves (MOG2 foreground-area ratio), how often
anything moves at all (activity fraction), how bursty that motion is (variance),
the resolution / frame rate, and whether there's an audio track. A small
decision tree then recommends one of the named surveillance presets from
``pipeline.presets`` (e.g. a mostly-static 24/7 camera -> "Continuous CCTV",
sparse close-range events -> "Doorbell", a busy street -> "Active scene").

This is deliberately **not** a CNN: every recommendation comes with the signal
values and a one-line human reason, so an operator can see why and override it.
The interface (``analyze_video`` -> ``ContentSignals``; ``recommend_preset`` ->
``PresetRecommendation``) is kept swappable so a future learned classifier can
drop in behind ``detect_content`` without touching callers.

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 3.2 — content auto-detection).
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import cv2

try:  # one-way import shim used throughout the repo
    from background_subtraction.background_subtraction import BackgroundSubtractor
    from pipeline.presets import DEFAULT_PRESET, PRESETS, get_preset
    from utils.ffmpeg import ffprobe_path
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.background_subtraction.background_subtraction import BackgroundSubtractor
    from src.pipeline.presets import DEFAULT_PRESET, PRESETS, get_preset
    from src.utils.ffmpeg import ffprobe_path


# ── Tunable thresholds ────────────────────────────────────────────────────────
# Kept as module constants (not magic numbers in the tree) so they're easy to
# re-tune against real footage and easy to assert on in tests. All fractions are
# of the analyzed window, not the whole clip.

# A frame is "active" (something is moving) when this fraction of its pixels are
# foreground. 0.4% of pixels rejects MOG2 speckle but catches a distant walker.
ACTIVE_PIXEL_FRAC = 0.004
# Below this activity fraction the camera is essentially idle -> max-savings CCTV.
IDLE_ACTIVITY_FRAC = 0.05
# At/above this activity fraction the scene is busy -> dual-CRF "active scene".
BUSY_ACTIVITY_FRAC = 0.35
# When active, a foreground this large means a close, frame-filling subject
# (someone at a doorbell) rather than a distant target.
CLOSE_SUBJECT_FG_FRAC = 0.18
# Below this overall mean foreground the static camera really is static.
STATIC_MEAN_FG_FRAC = 0.02

# Sampling: analyze at most this many seconds, at this many frames/second. MOG2
# needs a short warmup before its mask is meaningful; we discard it.
DEFAULT_MAX_SECONDS = 30.0
DEFAULT_SAMPLE_FPS = 5.0
WARMUP_FRAMES = 5


@dataclass(frozen=True)
class ContentSignals:
    """Cheap, explainable signals extracted from the analyzed window."""
    width: int
    height: int
    source_fps: float
    frames_analyzed: int
    seconds_analyzed: float
    # mean fraction of frame that is foreground, across analyzed frames
    mean_foreground_frac: float
    # fraction of analyzed frames with any meaningful motion
    activity_frac: float
    # mean foreground fraction *during* active frames (object closeness proxy)
    active_foreground_frac: float
    # variance of per-frame foreground fraction (burstiness of motion)
    motion_variance: float
    has_audio: bool

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PresetRecommendation:
    """A recommended preset plus the human-readable reason and the signals."""
    preset: str
    label: str
    reason: str
    signals: ContentSignals

    def as_dict(self) -> dict:
        return {
            "preset": self.preset,
            "label": self.label,
            "reason": self.reason,
            "signals": self.signals.as_dict(),
        }


def _probe_has_audio(path: Path) -> bool:
    """True if ffprobe reports at least one audio stream. Best-effort."""
    try:
        out = subprocess.run(
            [
                ffprobe_path(), "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index",
                "-of", "csv=p=0",
                str(path),
            ],
            capture_output=True, text=True, timeout=15,
        )
        return bool(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - env dependent
        return False


def analyze_video(
    path,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    bg_method: str = "MOG2",
) -> ContentSignals:
    """Sample the first ``max_seconds`` of ``path`` and extract content signals.

    Frames are sampled at ``sample_fps`` (independent of the source frame rate)
    so the cost is bounded regardless of clip length or fps. The MOG2 mask drives
    the foreground signals; ffprobe supplies audio presence.

    Raises FileNotFoundError if the path doesn't exist and ValueError if it
    can't be opened as a video.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"no such file: {p}")

    cap = cv2.VideoCapture(str(p))
    if not cap.isOpened():
        cap.release()
        raise ValueError(f"could not open video: {p}")

    try:
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        if src_fps <= 1e-3 or src_fps > 1000:
            src_fps = 30.0  # some containers report 0; assume a sane default
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

        # Take every Nth source frame to approximate sample_fps.
        step = max(1, int(round(src_fps / max(0.1, sample_fps))))
        max_src_frames = int(max_seconds * src_fps)

        subtractor = BackgroundSubtractor(method=bg_method)
        fg_fracs = []          # foreground fraction per analyzed (post-warmup) frame
        src_idx = 0
        warmed = 0
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            if src_idx >= max_src_frames:
                break
            if src_idx % step == 0:
                if width == 0 or height == 0:
                    h, w = frame.shape[:2]
                    width, height = w, h
                mask = subtractor.apply(frame)
                warmed += 1
                if warmed > WARMUP_FRAMES:  # discard MOG2 warmup
                    total = mask.shape[0] * mask.shape[1]
                    fg = int(cv2.countNonZero(mask))
                    fg_fracs.append(fg / total if total else 0.0)
            src_idx += 1
    finally:
        cap.release()

    frames_analyzed = len(fg_fracs)
    seconds_analyzed = (frames_analyzed * step / src_fps) if frames_analyzed else 0.0

    if frames_analyzed:
        mean_fg = sum(fg_fracs) / frames_analyzed
        active_flags = [f >= ACTIVE_PIXEL_FRAC for f in fg_fracs]
        n_active = sum(active_flags)
        activity_frac = n_active / frames_analyzed
        active_fg = (
            sum(f for f, a in zip(fg_fracs, active_flags) if a) / n_active
            if n_active else 0.0
        )
        variance = sum((f - mean_fg) ** 2 for f in fg_fracs) / frames_analyzed
    else:
        mean_fg = activity_frac = active_fg = variance = 0.0

    return ContentSignals(
        width=width,
        height=height,
        source_fps=round(float(src_fps), 3),
        frames_analyzed=frames_analyzed,
        seconds_analyzed=round(seconds_analyzed, 3),
        mean_foreground_frac=round(mean_fg, 6),
        activity_frac=round(activity_frac, 6),
        active_foreground_frac=round(active_fg, 6),
        motion_variance=round(variance, 9),
        has_audio=_probe_has_audio(p),
    )


def recommend_preset(signals: ContentSignals) -> PresetRecommendation:
    """Map content signals to a named surveillance preset via a small rule tree.

    The branches, in order:
      1. Idle camera (rare motion, low mean foreground)         -> continuous_cctv
      2. Sparse motion + close, frame-filling subject           -> doorbell
      3. Sparse / occasional motion                             -> motion_event
      4. Busy scene (near-constant motion)                      -> active_scene
      5. Anything else / no usable signal                       -> generic default

    Each branch returns a one-line reason quoting the deciding signal so the
    operator can see (and override) the call.
    """
    s = signals
    pct = lambda x: f"{x * 100:.1f}%"

    # 0. No usable signal (unreadable / empty window): fall back to the default.
    if s.frames_analyzed == 0:
        key = DEFAULT_PRESET
        return PresetRecommendation(
            key, get_preset(key).label,
            "No analyzable frames; using the default preset.", s,
        )

    # 1. Mostly idle, static camera -> the biggest storage win.
    if s.activity_frac < IDLE_ACTIVITY_FRAC and s.mean_foreground_frac < STATIC_MEAN_FG_FRAC:
        key = "continuous_cctv"
        reason = (
            f"Mostly static: only {pct(s.activity_frac)} of frames had motion "
            f"({pct(s.mean_foreground_frac)} mean foreground)."
        )
    # 4. Busy scene -> dual-CRF keeps moving subjects sharp.
    elif s.activity_frac >= BUSY_ACTIVITY_FRAC:
        key = "active_scene"
        reason = (
            f"Busy scene: {pct(s.activity_frac)} of frames had motion — "
            "near-constant activity."
        )
    # 2/3. Sparse, occasional motion -> doorbell if the subject fills the frame,
    #      otherwise a general motion-event camera.
    elif s.active_foreground_frac >= CLOSE_SUBJECT_FG_FRAC:
        key = "doorbell"
        reason = (
            f"Sparse close-range events: motion in {pct(s.activity_frac)} of "
            f"frames, large subject ({pct(s.active_foreground_frac)} of frame when present)."
        )
    else:
        key = "motion_event"
        reason = (
            f"Occasional motion: {pct(s.activity_frac)} of frames active with a "
            f"distant subject ({pct(s.active_foreground_frac)} of frame when present)."
        )

    return PresetRecommendation(key, get_preset(key).label, reason, s)


def detect_content(
    path,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
) -> PresetRecommendation:
    """Convenience: analyze ``path`` and return a preset recommendation.

    This is the single entry point the GUI/API calls; swap the internals for a
    learned model later without changing callers.
    """
    signals = analyze_video(path, max_seconds=max_seconds, sample_fps=sample_fps)
    rec = recommend_preset(signals)
    assert rec.preset in PRESETS  # tree only ever returns known keys
    return rec
