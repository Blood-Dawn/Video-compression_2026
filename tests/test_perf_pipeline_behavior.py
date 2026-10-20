"""
Behavior locks for the pipeline perf/readability pass.

Each test pins down something the optimized code must keep doing exactly as
before: the cv2-based brightness sample matches ndarray.mean, the squared-
distance centroid matcher matches the original sqrt version, the running
Counter keeps Counter(list).most_common tie-breaking, and the background
subtraction module still builds the same masks and regions. One test covers
the upscale_output-without-enhance crash fixed in the same pass.

Author: Bloodawn (KheivenD), 2026-10-13.
"""

from collections import Counter

import numpy as np
import pytest

import pipeline.pipeline as pp
from background_subtraction.background_subtraction import BackgroundSubtractor
from pipeline.pipeline import (
    _match_motion_vectors,
    _mean_brightness,
    _time_of_day_from_brightness,
    _time_of_day_from_mean,
    run_pipeline,
)


def _original_match(curr, prev):
    """The pre-refactor inline loop from run_pipeline, kept verbatim."""
    vecs = []
    for cx, cy in curr:
        best_dx, best_dy, best_dist = 0, 0, float("inf")
        for px, py in prev:
            d = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
            if d < best_dist:
                best_dist, best_dx, best_dy = d, cx - px, cy - py
        if best_dist < 80:
            vecs.append((best_dx, best_dy))
    return vecs


@pytest.mark.parametrize("shape", [(16, 16, 3), (480, 640, 3), (37, 53, 3), (20, 30)])
def test_mean_brightness_matches_ndarray_mean(shape):
    rng = np.random.default_rng(7)
    frame = rng.integers(0, 256, shape, dtype=np.uint8)
    assert _mean_brightness(frame) == pytest.approx(float(frame.mean()), abs=1e-9)


def test_match_motion_vectors_matches_original_loop():
    rng = np.random.default_rng(11)
    for _ in range(500):
        curr = [tuple(int(v) for v in rng.integers(0, 300, 2))
                for _ in range(rng.integers(0, 6))]
        prev = [tuple(int(v) for v in rng.integers(0, 300, 2))
                for _ in range(rng.integers(0, 6))]
        assert _match_motion_vectors(curr, prev) == _original_match(curr, prev)


def test_match_motion_vectors_boundary_is_exclusive():
    assert _match_motion_vectors([(80, 0)], [(0, 0)]) == []
    assert _match_motion_vectors([(79, 0)], [(0, 0)]) == [(79, 0)]


def test_running_counter_keeps_most_common_tie_break():
    samples = ["red", "blue", "blue", "red", "white"]
    running = Counter()
    for s in samples:
        running[s] += 1
    assert running.most_common(1) == Counter(samples).most_common(1)


def test_time_of_day_running_mean_matches_list_version():
    rng = np.random.default_rng(3)
    for _ in range(200):
        samples = [float(v) for v in rng.uniform(0, 255, rng.integers(1, 50))]
        total = 0.0
        for s in samples:
            total += s
        assert _time_of_day_from_mean(total / len(samples)) == \
            _time_of_day_from_brightness(samples)
    assert _time_of_day_from_brightness([]) == "unknown"


def test_background_subtractor_masks_and_regions_are_deterministic():
    """Same input sequence gives the same mask and regions on two instances."""
    frames = [np.full((120, 160, 3), 40, dtype=np.uint8) for _ in range(30)]
    moving = frames[-1].copy()
    moving[30:90, 40:100] = 230
    frames.append(moving)

    outs = []
    for _ in range(2):
        bs = BackgroundSubtractor(method="MOG2", min_area=100)
        for f in frames:
            mask = bs.apply(f)
        outs.append((mask, [r.to_tuple() for r in bs.get_foreground_regions(mask)]))
    assert np.array_equal(outs[0][0], outs[1][0])
    assert outs[0][1] == outs[1][1]
    assert outs[0][1], "the bright block should be detected"


# ---------------------------------------------------------------------------
# upscale_output without enhance used to crash on the first eligible ROI
# ---------------------------------------------------------------------------

class _Source:
    def __init__(self, frames):
        self.frames = frames
        self.i = 0
        self.fps = 10.0
        self.width = frames[0].shape[1]
        self.height = frames[0].shape[0]

    def read(self):
        if self.i < len(self.frames):
            self.i += 1
            return True, self.frames[self.i - 1]
        return False, None

    def release(self):
        pass

    def get_warmup_frames(self, fallback):
        return 0


class _Region:
    def __init__(self):
        self.x, self.y, self.w, self.h = 8, 8, 20, 20

    def to_tuple(self):
        return (self.x, self.y, self.w, self.h)


class _Subtractor:
    def __init__(self, *a, **k):
        pass

    def apply(self, frame):
        return np.zeros(frame.shape[:2], dtype=np.uint8)

    def get_foreground_regions(self, mask):
        return [_Region()]

    def draw_regions(self, frame, regions):
        return frame


class _Encoder:
    def __init__(self, written):
        self.written = written

    def begin_segment(self, **kwargs):
        pass

    def write_frame(self, frame, **kwargs):
        self.written.append(frame.shape)

    def abort_segment(self):
        pass

    def finish_segment(self, **kwargs):
        return {"file_path": "dummy.mp4", "avg_sharpness": None, "sharpness_label": None}

    def get_storage_report(self):
        return {}


class _Enhancer:
    backend = "bicubic"

    def __init__(self, scale=2, **kwargs):
        self.scale = scale

    def upscale_frame(self, frame):
        return np.repeat(np.repeat(frame, self.scale, axis=0), self.scale, axis=1)

    def upscale_roi(self, frame, box):
        return frame


def test_upscale_output_without_enhance_does_not_crash(monkeypatch, tmp_path):
    frames = [np.full((64, 64, 3), 100, dtype=np.uint8) for _ in range(6)]
    written = []
    monkeypatch.setattr(pp, "FrameSource", lambda *a, **k: _Source(frames))
    monkeypatch.setattr(pp, "BackgroundSubtractor", _Subtractor)
    monkeypatch.setattr(pp, "initialize_database", lambda *a, **k: None)
    monkeypatch.setattr(pp, "ROIEncoder", lambda *a, **k: _Encoder(written))
    monkeypatch.setattr(pp, "Enhancer", _Enhancer)

    run_pipeline(
        input_source="dummy.mp4", camera_id="cam_perf", output_dir=str(tmp_path),
        segment_seconds=60, mode="mode0", warmup_frames=0,
        enhance=False, upscale_output=True, enhance_scale=2,
    )
    assert written == [(128, 128, 3)] * len(frames)
