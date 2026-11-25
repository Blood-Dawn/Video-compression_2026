"""Pipeline job history records video length, wall time and realtime speed.

Author: Bloodawn (KheivenD), 2026-11-25.
"""
import pytest

from src.gui.services import pipeline_runner as pr

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


def _tiny_video(path, frames=60, fps=30):
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 48))
    assert w.isOpened()
    for i in range(frames):
        w.write(np.full((48, 64, 3), i % 255, dtype=np.uint8))
    w.release()


def test_speed_numbers_for_a_two_second_clip_done_in_one_second(tmp_path):
    src = tmp_path / "clip.mp4"
    _tiny_video(src, frames=60, fps=30)
    out = pr._speed_numbers(str(src), 60, 100.0, 101.0)
    assert out["video_seconds"] == 2.0
    assert out["wall_seconds"] == 1.0
    assert out["realtime_x"] == 2.0
    assert out["time_ratio"] == 0.5


def test_speed_numbers_slower_than_realtime(tmp_path):
    src = tmp_path / "clip.mp4"
    _tiny_video(src, frames=30, fps=30)
    out = pr._speed_numbers(str(src), 30, 0.0, 4.0)
    assert out["realtime_x"] == 0.25
    assert out["time_ratio"] == 4.0


def test_speed_numbers_use_frames_processed_for_a_stopped_run(tmp_path):
    src = tmp_path / "clip.mp4"
    _tiny_video(src, frames=60, fps=30)
    out = pr._speed_numbers(str(src), 30, 0.0, 1.0)
    assert out["video_seconds"] == 1.0


def test_speed_numbers_empty_when_not_measurable(tmp_path):
    assert pr._speed_numbers(str(tmp_path / "missing.mp4"), 10, 0.0, 1.0) == {}
    src = tmp_path / "clip.mp4"
    _tiny_video(src)
    assert pr._speed_numbers(str(src), 0, 0.0, 1.0) == {}
    assert pr._speed_numbers(str(src), 60, 5.0, 5.0) == {}
