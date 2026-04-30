"""
test_webcam_cpu.py

Unit and integration tests for webcam (device-index) input and CPU-only pipeline.

Test classes:
    TestFrameSourceDevice   -- FrameSource accepts int and numeric-string device
                               indices (mocked VideoCapture, no real camera needed)
    TestPipelineWebcamMode  -- End-to-end pipeline run with a mocked device-0
                               source producing synthetic frames (no GPU, no YOLO)
    TestWebcamHardware      -- REAL hardware test; skipped unless --webcam flag
                               is passed or SVCS_TEST_WEBCAM=1 is set in the env.
                               Run: uv run pytest tests/test_webcam_cpu.py -v -m hardware

Usage:
    # Fast suite (mocked, no camera required):
    uv run pytest tests/test_webcam_cpu.py -v -m "not hardware"

    # Full suite including real webcam:
    uv run pytest tests/test_webcam_cpu.py -v -m hardware
    # or:
    SVCS_TEST_WEBCAM=1 uv run pytest tests/test_webcam_cpu.py -v
"""

import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import cv2
import numpy as np
import pytest

from utils.frame_source import FrameSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_cap(w: int = 640, h: int = 480, fps: float = 30.0, n_frames: int = 60):
    """Return a MagicMock that behaves like cv2.VideoCapture for a live device."""
    rng = np.random.default_rng(42)
    frames = [rng.integers(0, 256, (h, w, 3), dtype=np.uint8) for _ in range(n_frames)]
    call_count = {"n": 0}

    def _read():
        i = call_count["n"]
        call_count["n"] += 1
        if i < len(frames):
            return True, frames[i].copy()
        return False, None

    def _get(prop_id):
        return {
            cv2.CAP_PROP_FPS: fps,
            cv2.CAP_PROP_FRAME_WIDTH: float(w),
            cv2.CAP_PROP_FRAME_HEIGHT: float(h),
        }.get(prop_id, 0.0)

    cap = MagicMock()
    cap.isOpened.return_value = True
    cap.read.side_effect = _read
    cap.get.side_effect = _get
    cap.release.return_value = None
    return cap


_WEBCAM_SKIP = pytest.mark.skipif(
    not (os.getenv("SVCS_TEST_WEBCAM") == "1"),
    reason="Real webcam test. Set SVCS_TEST_WEBCAM=1 to run, or use -m hardware.",
)


# ---------------------------------------------------------------------------
# Unit tests: FrameSource device-index handling
# ---------------------------------------------------------------------------

