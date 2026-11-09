"""Pins _apply_vmaf_target and _resolve_max_bitrate_kbps, taken out of run_pipeline."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from compression import vmaf_target  # noqa: E402
from pipeline import pipeline as pl  # noqa: E402


def _result(used, crf=26, reason="no libvmaf"):
    return SimpleNamespace(used_target=used, crf=crf, target_vmaf=93.0, measured_vmaf=93.4,
                           probes=3, cached=False, fallback_reason=reason)


@pytest.fixture()
def finder(monkeypatch):
    calls = []

    def fake(source, **kwargs):
        calls.append((source, kwargs))
        return fake.result

    fake.result = _result(True)
    monkeypatch.setattr(vmaf_target, "find_crf_for_target", fake)
    return fake, calls


# -- VMAF target -------------------------------------------------------------


def test_no_target_means_no_search(finder):
    _, calls = finder
    assert pl._apply_vmaf_target("clip.mp4", "libx264", 18, None, "veryfast") == 18
    assert calls == []


@pytest.mark.parametrize("live", [0, 1])
def test_live_sources_are_never_searched(finder, live):
    _, calls = finder
    assert pl._apply_vmaf_target(live, "libx264", 18, 93.0, "veryfast") == 18
    assert calls == []


def test_used_target_replaces_the_crf_and_forwards_the_arguments(finder):
    _, calls = finder
    assert pl._apply_vmaf_target("clip.mp4", "libsvtav1", 23, 93.0, "ultrafast") == 26
    assert calls == [("clip.mp4", {"codec": "libsvtav1", "fixed_crf": 23,
                                   "target_vmaf": 93.0, "preset": "ultrafast"})]


def test_unused_target_keeps_the_fixed_crf(finder):
    fake, calls = finder
    fake.result = _result(False)
    assert pl._apply_vmaf_target("clip.mp4", "libx264", 18, 93.0, "veryfast") == 18
    assert len(calls) == 1


# -- auto bitrate cap --------------------------------------------------------


@pytest.fixture()
def measured(monkeypatch):
    calls = []

    def fake(source, total_frames, fps):
        calls.append((source, total_frames, fps))
        return fake.value

    fake.value = 1500
    monkeypatch.setattr(pl, "_source_bitrate_kbps", fake)
    return fake, calls


def test_mode0_is_never_capped_or_measured(measured):
    _, calls = measured
    assert pl._resolve_max_bitrate_kbps("mode0", 0, "clip.mp4", 100, 25.0) == 0
    assert calls == []


@pytest.mark.parametrize("given", [500, 99999])
@pytest.mark.parametrize("mode", ["mode1", "mode2", "mode3"])
def test_an_explicit_cap_always_wins(measured, mode, given):
    _, calls = measured
    assert pl._resolve_max_bitrate_kbps(mode, given, "clip.mp4", 100, 25.0) == given
    assert calls == []


@pytest.mark.parametrize("mode", ["mode1", "mode2", "mode3"])
@pytest.mark.parametrize("empty", [0, None])
def test_no_cap_in_modes_1_to_3_uses_the_source_bitrate(measured, mode, empty):
    _, calls = measured
    assert pl._resolve_max_bitrate_kbps(mode, empty, "clip.mp4", 100, 25.0) == 1500
    assert calls == [("clip.mp4", 100, 25.0)]


@pytest.mark.parametrize("empty", [0, None])
def test_an_unmeasurable_source_leaves_the_value_alone(measured, empty):
    fake, _ = measured
    fake.value = 0
    assert pl._resolve_max_bitrate_kbps("mode2", empty, 0, 0, 30.0) == empty
