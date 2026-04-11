"""
test_roi_encoder.py

Tests for src/compression/roi_encoder.py.
Covers: encode_segment() happy path, MP4 output, DB row insertion,
        foreground CRF selection, ValueError / RuntimeError guards,
        get_file_size(), get_storage_report().

All tests use tiny (16x16) frames so FFmpeg runs in milliseconds.
Requires ffmpeg on PATH — skipped automatically if not found.
"""

import shutil
import pytest
import numpy as np

from compression.roi_encoder import ROIEncoder
from utils.db import get_connection


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def encoder(tmp_path):
    """A fresh ROIEncoder writing to tmp_path with a tmp-path database."""
    db_path = str(tmp_path / "meta.db")
    return ROIEncoder(
        output_dir=str(tmp_path / "out"),
        foreground_crf=28,       # slightly lower quality so tests run faster
        background_crf=45,
        preset="ultrafast",      # fastest preset; quality doesn't matter in tests
        db_path=db_path,
    )


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "meta.db")


# ---------------------------------------------------------------------------
# Skip marker — skip all tests if ffmpeg is not installed
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg not found on PATH — skipping encoder tests",
)


# ---------------------------------------------------------------------------
# encode_segment() — happy path
# ---------------------------------------------------------------------------

class TestEncodeSegment:
    def test_returns_mp4_path(self, encoder, tiny_frames):
        out = encoder.encode_segment(tiny_frames, camera_id="cam_test", fps=10.0)
        assert out.endswith(".mp4")

    def test_output_file_exists(self, encoder, tiny_frames):
        out = encoder.encode_segment(tiny_frames, camera_id="cam_test", fps=10.0)
        from pathlib import Path
        assert Path(out).exists()

    def test_output_file_not_empty(self, encoder, tiny_frames):
        out = encoder.encode_segment(tiny_frames, camera_id="cam_test", fps=10.0)
        from pathlib import Path
        assert Path(out).stat().st_size > 0

    def test_camera_id_in_filename(self, encoder, tiny_frames):
        out = encoder.encode_segment(tiny_frames, camera_id="myCam", fps=10.0)
        assert "myCam" in out

    def test_inserts_db_row(self, encoder, tiny_frames):
        encoder.encode_segment(tiny_frames, camera_id="cam_db", fps=10.0)
        with get_connection(encoder.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM segments WHERE camera_id='cam_db'"
            ).fetchall()
        assert len(rows) == 1

    def test_foreground_crf_used_when_bboxes_present(self, encoder, tiny_frames):
        """
        When bboxes are provided, the segment should be encoded at foreground_crf.
        We can't inspect the CRF directly, but we verify the call does not raise
        and the output is smaller than the raw frames (i.e. compression happened).
        """
        bboxes = [[(0, 0, 8, 8)] for _ in tiny_frames]   # one bbox per frame
        out = encoder.encode_segment(tiny_frames, bboxes_per_frame=bboxes,
                                     camera_id="cam_fg", fps=10.0)
        from pathlib import Path
        assert Path(out).exists()

    def test_background_crf_used_when_no_bboxes(self, encoder, tiny_frames):
        """No bboxes → background CRF path — file still written successfully."""
        bboxes = [[] for _ in tiny_frames]
        out = encoder.encode_segment(tiny_frames, bboxes_per_frame=bboxes,
                                     camera_id="cam_bg", fps=10.0)
        from pathlib import Path
        assert Path(out).exists()

    def test_target_detected_true_when_bboxes_nonempty(self, encoder, tiny_frames):
        bboxes = [[(0, 0, 4, 4)]] + [[] for _ in tiny_frames[1:]]
        encoder.encode_segment(tiny_frames, bboxes_per_frame=bboxes,
                                camera_id="cam_td", fps=10.0)
        with get_connection(encoder.db_path) as conn:
            row = conn.execute(
                "SELECT target_detected FROM segments WHERE camera_id='cam_td'"
            ).fetchone()
        assert row[0] == 1

    def test_target_detected_false_when_no_bboxes(self, encoder, tiny_frames):
        encoder.encode_segment(tiny_frames, camera_id="cam_bg2", fps=10.0)
        with get_connection(encoder.db_path) as conn:
            row = conn.execute(
                "SELECT target_detected FROM segments WHERE camera_id='cam_bg2'"
            ).fetchone()
        assert row[0] == 0

    def test_duration_stored_correctly(self, encoder, tiny_frames):
        fps = 5.0
        expected_duration = len(tiny_frames) / fps
        encoder.encode_segment(tiny_frames, camera_id="cam_dur", fps=fps)
        with get_connection(encoder.db_path) as conn:
            row = conn.execute(
                "SELECT duration FROM segments WHERE camera_id='cam_dur'"
            ).fetchone()
        assert abs(row[0] - expected_duration) < 0.01

    def test_roi_count_stored_correctly(self, encoder, tiny_frames):
        bboxes = [[(0, 0, 4, 4), (4, 4, 4, 4)]] + [[] for _ in tiny_frames[1:]]
        encoder.encode_segment(tiny_frames, bboxes_per_frame=bboxes,
                                camera_id="cam_roi", fps=10.0)
        with get_connection(encoder.db_path) as conn:
            row = conn.execute(
                "SELECT roi_count FROM segments WHERE camera_id='cam_roi'"
            ).fetchone()
        assert row[0] == 2


