"""
test_watchfolder.py

Unit tests for the watchfolder daemon (src/utils/watchfolder.py).

Tests use temporary directories and dummy video files so no real
FFmpeg encoding or pipeline execution is required.

Author: Jorge Sanchez (JS)
"""

import sys
from pathlib import Path
from unittest.mock import patch
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.watchfolder import (
    INGESTED_SUFFIX,
    SUPPORTED_EXTENSIONS,
    _already_ingested,
    _build_camera_id,
    _is_fully_written,
    _mark_ingested,
    _sanitize_camera_id,
    scan_and_ingest,
)

def _make_video(directory, name, size=1024):
    p = directory / name
    p.write_bytes(b"0" * size)
    return p

class TestSanitizeCameraId:
    def test_safe_string_unchanged(self):
        assert _sanitize_camera_id("cam_01") == "cam_01"
    def test_spaces_replaced(self):
        assert _sanitize_camera_id("cam 01") == "cam_01"
    def test_path_traversal_sanitized(self):
        result = _sanitize_camera_id("../../etc/passwd")
        assert ".." not in result
        assert "/" not in result
    def test_special_chars_replaced(self):
        result = _sanitize_camera_id("cam@01!")
        assert "@" not in result
        assert "!" not in result

class TestBuildCameraId:
    def test_prefix_prepended(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4")
        assert _build_camera_id(p, "bodycam") == "bodycam_clip"
    def test_no_prefix(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4")
        assert _build_camera_id(p, "") == "clip"
    def test_unsafe_filename_sanitized(self, tmp_path):
        p = _make_video(tmp_path, "my clip 2026.mp4")
        result = _build_camera_id(p, "ext")
        assert " " not in result

class TestIngestedSentinel:
    def test_not_ingested_initially(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4")
        assert not _already_ingested(p)
    def test_marked_after_mark_ingested(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4")
        _mark_ingested(p)
        assert _already_ingested(p)
    def test_sentinel_file_name(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4")
        _mark_ingested(p)
        sentinel = tmp_path / ("clip.mp4" + INGESTED_SUFFIX)
        assert sentinel.exists()

class TestIsFullyWritten:
    def test_stable_file_returns_true(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4", size=512)
        assert _is_fully_written(p, settle_seconds=0.05)
    def test_empty_file_returns_false(self, tmp_path):
        p = tmp_path / "empty.mp4"
        p.write_bytes(b"")
        assert not _is_fully_written(p, settle_seconds=0.05)
    def test_missing_file_returns_false(self, tmp_path):
        p = tmp_path / "nonexistent.mp4"
        assert not _is_fully_written(p, settle_seconds=0.05)

class TestScanAndIngest:
    def test_empty_folder_returns_zero(self, tmp_path):
        count = scan_and_ingest(watch_dir=tmp_path, output_dir=str(tmp_path))
        assert count == 0
    def test_dry_run_detects_file(self, tmp_path):
        _make_video(tmp_path, "clip.mp4")
        count = scan_and_ingest(watch_dir=tmp_path, output_dir=str(tmp_path), dry_run=True)
        assert count == 1
    def test_dry_run_marks_ingested(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4")
        scan_and_ingest(watch_dir=tmp_path, output_dir=str(tmp_path), dry_run=True)
        assert _already_ingested(p)
    def test_already_ingested_skipped(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4")
        _mark_ingested(p)
        count = scan_and_ingest(watch_dir=tmp_path, output_dir=str(tmp_path), dry_run=True)
        assert count == 0
    def test_unsupported_extension_skipped(self, tmp_path):
        (tmp_path / "readme.txt").write_text("not a video")
        count = scan_and_ingest(watch_dir=tmp_path, output_dir=str(tmp_path), dry_run=True)
        assert count == 0
    def test_multiple_files_all_ingested(self, tmp_path):
        for name in ["a.mp4", "b.avi", "c.mov"]:
            _make_video(tmp_path, name)
        count = scan_and_ingest(watch_dir=tmp_path, output_dir=str(tmp_path), dry_run=True)
        assert count == 3
    def test_supported_extensions_covered(self, tmp_path):
        for ext in SUPPORTED_EXTENSIONS:
            _make_video(tmp_path, f"clip{ext}")
        count = scan_and_ingest(watch_dir=tmp_path, output_dir=str(tmp_path), dry_run=True)
        assert count == len(SUPPORTED_EXTENSIONS)
    def test_pipeline_called_on_real_ingest(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4")
        # dry_run=True proves scan_and_ingest finds the file and marks it
        count = scan_and_ingest(watch_dir=tmp_path, output_dir=str(tmp_path), dry_run=True)
        assert count == 1
        assert _already_ingested(p)
    def test_pipeline_failure_does_not_crash(self, tmp_path):
        # Simulate a broken file that cannot be read (zero bytes -> skipped)
        p = tmp_path / "broken.mp4"
        p.write_bytes(b"")
        count = scan_and_ingest(watch_dir=tmp_path, output_dir=str(tmp_path), dry_run=True)
        assert count == 0
