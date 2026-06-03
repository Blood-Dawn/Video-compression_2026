"""
tests/test_verbose_logging.py

Tests the verbose compression-logging toggle (FIX 7).

run_pipeline gains a ``verbose`` flag. At Normal verbosity it logs the key steps
(source, mode/codec/crf, warmup, per-segment saves + detail). Verbose adds a
"Verbose logging ON" announce and per-100-frame progress lines. This asserts the
verbose run emits strictly more log records than the normal run on the same
input, using lightweight fakes so no real ffmpeg runs.

Author: Bloodawn (KheivenD), 2026-06-03 (FIX 7).
"""

import logging
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pipeline.pipeline import run_pipeline  # noqa: E402


class _Region:
    def __init__(self, x=0, y=0, w=4, h=4):
        self.x, self.y, self.w, self.h = x, y, w, h

    def to_tuple(self):
        return (self.x, self.y, self.w, self.h)


class _FrameSource:
    def __init__(self, frames, fps=10.0, width=16, height=16):
        self.frames, self.index = frames, 0
        self.fps, self.width, self.height = fps, width, height

    def read(self):
        if self.index < len(self.frames):
            f = self.frames[self.index]
            self.index += 1
            return True, f
        return False, None

    def release(self):
        pass

    def get_warmup_frames(self, fallback):
        return 0


class _Subtractor:
    def __init__(self, *a, **k):
        pass

    def apply(self, frame):
        return np.zeros((frame.shape[0], frame.shape[1]), dtype=np.uint8)

    def get_foreground_regions(self, mask):
        return [_Region()]

    def draw_regions(self, frame, regions):
        return frame


class _Encoder:
    def __init__(self, *a, **k):
        self._n = 0

    def begin_segment(self, *a, **k):
        pass

    def write_frame(self, *a, **k):
        pass

    def abort_segment(self):
        pass

    def finish_segment(self, *a, **k):
        self._n += 1
        return {"file_path": f"seg_{self._n}.mp4", "avg_sharpness": None,
                "sharpness_label": None}

    def get_storage_report(self):
        return {"total_segments": self._n}


def _run(verbose, monkeypatch, tmp_path, caplog):
    frames = [np.random.default_rng(1).integers(0, 256, (16, 16, 3), dtype=np.uint8)
              for _ in range(250)]
    monkeypatch.setattr("pipeline.pipeline.FrameSource", lambda *a, **k: _FrameSource(frames))
    monkeypatch.setattr("pipeline.pipeline.BackgroundSubtractor", _Subtractor)
    monkeypatch.setattr("pipeline.pipeline.initialize_database", lambda *a, **k: None)
    monkeypatch.setattr("pipeline.pipeline.ROIEncoder", lambda *a, **k: _Encoder())
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="pipeline.pipeline"):
        run_pipeline(input_source="dummy.mp4", camera_id="cam",
                     output_dir=str(tmp_path), segment_seconds=2, mode="mode0",
                     warmup_frames=0, verbose=verbose)
    return [r for r in caplog.records if r.name.endswith("pipeline")]


def test_verbose_emits_more_log_records(monkeypatch, tmp_path, caplog):
    normal = _run(False, monkeypatch, tmp_path, caplog)
    verbose = _run(True, monkeypatch, tmp_path, caplog)
    assert len(verbose) > len(normal), (len(verbose), len(normal))
    # Verbose adds the announce + at least one per-100-frame progress line.
    assert len(verbose) - len(normal) >= 2


def test_verbose_progress_lines_present(monkeypatch, tmp_path, caplog):
    verbose = _run(True, monkeypatch, tmp_path, caplog)
    msgs = " ".join(r.getMessage() for r in verbose)
    assert "Verbose logging ON" in msgs
    assert "Progress:" in msgs


def test_normal_has_no_progress_lines(monkeypatch, tmp_path, caplog):
    normal = _run(False, monkeypatch, tmp_path, caplog)
    msgs = " ".join(r.getMessage() for r in normal)
    assert "Progress:" not in msgs
    # The per-segment detail line is logged at Normal verbosity too.
    assert "detail:" in msgs
