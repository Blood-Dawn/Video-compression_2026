"""
tests/test_pipeline_stress.py

Milestone 2 - Section 2.5: Pipeline Memory and Storage Stress Test

Simulates continuous footage by looping synthetic segments.
Verifies:
  - Pipeline encodes all segments without crash
  - Memory does not grow unbounded (tracked via tracemalloc peak, not just endpoints)
  - Storage extrapolation math is documented

Duration is configurable via STRESS_DURATION_S environment variable so CI
can run a short smoke test without the full 1-hour wall time:

    STRESS_DURATION_S=120 pytest tests/test_pipeline_stress.py -v -s -m slow

Default (no env var) runs the full 1-hour simulation for sign-off runs.

Mark: tests decorated with @pytest.mark.slow are excluded from the normal
pytest run. Run explicitly when needed:

    pytest tests/test_pipeline_stress.py -v -s -m slow

Author: Jorge Sanchez
Fixes applied by KD (Apr 13 2026):
  - Removed sys.path.insert — conftest.py adds src/ to sys.path for all tests
  - SIMULATED_DURATION_S now reads STRESS_DURATION_S env var (default 3600)
    so CI / quick runs don't have to wait a full hour
  - Memory growth check now uses peak tracemalloc reading, not just
    final vs initial, so transient spikes are caught
"""

import os
import time
import sqlite3
import tempfile
import tracemalloc
import numpy as np
import pytest
from pathlib import Path

from compression.roi_encoder import ROIEncoder
from background_subtraction.background_subtraction import BackgroundSubtractor


# ---------------------------------------------------------------------------
# Configuration — override STRESS_DURATION_S for faster CI runs
# ---------------------------------------------------------------------------

SIMULATED_DURATION_S  = int(os.environ.get("STRESS_DURATION_S", 3600))
SEGMENT_DURATION_S    = 60
FPS                   = 30
FRAME_HEIGHT          = 240
FRAME_WIDTH           = 320
FRAMES_PER_SEGMENT    = FPS * SEGMENT_DURATION_S          # 1800 frames/segment
TOTAL_SEGMENTS        = max(1, SIMULATED_DURATION_S // SEGMENT_DURATION_S)

# Fail if tracemalloc peak grows more than this over baseline
MAX_MEMORY_GROWTH_MB  = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_synthetic_segment(segment_index: int, has_motion: bool = True):
    """
    Generate one synthetic segment worth of frames.

    Odd segments include a moving white rectangle (foreground).
    Even segments are static dark-gray (background only).
    """
    frames = []
    bboxes = []

    for i in range(FRAMES_PER_SEGMENT):
        frame = np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)
        frame[:] = (30, 30, 30)

        if has_motion:
            x = int((i / FRAMES_PER_SEGMENT) * (FRAME_WIDTH - 40))
            cv_bbox = (x, 80, 40, 60)
            frame[80:140, x:x + 40] = (200, 200, 200)
            bboxes.append([cv_bbox])
        else:
            bboxes.append([])

        frames.append(frame)

    return frames, bboxes


