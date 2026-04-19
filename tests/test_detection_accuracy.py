"""
test_detection_accuracy.py

Verifies that BackgroundSubtractor detects foreground regions on real footage
using CDnet 2014 benchmark videos from data/samples/cdnet_mp4/.

No external clip or env var needed — the CDnet videos are bundled with the repo.
Set TEST_CLIP=/path/to/clip.mp4 to override and use a specific clip instead.

To run:
    uv run pytest tests/test_detection_accuracy.py -v

To use a custom clip:
    TEST_CLIP=path/to/clip.mp4 uv run pytest tests/test_detection_accuracy.py -v
"""

import os
from pathlib import Path

import cv2
import pytest


# ──────────────────────────────────────────────
# Clip resolution helpers
# ──────────────────────────────────────────────

CDNET_ROOT = Path("data/samples/cdnet_mp4")

# Preferred clips for each test role.  Ordered by preference — the first one
# found on disk is used.  All are CDnet 2014 baseline sequences with clear,
# consistent motion (or a stable background for the FP test).
_MOTION_CLIPS = [
    CDNET_ROOT / "baseline" / "baseline_pedestrians.mp4",
    CDNET_ROOT / "baseline" / "baseline_highway.mp4",
    CDNET_ROOT / "cameraJitter" / "cameraJitter_traffic.mp4",
    CDNET_ROOT / "shadow" / "shadow_busStation.mp4",
    CDNET_ROOT / "baseline" / "baseline_PETS2006.mp4",
]

_STATIC_SCENE_CLIPS = [
    CDNET_ROOT / "baseline" / "baseline_office.mp4",
    CDNET_ROOT / "intermittentObjectMotion" / "intermittentObjectMotion_sofa.mp4",
    CDNET_ROOT / "intermittentObjectMotion" / "intermittentObjectMotion_abandonedBox.mp4",
    CDNET_ROOT / "shadow" / "shadow_copyMachine.mp4",
]


def _resolve_clip(candidates: list[Path]) -> Path | None:
    """Return the first candidate that exists on disk, or None."""
    for p in candidates:
        if p.exists():
            return p
    return None


def _find_any_cdnet_clip() -> Path | None:
    """Return any .mp4 from the CDnet tree — used as last-resort fallback."""
    if CDNET_ROOT.exists():
        for mp4 in sorted(CDNET_ROOT.rglob("*.mp4")):
            return mp4
    return None


def _find_motion_clip() -> str | None:
    # 1. Explicit override
    override = os.environ.get("TEST_CLIP", "")
    if override and Path(override).exists():
        return override
    # 2. Preferred motion clips from CDnet
    p = _resolve_clip(_MOTION_CLIPS)
    if p:
        return str(p)
    # 3. Any CDnet clip
    p = _find_any_cdnet_clip()
    if p:
        return str(p)
    # 4. Legacy developer path (kept for backwards compatibility)
    legacy = "/Users/ashleynm/Downloads/test_clip.mp4"
    if Path(legacy).exists():
        return legacy
    return None


def _find_static_clip() -> str | None:
    # 1. Explicit override (same clip, just a different warmup period)
    override = os.environ.get("TEST_CLIP", "")
    if override and Path(override).exists():
        return override
    # 2. Preferred static-scene clips from CDnet
    p = _resolve_clip(_STATIC_SCENE_CLIPS)
    if p:
        return str(p)
    # 3. Fall back to any motion clip — warmup will still stabilise the model
    return _find_motion_clip()


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def motion_clip():
    path = _find_motion_clip()
    if path is None:
        pytest.skip(
            "No CDnet clips found. Run `git lfs pull` or place a clip at "
            "data/samples/cdnet_mp4/baseline/baseline_pedestrians.mp4, "
            "or set TEST_CLIP=/path/to/clip.mp4."
        )
    return path


@pytest.fixture(scope="module")
def static_clip():
    path = _find_static_clip()
    if path is None:
        pytest.skip(
            "No CDnet clips found. Run `git lfs pull` or set TEST_CLIP=/path/to/clip.mp4."
        )
    return path


# Parametrized fixture: one test run per CDnet category that has a clip.
def _cdnet_clips_by_category() -> list[tuple[str, str]]:
    """Return [(category_name, clip_path), ...] for all CDnet categories found."""
    result = []
    if not CDNET_ROOT.exists():
        return result
    for category_dir in sorted(CDNET_ROOT.iterdir()):
        if not category_dir.is_dir():
            continue
        clips = sorted(category_dir.glob("*.mp4"))
        if clips:
            result.append((category_dir.name, str(clips[0])))
    return result


_CATEGORY_CLIPS = _cdnet_clips_by_category()


# ──────────────────────────────────────────────
# Core detection tests
# ──────────────────────────────────────────────

