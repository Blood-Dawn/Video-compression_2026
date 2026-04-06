"""
test_pipeline.py

Unit tests for src/pipeline/pipeline.py.
Covers:
  - EOF behavior when the video ends exactly on a full segment boundary
  - No extra final partial-segment encode when zero leftover frames remain
  - Cleanup/reporting still run on exit (preview cleanup + storage report)

These tests use monkeypatch with lightweight dummy classes so they run fast
and do not depend on real video files, OpenCV capture devices, or FFmpeg.
"""

import numpy as np
import pytest

from pipeline.pipeline import run_pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class DummyFrameSource:
    """
    Minimal fake FrameSource that returns a fixed list of frames and then EOF.

    Exposes the same attributes run_pipeline expects:
      - fps
      - width
      - height
      - read()
      - release()
      - get_warmup_frames()
    """
    def __init__(self, frames, fps=10.0, width=16, height=16):
        self.frames = frames
        self.index = 0
        self.fps = fps
        self.width = width
        self.height = height

    def read(self):
        if self.index < len(self.frames):
            frame = self.frames[self.index]
            self.index += 1
            return True, frame
        return False, None

    def release(self):
        pass

    def get_warmup_frames(self, fallback):
        return 0


class DummyRegion:
    """Minimal stand-in for ForegroundRegion used by pipeline serialization."""
    def to_tuple(self):
        return (0, 0, 4, 4)


class DummySubtractor:
    """
    Fake BackgroundSubtractor.

    Always reports one foreground region so mode0 buffers frames and the
    pipeline reaches the full-segment encode path deterministically.
    """
    def __init__(self, *args, **kwargs):
        pass

    def apply(self, frame):
        return np.zeros((frame.shape[0], frame.shape[1]), dtype=np.uint8)

    def get_foreground_regions(self, mask):
        return [DummyRegion()]

    def draw_regions(self, frame, regions):
        return frame


class DummyEncoder:
    """
    Fake ROIEncoder that records calls without writing any files.
    """
    def __init__(self, call_log, *args, **kwargs):
        self.call_log = call_log

    def encode_segment(self, frames, bboxes_per_frame, camera_id, fps):
        self.call_log["encode_segment"] += 1
        return f"dummy_segment_{self.call_log['encode_segment']}.mp4"

    def get_storage_report(self):
        self.call_log["get_storage_report"] += 1
        return {"total_segments": self.call_log["encode_segment"]}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def exact_segment_frames():
    """
    20 frames total.

    With fps=10 and segment_seconds=2, this is exactly one full segment,
    so EOF should occur with zero leftover frames.
    """
    rng = np.random.default_rng(123)
    return [
        rng.integers(0, 256, (16, 16, 3), dtype=np.uint8)
        for _ in range(20)
    ]


# ---------------------------------------------------------------------------
# EOF / segment-boundary behavior
# ---------------------------------------------------------------------------

class TestEOFBoundaryBehavior:
    def test_no_extra_partial_encode_when_video_ends_on_exact_segment_boundary(
        self, monkeypatch, tmp_path, exact_segment_frames
    ):
        """
        If the source ends exactly on a full segment boundary, run_pipeline()
        should perform the normal full-segment encode only once and must not
        perform a second EOF partial-segment encode.

        Cleanup/reporting should still run even though there are zero leftover
        buffered frames at shutdown.
        """
        calls = {
            "encode_segment": 0,
            "get_storage_report": 0,
        }

        monkeypatch.setattr(
            "pipeline.pipeline.FrameSource",
            lambda *_args, **_kwargs: DummyFrameSource(exact_segment_frames)
        )
        monkeypatch.setattr(
            "pipeline.pipeline.BackgroundSubtractor",
            DummySubtractor
        )
        monkeypatch.setattr(
            "pipeline.pipeline.ROIEncoder",
            lambda *args, **kwargs: DummyEncoder(calls, *args, **kwargs)
        )
        monkeypatch.setattr(
            "pipeline.pipeline.initialize_database",
            lambda *_args, **_kwargs: None
        )
        

        run_pipeline(
            input_source="dummy.mp4",
            camera_id="cam_test",
            output_dir=str(tmp_path),
            segment_seconds=2,
            bg_method="MOG2",
            show_preview=False,
            warmup_frames=0,
        )

        # One normal full-segment encode, no extra EOF partial encode.
        assert calls["encode_segment"] == 1

        # Cleanup/reporting should still run with zero leftover frames.
        assert calls["get_storage_report"] == 1
