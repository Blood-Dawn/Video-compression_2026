"""
tests/test_split_screen.py

Verifies the 2026-05-04 split-screen "no double label" fix in
src/demo/split_screen.py.

Background:
    Each per-mode demo video already has "MODE 0 · SEG 1" baked into
    its top-left corner by add_bottom_right_labels in demo.py. The
    older build_composite_frame then called draw_label again on each
    cell, producing a stacked "M0" badge on top of the existing
    "MODE 0" text. Riley flagged this 2026-05-04.

    The fix was to remove the draw_label call from
    build_composite_frame. Per-mode labels survive (they were already
    in the underlying video), no second pass.

These tests defend against accidental re-introduction of the second
draw_label call during a future refactor.

Author: Bloodawn (KheivenD), 2026-05-14.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from demo import split_screen  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def four_dummy_frames():
    """Return 4 small distinct frames labelled mode0..mode3."""
    out = []
    for i in range(4):
        frame = np.zeros((90, 120, 3), dtype=np.uint8)
        # Each frame is a solid gray of distinct value so we can tell
        # them apart after stitching.
        frame[:] = (40 * (i + 1), 40 * (i + 1), 40 * (i + 1))
        out.append((f"mode{i}", frame))
    return out


# ── Core invariant: draw_label not called by build_composite_frame ────────


class TestNoDoubleLabel:

    def test_draw_label_not_invoked_during_composite(self, four_dummy_frames):
        """The fix removed draw_label from build_composite_frame entirely.

        If anyone re-adds it, this assertion fires.
        """
        with mock.patch.object(split_screen, "draw_label") as mocked:
            split_screen.build_composite_frame(
                four_dummy_frames, rows=2, cols=2, cell_w=120, cell_h=90
            )
            assert mocked.call_count == 0, (
                "build_composite_frame must NOT call draw_label; the "
                "per-mode demo videos already carry their corner labels."
            )

    def test_fewer_frames_than_cells_pads_with_blank(self, four_dummy_frames):
        """3 frames in a 2x2 grid -> last cell is solid black, no label."""
        with mock.patch.object(split_screen, "draw_label") as mocked:
            out = split_screen.build_composite_frame(
                four_dummy_frames[:3], rows=2, cols=2, cell_w=120, cell_h=90
            )
            assert mocked.call_count == 0

        # Bottom-right quadrant of a 2x2 grid (240w x 180h composite)
        # should be all zero (black) since we passed only 3 frames.
        bottom_right = out[90:, 120:]
        assert bottom_right.sum() == 0


# ── Composite output shape and contents ───────────────────────────────────


class TestCompositeOutput:

    def test_2x2_grid_dimensions(self, four_dummy_frames):
        out = split_screen.build_composite_frame(
            four_dummy_frames, rows=2, cols=2, cell_w=120, cell_h=90
        )
        # Width = 2 cells * 120 px = 240
        # Height = 2 cells * 90 px = 180
        assert out.shape == (180, 240, 3)
        assert out.dtype == np.uint8

    def test_each_cell_preserves_intensity(self, four_dummy_frames):
        """The fit_frame letterboxing should keep the cell value
        recognisable in the centre of each quadrant."""
        out = split_screen.build_composite_frame(
            four_dummy_frames, rows=2, cols=2, cell_w=120, cell_h=90
        )
        # Top-left center pixel comes from mode0 (intensity ~40)
        # Top-right center comes from mode1 (intensity ~80)
        # Bottom-left from mode2 (~120)
        # Bottom-right from mode3 (~160)
        tl = out[45, 60]
        tr = out[45, 180]
        bl = out[135, 60]
        br = out[135, 180]
        # Allow noise because fit_frame uses cv2.resize bilinear which
        # may smudge boundaries a few units off the source intensity.
        assert abs(int(tl[0]) - 40) < 5
        assert abs(int(tr[0]) - 80) < 5
        assert abs(int(bl[0]) - 120) < 5
        assert abs(int(br[0]) - 160) < 5


# ── draw_label still works for callers that want it (e.g. legacy code) ────


class TestDrawLabelStillFunctional:
    """draw_label remains a public function; just isn't called by
    build_composite_frame any more. Verify it still renders a tag."""

    def test_draw_label_paints_text_area(self):
        frame = np.zeros((120, 200, 3), dtype=np.uint8)
        before = frame.sum()
        split_screen.draw_label(frame, "mode0")
        after = frame.sum()
        assert after > before, "draw_label should change pixel values"

    def test_draw_label_strips_mode_prefix(self):
        """The fix shrinks 'mode0' to 'M0' before stamping."""
        frame = np.zeros((120, 200, 3), dtype=np.uint8)
        # No clean way to read back the text from a numpy frame, but we
        # can at least confirm the call doesn't crash and writes pixels.
        split_screen.draw_label(frame, "mode0")
        assert frame.sum() > 0