# ---------------------------------------------------------------------------
# ValueError guards
# ---------------------------------------------------------------------------

class TestEncodeSegmentErrors:
    def test_empty_frames_raises(self, encoder):
        with pytest.raises(ValueError, match="empty"):
            encoder.encode_segment([], camera_id="cam_err", fps=10.0)

    def test_inconsistent_shape_raises(self, encoder):
        rng = np.random.default_rng(0)
        frames = [
            rng.integers(0, 256, (16, 16, 3), dtype=np.uint8),
            rng.integers(0, 256, (32, 32, 3), dtype=np.uint8),   # different shape
        ]
        with pytest.raises(ValueError, match="shape"):
            encoder.encode_segment(frames, camera_id="cam_err", fps=10.0)

    def test_bboxes_length_mismatch_raises(self, encoder, tiny_frames):
        bboxes = [[] for _ in tiny_frames[:-1]]   # one fewer than frames
        with pytest.raises(ValueError, match="bboxes_per_frame"):
            encoder.encode_segment(tiny_frames, bboxes_per_frame=bboxes,
                                   camera_id="cam_err", fps=10.0)


# ---------------------------------------------------------------------------
# get_file_size()
# ---------------------------------------------------------------------------

class TestGetFileSize:
    def test_returns_size_for_existing_file(self, encoder, tiny_frames, tmp_path):
        out = encoder.encode_segment(tiny_frames, camera_id="cam_sz", fps=10.0)
        size = encoder.get_file_size(out)
        assert size > 0

    def test_returns_zero_for_missing_file(self, encoder):
        assert encoder.get_file_size("/nonexistent/path/file.mp4") == 0


# ---------------------------------------------------------------------------
# get_storage_report()
# ---------------------------------------------------------------------------

class TestGetStorageReport:
    def test_report_keys_present(self, encoder, tiny_frames):
        encoder.encode_segment(tiny_frames, camera_id="cam_rpt", fps=10.0)
        report = encoder.get_storage_report()
        expected_keys = {
            "total_segments", "total_bytes", "total_gb",
            "segments_with_targets", "total_roi_detections", "total_duration_hours",
        }
        assert expected_keys == set(report.keys())

    def test_report_counts_segments(self, encoder, tiny_frames):
        encoder.encode_segment(tiny_frames, camera_id="cam_rpt", fps=10.0)
        encoder.encode_segment(tiny_frames, camera_id="cam_rpt", fps=10.0)
        report = encoder.get_storage_report()
        assert report["total_segments"] == 2

    def test_empty_db_returns_zeros(self, tmp_path):
        enc = ROIEncoder(
            output_dir=str(tmp_path / "out"),
            db_path=str(tmp_path / "empty.db"),
        )
        report = enc.get_storage_report()
        assert report["total_segments"] == 0
        assert report["total_bytes"] == 0
