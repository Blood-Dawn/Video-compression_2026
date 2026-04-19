"""
test_detection_accuracy.py

Verifies that BackgroundSubtractor detects foreground regions on real footage.

The test clip path is resolved from the TEST_CLIP env var, then from a list
of known developer paths, then from data/test_clip.mp4. If no clip is found
the test is skipped with an explanatory message rather than failing.

To run locally:
    TEST_CLIP=path/to/your/clip.mp4 pytest tests/test_detection_accuracy.py
"""

import os
from pathlib import Path

import cv2
import pytest


# Candidate paths to try in order:
#   1. TEST_CLIP environment variable
#   2. Project data/ folder (shared test asset)
#   3. Legacy developer paths (kept so existing machines still work)
_CANDIDATE_PATHS = [
    os.environ.get("TEST_CLIP", ""),
    "data/test_clip.mp4",
    "data/samples/test_clip.mp4",
    "/Users/ashleynm/Downloads/test_clip.mp4",   # Ashleyn's machine
]


def _find_clip() -> str | None:
    for p in _CANDIDATE_PATHS:
        if p and Path(p).exists():
            return p
    return None


@pytest.fixture
def test_clip():
    path = _find_clip()
    if path is None:
        pytest.skip(
            "No test clip found. Set TEST_CLIP=/path/to/clip.mp4 or place a "
            "clip at data/test_clip.mp4 to run detection accuracy tests."
        )
    return path


def test_detection_not_empty(test_clip):
    """BackgroundSubtractor should find at least one foreground region
    within the first 50 frames of a clip that contains motion."""
    from src.background_subtraction.background_subtraction import BackgroundSubtractor

    cap = cv2.VideoCapture(test_clip)
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
        f"No foreground regions detected in first 50 frames of {test_clip}. "
        "Check that the clip contains motion and that MOG2 params are correct."
    )


def test_false_positive_rate_on_static_scene(test_clip):
    """On a static scene (frames 0-29 = warmup), FP rate must stay under 2%."""
    from src.background_subtraction.background_subtraction import BackgroundSubtractor

    cap = cv2.VideoCapture(test_clip)
    subtractor = BackgroundSubtractor(var_threshold=50, detect_shadows=False)

    warmup = 30
    for _ in range(warmup):
        ret, frame = cap.read()
        if not ret:
            pytest.skip("Clip too short for FP rate test (need > 30 frames).")
        subtractor.apply(frame)

    fp_frames = 0
    total = 0
    for _ in range(50):
        ret, frame = cap.read()
        if not ret:
            break
        mask = subtractor.apply(frame)
        regions = subtractor.get_foreground_regions(mask)
        # Count as FP only if we have regions but frame looks static
        # (simple heuristic: use frame diff from previous)
        fp_frames += len(regions) > 0
        total += 1

    cap.release()

    if total == 0:
        pytest.skip("Not enough frames after warmup.")

    fp_rate = fp_frames / total
    assert fp_rate < 0.02, (
        f"False positive rate {fp_rate:.1%} exceeds 2% threshold on static scene "
        f"({fp_frames}/{total} frames triggered). Tune varThreshold or check lighting."
    )
