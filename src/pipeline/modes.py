"""
modes.py

Mode policy helpers for the selective compression pipeline.

This file is intentionally small: it only contains the logic that decides
how each pipeline mode handles a post-warmup frame.

Current modes:
- mode0: buffer every post-warmup frame; mark target frames when detections exist
- mode1: buffer only frames that contain detections
- mode2: buffer foreground frames and encode bbox patches over a clean background
- mode3: buffer only foreground frames and encode only bbox pixels

The goal is to keep pipeline.py focused on orchestration while keeping
mode-specific behavior isolated here for easier extension later.
"""

from dataclasses import dataclass
from typing import Iterable


VALID_MODES = {"mode0", "mode1", "mode2", "mode3"}


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
        store_foreground_layer:
            Legacy flag for the old crop/mask artifact path. New mode3 output
            uses the normal encoder with object_only=True instead.
    """
    buffer_frame: bool
    target_detected: bool
    store_foreground_layer: bool = False

    @property
    def store_full_frame(self) -> bool:
        """
        Preferred name for new mode code. Kept as a property so existing tests
        and callers that use buffer_frame continue to work unchanged.
        """
        return self.buffer_frame


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
        return ModeDecision(buffer_frame=True, target_detected=has_targets)

    # mode1 (event recording), mode2 (background keyframe plus patches) and
    # mode3 (object-only) all keep event frames only; they differ in how the
    # encoder renders those frames, not in which frames are kept.
    return ModeDecision(buffer_frame=has_targets, target_detected=has_targets)


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
        "mode2": (
            "Background keyframe plus object patches: store detected "
            "bounding-box pixels composited over a clean scene background."
        ),
        "mode3": (
            "Object-only segment: store detected bounding-box pixels on a "
            "black canvas using the normal MP4 encoder."
        ),
    }
    return descriptions[mode]
