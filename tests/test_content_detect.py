"""
tests/test_content_detect.py

Tests for rule-based content auto-detection (M3 TASK 3.2).

Two layers:
  * Unit — the decision tree (recommend_preset) is exercised on hand-built
    ContentSignals so every branch is asserted deterministically, no video I/O.
  * Integration — tiny synthetic clips are generated on the fly (a static frame
    vs. a large moving rectangle) and run through analyze_video + detect_content,
    so CI exercises the real MOG2 pipeline without any LFS assets. A real CDnet
    surveillance clip is used if present, otherwise that case is skipped.

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 3.2 — content auto-detection).
"""

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import cv2  # noqa: E402

from pipeline.content_detect import (  # noqa: E402
    ContentSignals,
    analyze_video,
    detect_content,
    recommend_preset,
    ACTIVE_PIXEL_FRAC,
    BUSY_ACTIVITY_FRAC,
    CLOSE_SUBJECT_FG_FRAC,
    IDLE_ACTIVITY_FRAC,
    STATIC_MEAN_FG_FRAC,
)
from pipeline.presets import PRESETS  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────

def _signals(**over) -> ContentSignals:
    """Build a ContentSignals with sane defaults, overriding the fields a test
    cares about. Defaults describe an idle static camera."""
    base = dict(
        width=640, height=480, source_fps=30.0,
        frames_analyzed=30, seconds_analyzed=30.0,
        mean_foreground_frac=0.0, activity_frac=0.0,
        active_foreground_frac=0.0, motion_variance=0.0, has_audio=False,
    )
    base.update(over)
    return ContentSignals(**base)


def _write_clip(path: Path, make_frame, n_frames=80, size=(320, 240), fps=10.0):
    """Write an .avi (MJPG, intra-frame) clip; skip the test if no encoder.

    make_frame(i) -> HxWx3 uint8 BGR frame. MJPG is intra-only so identical
    input frames decode with minimal temporal noise — important for the static
    case where we assert near-zero motion.
    """
    w, h = size
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    if not writer.isOpened():  # pragma: no cover - environment without MJPG
        writer.release()
        pytest.skip("no MJPG VideoWriter available in this environment")
    for i in range(n_frames):
        writer.write(make_frame(i))
    writer.release()


# ── unit: decision tree ──────────────────────────────────────────────────────

def test_tree_idle_static_camera_to_continuous_cctv():
    s = _signals(activity_frac=0.01, mean_foreground_frac=0.005)
    rec = recommend_preset(s)
    assert rec.preset == "continuous_cctv"
    assert "static" in rec.reason.lower()
    assert rec.label == PRESETS["continuous_cctv"].label


def test_tree_busy_scene_to_active_scene():
    s = _signals(activity_frac=BUSY_ACTIVITY_FRAC + 0.1,
                 mean_foreground_frac=0.25, active_foreground_frac=0.30)
    rec = recommend_preset(s)
    assert rec.preset == "active_scene"
    assert "busy" in rec.reason.lower()


def test_tree_sparse_close_subject_to_doorbell():
    # Occasional motion, but when present the subject fills much of the frame.
    s = _signals(activity_frac=0.12, mean_foreground_frac=0.05,
                 active_foreground_frac=CLOSE_SUBJECT_FG_FRAC + 0.05)
    rec = recommend_preset(s)
    assert rec.preset == "doorbell"


def test_tree_sparse_distant_subject_to_motion_event():
    # Occasional motion with a small/distant subject -> general motion-event cam.
    s = _signals(activity_frac=0.12, mean_foreground_frac=0.03,
                 active_foreground_frac=0.05)
    rec = recommend_preset(s)
    assert rec.preset == "motion_event"


def test_tree_no_frames_falls_back_to_default():
    s = _signals(frames_analyzed=0, seconds_analyzed=0.0)
    rec = recommend_preset(s)
    assert rec.preset in PRESETS  # default preset key
    assert "default" in rec.reason.lower()


