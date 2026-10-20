"""
tests/test_perf_enhdemo_equivalence.py

Pins the behavior of the src/demo and src/enhancement speedups: each test
compares the faster code against the straightforward formula it replaced, or
checks the cost-saving property directly (one full-frame SR per sampled
frame, no torch probe for a bicubic Enhancer).

Author: Bloodawn (KheivenD), 2026-10-13.
"""

from __future__ import annotations

import io
import json
import sqlite3

import cv2
import numpy as np
import pytest

from src.demo import demo as demo_mod
from src.demo import split_screen
from src.demo.video_writer import H264Writer
from src.enhancement import enhancement_benchmark as bench
from src.enhancement import enhancer as enhancer_mod
from src.enhancement.plate_reader import PlateReader

RNG = np.random.default_rng(7)
SHAPES = [(1080, 1920), (479, 641), (37, 53), (15, 400)]


def _old_focus_background(frame, dim_alpha=0.45, tint_strength=0.08):
    darkened = (frame.astype(np.float32) * dim_alpha).clip(0, 255).astype(np.uint8)
    bg_tint = np.full_like(frame, (20, 28, 20), dtype=np.uint8)
    return cv2.addWeighted(darkened, 1.0 - tint_strength, bg_tint, tint_strength, 0)


@pytest.mark.parametrize("shape", SHAPES)
def test_roi_focus_background_matches_per_pixel_formula(shape):
    frame = RNG.integers(0, 256, shape + (3,), dtype=np.uint8)
    out = demo_mod.build_roi_focus_frame(frame, [], draw_boxes=False)
    assert np.array_equal(out, _old_focus_background(frame))


def test_roi_focus_frame_restores_rois_and_draws_boxes_last():
    frame = RNG.integers(0, 256, (120, 160, 3), dtype=np.uint8)
    regions = [[10, 10, 40, 30], [-5, 90, 30, 50], [1, 2, 3]]
    expected = _old_focus_background(frame)
    for x, y, w, h in ([10, 10, 40, 30], [-5, 90, 30, 50]):
        x1, y1, x2, y2 = demo_mod.clip_bbox(x, y, w, h, 160, 120)
        expected[y1:y2, x1:x2] = frame[y1:y2, x1:x2]
        cv2.rectangle(expected, (x1, y1), (x2, y2), (0, 255, 0), 2)
    assert np.array_equal(demo_mod.build_roi_focus_frame(frame, regions), expected)


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("corner", ["tl", "tr", "bl", "br"])
def test_corner_label_matches_full_frame_blend(shape, corner):
    frame = RNG.integers(0, 256, shape + (3,), dtype=np.uint8)
    text = "MODE 0  ·  SEG 12  ·  ROI_TINT"

    # The original implementation: blend the whole frame with a copy that
    # has the pad filled black.
    expected = frame.copy()
    h, w = expected.shape[:2]
    (tw, th), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    box_w, box_h = tw + 12, th + baseline + 8
    x1 = 8 if corner in ("tl", "bl") else w - box_w - 8
    y1 = 8 if corner in ("tl", "tr") else h - box_h - 8
    overlay = expected.copy()
    cv2.rectangle(overlay, (x1, y1), (x1 + box_w, y1 + box_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, expected, 0.45, 0, dst=expected)
    cv2.putText(expected, text, (x1 + 6, y1 + 4 + th), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                (255, 255, 255), 1, cv2.LINE_AA)

    actual = frame.copy()
    demo_mod._draw_corner_label(actual, text, corner=corner)
    assert np.array_equal(actual, expected)


def test_add_bottom_right_labels_leaves_input_untouched():
    frame = RNG.integers(0, 256, (90, 160, 3), dtype=np.uint8)
    before = frame.copy()
    out = demo_mod.add_bottom_right_labels(frame, time_text="00:00:01.000", mode="mode0",
                                           segment_index=0, view="standard")
    assert np.array_equal(frame, before)
    assert not np.array_equal(out, frame)


@pytest.mark.parametrize("max_index", [-3, -1, 0, 4, 50])
def test_load_segment_rows_limit_matches_full_fetch(tmp_path, max_index):
    db = tmp_path / "metadata.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE segments (timestamp TEXT, file_path TEXT)")
    conn.executemany("INSERT INTO segments VALUES (?, ?)",
                     [(f"2026-01-{30 - i:02d}", f"seg{i}.mp4") for i in range(10)])
    conn.commit()
    all_rows = conn.execute("SELECT timestamp, file_path FROM segments ORDER BY timestamp ASC").fetchall()
    conn.close()

    expected = [(i, path) for i, (_, path) in enumerate(all_rows[: max_index + 1])]
    records = [{"segment_index": min(0, max_index)}, {"segment_index": max_index}]
    assert demo_mod.load_segment_rows(db, records) == expected


class _RecordingWriter:
    instances: list = []

    def __init__(self, *_args, **_kwargs):
        self.frames: list[np.ndarray] = []
        _RecordingWriter.instances.append(self)

    def isOpened(self):
        return True

    def write(self, frame):
        self.frames.append(frame.copy())

    def release(self):
        pass


