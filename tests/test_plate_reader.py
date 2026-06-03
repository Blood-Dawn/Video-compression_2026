"""
tests/test_plate_reader.py

Unit tests for src/enhancement/plate_reader.py.

Strategy:
  * Test the pure-logic helpers (text normalisation, scoring) directly.
  * Test the PlateReader's video-walking + consensus pipeline by injecting
    a stub OCR backend so we don't need PaddleOCR / EasyOCR weights to run
    these tests in CI.
  * Generate a tiny synthetic .mp4 clip on the fly so the test is hermetic.

These tests intentionally do NOT cover the real PaddleOCR/EasyOCR engines  - 
those are heavy and license-plate accuracy is best validated by the team's
manual review on real footage. The pipeline plumbing is what the unit tests
need to lock down.

Author: Bloodawn (KheivenD)
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

# Make sure src/ is importable
SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from enhancement.plate_reader import (  # noqa: E402
    PlateRead,
    PlateReader,
    PlateReadResult,
    _normalise_plate_text,
    _score_candidate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_synthetic_video(path: Path, n_frames: int = 30, w: int = 320, h: int = 180) -> None:
    """Write an n-frame .mp4 with a slow gradient so OpenCV can decode it.

    Real plate text on a 320x180 frame is unreadable - these tests don't
    validate OCR accuracy, only the pipeline plumbing. The fake OCR backend
    in tests below returns plate strings independent of pixel content.
    """
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, 15.0, (w, h))
    try:
        for i in range(n_frames):
            frame = np.full((h, w, 3), (i * 7) % 256, dtype=np.uint8)
            cv2.putText(frame, f"frame {i}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                        1.0, (255, 255, 255), 2)
            writer.write(frame)
    finally:
        writer.release()


class _FakeOcr:
    """OCR stub. Returns a fixed set of (text, confidence, bbox) reads."""

    def __init__(self, returns):
        self._returns = returns
        self.name = "fake-ocr"
        self.calls = 0

    @property
    def available(self):
        return True

    def ocr(self, frame):  # noqa: ARG002 - frame is unused
        self.calls += 1
        return list(self._returns)


class _NoopEnhancer:
    """Stand-in for the real Enhancer - just bicubic-upscales by 1×."""

    backend = "stub"

    def upscale_frame(self, frame, scale=4):  # noqa: ARG002
        return frame


# ---------------------------------------------------------------------------
# _normalise_plate_text
# ---------------------------------------------------------------------------


class TestNormalise:
    def test_uppercases_and_strips_spaces(self):
        assert _normalise_plate_text("abc 1234") == "ABC1234"

    def test_strips_punctuation(self):
        assert _normalise_plate_text("AB-12-34") == "AB1234"

    def test_rejects_too_short(self):
        assert _normalise_plate_text("AB") is None
        assert _normalise_plate_text("123") is None

    def test_rejects_too_long(self):
        assert _normalise_plate_text("ABCDEFGHIJ") is None

    def test_returns_none_on_empty(self):
        assert _normalise_plate_text("") is None
        assert _normalise_plate_text(None) is None


# ---------------------------------------------------------------------------
# _score_candidate
# ---------------------------------------------------------------------------


class TestScoreCandidate:
    def test_high_verdict_for_strong_consensus(self):
        score, verdict = _score_candidate(votes=4, ocr_avg=0.75, frames_examined=15)
        assert verdict == "high"
        assert 0 < score <= 1

    def test_medium_verdict_for_two_frame_consensus(self):
        _, verdict = _score_candidate(votes=2, ocr_avg=0.55, frames_examined=20)
        assert verdict == "medium"

    def test_low_verdict_for_single_strong_read(self):
        _, verdict = _score_candidate(votes=1, ocr_avg=0.80, frames_examined=20)
        assert verdict == "low"

    def test_uncertain_for_single_weak_read(self):
        _, verdict = _score_candidate(votes=1, ocr_avg=0.45, frames_examined=20)
        assert verdict == "uncertain"

    def test_zero_frames_examined_returns_uncertain(self):
        score, verdict = _score_candidate(votes=0, ocr_avg=0.0, frames_examined=0)
        assert verdict == "uncertain"
        assert score == 0.0


# ---------------------------------------------------------------------------
# PlateReader.read_plates_from_video - uses synthetic video + fake OCR
# ---------------------------------------------------------------------------


class TestPlateReaderPipeline:

    def test_missing_file_returns_warning(self, tmp_path):
        reader = PlateReader(enhancer=_NoopEnhancer())
        res = reader.read_plates_from_video(tmp_path / "does_not_exist.mp4")
        assert isinstance(res, PlateReadResult)
        assert res.candidate_plates == []
        assert res.best_read is None
        assert any("not found" in w.lower() for w in res.warnings)

    def test_status_dict_is_jsonable(self):
        reader = PlateReader(enhancer=_NoopEnhancer())
        st = reader.status()
        assert isinstance(st, dict)
        for key in ("ocr_backend", "ocr_available", "sr_backend",
                    "sr_available", "sr_scale"):
            assert key in st

    def test_consensus_voting_picks_repeated_read(self, tmp_path, monkeypatch):
        """Three frames see plate "ABC1234"; one sees noise. Consensus wins."""
        video = tmp_path / "synth.mp4"
        _write_synthetic_video(video, n_frames=20, w=320, h=180)

        # Fake OCR returns ABC1234 every time at 0.85 confidence.
        fake = _FakeOcr([("ABC1234", 0.85, (5, 10, 90, 30))])
        reader = PlateReader(enhancer=_NoopEnhancer())
        monkeypatch.setattr(reader, "_ocr", fake)

        res = reader.read_plates_from_video(
            video, sample_every_n_frames=3, max_frames=10,
        )

        assert res.frames_examined > 0
        assert fake.calls == res.frames_examined
        assert res.best_read == "ABC1234"

        # First candidate is the most-voted, highest-confidence one.
        top = res.candidate_plates[0]
        assert top.text == "ABC1234"
        assert top.votes == res.frames_examined
        assert top.verdict in ("high", "medium")
        assert top.bbox_first == (5, 10, 90, 30)

    def test_low_confidence_reads_get_dropped(self, tmp_path, monkeypatch):
        """Reads below min_ocr_confidence must not contribute votes."""
        video = tmp_path / "synth.mp4"
        _write_synthetic_video(video, n_frames=20, w=320, h=180)

        fake = _FakeOcr([("XX", 0.99, (0, 0, 10, 10)),         # too short
                         ("ZZZZZZ", 0.10, (0, 0, 10, 10))])    # too low conf
        reader = PlateReader(enhancer=_NoopEnhancer(), min_ocr_confidence=0.4)
        monkeypatch.setattr(reader, "_ocr", fake)

        res = reader.read_plates_from_video(video, sample_every_n_frames=3, max_frames=8)
        assert res.candidate_plates == []
        assert res.best_read is None

    def test_min_consensus_votes_filters_singletons(self, tmp_path, monkeypatch):
        """When min_consensus_votes=2, single-frame reads disappear."""
        video = tmp_path / "synth.mp4"
        _write_synthetic_video(video, n_frames=20, w=320, h=180)

        # Different plate every call so each text gets exactly 1 vote.
        seq = [[("PLATE001", 0.80, (0, 0, 10, 10))],
               [("PLATE002", 0.80, (0, 0, 10, 10))],
               [("PLATE003", 0.80, (0, 0, 10, 10))],
               [("PLATE004", 0.80, (0, 0, 10, 10))]]

        class _SeqOcr(_FakeOcr):
            def __init__(self, seq):
                super().__init__([])
                self._seq = seq
                self._idx = 0
            def ocr(self, frame):
                self.calls += 1
                if self._idx >= len(self._seq):
                    return []
                out = self._seq[self._idx]; self._idx += 1
                return list(out)

        fake = _SeqOcr(seq)
        reader = PlateReader(enhancer=_NoopEnhancer())
        monkeypatch.setattr(reader, "_ocr", fake)

        # min_consensus_votes=2 should drop everything.
        res = reader.read_plates_from_video(
            video, sample_every_n_frames=3, max_frames=4,
            min_consensus_votes=2,
        )
        assert res.candidate_plates == []

    def test_roi_boxes_subset_frame(self, tmp_path, monkeypatch):
        """When roi_boxes are passed, only those crops are OCR'd."""
        video = tmp_path / "synth.mp4"
        _write_synthetic_video(video, n_frames=20, w=320, h=180)

        # Two fake ROIs → two OCR calls per sampled frame.
        captured_shapes = []

        class _ShapeOcr(_FakeOcr):
            def ocr(self, frame):
                captured_shapes.append(frame.shape)
                self.calls += 1
                return [("ABC1234", 0.85, (0, 0, 10, 10))]

        reader = PlateReader(enhancer=_NoopEnhancer())
        fake = _ShapeOcr([])
        monkeypatch.setattr(reader, "_ocr", fake)

        res = reader.read_plates_from_video(
            video, sample_every_n_frames=3, max_frames=4,
            roi_boxes=[(0, 0, 100, 50), (50, 50, 100, 50)],
        )
        # 4 sampled frames * 2 ROIs = 8 OCR calls
        assert fake.calls == 8
        # All inputs should be the cropped sub-region size, not the full frame
        assert all(s == (50, 100, 3) for s in captured_shapes)
        assert res.best_read == "ABC1234"
