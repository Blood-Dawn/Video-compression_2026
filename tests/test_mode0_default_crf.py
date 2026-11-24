"""Mode 0 default CRF: regular compression, not near lossless (2026-11-23)."""
from src.pipeline.pipeline import _resolve_foreground_crf


def test_mode0_defaults_to_regular_compression():
    assert _resolve_foreground_crf("mode0", None) == 26


def test_other_modes_keep_their_defaults():
    assert _resolve_foreground_crf("mode1", None) == 18
    assert _resolve_foreground_crf("mode2", None) == 23
    assert _resolve_foreground_crf("mode3", None) == 38


def test_explicit_crf_still_wins():
    assert _resolve_foreground_crf("mode0", 16) == 16
