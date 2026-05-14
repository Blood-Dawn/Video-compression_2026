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


def _patch_three(monkeypatch, *, easy: bool, paddle: bool, tess: bool):
    """Patch all three real backend classes with stubs of the given state."""
    monkeypatch.setattr(plate_reader, "_EasyOcrBackend", _stub_backend("easyocr", easy))
    monkeypatch.setattr(plate_reader, "_PaddleOcrBackend", _stub_backend("paddleocr", paddle))
    monkeypatch.setattr(plate_reader, "_TesseractBackend", _stub_backend("tesseract", tess))


# ── auto mode (the production default) ────────────────────────────────────


class TestAutoMode:
    """Order rationale: easyocr first, paddleocr second, tesseract third."""

    def test_all_available_picks_easyocr(self, monkeypatch):
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

        monkeypatch.setattr(plate_reader, "_EasyOcrBackend", _Stub)
        monkeypatch.setattr(plate_reader, "_PaddleOcrBackend",
                            _stub_backend("paddleocr", False))
        monkeypatch.setattr(plate_reader, "_TesseractBackend",
                            _stub_backend("tesseract", False))

        plate_reader._select_backend(prefer="auto", use_gpu=True)
        assert captured.get("use_gpu") is True