def test_tree_only_returns_known_preset_keys():
    # Sweep a grid of signal combinations; every recommendation must be a real
    # preset and carry a non-empty reason.
    for af in (0.0, 0.03, 0.12, 0.5, 0.95):
        for mf in (0.001, 0.03, 0.2):
            for cf in (0.01, 0.2, 0.6):
                rec = recommend_preset(_signals(
                    activity_frac=af, mean_foreground_frac=mf,
                    active_foreground_frac=cf))
                assert rec.preset in PRESETS
                assert rec.reason.strip()


def test_tree_thresholds_are_ordered():
    # Sanity on the constants so a future re-tune can't silently invert them.
    assert 0 < ACTIVE_PIXEL_FRAC < STATIC_MEAN_FG_FRAC
    assert 0 < IDLE_ACTIVITY_FRAC < BUSY_ACTIVITY_FRAC < 1
    assert 0 < CLOSE_SUBJECT_FG_FRAC < 1


# ── integration: synthetic clips through real MOG2 ───────────────────────────

def test_analyze_static_clip_recommends_continuous_cctv(tmp_path):
    """An unchanging frame -> ~no motion -> Continuous CCTV (max savings)."""
    clip = tmp_path / "static.avi"
    gray = np.full((240, 320, 3), 120, np.uint8)
    _write_clip(clip, lambda i: gray)

    signals = analyze_video(clip)
    assert signals.frames_analyzed > 0
    assert signals.width == 320 and signals.height == 240
    assert signals.activity_frac < IDLE_ACTIVITY_FRAC
    assert signals.mean_foreground_frac < STATIC_MEAN_FG_FRAC

    rec = detect_content(clip)
    assert rec.preset == "continuous_cctv"


def test_analyze_busy_clip_recommends_active_scene(tmp_path):
    """A large rectangle moving every frame -> constant motion -> Active scene."""
    clip = tmp_path / "busy.avi"

    rng = np.random.default_rng(1234)

    def frame(i):
        # A fresh field of coarse random blocks every frame: no pixel ever has a
        # stable value, so MOG2 can't model any of it as background — the whole
        # frame reads as motion. Coarse (16px) blocks survive MJPG compression.
        small = rng.integers(0, 256, (15, 20, 3), dtype=np.uint8)
        return cv2.resize(small, (320, 240), interpolation=cv2.INTER_NEAREST)

    _write_clip(clip, frame)
    signals = analyze_video(clip)
    assert signals.activity_frac >= BUSY_ACTIVITY_FRAC
    assert recommend_preset(signals).preset == "active_scene"


def test_detect_content_returns_known_key_and_signals(tmp_path):
    clip = tmp_path / "static2.avi"
    gray = np.full((240, 320, 3), 90, np.uint8)
    _write_clip(clip, lambda i: gray)
    rec = detect_content(clip)
    assert rec.preset in PRESETS
    d = rec.as_dict()
    assert set(d) == {"preset", "label", "reason", "signals"}
    assert d["signals"]["frames_analyzed"] > 0
    assert d["signals"]["has_audio"] is False  # silent synthetic clip


def test_analyze_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        analyze_video("does/not/exist.mp4")


def test_analyze_non_video_raises(tmp_path):
    bad = tmp_path / "nota.video"
    bad.write_bytes(b"not a video at all")
    with pytest.raises((ValueError, FileNotFoundError)):
        analyze_video(bad)


# ── optional: a real CDnet surveillance clip if it's available locally ───────

def _find_cdnet_clip():
    roots = [
        Path(__file__).parent.parent / "data" / "samples" / "cdnet_mp4",
        Path(__file__).parent.parent / "data" / "samples",
        Path(__file__).parent.parent / "tests" / "data",
    ]
    for root in roots:
        if root.is_dir():
            for mp4 in sorted(root.rglob("*.mp4")):
                return mp4
    return None


def test_cdnet_surveillance_clip_is_continuous_cctv():
    clip = _find_cdnet_clip()
    if clip is None:
        pytest.skip("no CDnet sample clip present (LFS/local-only)")
    rec = detect_content(clip)
    # A static surveillance feed with sparse traffic should land on a
    # surveillance preset; assert it's recognized and surveillance-family.
    assert rec.preset in PRESETS
    assert PRESETS[rec.preset].surveillance, (
        f"CDnet clip mapped to non-surveillance preset {rec.preset!r}"
    )