def test_render_demo_fills_gaps_with_hold_frames_and_skip_cards(tmp_path, monkeypatch):
    w, h, fps = 64, 48, 10.0
    video = tmp_path / "seg0.avi"
    vw = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    for i in range(3):
        vw.write(np.full((h, w, 3), 60 * (i + 1), dtype=np.uint8))
    vw.release()

    db = tmp_path / "metadata.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE segments (timestamp TEXT, file_path TEXT)")
    conn.execute("INSERT INTO segments VALUES ('2026-01-01', ?)", (str(video),))
    conn.commit()
    conn.close()

    # 0.0 -> 0.2 s is one missing frame (held); 0.2 -> 1.0 s is seven (skip card).
    times = [0.0, 0.2, 1.0]
    sidecar = tmp_path / "frames.jsonl"
    sidecar.write_text("\n".join(json.dumps({
        "source_frame_index": i, "source_time_seconds": t, "mode": "mode1",
        "segment_index": 0, "frame_index_within_segment": i, "regions": [],
    }) for i, t in enumerate(times)), encoding="utf-8")

    monkeypatch.setattr(demo_mod, "H264Writer", _RecordingWriter)
    _RecordingWriter.instances.clear()
    demo_mod.render_demo(db_path=str(db), metadata_path=str(sidecar),
                         output_path=str(tmp_path / "out.mp4"), fps_override=fps,
                         draw_tint=False, draw_boxes=False)
    frames = _RecordingWriter.instances[-1].frames

    assert len(frames) == 1 + 1 + 1 + 7 + 1
    assert np.array_equal(frames[1], frames[0])  # held frame
    card = demo_mod.make_skip_card(w, h, mode="mode1", skip_seconds=0.7,
                                   next_time_seconds=1.0, frame_count=1)[0]
    for f in frames[3:10]:
        assert np.array_equal(f, card)


def test_make_skip_card_frames_are_independent_arrays():
    frames = demo_mod.make_skip_card(80, 60, mode="m", skip_seconds=1.0,
                                     next_time_seconds=2.0, frame_count=3)
    assert len(frames) == 3
    frames[0][:] = 0
    assert np.count_nonzero(frames[1]) > 0


def test_composite_matches_hconcat_vconcat_reference():
    frames = [(f"mode{i}", RNG.integers(0, 256, s + (3,), dtype=np.uint8))
              for i, s in enumerate([(360, 640), (480, 640), (720, 1280)])]
    cell_w, cell_h = 1280, 720
    cells = [split_screen.fit_frame(f, cell_w, cell_h) for _, f in frames]
    cells.append(np.zeros((cell_h, cell_w, 3), dtype=np.uint8))
    expected = cv2.vconcat([cv2.hconcat(cells[0:2]), cv2.hconcat(cells[2:4])])
    actual = split_screen.build_composite_frame(frames, 2, 2, cell_w, cell_h)
    assert np.array_equal(actual, expected)


class _FakeProc:
    def __init__(self):
        self.stdin = io.BytesIO()


@pytest.mark.parametrize("view", ["contiguous", "flipped", "crop", "fortran"])
def test_h264_writer_sends_the_same_bytes_as_tobytes(view):
    frame = RNG.integers(0, 256, (48, 64, 3), dtype=np.uint8)
    big = RNG.integers(0, 256, (96, 128, 3), dtype=np.uint8)
    candidate = {
        "contiguous": frame,
        "flipped": frame[:, ::-1],
        "crop": big[10:58, 20:84],
        "fortran": np.asfortranarray(frame),
    }[view]
    writer = H264Writer.__new__(H264Writer)
    writer._width, writer._height = 64, 48
    writer._proc = _FakeProc()
    writer.write(candidate)
    assert writer._proc.stdin.getvalue() == candidate.tobytes()


class _CountingEnhancer:
    backend = "stub-cpu"

    def __init__(self, full_shape):
        self.full_shape = full_shape
        self.full_frame_calls = 0
        self.last_full = None

    def upscale_frame(self, frame, scale=4):
        up = cv2.resize(frame, (frame.shape[1] * scale, frame.shape[0] * scale),
                        interpolation=cv2.INTER_NEAREST)
        if frame.shape[:2] == self.full_shape:
            self.full_frame_calls += 1
            self.last_full = up
        return up


def _write_clip(path, n, w, h):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (w, h))
    for i in range(n):
        f = RNG.integers(0, 256, (h, w, 3), dtype=np.uint8)
        f[:4, :4] = i * 10
        vw.write(f)
    vw.release()


def test_benchmark_runs_full_frame_sr_once_per_sampled_frame(tmp_path):
    clip = tmp_path / "clip.avi"
    _write_clip(clip, 12, 64, 48)
    enh = _CountingEnhancer((48, 64))
    result = bench.benchmark_enhancement(clip, roi_box=(8, 8, 16, 16), enhancer=enh,
                                         sample_every_n_frames=3, max_frames=10, sr_scale=2)
    assert result.frames_examined == 4
    assert enh.full_frame_calls == 4
    assert result.variants["full_frame_sr"].avg_sharpness_full > 0


def test_plate_reader_samples_the_same_frames_with_grab(tmp_path):
    clip = tmp_path / "clip.avi"
    _write_clip(clip, 17, 32, 24)

    class _Ocr:
        name = "stub"
        available = True

        def ocr(self, frame):
            return [("ABC123", 0.9, (0, 0, 1, 1))]

    reader = PlateReader(enhancer=_CountingEnhancer((0, 0)), ocr_backend="none")
    reader._ocr = _Ocr()
    result = reader.read_plates_from_video(clip, sample_every_n_frames=4, max_frames=60)
    assert result.frames_examined == 5
    assert result.candidate_plates[0].frames == [0, 4, 8, 12, 16]


def test_bicubic_enhancer_defers_device_detection(monkeypatch):
    calls = []

    def fake_best_device():
        calls.append(1)
        return "cpu"

    monkeypatch.setattr(enhancer_mod, "best_device", fake_best_device)
    e = enhancer_mod.Enhancer(model="bicubic", use_nn=False, scale=2)
    assert calls == []
    assert e.backend == "bicubic"
    assert e.device == "cpu"
    assert e.device == "cpu"
    assert calls == [1]
    assert enhancer_mod.Enhancer(model="bicubic", use_nn=False, device=" MPS ").device == "mps"
