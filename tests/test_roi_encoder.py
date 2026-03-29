"""
tests/test_roi_encoder.py

Integration tests for the ROIEncoder class (Milestone 1 - Section 1.2).

Tests cover:
  - encode_segment() produces a real output file
  - Output file is smaller than the raw input equivalent
  - get_file_size() returns correct byte count
  - No FFmpeg subprocess errors on valid input
  - Metadata database row is written correctly
  - Empty bounding boxes trigger background CRF (high compression)
  - Non-empty bounding boxes trigger foreground CRF (high quality)
"""

import os
import sqlite3
import tempfile
import numpy as np
import pytest
from pathlib import Path

# Make sure src/ is importable when running from project root
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from compression.roi_encoder import ROIEncoder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_frames(count: int = 10, height: int = 120, width: int = 160) -> list:
    """Generate solid-color BGR frames (fast, no disk I/O needed)."""
    frames = []
    for i in range(count):
        frame = np.full((height, width, 3), fill_value=(i * 8) % 255, dtype=np.uint8)
        frames.append(frame)
    return frames


def make_bboxes_with_motion(frame_count: int) -> list:
    """Return a bbox list where half the frames have a detected object."""
    bboxes = []
    for i in range(frame_count):
        if i % 2 == 0:
            bboxes.append([(50, 50, 80, 120)])   # one detection
        else:
            bboxes.append([])
    return bboxes


