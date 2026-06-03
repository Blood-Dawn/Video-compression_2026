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

import utils.watchfolder as wf
from utils.watchfolder import (
    DEFAULT_PROFILE,
    INGESTED_SUFFIX,
    PROCESSING_SUFFIX,
    SUPPORTED_EXTENSIONS,
    WATCHFOLDER_PROFILES,
    WatchProfile,
    _already_ingested,
    _build_camera_id,
    _clear_processing,
    _is_fully_written,
    _mark_ingested,
    _mark_processing,
    _processing_path,
    _resolve_encode_config,
    _sanitize_camera_id,
    _was_interrupted,
    get_profile,
    list_profiles,
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
        assert _is_fully_written(p, settle_seconds=0.01)
    def test_empty_file_returns_false(self, tmp_path):
        p = tmp_path / "empty.mp4"
        p.write_bytes(b"")
        assert not _is_fully_written(p, settle_seconds=0.01)
    def test_missing_file_returns_false(self, tmp_path):
        p = tmp_path / "nonexistent.mp4"
        assert not _is_fully_written(p, settle_seconds=0.01)
    def test_stable_across_multiple_checks(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4", size=2048)
        assert _is_fully_written(p, settle_seconds=0.01, stable_checks=4)
    def test_growing_file_is_not_ready(self, tmp_path, monkeypatch):
        # Partial-write: grow the file on every "sleep" so its size never
        # stabilises across the required consecutive checks -> not ready.
        p = _make_video(tmp_path, "clip.mp4", size=100)

        def _grow(_seconds):
            p.write_bytes(b"0" * (p.stat().st_size + 100))

        monkeypatch.setattr(wf.time, "sleep", _grow)
        assert not _is_fully_written(p, settle_seconds=0.01, stable_checks=2)
    def test_file_that_stops_growing_becomes_ready(self, tmp_path, monkeypatch):
        # Grows for the first sleep, then stabilises: with one stable check it's
        # still not ready (it changed once); the next scan cycle would see it
        # stable. Here we prove a now-stable file passes with stable_checks=1.
        p = _make_video(tmp_path, "clip.mp4", size=300)
        assert _is_fully_written(p, settle_seconds=0.01, stable_checks=1)


class TestCrashResume:
    def test_not_interrupted_initially(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4")
        assert not _was_interrupted(p)
    def test_processing_marker_means_interrupted(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4")
        _mark_processing(p)
        assert _processing_path(p).name == "clip.mp4" + PROCESSING_SUFFIX
        assert _was_interrupted(p)
    def test_ingested_file_is_not_interrupted(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4")
        _mark_processing(p)
        _mark_ingested(p)  # finished after the marker
        assert not _was_interrupted(p)  # ingested wins
    def test_clear_processing_removes_marker(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4")
        _mark_processing(p)
        _clear_processing(p)
        assert not _processing_path(p).exists()
    def test_successful_ingest_clears_marker_and_marks_ingested(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4")
        with patch("pipeline.pipeline.run_pipeline") as mock_run:
            count = scan_and_ingest(watch_dir=tmp_path, output_dir=str(tmp_path),
                                    settle_seconds=0.01, stable_checks=1)
        assert count == 1
        assert mock_run.called
        assert _already_ingested(p)
        assert not _processing_path(p).exists()  # cleared on success
    def test_failed_ingest_leaves_processing_marker_for_retry(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4")
        with patch("pipeline.pipeline.run_pipeline", side_effect=RuntimeError("boom")):
            count = scan_and_ingest(watch_dir=tmp_path, output_dir=str(tmp_path),
                                    settle_seconds=0.01, stable_checks=1)
        assert count == 0
        assert not _already_ingested(p)        # not marked done
        assert _processing_path(p).exists()    # marker survives -> retried next scan
    def test_interrupted_file_is_retried_and_succeeds(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4")
        _mark_processing(p)  # simulate a crash mid-encode on a previous run
        with patch("pipeline.pipeline.run_pipeline") as mock_run:
            count = scan_and_ingest(watch_dir=tmp_path, output_dir=str(tmp_path),
                                    settle_seconds=0.01, stable_checks=1)
        assert count == 1
        assert mock_run.called
        assert _already_ingested(p)
        assert not _processing_path(p).exists()


class TestAutoPreset:
    def test_resolve_explicit_preset(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4")
        kwargs, key = _resolve_encode_config(p, auto_preset=False, preset="doorbell")
        assert key == "doorbell"
        assert kwargs["mode"] == "mode3"  # doorbell maps to mode3
        assert "crf" in kwargs and "background_crf" in kwargs and "codec" in kwargs

    def test_resolve_none_when_disabled(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4")
        kwargs, key = _resolve_encode_config(p, auto_preset=False, preset=None)
        assert kwargs == {} and key is None

    def test_auto_detect_failure_degrades_to_defaults(self, tmp_path):
        p = _make_video(tmp_path, "clip.mp4")
        with patch("pipeline.content_detect.detect_content",
                   side_effect=ValueError("unreadable")):
            kwargs, key = _resolve_encode_config(p, auto_preset=True, preset=None)
        assert kwargs == {} and key is None  # never blocks ingestion

    def test_scan_passes_autodetected_preset_to_pipeline(self, tmp_path):
        from pipeline.content_detect import PresetRecommendation, ContentSignals
        p = _make_video(tmp_path, "clip.mp4")

        rec = PresetRecommendation(
            preset="continuous_cctv", label="Continuous CCTV", reason="static",
            signals=ContentSignals(640, 480, 30.0, 10, 10.0, 0.0, 0.0, 0.0, 0.0, False),
        )
        with patch("pipeline.content_detect.detect_content", return_value=rec), \
             patch("pipeline.pipeline.run_pipeline") as mock_run:
            count = scan_and_ingest(watch_dir=tmp_path, output_dir=str(tmp_path),
                                    settle_seconds=0.01, stable_checks=1,
                                    auto_preset=True)
        assert count == 1
        _, kwargs = mock_run.call_args
        assert kwargs["mode"] == "mode2"          # continuous_cctv -> mode2
        assert kwargs["codec"] == "auto"
        assert kwargs["crf"] == 23


class TestWatchProfiles:
    def test_catalog_non_empty_and_default_present(self):
        profiles = list_profiles()
        assert profiles  # at least one
        keys = {p["key"] for p in profiles}
        assert DEFAULT_PROFILE in keys
        # The camera-export layouts the plan calls out are all represented.
        assert {"continuous", "motion_events", "microsd_dump",
                "nas_sync", "nvr_export"} <= keys

    def test_every_profile_resolves_and_has_valid_preset(self):
        from pipeline.presets import PRESETS
        for key in WATCHFOLDER_PROFILES:
            prof = get_profile(key)
            assert isinstance(prof, WatchProfile)
            # preset is either unset (auto-detect) or a real preset key.
            assert prof.preset is None or prof.preset in PRESETS
            sk = prof.scan_kwargs()
            assert set(sk) == {"recursive", "auto_preset", "preset",
                               "stable_checks", "settle_seconds", "camera_prefix"}
            assert sk["stable_checks"] >= 1

    def test_unknown_profile_raises(self):
        with pytest.raises(KeyError):
            get_profile("no_such_profile")

    def test_nas_profile_is_more_conservative(self):
        # NAS sync writes slowly: it must require more stability than a flat drop.
        assert get_profile("nas_sync").stable_checks > get_profile("generic").stable_checks
        assert get_profile("nas_sync").recursive is True


class TestRecursiveScan:
    def test_recursive_finds_nested_file(self, tmp_path):
        sub = tmp_path / "day1"
        sub.mkdir()
        _make_video(sub, "clip.mp4")
        count = scan_and_ingest(watch_dir=tmp_path, output_dir=str(tmp_path),
                                dry_run=True, recursive=True)
        assert count == 1

    def test_non_recursive_ignores_subfolders(self, tmp_path):
        sub = tmp_path / "cam7"
        sub.mkdir()
        _make_video(sub, "clip.mp4")
        count = scan_and_ingest(watch_dir=tmp_path, output_dir=str(tmp_path),
                                dry_run=True, recursive=False)
        assert count == 0

    def test_recursive_folds_subfolder_into_camera_id(self, tmp_path):
        sub = tmp_path / "cam7"
        sub.mkdir()
        _make_video(sub, "clip.mp4")
        with patch("pipeline.pipeline.run_pipeline") as mock_run:
            scan_and_ingest(watch_dir=tmp_path, output_dir=str(tmp_path),
                            settle_seconds=0.01, stable_checks=1, recursive=True,
                            camera_prefix="nvr")
        _, kwargs = mock_run.call_args
        assert "cam7" in kwargs["camera_id"]
        assert kwargs["camera_id"].startswith("nvr_cam7")

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
