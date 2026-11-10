"""Pins the helpers taken out of demo.render_demo."""

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from demo import demo as dm  # noqa: E402


def _rec(seg, idx):
    return {"segment_index": seg, "frame_index_within_segment": idx}


def test_records_are_grouped_by_segment_and_sorted_by_frame():
    groups = dm._group_records_by_segment([_rec(1, 2), _rec(0, 5), _rec(1, 0), _rec(0, 1)])
    assert sorted(groups) == [0, 1]
    assert [r["frame_index_within_segment"] for r in groups[0]] == [1, 5]
    assert [r["frame_index_within_segment"] for r in groups[1]] == [0, 2]


def test_no_records_gives_no_groups():
    assert dict(dm._group_records_by_segment([])) == {}


def _video(path: Path, w=64, h=48, fps=10.0, n=3):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    for i in range(n):
        vw.write(np.full((h, w, 3), 40 * (i + 1), dtype=np.uint8))
    vw.release()
    return str(path)


def test_geometry_comes_from_the_first_video(tmp_path):
    first_sparse, w, h, fps = dm._probe_output_geometry(_video(tmp_path / "a.avi"), None)
    assert first_sparse is None and (w, h) == (64, 48) and fps == pytest.approx(10.0)


def test_fps_override_wins(tmp_path):
    assert dm._probe_output_geometry(_video(tmp_path / "a.avi"), 25.0)[3] == 25.0


def test_an_unreadable_first_segment_is_an_error(tmp_path):
    with pytest.raises(RuntimeError, match="Could not open segment video"):
        dm._probe_output_geometry(str(tmp_path / "missing.avi"), None)


def test_a_normal_segment_opens_a_capture_and_no_sparse_state(tmp_path):
    cap, art, meta, frames, cache = dm._open_segment_source(_video(tmp_path / "a.avi"), None)
    try:
        assert cap is not None and cap.isOpened() and (art, meta, frames, cache) == (None, None, None, None)
    finally:
        cap.release()


def test_an_unreadable_segment_is_an_error(tmp_path):
    with pytest.raises(RuntimeError, match="Could not open segment video"):
        dm._open_segment_source(str(tmp_path / "missing.avi"), None)


def test_a_sparse_segment_has_no_capture(monkeypatch):
    monkeypatch.setattr(dm, "build_sparse_frame_lookup", lambda m: {"lookup": m})
    cap, art, meta, frames, cache = dm._open_segment_source("seg", ("dir", {"k": 1}))
    assert cap is None and art == "dir" and meta == {"k": 1} and frames == {"lookup": {"k": 1}} and cache == {}


class Writer:
    def __init__(self):
        self.frames = []

    def write(self, frame):
        self.frames.append(frame.copy())


def test_a_short_gap_holds_the_previous_frame():
    w = Writer()
    prev = np.full((48, 64, 3), 77, dtype=np.uint8)
    dm._fill_gap(w, 0.0, 0.2, 10.0, 0.25, prev, 64, 48, "mode1")
    assert len(w.frames) == 1 and np.array_equal(w.frames[0], prev)


def test_a_long_gap_shows_skip_cards():
    w = Writer()
    prev = np.full((48, 64, 3), 77, dtype=np.uint8)
    dm._fill_gap(w, 0.2, 1.0, 10.0, 0.25, prev, 64, 48, "mode1")
    card = dm.make_skip_card(64, 48, mode="mode1", skip_seconds=0.7, next_time_seconds=1.0, frame_count=1)[0]
    assert len(w.frames) == 7 and all(np.array_equal(f, card) for f in w.frames)


def test_a_short_gap_with_no_previous_frame_still_uses_a_card():
    w = Writer()
    dm._fill_gap(w, 0.0, 0.2, 10.0, 0.25, None, 64, 48, "mode1")
    assert len(w.frames) == 1 and not np.array_equal(w.frames[0], np.zeros((48, 64, 3), np.uint8))


def test_no_gap_writes_nothing():
    w = Writer()
    dm._fill_gap(w, 0.0, 0.1, 10.0, 0.25, np.zeros((48, 64, 3), np.uint8), 64, 48, "mode1")
    assert w.frames == []


def test_next_frame_reads_the_video_in_order(tmp_path):
    cap = cv2.VideoCapture(_video(tmp_path / "a.avi", n=2))
    f0 = dm._next_source_frame({}, cap, None, None, None, None, "seg", 0)
    f1 = dm._next_source_frame({}, cap, None, None, None, None, "seg", 0)
    assert f0.mean() < f1.mean()
    with pytest.raises(RuntimeError, match="ended early while reading seg for segment_index=3"):
        dm._next_source_frame({}, cap, None, None, None, None, "seg", 3)
    cap.release()


def test_next_frame_uses_the_sparse_renderer_when_there_is_sparse_metadata(monkeypatch):
    seen = {}

    def fake(art, meta, entry, cache):
        seen["args"] = (art, meta, entry, cache)
        return "FRAME"

    monkeypatch.setattr(dm, "render_sparse_mode3_frame", fake)
    out = dm._next_source_frame({"source_frame_index": 4}, None, "dir", {"m": 1}, {4: "entry"}, {}, "seg", 0)
    assert out == "FRAME" and seen["args"] == ("dir", {"m": 1}, "entry", {})
    dm._next_source_frame({"source_frame_index": 9}, None, "dir", {"m": 1}, {4: "entry"}, {}, "seg", 0)
    assert seen["args"][2] is None
