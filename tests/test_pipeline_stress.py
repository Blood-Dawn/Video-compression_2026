"""
tests/test_pipeline_stress.py

Milestone 2 - Section 2.5: Pipeline Memory and Storage Stress Test

Simulates 1 hour of continuous footage by looping a short test clip.
Verifies:
  - Pipeline runs for 1 hour without crash
  - Memory does not grow unbounded (tracked via tracemalloc)
  - Storage extrapolation math is documented

Usage:
    pytest tests/test_pipeline_stress.py -v -s

Note: This test is slow by design (simulates 1 hour of footage).
      It is excluded from the normal pytest run via the @pytest.mark.slow marker.
      Run explicitly when needed.
"""

import os
import sys
import time
import sqlite3
import tempfile
import tracemalloc
import numpy as np
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from compression.roi_encoder import ROIEncoder
from background_subtraction.background_subtraction import BackgroundSubtractor


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SIMULATED_DURATION_S = 3600   # 1 hour
SEGMENT_DURATION_S = 60       # 1 segment per minute
FPS = 30
FRAME_HEIGHT = 240
FRAME_WIDTH = 320
FRAMES_PER_SEGMENT = FPS * SEGMENT_DURATION_S  # 1800 frames per segment
TOTAL_SEGMENTS = SIMULATED_DURATION_S // SEGMENT_DURATION_S  # 60 segments

# Memory growth limit — fail if peak grows more than this over the test
MAX_MEMORY_GROWTH_MB = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_synthetic_segment(segment_index: int, has_motion: bool = True):
    """
    Generate a synthetic segment of frames.
    Odd segments have a moving white rectangle to simulate foreground.
    Even segments are static to simulate background-only footage.
    """
    frames = []
    bboxes = []

    for i in range(FRAMES_PER_SEGMENT):
        frame = np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)
        frame[:] = (30, 30, 30)  # dark gray background

        if has_motion:
            # Simulate a moving object across the frame
            x = int((i / FRAMES_PER_SEGMENT) * (FRAME_WIDTH - 40))
            cv_bbox = (x, 80, 40, 60)  # x, y, w, h
            frame[80:140, x:x+40] = (200, 200, 200)  # white rectangle
            bboxes.append([cv_bbox])
        else:
            bboxes.append([])

        frames.append(frame)

    return frames, bboxes


def get_memory_mb() -> float:
    """Return current tracemalloc memory usage in MB."""
    current, peak = tracemalloc.get_traced_memory()
    return current / 1024 / 1024


