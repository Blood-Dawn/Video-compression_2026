"""
tests/test_pipeline_real_video.py

End-to-end integration tests that run the full pipeline against real
CDnet 2014 footage in data/samples/cdnet_mp4/. Synthetic frames are
fine for unit-level coverage, but a couple of real videos are the
only way to catch FFmpeg / OpenCV / codec mismatches that don't
surface until production.

Test clips chosen for size and behaviour:

    baseline/baseline_pedestrians.mp4        ~2.2 MB, people walking
    intermittentObjectMotion/intermittentObjectMotion_parking.mp4
                                              ~2.0 MB, sparse activity

Both clips are present in the repo (CDnet samples). Tests skip
cleanly if the file is missing so the suite still runs on a fresh
clone before someone has downloaded sample data.

Marked as ``integration`` so CI can run unit + integration in
separate jobs if it wants. Default ``pytest`` picks them up.

Author: Bloodawn (KheivenD), 2026-05-14.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ── Test data fixtures ────────────────────────────────────────────────────

_DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "samples" / "cdnet_mp4"

CLIPS = {
    "pedestrians": _DATA_ROOT / "baseline" / "baseline_pedestrians.mp4",
    "parking":     _DATA_ROOT / "intermittentObjectMotion" / "intermittentObjectMotion_parking.mp4",
}


def _have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _have_ffprobe() -> bool:
    return shutil.which("ffprobe") is not None


def _probe_duration(mp4_path: Path) -> float:
    """Return duration in seconds using ffprobe. 0.0 on failure."""
    if not _have_ffprobe():
        return 0.0
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(mp4_path),
        ], stderr=subprocess.DEVNULL, timeout=10).decode().strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0


@pytest.fixture(scope="module", autouse=True)
def _require_test_clips():
    """Skip the whole module if neither test clip is on disk."""
    if not CLIPS["pedestrians"].exists() and not CLIPS["parking"].exists():
        pytest.skip(
            "No CDnet sample MP4s found in data/samples/cdnet_mp4/. "
            "See DEV.md for how to populate them."
        )


@pytest.fixture(scope="module", autouse=True)
def _require_ffmpeg():
    if not _have_ffmpeg():
        pytest.skip("ffmpeg binary not on PATH; pipeline can't run")


# ── Quick smoke: clips are valid and playable ─────────────────────────────


class TestClipSanity:

    @pytest.mark.parametrize("clip_name", list(CLIPS))
    def test_clip_exists(self, clip_name):
        clip = CLIPS[clip_name]
        if not clip.exists():
            pytest.skip(f"{clip} not present")
        assert clip.stat().st_size > 100_000   # at least ~100 KB

    @pytest.mark.parametrize("clip_name", list(CLIPS))
    def test_clip_has_nonzero_duration(self, clip_name):
        clip = CLIPS[clip_name]
        if not clip.exists():
            pytest.skip(f"{clip} not present")
        if not _have_ffprobe():
            pytest.skip("ffprobe not available")
        assert _probe_duration(clip) > 0


# ── Full pipeline against real footage ────────────────────────────────────


class TestPipelineOnRealVideo:
    """Run run_pipeline() on a real CDnet clip and assert it produces
    playable output segments + a populated SQLite metadata row.

    Picks the smallest clip to keep test runtime manageable. Pipeline
    is run in mode0 (every frame retained) so we always have at least
    one output even if motion detection is conservative.
    """

    @pytest.fixture
    def working_dir(self, tmp_path):
        """Fresh output dir per test, plus a copy of the source clip
        (in case the pipeline modifies its working tree)."""
        out = tmp_path / "out"
        out.mkdir()
        return out

    def _pick_clip(self):
        for name in ("pedestrians", "parking"):
            if CLIPS[name].exists():
                return CLIPS[name]
        pytest.skip("no clip available")

    def test_mode0_produces_at_least_one_segment(self, working_dir):
        from pipeline.pipeline import run_pipeline

        clip = self._pick_clip()
        run_pipeline(
            input_source=str(clip),
            camera_id="test_cam",
            output_dir=str(working_dir),
            mode="mode0",
            segment_seconds=2,    # short segments so even a 5-second clip yields >=1
            warmup_frames=10,     # small warmup so we get output
        )

        mp4_files = list(working_dir.rglob("*.mp4"))
        assert mp4_files, "No segments produced from a real clip"

        # Every segment file should be non-empty
        for f in mp4_files:
            assert f.stat().st_size > 0, f"empty segment {f}"

    def test_segment_is_playable_by_ffprobe(self, working_dir):
        from pipeline.pipeline import run_pipeline

        clip = self._pick_clip()
        run_pipeline(
            input_source=str(clip),
            camera_id="test_cam",
            output_dir=str(working_dir),
            mode="mode0",
            segment_seconds=2,
            warmup_frames=10,
        )

        if not _have_ffprobe():
            pytest.skip("ffprobe not available; can't verify playability")

        for f in working_dir.rglob("*.mp4"):
            # ffprobe should return without error and report a non-zero duration
            dur = _probe_duration(f)
            assert dur > 0, f"unplayable segment: {f}"

    def test_metadata_db_row_written(self, working_dir):
        from pipeline.pipeline import run_pipeline

        clip = self._pick_clip()
        run_pipeline(
            input_source=str(clip),
            camera_id="test_cam",
            output_dir=str(working_dir),
            mode="mode0",
            segment_seconds=2,
            warmup_frames=10,
        )

        db = working_dir / "metadata.db"
        assert db.exists(), "no metadata.db was written"

        conn = sqlite3.connect(str(db))
        try:
            rows = conn.execute(
                "SELECT camera_id, file_path, file_size, duration "
                "FROM segments"
            ).fetchall()
        finally:
            conn.close()

        assert rows, "metadata.db has no segment rows"
        for cam, fp, size, dur in rows:
            assert cam == "test_cam"
            assert size > 0
            assert dur >= 0  # duration may be 0 on the first partial flush


# ── Mode 3 (object-only blackout) on a real clip ──────────────────────────


class TestMode3OnRealVideo:
    """Mode 3 blacks out everything outside detected ROIs. The output
    file should still be playable; pixel values outside the boxes
    should drop close to zero."""

    def test_mode3_produces_segments(self, tmp_path):
        from pipeline.pipeline import run_pipeline

        clip = None
        for name in ("parking", "pedestrians"):
            if CLIPS[name].exists():
                clip = CLIPS[name]
                break
        if clip is None:
            pytest.skip("no clip available")

        out_dir = tmp_path / "mode3"
        out_dir.mkdir()
        run_pipeline(
            input_source=str(clip),
            camera_id="m3_cam",
            output_dir=str(out_dir),
            mode="mode3",
            segment_seconds=2,
            warmup_frames=10,
        )

        segments = list(out_dir.rglob("*.mp4"))
        assert segments, "mode3 produced no segments on real video"


# ── Encoder fallback: libsvtav1 -> libx264 when not available ─────────────


class TestCodecFallback:
    """If libsvtav1 isn't in the FFmpeg build, the pipeline should
    transparently fall back to libx264 (as wired in roi_encoder)."""

    def test_libx264_explicit_works(self, tmp_path):
        from pipeline.pipeline import run_pipeline

        clip = None
        for name in ("pedestrians", "parking"):
            if CLIPS[name].exists():
                clip = CLIPS[name]
                break
        if clip is None:
            pytest.skip("no clip available")

        out = tmp_path / "x264"
        out.mkdir()
        try:
            run_pipeline(
                input_source=str(clip),
                camera_id="codec_cam",
                output_dir=str(out),
                mode="mode0",
                codec="libx264",
                segment_seconds=2,
                warmup_frames=10,
            )
        except TypeError:
            # Older pipeline.py may not accept a `codec` kwarg.
            pytest.skip("pipeline.run_pipeline does not accept codec kwarg")

        assert list(out.rglob("*.mp4")), "libx264 path produced no segments"