def test_detection_not_empty(motion_clip):
    """BackgroundSubtractor finds at least one foreground region within the
    first 50 frames of a clip that contains motion (CDnet baseline sequences
    all have foreground activity from frame 1)."""
    from src.background_subtraction.background_subtraction import BackgroundSubtractor

    cap = cv2.VideoCapture(motion_clip)
    subtractor = BackgroundSubtractor()

    detected = False
    for _ in range(50):
        ret, frame = cap.read()
        if not ret:
            break
        mask = subtractor.apply(frame)
        regions = subtractor.get_foreground_regions(mask)
        if regions:
            detected = True
            break

    cap.release()
    assert detected, (
        f"No foreground regions detected in first 50 frames of {motion_clip}. "
        "Verify MOG2 params (varThreshold, detectShadows) and that the clip "
        "contains visible motion."
    )


def test_false_positive_rate_on_static_scene(static_clip):
    """After a 30-frame warmup the FP rate must stay under 2%.

    The sponsor requirement is 0% FP on static scenes in deployment; 2% is the
    test-suite threshold to allow for CDnet clips that have slight background
    variation (e.g. waving plants, subtle lighting changes).
    """
    from src.background_subtraction.background_subtraction import BackgroundSubtractor

    cap = cv2.VideoCapture(static_clip)
    subtractor = BackgroundSubtractor(var_threshold=50)

    warmup = 30
    for _ in range(warmup):
        ret, frame = cap.read()
        if not ret:
            pytest.skip(f"Clip {static_clip!r} is too short for FP rate test (need > 30 frames).")
        subtractor.apply(frame)

    fp_frames = 0
    total = 0
    for _ in range(50):
        ret, frame = cap.read()
        if not ret:
            break
        mask = subtractor.apply(frame)
        regions = subtractor.get_foreground_regions(mask)
        fp_frames += len(regions) > 0
        total += 1

    cap.release()

    if total == 0:
        pytest.skip(f"Not enough frames after warmup in {static_clip!r}.")

    fp_rate = fp_frames / total
    assert fp_rate < 0.02, (
        f"False positive rate {fp_rate:.1%} exceeds 2% threshold on static scene "
        f"({fp_frames}/{total} frames triggered) using {static_clip}. "
        "Tune varThreshold or inspect clip for non-static background content."
    )


# ──────────────────────────────────────────────
# Parametrized per-category smoke tests
# ──────────────────────────────────────────────

@pytest.mark.parametrize("category,clip_path", _CATEGORY_CLIPS)
def test_no_crash_on_cdnet_category(category, clip_path):
    """BackgroundSubtractor must not crash on any CDnet category clip.

    Reads 30 frames from the first clip in each category.  Does not assert
    detection — some categories (e.g. thermal, turbulence) may not trigger
    foreground detections with the default MOG2 params, and that's expected.
    What must not happen is an exception or a corrupt mask shape.
    """
    from src.background_subtraction.background_subtraction import BackgroundSubtractor

    cap = cv2.VideoCapture(clip_path)
    assert cap.isOpened(), f"Could not open {clip_path}"
    subtractor = BackgroundSubtractor()

    frames_read = 0
    for _ in range(30):
        ret, frame = cap.read()
        if not ret:
            break
        mask = subtractor.apply(frame)
        assert mask is not None, f"apply() returned None on frame {frames_read} of {clip_path}"
        assert mask.shape == frame.shape[:2], (
            f"Mask shape {mask.shape} != frame shape {frame.shape[:2]} in {clip_path}"
        )
        frames_read += 1

    cap.release()
    assert frames_read > 0, f"Could not read any frames from {clip_path}"


@pytest.mark.skipif(not _CATEGORY_CLIPS, reason="No CDnet clips found")
def test_detection_on_nightVideos():
    """Night mode (CLAHE preprocessing) should find motion in bridgeEntry.

    bridgeEntry is a dark clip where daytime MOG2 alone struggles.  This test
    confirms the night-mode code path kicks in and improves detection.
    """
    night_clip = CDNET_ROOT / "nightVideos" / "nightVideos_bridgeEntry.mp4"
    if not night_clip.exists():
        pytest.skip(f"{night_clip} not found — run git lfs pull to get CDnet clips.")

    from src.background_subtraction.background_subtraction import BackgroundSubtractor

    cap = cv2.VideoCapture(str(night_clip))
    # night_mode=True enables CLAHE preprocessing
    subtractor = BackgroundSubtractor(night_mode=True)

    detected = False
    for _ in range(80):
        ret, frame = cap.read()
        if not ret:
            break
        mask = subtractor.apply(frame)
        regions = subtractor.get_foreground_regions(mask)
        if regions:
            detected = True
            break

    cap.release()
    assert detected, (
        "Night-mode BackgroundSubtractor failed to detect any foreground in "
        "nightVideos_bridgeEntry within 80 frames. Check CLAHE params."
    )
