"""
tests/test_plate_backend_order.py

Validates _select_backend() in src/enhancement/plate_reader.py.

The 2026-05-14 license-cleanup change reordered the OCR backend
preference so EasyOCR is tried before PaddleOCR ("EasyOCR-first").
Regressions here would silently flip the consumer install back to
pulling paddlepaddle, which is the whole reason we made the change.

Strategy: stub each backend's `available` flag so we don't need the
real OCR libs (or model weights) installed in CI. We assert which one
the selector returns under each combination of available backends.

Author: Bloodawn (KheivenD), 2026-05-14.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from enhancement import plate_reader  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────


def _stub_backend(name: str, available: bool):
    """Build a fake backend that mimics _OcrBackend with controllable state."""
    class _Stub:
        def __init__(self, *args, **kwargs):
            self.name = name
            self.available = available

        def ocr(self, *_a, **_kw):
            return []
    return _Stub


def _patch_all(monkeypatch, *, onnx: bool, easy: bool, paddle: bool, tess: bool):
    """Patch every real backend class with stubs of the given availability."""
    monkeypatch.setattr(plate_reader, "_FastPlateOcrBackend", _stub_backend("onnx-alpr", onnx))
    monkeypatch.setattr(plate_reader, "_EasyOcrBackend", _stub_backend("easyocr", easy))
    monkeypatch.setattr(plate_reader, "_PaddleOcrBackend", _stub_backend("paddleocr", paddle))
    monkeypatch.setattr(plate_reader, "_TesseractBackend", _stub_backend("tesseract", tess))


def _patch_three(monkeypatch, *, easy: bool, paddle: bool, tess: bool):
    """Legacy helper: the ONNX ALPR backend is stubbed UNAVAILABLE so these
    assert the easyocr/paddle/tesseract order exactly as before R4 Phase 5."""
    _patch_all(monkeypatch, onnx=False, easy=easy, paddle=paddle, tess=tess)


# ── auto mode (the production default) ────────────────────────────────────


class TestAutoMode:
    """Order rationale (R4 Phase 5): ONNX ALPR first, then easyocr, paddleocr,
    tesseract."""

    def test_onnx_first_when_available(self, monkeypatch):
        _patch_all(monkeypatch, onnx=True, easy=True, paddle=True, tess=True)
        b = plate_reader._select_backend(prefer="auto")
        assert b.name == "onnx-alpr"

    def test_onnx_unavailable_falls_back_to_easyocr(self, monkeypatch):
        _patch_all(monkeypatch, onnx=False, easy=True, paddle=True, tess=True)
        b = plate_reader._select_backend(prefer="auto")
        assert b.name == "easyocr"

    def test_all_available_picks_easyocr(self, monkeypatch):
        # Legacy: with ONNX stubbed unavailable, easyocr wins the rest.
        _patch_three(monkeypatch, easy=True, paddle=True, tess=True)
        b = plate_reader._select_backend(prefer="auto")
        assert b.name == "easyocr"

    def test_easyocr_unavailable_falls_back_to_paddle(self, monkeypatch):
        _patch_three(monkeypatch, easy=False, paddle=True, tess=True)
        b = plate_reader._select_backend(prefer="auto")
        assert b.name == "paddleocr"

    def test_only_tesseract_available(self, monkeypatch):
        _patch_three(monkeypatch, easy=False, paddle=False, tess=True)
        b = plate_reader._select_backend(prefer="auto")
        assert b.name == "tesseract"

    def test_none_available_returns_noop(self, monkeypatch):
        _patch_three(monkeypatch, easy=False, paddle=False, tess=False)
        b = plate_reader._select_backend(prefer="auto")
        # The fallback no-op is a base _OcrBackend instance with name "noop"
        # or similar. We assert it's at least not one of the three real ones.
        assert getattr(b, "name", None) not in ("easyocr", "paddleocr", "tesseract")
        # And it should not be "available"
        assert not getattr(b, "available", False)


# ── Explicit prefer overrides auto order ──────────────────────────────────


class TestExplicitPrefer:

    def test_prefer_paddle_picks_paddle_even_if_easyocr_available(self, monkeypatch):
        _patch_three(monkeypatch, easy=True, paddle=True, tess=True)
        b = plate_reader._select_backend(prefer="paddleocr")
        assert b.name == "paddleocr"

    def test_prefer_tesseract_picks_tesseract(self, monkeypatch):
        _patch_three(monkeypatch, easy=True, paddle=True, tess=True)
        b = plate_reader._select_backend(prefer="tesseract")
        assert b.name == "tesseract"

    def test_prefer_easyocr_picks_easyocr(self, monkeypatch):
        _patch_three(monkeypatch, easy=True, paddle=True, tess=True)
        b = plate_reader._select_backend(prefer="easyocr")
        assert b.name == "easyocr"

    def test_prefer_onnx_picks_onnx(self, monkeypatch):
        _patch_all(monkeypatch, onnx=True, easy=True, paddle=True, tess=True)
        assert plate_reader._select_backend(prefer="onnx").name == "onnx-alpr"

    def test_prefer_onnx_unavailable_returns_unavailable_stub(self, monkeypatch):
        """Explicit onnx when not installed returns the onnx stub (available
        False) rather than silently switching backends."""
        _patch_all(monkeypatch, onnx=False, easy=True, paddle=True, tess=True)
        b = plate_reader._select_backend(prefer="onnx")
        assert b.name == "onnx-alpr" and not b.available

    def test_prefer_unknown_falls_through_to_noop(self, monkeypatch):
        _patch_three(monkeypatch, easy=False, paddle=False, tess=False)
        b = plate_reader._select_backend(prefer="nonsense")
        assert getattr(b, "name", None) not in ("easyocr", "paddleocr", "tesseract")

    def test_prefer_paddleocr_when_unavailable_returns_unavailable_stub(self, monkeypatch):
        """If user explicitly asks for paddleocr but it isn't installed,
        we should return the paddle stub anyway (so the caller can see
        backend.available is False) rather than silently switching."""
        _patch_three(monkeypatch, easy=True, paddle=False, tess=True)
        b = plate_reader._select_backend(prefer="paddleocr")
        assert b.name == "paddleocr"
        assert not b.available


# ── Case insensitivity & None handling ────────────────────────────────────


class TestArgHandling:

    def test_prefer_uppercase(self, monkeypatch):
        _patch_three(monkeypatch, easy=True, paddle=True, tess=True)
        b = plate_reader._select_backend(prefer="EASYOCR")
        assert b.name == "easyocr"

    def test_prefer_none(self, monkeypatch):
        """prefer=None should default to auto."""
        _patch_three(monkeypatch, easy=True, paddle=True, tess=True)
        b = plate_reader._select_backend(prefer=None)
        assert b.name == "easyocr"

    def test_prefer_empty_string(self, monkeypatch):
        _patch_three(monkeypatch, easy=True, paddle=True, tess=True)
        b = plate_reader._select_backend(prefer="")
        assert b.name == "easyocr"


# ── use_gpu pass-through ──────────────────────────────────────────────────


class TestGpuFlag:

    def test_use_gpu_passed_to_backend(self, monkeypatch):
        captured = {}

        class _Stub:
            def __init__(self, use_gpu=False):
                captured["use_gpu"] = use_gpu
                self.name = "easyocr"
                self.available = True

            def ocr(self, *a, **kw): return []

        monkeypatch.setattr(plate_reader, "_FastPlateOcrBackend",
                            _stub_backend("onnx-alpr", False))
        monkeypatch.setattr(plate_reader, "_EasyOcrBackend", _Stub)
        monkeypatch.setattr(plate_reader, "_PaddleOcrBackend",
                            _stub_backend("paddleocr", False))
        monkeypatch.setattr(plate_reader, "_TesseractBackend",
                            _stub_backend("tesseract", False))

        plate_reader._select_backend(prefer="auto", use_gpu=True)
        assert captured.get("use_gpu") is True


# ── ONNX ALPR adapter (R4 Phase 5) - parses the real API shape via fakes ──────


class TestOnnxAlprAdapter:
    """Cover the _FastPlateOcrBackend adapter without the real package, using
    fakes shaped like fast-plate-ocr / open-image-models return values."""

    class _Pred:
        def __init__(self, plate, char_probs=None):
            self.plate = plate
            self.char_probs = char_probs

    class _FakeRec:
        def __init__(self, preds):
            self._preds = preds
        def run(self, crop):
            return list(self._preds)

    class _BBox:
        def __init__(self, x1, y1, x2, y2):
            self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2

    class _Det:
        def __init__(self, bbox):
            self.bounding_box = bbox

    def _backend(self, recognizer, detector=None):
        b = plate_reader._FastPlateOcrBackend.__new__(plate_reader._FastPlateOcrBackend)
        b._recognizer = recognizer
        b._detector = detector
        return b

    def test_ocr_whole_frame_when_no_detector(self):
        import numpy as np
        rec = self._FakeRec([self._Pred("ABC123", char_probs=[0.9, 0.8, 0.7, 1.0, 1.0, 1.0])])
        b = self._backend(rec, detector=None)
        out = b.ocr(np.zeros((40, 120, 3), dtype=np.uint8))
        assert len(out) == 1
        text, conf, bbox = out[0]
        assert text == "ABC123"
        assert abs(conf - (0.9 + 0.8 + 0.7 + 1.0 + 1.0 + 1.0) / 6) < 1e-6
        assert bbox == (0, 0, 120, 40)   # whole frame

    def test_confidence_defaults_when_no_char_probs(self):
        import numpy as np
        rec = self._FakeRec([self._Pred("XY9988", char_probs=None)])
        b = self._backend(rec, detector=None)
        _text, conf, _bbox = b.ocr(np.zeros((30, 90, 3), dtype=np.uint8))[0]
        assert conf == plate_reader._FastPlateOcrBackend._NO_PROB_CONFIDENCE

    def test_detector_crops_are_ocred_with_detected_bbox(self):
        import numpy as np
        rec = self._FakeRec([self._Pred("PLATE1", char_probs=[1.0] * 6)])

        class _FakeDet:
            def predict(self, frame):
                return [TestOnnxAlprAdapter._Det(TestOnnxAlprAdapter._BBox(10, 20, 60, 45))]

        b = self._backend(rec, detector=_FakeDet())
        out = b.ocr(np.zeros((100, 200, 3), dtype=np.uint8))
        assert len(out) == 1
        text, _conf, bbox = out[0]
        assert text == "PLATE1"
        assert bbox == (10, 20, 50, 25)   # (x, y, w, h) from the detection

    def test_empty_when_no_recognizer(self):
        import numpy as np
        b = self._backend(recognizer=None)
        assert b.ocr(np.zeros((10, 10, 3), dtype=np.uint8)) == []
        assert b.available is False
