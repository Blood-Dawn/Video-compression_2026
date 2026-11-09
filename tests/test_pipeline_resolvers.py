"""Pins the pure setting resolvers extracted from run_pipeline.

These are the exact rules run_pipeline applied inline before the extraction
(same results for every mode, override and odd input), so a refactor of the
long function cannot silently change which CRF or codec a run uses.
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config import default_codec_for_mode  # noqa: E402
from pipeline.pipeline import (  # noqa: E402
    _resolve_background_crf,
    _resolve_codec,
    _resolve_foreground_crf,
)


@pytest.mark.parametrize("mode,expected", [
    ("mode0", 18), ("mode1", 18), ("mode2", 23), ("mode3", 38),
    ("unknown", 18), ("", 18),
])
def test_foreground_crf_defaults_per_mode(mode, expected):
    assert _resolve_foreground_crf(mode, None) == expected


@pytest.mark.parametrize("mode", ["mode0", "mode1", "mode2", "mode3"])
@pytest.mark.parametrize("crf,expected", [(0, 0), (10, 10), (51, 51), ("28", 28), (30.0, 30)])
def test_explicit_foreground_crf_wins_including_zero(mode, crf, expected):
    assert _resolve_foreground_crf(mode, crf) == expected


@pytest.mark.parametrize("mode", ["mode0", "mode1", "mode2", "mode3"])
@pytest.mark.parametrize("codec", [None, "", "auto", "AUTO", " Auto ", "   "])
def test_codec_auto_forms_pick_the_mode_default(mode, codec):
    assert _resolve_codec(mode, codec) == default_codec_for_mode(mode)


@pytest.mark.parametrize("codec", ["libx264", "libsvtav1", "libx265", " libx264"])
def test_explicit_codec_is_returned_untouched(codec):
    assert _resolve_codec("mode3", codec) == codec


def test_per_mode_codec_defaults_are_h264_then_av1():
    assert _resolve_codec("mode0", None) == "libx264"
    assert _resolve_codec("mode1", None) == "libx264"
    assert _resolve_codec("mode2", None) == "libsvtav1"
    assert _resolve_codec("mode3", None) == "libsvtav1"


@pytest.mark.parametrize("value,expected", [(None, 40), (0, 0), (35, 35), ("45", 45)])
def test_background_crf(value, expected):
    assert _resolve_background_crf(value) == expected
