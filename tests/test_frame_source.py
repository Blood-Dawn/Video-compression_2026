"""
test_frame_source.py

Tests for src/utils/frame_source.py.
Covers: video file mode, CDnet image sequence mode, temporal_roi parsing,
        get_warmup_frames(), context manager, __repr__, error handling.

All CDnet fixtures are synthesised in tmp_path to avoid any real dataset
dependency — each test creates the minimal folder layout it needs.
"""

import cv2
import numpy as np
import pytest
from pathlib import Path

from utils.frame_source import FrameSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_tiny_video(path: Path, n_frames: int = 5, w: int = 32, h: int = 32, fps: float = 15.0):
    """Write a minimal MP4 file using OpenCV's VideoWriter."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (w, h))
    rng = np.random.default_rng(0)
    for _ in range(n_frames):
        frame = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
        writer.write(frame)
    writer.release()


def _write_cdnet_sequence(scene_dir: Path, n_frames: int = 6, temporal_roi: str = "3 6"):
    """
    Create a minimal CDnet-style scene folder:
        scene_dir/
            input/
                in000001.jpg ... in000006.jpg
            temporalROI.txt  (optional, written when temporal_roi is not None)
    """
    input_dir = scene_dir / "input"
    input_dir.mkdir(parents=True)
    rng = np.random.default_rng(1)
    for i in range(1, n_frames + 1):
        frame = rng.integers(0, 256, (16, 16, 3), dtype=np.uint8)
        cv2.imwrite(str(input_dir / f"in{i:06d}.jpg"), frame)
    if temporal_roi is not None:
        (scene_dir / "temporalROI.txt").write_text(temporal_roi)


# ---------------------------------------------------------------------------
# Video file mode
# ---------------------------------------------------------------------------

class TestVideoFileMode:
    def test_opens_mp4(self, tmp_path):
        p = tmp_path / "clip.mp4"
        _write_tiny_video(p, n_frames=5, w=32, h=32, fps=15.0)
        src = FrameSource(str(p))
        assert not src.is_sequence
        assert src.width == 32
        assert src.height == 32
        src.release()

    def test_read_returns_correct_frame_count(self, tmp_path):
        p = tmp_path / "clip.mp4"
        _write_tiny_video(p, n_frames=5)
        frames_read = 0
        with FrameSource(str(p)) as src:
            while True:
                ok, frame = src.read()
                if not ok:
                    break
                assert frame is not None
                frames_read += 1
        assert frames_read == 5

    def test_read_after_exhaustion_returns_false(self, tmp_path):
        p = tmp_path / "clip.mp4"
        _write_tiny_video(p, n_frames=3)
        with FrameSource(str(p)) as src:
            for _ in range(3):
                src.read()
            ok, frame = src.read()
        assert not ok

    def test_no_temporal_roi_for_video(self, tmp_path):
        p = tmp_path / "clip.mp4"
        _write_tiny_video(p)
        with FrameSource(str(p)) as src:
            assert src.temporal_roi is None

    def test_get_warmup_frames_uses_fallback_for_video(self, tmp_path):
        p = tmp_path / "clip.mp4"
        _write_tiny_video(p)
        with FrameSource(str(p)) as src:
            assert src.get_warmup_frames(fallback=77) == 77

    def test_scene_name_is_stem(self, tmp_path):
        p = tmp_path / "highway_test.mp4"
        _write_tiny_video(p)
        with FrameSource(str(p)) as src:
            assert src.get_scene_name() == "highway_test"

    def test_raises_for_missing_file(self, tmp_path):
        with pytest.raises(RuntimeError):
            FrameSource(str(tmp_path / "nonexistent.mp4"))


# ---------------------------------------------------------------------------
# CDnet image sequence mode
# ---------------------------------------------------------------------------

class TestCDnetSequenceMode:
    def test_opens_scene_folder(self, tmp_path):
        scene = tmp_path / "highway"
        _write_cdnet_sequence(scene, n_frames=6)
        with FrameSource(str(scene)) as src:
            assert src.is_sequence
            assert src.total_frames == 6

    def test_opens_input_subfolder_directly(self, tmp_path):
        scene = tmp_path / "highway"
        _write_cdnet_sequence(scene, n_frames=4)
        with FrameSource(str(scene / "input")) as src:
            assert src.is_sequence
            assert src.total_frames == 4

    def test_reads_all_frames(self, tmp_path):
        scene = tmp_path / "scene"
        _write_cdnet_sequence(scene, n_frames=6)
        count = 0
        with FrameSource(str(scene)) as src:
            while True:
                ok, _ = src.read()
                if not ok:
                    break
                count += 1
        assert count == 6

    def test_temporal_roi_parsed(self, tmp_path):
        scene = tmp_path / "scene"
        _write_cdnet_sequence(scene, n_frames=10, temporal_roi="5 10")
        with FrameSource(str(scene)) as src:
            assert src.temporal_roi == (5, 10)

    def test_temporal_roi_absent_is_none(self, tmp_path):
        scene = tmp_path / "scene"
        _write_cdnet_sequence(scene, n_frames=5, temporal_roi=None)
        with FrameSource(str(scene)) as src:
            assert src.temporal_roi is None

    def test_get_warmup_frames_uses_temporal_roi(self, tmp_path):
        scene = tmp_path / "scene"
        _write_cdnet_sequence(scene, n_frames=10, temporal_roi="5 10")
        with FrameSource(str(scene)) as src:
            # temporal_roi[0]=5 is 1-indexed → warmup = 5 - 1 = 4
            assert src.get_warmup_frames(fallback=120) == 4

    def test_get_warmup_frames_fallback_when_no_roi(self, tmp_path):
        scene = tmp_path / "scene"
        _write_cdnet_sequence(scene, n_frames=5, temporal_roi=None)
        with FrameSource(str(scene)) as src:
            assert src.get_warmup_frames(fallback=50) == 50

    def test_raises_for_empty_input_folder(self, tmp_path):
        scene = tmp_path / "empty"
        (scene / "input").mkdir(parents=True)
        with pytest.raises(RuntimeError):
            FrameSource(str(scene))

    def test_default_fps_is_30(self, tmp_path):
        scene = tmp_path / "scene"
        _write_cdnet_sequence(scene, n_frames=3)
        with FrameSource(str(scene)) as src:
            assert src.fps == 30.0


# ---------------------------------------------------------------------------
# Context manager / release
# ---------------------------------------------------------------------------

class TestContextManager:
    def test_with_block_releases_capture(self, tmp_path):
        p = tmp_path / "clip.mp4"
        _write_tiny_video(p)
        with FrameSource(str(p)) as src:
            pass
        # After exiting the context manager, _cap should be None
        assert src._cap is None

    def test_double_release_is_safe(self, tmp_path):
        p = tmp_path / "clip.mp4"
        _write_tiny_video(p)
        src = FrameSource(str(p))
        src.release()
        src.release()   # should not raise


# ---------------------------------------------------------------------------
# __repr__
# ---------------------------------------------------------------------------

class TestRepr:
    def test_repr_contains_scene_name(self, tmp_path):
        scene = tmp_path / "myScene"
        _write_cdnet_sequence(scene, n_frames=3)
        with FrameSource(str(scene)) as src:
            r = repr(src)
        assert "myScene" in r

    def test_repr_mentions_sequence(self, tmp_path):
        scene = tmp_path / "scene"
        _write_cdnet_sequence(scene, n_frames=3)
        with FrameSource(str(scene)) as src:
            assert "sequence" in repr(src)
