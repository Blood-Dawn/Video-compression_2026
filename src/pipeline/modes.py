"""
modes.py

Mode policy helpers for the selective compression pipeline.

This file is intentionally small: it only contains the logic that decides
how each pipeline mode handles a post-warmup frame.

Current modes:
- mode0: buffer every post-warmup frame; mark target frames when detections exist
- mode1: buffer only frames that contain detections

The goal is to keep pipeline.py focused on orchestration while keeping
mode-specific behavior isolated here for easier extension later.
"""

from dataclasses import dataclass
from typing import Iterable


VALID_MODES = {"mode0", "mode1"}


@dataclass(frozen=True)
class ModeDecision:
    """
    Decision returned for a single post-warmup frame.

    Attributes:
        buffer_frame:
            Whether this frame should be added to the current output segment.
        target_detected:
            Whether this frame contains one or more detected foreground regions.
            This is used for stats/logging such as target_frames_this_segment.
    """
    buffer_frame: bool
    target_detected: bool


def validate_mode(mode: str) -> None:
    """
    Raise ValueError if mode is unsupported.

    Kept separate from argparse so run_pipeline() is also safe when called
    programmatically from tests or other modules.
    """
    if mode not in VALID_MODES:
        raise ValueError(
            f"Invalid mode '{mode}'. Expected one of: {sorted(VALID_MODES)}"
        )


def get_mode_decision(mode: str, regions: Iterable[object]) -> ModeDecision:
    """
    Return the per-frame buffering decision for the requested mode.

    Args:
        mode:
            Pipeline mode name.
        regions:
            Iterable of detected foreground regions for the current frame.

    Returns:
        ModeDecision describing whether to buffer the frame and whether the
        frame contains targets.
    """
    validate_mode(mode)

    has_targets = len(regions) > 0

    if mode == "mode0":
        # Baseline: keep every post-warmup frame, regardless of detections.
        return ModeDecision(
            buffer_frame=True,
            target_detected=has_targets,
        )

    if mode == "mode1":
        # Event recording: only keep frames where detections exist.
        return ModeDecision(
            buffer_frame=has_targets,
            target_detected=has_targets,
        )

    # Defensive fallback; validate_mode() should make this unreachable.
    raise ValueError(f"Unhandled mode: {mode}")


def describe_mode(mode: str) -> str:
    """
    Human-readable description for logs / CLI help / future UI use.
    """
    validate_mode(mode)

    descriptions = {
        "mode0": (
            "Current full-segment pipeline: store all post-warmup frames, "
            "whether targets are present or not."
        ),
        "mode1": (
            "Standard event recording: store only post-warmup frames with "
            "detected foreground objects."
        ),
    }
    return descriptions[mode]