def make_bboxes_empty(frame_count: int) -> list:
    """Return a bbox list with no detections (static scene)."""
    return [[] for _ in range(frame_count)]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def encoder(tmp_path):
    """Create an ROIEncoder that writes to a temp directory."""
    db_path = str(tmp_path / "metadata.db")
    return ROIEncoder(
        output_dir=str(tmp_path),
        foreground_crf=28,   # slightly relaxed for test speed
        background_crf=45,
        preset="ultrafast",  # fastest preset for tests
        db_path=db_path,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEncodeSegment:

    def test_output_file_is_created(self, encoder, tmp_path):
        """encode_segment() must produce a real .mp4 file on disk."""
        frames = make_frames(30)
        bboxes = make_bboxes_with_motion(30)

        output_path, file_size = encoder.encode_segment(
            frames=frames,
            bboxes_per_frame=bboxes,
            camera_id="cam_test",
            fps=30,
        )

        assert Path(output_path).exists(), "Output file was not created"
        assert output_path.endswith(".mp4"), "Output file should be .mp4"

    def test_output_file_is_valid_mp4(self, encoder):
        """Output file must be a playable video (non-zero size, readable by ffmpeg)."""
        import ffmpeg as ffmpeg_lib

        frames = make_frames(30)
        bboxes = make_bboxes_with_motion(30)

        output_path, file_size = encoder.encode_segment(
            frames=frames,
            bboxes_per_frame=bboxes,
            camera_id="cam_test",
            fps=30,
        )

        assert file_size > 0, "Output file is empty"

        # ffmpeg.probe() will raise if the file is corrupted
        probe = ffmpeg_lib.probe(output_path)
        video_streams = [s for s in probe["streams"] if s["codec_type"] == "video"]
        assert len(video_streams) >= 1, "No video stream found in output"

    def test_output_smaller_than_raw_input(self, encoder):
        """Compressed output must be smaller than the uncompressed raw frames."""
        frames = make_frames(10, height=120, width=160)
        bboxes = make_bboxes_with_motion(10)

        output_path, file_size = encoder.encode_segment(
            frames=frames,
            bboxes_per_frame=bboxes,
            camera_id="cam_test",
            fps=30,
        )

        # Raw size = num_frames * height * width * 3 bytes (BGR)
        raw_size = len(frames) * 120 * 160 * 3
        assert file_size < raw_size, (
            f"Compressed file ({file_size} bytes) is not smaller than raw "
            f"({raw_size} bytes) — something is wrong with encoding"
        )

    def test_returns_tuple_of_path_and_size(self, encoder):
        """encode_segment() must return (str, int)."""
        frames = make_frames(30)
        bboxes = make_bboxes_empty(30)

        result = encoder.encode_segment(
            frames=frames,
            bboxes_per_frame=bboxes,
            camera_id="cam_bg",
            fps=30,
        )

        assert isinstance(result, tuple), "Return value should be a tuple"
        assert len(result) == 2, "Return tuple should have 2 elements"
        path, size = result
        assert isinstance(path, str), "First element (path) should be a string"
        assert isinstance(size, int), "Second element (size) should be an int"

    def test_no_targets_uses_background_crf(self, encoder, tmp_path):
        """A static scene (no bboxes) should produce a smaller file than one with targets."""
        frames = make_frames(30)

        _, size_with_targets = encoder.encode_segment(
            frames=frames,
            bboxes_per_frame=make_bboxes_with_motion(30),
            camera_id="cam_fg",
            fps=30,
        )

        _, size_no_targets = encoder.encode_segment(
            frames=frames,
            bboxes_per_frame=make_bboxes_empty(30),
            camera_id="cam_bg",
            fps=30,
        )

        assert size_no_targets <= size_with_targets, (
            "Background-only segment should be smaller than or equal to "
            "a segment with foreground targets"
        )

    def test_metadata_written_to_database(self, encoder):
        """After encode_segment(), metadata.db must contain a matching row."""
        frames = make_frames(30)
        bboxes = make_bboxes_with_motion(30)

        output_path, file_size = encoder.encode_segment(
            frames=frames,
            bboxes_per_frame=bboxes,
            camera_id="cam_db_test",
            fps=30,
        )

        conn = sqlite3.connect(encoder.db_path)
        rows = conn.execute(
            "SELECT filename, camera_id, has_targets, file_size FROM segments "
            "WHERE camera_id = 'cam_db_test'"
        ).fetchall()
        conn.close()

        assert len(rows) == 1, "Expected exactly one metadata row"
        filename, camera_id, has_targets, db_file_size = rows[0]
        assert camera_id == "cam_db_test"
        assert has_targets == 1
        assert db_file_size == file_size

    def test_empty_frames_raises_error(self, encoder):
        """Passing an empty frames list should raise ValueError."""
        with pytest.raises(ValueError, match="empty"):
            encoder.encode_segment(
                frames=[],
                bboxes_per_frame=[],
                camera_id="cam_test",
            )

    def test_mismatched_bboxes_raises_error(self, encoder):
        """bboxes_per_frame length not matching frames length should raise ValueError."""
        frames = make_frames(10)
        wrong_bboxes = make_bboxes_empty(5)  # wrong length

        with pytest.raises(ValueError, match="must match"):
            encoder.encode_segment(
                frames=frames,
                bboxes_per_frame=wrong_bboxes,
                camera_id="cam_test",
            )


class TestGetFileSize:

    def test_returns_correct_size(self, encoder, tmp_path):
        """get_file_size() should match the actual file size on disk."""
        test_file = tmp_path / "dummy.bin"
        test_file.write_bytes(b"x" * 1234)

        assert encoder.get_file_size(str(test_file)) == 1234

    def test_returns_zero_for_missing_file(self, encoder, tmp_path):
        """get_file_size() should return 0 if the file does not exist."""
        missing = str(tmp_path / "does_not_exist.mp4")
        assert encoder.get_file_size(missing) == 0

    def test_matches_encode_segment_return_value(self, encoder):
        """File size returned by encode_segment should match get_file_size."""
        frames = make_frames(30)
        bboxes = make_bboxes_with_motion(30)

        output_path, returned_size = encoder.encode_segment(
            frames=frames,
            bboxes_per_frame=bboxes,
            camera_id="cam_size_check",
            fps=30,
        )

        assert encoder.get_file_size(output_path) == returned_size


class TestBackgroundSegmentDB:

    def test_background_segment_db_row(self, encoder):
        """A static scene (no targets) should write has_targets=0 and roi_count=0 to DB."""
        frames = make_frames(10)
        bboxes = make_bboxes_empty(10)

        encoder.encode_segment(
            frames=frames,
            bboxes_per_frame=bboxes,
            camera_id="cam_bg_db",
            fps=30,
        )

        conn = sqlite3.connect(encoder.db_path)
        rows = conn.execute(
            "SELECT has_targets, roi_count FROM segments WHERE camera_id = 'cam_bg_db'"
        ).fetchall()
        conn.close()

        assert len(rows) == 1
        has_targets, roi_count = rows[0]
        assert has_targets == 0
        assert roi_count == 0