# ---------------------------------------------------------------------------
# Stress Test
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_pipeline_stress_one_hour():
    """
    Simulate 1 hour of continuous footage through the encode pipeline.
    Verify no crash and no runaway memory growth.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "metadata.db")
        encoder = ROIEncoder(
            output_dir=tmpdir,
            foreground_crf=23,   # slightly relaxed for test speed
            background_crf=45,
            preset="ultrafast",
            db_path=db_path,
        )

        tracemalloc.start()
        memory_readings = []
        segments_encoded = 0
        errors = []

        print(f"\nStarting stress test: {TOTAL_SEGMENTS} segments x {SEGMENT_DURATION_S}s each")
        print(f"Simulated footage duration: {SIMULATED_DURATION_S / 3600:.1f} hours")

        start_time = time.time()

        for seg_idx in range(TOTAL_SEGMENTS):
            try:
                # Alternate between motion and static segments (70% static)
                has_motion = (seg_idx % 10) < 3  # 30% have motion

                frames, bboxes = make_synthetic_segment(seg_idx, has_motion=has_motion)

                output_path, file_size = encoder.encode_segment(
                    frames=frames,
                    bboxes_per_frame=bboxes,
                    camera_id="cam_stress",
                    fps=FPS,
                )

                segments_encoded += 1
                mem_mb = get_memory_mb()
                memory_readings.append(mem_mb)

                if seg_idx % 10 == 0:
                    elapsed = time.time() - start_time
                    print(f"  Segment {seg_idx+1}/{TOTAL_SEGMENTS} | "
                          f"Memory: {mem_mb:.1f} MB | "
                          f"Elapsed: {elapsed:.1f}s")

            except Exception as e:
                errors.append(f"Segment {seg_idx}: {e}")

        tracemalloc.stop()
        total_time = time.time() - start_time

        # --- Assertions ---

        assert len(errors) == 0, f"Pipeline errors during stress test:\n" + "\n".join(errors)
        assert segments_encoded == TOTAL_SEGMENTS, (
            f"Expected {TOTAL_SEGMENTS} segments, got {segments_encoded}"
        )

        # Memory growth check
        if len(memory_readings) >= 2:
            memory_growth = memory_readings[-1] - memory_readings[0]
            assert memory_growth < MAX_MEMORY_GROWTH_MB, (
                f"Memory grew by {memory_growth:.1f} MB over the test "
                f"(limit: {MAX_MEMORY_GROWTH_MB} MB) — possible memory leak"
            )

        # Database check
        conn = sqlite3.connect(db_path)
        row_count = conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
        conn.close()
        assert row_count == TOTAL_SEGMENTS, (
            f"Expected {TOTAL_SEGMENTS} DB rows, got {row_count}"
        )

        print(f"\nStress test passed.")
        print(f"  Segments encoded: {segments_encoded}")
        print(f"  Memory growth: {memory_readings[-1] - memory_readings[0]:.1f} MB")
        print(f"  Total wall time: {total_time:.1f}s")


@pytest.mark.slow
def test_storage_extrapolation():
    """
    Verify storage extrapolation math for 60-day / 100-camera estimate.
    This test encodes a small sample and uses the measured sizes to project
    storage requirements at scale.
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

        # Encode one foreground segment and one background segment
        fg_frames, fg_bboxes = make_synthetic_segment(0, has_motion=True)
        bg_frames, bg_bboxes = make_synthetic_segment(1, has_motion=False)

        _, fg_size = encoder.encode_segment(fg_frames, fg_bboxes, "cam_fg", fps=FPS)
        _, bg_size = encoder.encode_segment(bg_frames, bg_bboxes, "cam_bg", fps=FPS)

        # Extrapolation constants
        segments_per_hour = 3600 // SEGMENT_DURATION_S          # 60
        segments_per_day = segments_per_hour * 24                # 1440
        fg_ratio = 0.30                                          # 30% foreground
        bg_ratio = 0.70                                          # 70% background

        avg_bytes_per_day = (
            segments_per_day * fg_ratio * fg_size +
            segments_per_day * bg_ratio * bg_size
        )

        bytes_per_camera_per_week = avg_bytes_per_day * 7
        bytes_100_cameras_60_days = avg_bytes_per_day * 100 * 60

        gb_per_camera_per_week = bytes_per_camera_per_week / 1e9
        tb_100_cameras_60_days = bytes_100_cameras_60_days / 1e12

        print(f"\nStorage extrapolation:")
        print(f"  FG segment size: {fg_size / 1024:.1f} KB")
        print(f"  BG segment size: {bg_size / 1024:.1f} KB")
        print(f"  Per camera per week: {gb_per_camera_per_week:.2f} GB")
        print(f"  100 cameras, 60 days: {tb_100_cameras_60_days:.2f} TB")

        # Sanity check — should be well under 100 GB per camera per week
        assert gb_per_camera_per_week < 100, (
            f"Per-camera weekly storage ({gb_per_camera_per_week:.1f} GB) "
            f"exceeds 100 GB — check encoding settings"
        )

        # Should achieve at least 3x compression over naive H.264
        # Naive estimate: raw BGR at 30fps, 320x240, 60s segment
        raw_segment_bytes = FRAME_WIDTH * FRAME_HEIGHT * 3 * FPS * SEGMENT_DURATION_S
        naive_h264_bytes = raw_segment_bytes / 6  # H.264 ~6x over raw
        avg_our_bytes = fg_ratio * fg_size + bg_ratio * bg_size
        compression_vs_naive = naive_h264_bytes / avg_our_bytes

        print(f"  Compression vs naive H.264: {compression_vs_naive:.1f}x")

        assert compression_vs_naive >= 3.0, (
            f"Compression ratio vs naive H.264 ({compression_vs_naive:.1f}x) "
            f"is below 3x minimum"
        )