# ---------------------------------------------------------------------------
# Stress Test
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_pipeline_stress_one_hour():
    """
    Simulate SIMULATED_DURATION_S seconds of continuous footage through the
    encode pipeline. Verify no crash and no runaway memory growth.

    Memory check uses tracemalloc peak — catches transient spikes, not just
    the final vs. initial snapshot.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "metadata.db")
        encoder = ROIEncoder(
            output_dir=tmpdir,
            foreground_crf=23,
            background_crf=45,
            preset="ultrafast",
            db_path=db_path,
        )

        tracemalloc.start()
        baseline_mb = tracemalloc.get_traced_memory()[0] / 1024 / 1024

        segments_encoded = 0
        errors = []

        print(
            f"\nStarting stress test: {TOTAL_SEGMENTS} segments x {SEGMENT_DURATION_S}s each "
            f"(STRESS_DURATION_S={SIMULATED_DURATION_S})"
        )

        start_time = time.time()

        for seg_idx in range(TOTAL_SEGMENTS):
            try:
                has_motion = (seg_idx % 10) < 3   # 30% have motion

                frames, bboxes = make_synthetic_segment(seg_idx, has_motion=has_motion)

                output_path, file_size = encoder.encode_segment(
                    frames=frames,
                    bboxes_per_frame=bboxes,
                    camera_id="cam_stress",
                    fps=FPS,
                )

                segments_encoded += 1

                if seg_idx % 10 == 0:
                    current_mb = tracemalloc.get_traced_memory()[0] / 1024 / 1024
                    elapsed = time.time() - start_time
                    print(
                        f"  Segment {seg_idx + 1}/{TOTAL_SEGMENTS} | "
                        f"Memory: {current_mb:.1f} MB | "
                        f"Elapsed: {elapsed:.1f}s"
                    )

            except Exception as e:
                errors.append(f"Segment {seg_idx}: {e}")

        # Peak memory across the entire run (catches transient spikes)
        _current, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_mb = peak_bytes / 1024 / 1024
        memory_growth_mb = peak_mb - baseline_mb

        total_time = time.time() - start_time

        # --- Assertions ---

        assert len(errors) == 0, (
            f"Pipeline errors during stress test:\n" + "\n".join(errors)
        )
        assert segments_encoded == TOTAL_SEGMENTS, (
            f"Expected {TOTAL_SEGMENTS} segments, got {segments_encoded}"
        )
        assert memory_growth_mb < MAX_MEMORY_GROWTH_MB, (
            f"Peak memory grew {memory_growth_mb:.1f} MB above baseline "
            f"(limit {MAX_MEMORY_GROWTH_MB} MB) -- possible memory leak. "
            f"Peak: {peak_mb:.1f} MB, Baseline: {baseline_mb:.1f} MB"
        )

        conn = sqlite3.connect(db_path)
        row_count = conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
        conn.close()
        assert row_count == TOTAL_SEGMENTS, (
            f"Expected {TOTAL_SEGMENTS} DB rows, got {row_count}"
        )

        print(f"\nStress test passed.")
        print(f"  Segments encoded : {segments_encoded}")
        print(f"  Peak memory growth: {memory_growth_mb:.1f} MB")
        print(f"  Total wall time  : {total_time:.1f}s")


@pytest.mark.slow
def test_storage_extrapolation():
    """
    Verify storage extrapolation math for 60-day / 100-camera estimate.

    Encodes one foreground segment and one background segment, then projects
    storage requirements at scale using the measured file sizes.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "metadata.db")
        encoder = ROIEncoder(
            output_dir=tmpdir,
            foreground_crf=18,
            background_crf=45,
            preset="ultrafast",
            db_path=db_path,
        )

        fg_frames, fg_bboxes = make_synthetic_segment(0, has_motion=True)
        bg_frames, bg_bboxes = make_synthetic_segment(1, has_motion=False)

        _, fg_size = encoder.encode_segment(fg_frames, fg_bboxes, "cam_fg", fps=FPS)
        _, bg_size = encoder.encode_segment(bg_frames, bg_bboxes, "cam_bg", fps=FPS)

        segments_per_hour  = 3600 // SEGMENT_DURATION_S   # 60
        segments_per_day   = segments_per_hour * 24        # 1440
        fg_ratio           = 0.30
        bg_ratio           = 0.70

        avg_bytes_per_day = (
            segments_per_day * fg_ratio * fg_size +
            segments_per_day * bg_ratio * bg_size
        )

        bytes_per_camera_per_week  = avg_bytes_per_day * 7
        bytes_100_cameras_60_days  = avg_bytes_per_day * 100 * 60

        gb_per_camera_per_week    = bytes_per_camera_per_week  / 1e9
        tb_100_cameras_60_days    = bytes_100_cameras_60_days  / 1e12

        print(f"\nStorage extrapolation:")
        print(f"  FG segment size          : {fg_size / 1024:.1f} KB")
        print(f"  BG segment size          : {bg_size / 1024:.1f} KB")
        print(f"  Per camera per week      : {gb_per_camera_per_week:.2f} GB")
        print(f"  100 cameras, 60 days     : {tb_100_cameras_60_days:.2f} TB")

        assert gb_per_camera_per_week < 100, (
            f"Per-camera weekly storage ({gb_per_camera_per_week:.1f} GB) "
            f"exceeds 100 GB -- check encoding settings"
        )

        raw_segment_bytes   = FRAME_WIDTH * FRAME_HEIGHT * 3 * FPS * SEGMENT_DURATION_S
        naive_h264_bytes    = raw_segment_bytes / 6
        avg_our_bytes       = fg_ratio * fg_size + bg_ratio * bg_size
        compression_vs_naive = naive_h264_bytes / avg_our_bytes

        print(f"  Compression vs naive H.264: {compression_vs_naive:.1f}x")

        assert compression_vs_naive >= 3.0, (
            f"Compression ratio vs naive H.264 ({compression_vs_naive:.1f}x) "
            f"is below 3x minimum"
        )