class TestFrameSourceDevice:
    """FrameSource must accept int indices and numeric strings for camera devices."""

    def test_int_index_opens_device(self):
        """Passing integer 0 opens VideoCapture(0) and exposes correct metadata."""
        mock_cap = _make_mock_cap(w=640, h=480, fps=30.0)
        with patch("cv2.VideoCapture", return_value=mock_cap) as mock_vc:
            src = FrameSource(0)
            mock_vc.assert_called_once_with(0)
        assert src.fps == pytest.approx(30.0)
        assert src.width == 640
        assert src.height == 480
        assert src.total_frames == 0   # live device: unknown count
        assert not src.is_sequence

    def test_string_zero_treated_as_device(self):
        """Passing the string '0' should also open a camera device, not fail with
        'path does not exist'."""
        mock_cap = _make_mock_cap()
        with patch("cv2.VideoCapture", return_value=mock_cap) as mock_vc:
            src = FrameSource("0")
            mock_vc.assert_called_once_with(0)
        assert src.total_frames == 0

    def test_string_device_index_1(self):
        """'1' should map to VideoCapture(1)."""
        mock_cap = _make_mock_cap()
        with patch("cv2.VideoCapture", return_value=mock_cap) as mock_vc:
            FrameSource("1")
            mock_vc.assert_called_once_with(1)

    def test_device_read_returns_frames(self):
        """FrameSource.read() proxies VideoCapture.read() for device sources."""
        mock_cap = _make_mock_cap(n_frames=5)
        with patch("cv2.VideoCapture", return_value=mock_cap):
            src = FrameSource(0)
            frames_read = 0
            for _ in range(5):
                ok, frame = src.read()
                assert ok
                assert frame is not None
                assert frame.shape[2] == 3
                frames_read += 1
            assert frames_read == 5

    def test_device_eof_returns_false(self):
        """After all frames are exhausted, read() returns (False, None)."""
        mock_cap = _make_mock_cap(n_frames=2)
        with patch("cv2.VideoCapture", return_value=mock_cap):
            src = FrameSource(0)
            src.read(); src.read()          # consume both frames
            ok, frame = src.read()
            assert not ok
            assert frame is None

    def test_device_release(self):
        """Calling release() (or exiting context manager) releases the cap."""
        mock_cap = _make_mock_cap()
        with patch("cv2.VideoCapture", return_value=mock_cap):
            src = FrameSource(0)
            src.release()
        mock_cap.release.assert_called_once()

    def test_device_context_manager(self):
        """FrameSource works as a context manager for device sources."""
        mock_cap = _make_mock_cap()
        with patch("cv2.VideoCapture", return_value=mock_cap):
            with FrameSource(0) as src:
                ok, frame = src.read()
                assert ok
        mock_cap.release.assert_called_once()

    def test_device_not_opened_raises(self):
        """RuntimeError when the device index cannot be opened."""
        dead_cap = MagicMock()
        dead_cap.isOpened.return_value = False
        with patch("cv2.VideoCapture", return_value=dead_cap):
            with pytest.raises(RuntimeError, match="Cannot open camera device"):
                FrameSource(99)

    def test_fallback_fps_when_cap_returns_zero(self):
        """If the camera reports fps=0 (common on some OS), FrameSource defaults
        to 30 fps rather than storing 0."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.return_value = 0.0
        with patch("cv2.VideoCapture", return_value=mock_cap):
            src = FrameSource(0)
        assert src.fps == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# Integration: pipeline runs on mocked device-0 without GPU
# ---------------------------------------------------------------------------

class TestPipelineWebcamMode:
    """
    Run the SVCS pipeline end-to-end against a mocked webcam (device 0) using
    CPU-only processing, verifying that all four modes produce output without
    dropping frames or crashing.
    """

    @pytest.fixture(autouse=True)
    def _tmp_output(self, tmp_path):
        self.out = tmp_path / "segments"
        self.out.mkdir()

    def _run_pipeline(self, mode: str, tmp_path):
        """Run the pipeline for 45 synthetic frames and return the output dir."""
        from pipeline.pipeline import run_pipeline

        mock_cap = _make_mock_cap(w=320, h=240, fps=15.0, n_frames=45)
        with (
            patch("cv2.VideoCapture", return_value=mock_cap),
            patch("pipeline.pipeline.ObjectFilter") as mock_filter_cls,
        ):
            # Disable the YOLO filter so the test has no model-file dependency
            mock_filter = MagicMock()
            mock_filter.is_object.return_value = True
            mock_filter_cls.return_value = mock_filter

            run_pipeline(
                input_source=0,
                output_dir=str(tmp_path),
                mode=mode,
                segment_seconds=3,
                warmup_frames=10,
                bg_method="MOG2",
                enhance=False,
                object_filter=False,
                encrypt=False,
            )
        return tmp_path

    @pytest.mark.parametrize("mode", ["mode0", "mode1", "mode2", "mode3"])
    def test_all_modes_produce_output(self, tmp_path, mode):
        """Each mode must write at least one .mp4 segment from 45 synthetic frames."""
        out_dir = self._run_pipeline(mode, tmp_path)
        mp4_files = list(Path(out_dir).rglob("*.mp4"))
        assert len(mp4_files) >= 1, f"{mode} produced no .mp4 output"

    def test_mode0_no_frame_drops(self, tmp_path):
        """Mode 0 encodes every frame; the output segment must contain frames."""
        out_dir = self._run_pipeline("mode0", tmp_path)
        for mp4 in Path(out_dir).rglob("*.mp4"):
            cap = cv2.VideoCapture(str(mp4))
            assert cap.isOpened(), f"Cannot open output: {mp4}"
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
            assert frame_count > 0, f"Output segment {mp4.name} has 0 frames"


# ---------------------------------------------------------------------------
# Hardware test: real webcam
# ---------------------------------------------------------------------------

@pytest.mark.hardware
class TestWebcamHardware:
    """
    Real hardware test against a live webcam (device 0).

    Prerequisites:
        - A webcam must be connected and accessible as device 0.
        - Set SVCS_TEST_WEBCAM=1 in your environment before running.
        - FFmpeg must be on PATH for mode encoding.

    Run:
        SVCS_TEST_WEBCAM=1 uv run pytest tests/test_webcam_cpu.py::TestWebcamHardware -v
    """

    @_WEBCAM_SKIP
    def test_device_0_opens(self):
        """Camera device 0 must open and return at least one valid frame."""
        src = FrameSource(0)
        ok, frame = src.read()
        src.release()
        assert ok, "cv2.VideoCapture(0).read() returned False — no webcam connected?"
        assert frame is not None
        assert frame.ndim == 3 and frame.shape[2] == 3

    @_WEBCAM_SKIP
    def test_30_frames_no_drop(self):
        """Read 30 consecutive frames; all must succeed (no dropped reads)."""
        src = FrameSource(0)
        try:
            drop_count = 0
            for _ in range(30):
                ok, frame = src.read()
                if not ok or frame is None:
                    drop_count += 1
        finally:
            src.release()
        assert drop_count == 0, f"{drop_count}/30 frames dropped from webcam"

    @_WEBCAM_SKIP
    def test_pipeline_mode0_cpu_only_webcam(self, tmp_path):
        """
        Run Mode 0 for 3 seconds on webcam input with no GPU, no object filter.
        Verifies the pipeline completes without error and produces an output file.

        This is the Geena scenario: laptop + camera, no network.
        """
        from pipeline.pipeline import run_pipeline

        run_pipeline(
            input_source=0,
            output_dir=str(tmp_path),
            mode="mode0",
            segment_seconds=3,
            warmup_frames=30,
            bg_method="MOG2",
            enhance=False,
            object_filter=False,
            encrypt=False,
        )
        mp4_files = list(tmp_path.rglob("*.mp4"))
        assert len(mp4_files) >= 1, "Mode 0 + webcam produced no output segments"

        # Verify the segment is a playable video
        for mp4 in mp4_files:
            cap = cv2.VideoCapture(str(mp4))
            assert cap.isOpened()
            n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
            assert n > 0, f"Segment {mp4.name} has no frames"
