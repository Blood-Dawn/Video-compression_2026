"""
tests/test_vmaf_target.py

R5 TASK 5.1: VMAF-targeted rate control. Design: docs/RESEARCH-VMAF-TARGET.md.

Most tests are pure-function or stubbed so CI never runs a real encode:
  * clamping of the target band and the per-codec CRF window;
  * the interpolation step (bracketing, linear guess, bisection, convergence);
  * the search itself against a SYNTHETIC monotonic CRF->VMAF curve (stubbing
    the measure step), including "picks the largest CRF that still clears the
    target", probe caps, and the cache;
  * graceful fallback to the fixed CRF when the VMAF backend / ffmpeg / source
    is absent - target mode must never raise or hang an encode;
  * the /api/start route clamps target_vmaf and defaults it to None.

One guarded integration test does real sample encodes to assert the monotonic
CRF->VMAF assumption the whole search rests on (skipped without ffmpeg+libvmaf).

Author: Bloodawn (KheivenD), 2026-07-16 (R5 TASK 5.1).
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from compression import vmaf_target as vt          # noqa: E402
from utils.ffmpeg import ffmpeg_available          # noqa: E402

_SAMPLE = ROOT / "data" / "samples" / "parking_input.mp4"


@pytest.fixture()
def iso_cache(tmp_path, monkeypatch):
    """Point the CRF cache at a tmp dir (lazy state_file resolution)."""
    monkeypatch.setattr(vt._paths, "state_file", lambda name: tmp_path / name)
    return tmp_path


# ── clamping ──────────────────────────────────────────────────────────────────

def test_clamp_target_band():
    assert vt.clamp_target(93) == 93.0
    assert vt.clamp_target(50) == vt.TARGET_VMAF_MIN     # below band
    assert vt.clamp_target(100) == vt.TARGET_VMAF_MAX    # above band
    assert vt.clamp_target(None) == vt.DEFAULT_TARGET_VMAF


def test_clamp_target_rejects_garbage():
    assert vt.clamp_target("banana") == vt.DEFAULT_TARGET_VMAF
    assert vt.clamp_target(float("nan")) == vt.DEFAULT_TARGET_VMAF
    assert vt.clamp_target(float("inf")) == vt.TARGET_VMAF_MAX


def test_crf_bounds_per_codec():
    lo_h, hi_h = vt.crf_bounds("libx264")
    lo_a, hi_a = vt.crf_bounds("libsvtav1")
    assert hi_a > hi_h          # AV1's 0-63 scale searches further
    assert lo_h == lo_a == vt._SEARCH_CRF_MIN


# ── interpolation (pure) ──────────────────────────────────────────────────────

def test_interpolate_bisects_without_a_bracket():
    assert vt.interpolate_crf([], target=93.0, lo=14, hi=46) == 30


def test_interpolate_uses_the_bracket():
    # VMAF 95 @ CRF 20 (above target), VMAF 89 @ CRF 30 (below). Target 93 sits
    # 1/3 of the way down, so the guess lands near CRF 23.
    m = [(20, 95.0), (30, 89.0)]
    nxt = vt.interpolate_crf(m, target=93.0, lo=14, hi=46)
    assert 21 <= nxt <= 25
    assert 20 < nxt < 30        # strictly inside the bracket


def test_interpolate_converges_on_adjacent_crfs():
    # Adjacent bracket: nothing left to probe, return the passing (lower) CRF.
    m = [(23, 93.4), (24, 92.1)]
    assert vt.interpolate_crf(m, target=93.0, lo=14, hi=46) == 23


def test_interpolate_bisects_when_all_points_clear_the_target():
    # Both points are AT the target, so both count as "above" and there is no
    # bracket yet: the next probe bisects the remaining window rather than
    # interpolating off a one-sided set.
    m = [(20, 93.0), (30, 93.0)]
    assert vt.interpolate_crf(m, target=93.0, lo=14, hi=46) == 30


# ── the search, against a synthetic monotonic curve ───────────────────────────

def _fake_curve(crf: int) -> float:
    """Synthetic monotonic decreasing CRF -> VMAF, FITTED to the real curve
    measured on data/samples/parking_input.mp4 (docs/RESEARCH-VMAF-TARGET.md):

        CRF 18 -> 95.60 | 24 -> 91.04 | 30 -> 81.53 | 36 -> 65.27

    The VMAF deficit roughly doubles every 6 CRF through the useful 85-97 band,
    so 100 - 4.4 * 2**((crf-18)/6) reproduces it closely there (95.6 / 91.2 /
    82.4 / 64.8). Fitting the stub to reality keeps the search tests honest
    about which CRF a real target actually lands on.
    """
    return max(0.0, min(100.0, 100.0 - 4.4 * (2.0 ** ((crf - 18) / 6.0))))


def _stub_search(monkeypatch, curve=_fake_curve, calls=None):
    """Stub out sampling + measuring so no real encode runs."""
    monkeypatch.setattr(vt, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(vt, "_probe_duration", lambda s: 60.0)
    monkeypatch.setattr(vt, "_extract_sample",
                        lambda src, start, secs, dest: (dest.write_bytes(b"x"), True)[1])

    def _measure(samples, crf, codec, preset, workdir):
        if calls is not None:
            calls.append(crf)
        return curve(crf)
    monkeypatch.setattr(vt, "_measure_crf", _measure)


def test_search_picks_largest_crf_meeting_target(iso_cache, monkeypatch, tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fake")
    calls = []
    _stub_search(monkeypatch, calls=calls)
    res = vt.find_crf_for_target(src, codec="libx264", fixed_crf=18,
                                 target_vmaf=93.0, preset="veryfast")
    assert res.used_target, res.fallback_reason
    assert res.measured_vmaf >= 93.0                  # the target is a FLOOR
    # It is the LARGEST such CRF: one step higher must fail the target.
    assert _fake_curve(res.crf + 1) < 93.0
    assert res.probes <= vt.MAX_PROBES
    assert len(calls) == res.probes


def test_search_result_beats_a_conservative_fixed_crf(iso_cache, monkeypatch, tmp_path):
    """The point of the feature: at a 93 target the search should pick a HIGHER
    CRF (smaller file) than a fixed CRF 18, which over-delivers quality."""
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fake")
    _stub_search(monkeypatch)
    res = vt.find_crf_for_target(src, codec="libx264", fixed_crf=18,
                                 target_vmaf=93.0, preset="veryfast")
    assert res.crf > 18


def test_search_caches_the_result(iso_cache, monkeypatch, tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fake")
    calls = []
    _stub_search(monkeypatch, calls=calls)
    first = vt.find_crf_for_target(src, codec="libx264", fixed_crf=18, target_vmaf=93.0)
    assert first.probes > 0 and not first.cached
    n = len(calls)
    second = vt.find_crf_for_target(src, codec="libx264", fixed_crf=18, target_vmaf=93.0)
    assert second.cached and second.crf == first.crf
    assert len(calls) == n, "a cache hit must not re-probe"


def test_cache_key_separates_target_and_codec(iso_cache, monkeypatch, tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fake")
    _stub_search(monkeypatch)
    vt.find_crf_for_target(src, codec="libx264", fixed_crf=18, target_vmaf=93.0)
    # A different target must MISS the cache (different quality bar).
    other = vt.find_crf_for_target(src, codec="libx264", fixed_crf=18, target_vmaf=88.0)
    assert not other.cached
    # A different codec likewise (different CRF scale entirely).
    av1 = vt.find_crf_for_target(src, codec="libsvtav1", fixed_crf=23, target_vmaf=93.0)
    assert not av1.cached


def test_cache_key_includes_the_sampling_scheme(iso_cache, monkeypatch, tmp_path):
    """A different sampling scheme measures a different VMAF and can pick a
    different CRF, so it must MISS the cache. Without this, tuning the sampling
    defaults keeps serving CRFs found under the old scheme (a real bug hit
    during development: the 3x2s answer survived the move to 4x3s)."""
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fake")
    _stub_search(monkeypatch)
    first = vt.find_crf_for_target(src, codec="libx264", fixed_crf=18,
                                   target_vmaf=93.0, samples=3, sample_seconds=2.0)
    assert not first.cached
    # Same clip/codec/target, DIFFERENT scheme -> must re-search, not reuse.
    second = vt.find_crf_for_target(src, codec="libx264", fixed_crf=18,
                                    target_vmaf=93.0, samples=4, sample_seconds=3.0)
    assert not second.cached, "a scheme change must invalidate the cached CRF"
    # And the same scheme again DOES hit.
    third = vt.find_crf_for_target(src, codec="libx264", fixed_crf=18,
                                   target_vmaf=93.0, samples=4, sample_seconds=3.0)
    assert third.cached


def test_higher_target_yields_lower_crf(iso_cache, monkeypatch, tmp_path):
    """Monotonicity, end to end: a stricter quality bar must spend more bits."""
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fake")
    _stub_search(monkeypatch)
    strict = vt.find_crf_for_target(src, codec="libx264", fixed_crf=18, target_vmaf=96.0)
    loose = vt.find_crf_for_target(src, codec="libx264", fixed_crf=18, target_vmaf=86.0)
    assert strict.crf < loose.crf


# ── graceful fallback (never raise, never hang) ───────────────────────────────

def test_fallback_when_ffmpeg_missing(iso_cache, monkeypatch, tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fake")
    monkeypatch.setattr(vt, "ffmpeg_available", lambda: False)
    res = vt.find_crf_for_target(src, codec="libx264", fixed_crf=18, target_vmaf=93.0)
    assert res.crf == 18 and not res.used_target
    assert "ffmpeg" in res.fallback_reason


def test_fallback_when_vmaf_unavailable(iso_cache, monkeypatch, tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fake")
    _stub_search(monkeypatch)
    monkeypatch.setattr(vt, "_measure_crf", lambda *a, **k: None)   # no libvmaf
    res = vt.find_crf_for_target(src, codec="libx264", fixed_crf=18, target_vmaf=93.0)
    assert res.crf == 18 and not res.used_target
    assert "VMAF" in res.fallback_reason


def test_fallback_when_source_missing(iso_cache, tmp_path):
    res = vt.find_crf_for_target(tmp_path / "nope.mp4", codec="libx264",
                                 fixed_crf=22, target_vmaf=93.0)
    assert res.crf == 22 and not res.used_target


def test_fallback_when_samples_cannot_be_cut(iso_cache, monkeypatch, tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fake")
    _stub_search(monkeypatch)
    monkeypatch.setattr(vt, "_extract_sample", lambda *a, **k: False)
    res = vt.find_crf_for_target(src, codec="libx264", fixed_crf=18, target_vmaf=93.0)
    assert res.crf == 18 and "samples" in res.fallback_reason


def test_fallback_when_nothing_meets_target(iso_cache, monkeypatch, tmp_path):
    """A brutal source where even the lowest CRF misses the bar keeps the fixed
    CRF rather than silently shipping below the quality floor."""
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fake")
    _stub_search(monkeypatch, curve=lambda crf: 40.0)   # never reaches 93
    res = vt.find_crf_for_target(src, codec="libx264", fixed_crf=18, target_vmaf=93.0)
    assert res.crf == 18 and not res.used_target


def test_search_never_raises_on_internal_error(iso_cache, monkeypatch, tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fake")
    monkeypatch.setattr(vt, "ffmpeg_available", lambda: True)
    def _boom(*a, **k):
        raise RuntimeError("probe exploded")
    monkeypatch.setattr(vt, "_probe_duration", _boom)
    res = vt.find_crf_for_target(src, codec="libx264", fixed_crf=27, target_vmaf=93.0)
    assert res.crf == 27 and not res.used_target       # degraded, did not raise


# ── sample offsets ────────────────────────────────────────────────────────────

def test_sample_offsets_spread_across_the_clip():
    offs = vt.sample_offsets(duration=100.0, samples=3, sample_seconds=2.0)
    assert len(offs) == 3
    assert offs == sorted(offs)
    assert offs[0] > 0                      # not just the head
    assert offs[-1] + 2.0 <= 100.0          # never runs off the end


def test_sample_offsets_short_clip():
    assert vt.sample_offsets(duration=1.0, samples=3, sample_seconds=2.0) == [0.0]
    assert vt.sample_offsets(duration=0.0, samples=3, sample_seconds=2.0) == [0.0]


# ── route plumbing ────────────────────────────────────────────────────────────

def test_route_clamp_float_or_none():
    from gui.routes.pipeline_bp import _clamp_float_or_none as c
    assert c(None, 85, 97) is None
    assert c("", 85, 97) is None
    assert c("banana", 85, 97) is None
    assert c("inf", 85, 97) is None          # must not 500 (the R4 lesson)
    assert c("nan", 85, 97) is None
    assert c(93, 85, 97) == 93.0
    assert c(50, 85, 97) == 85.0             # clamped up
    assert c(200, 85, 97) == 97.0            # clamped down


# ── real-encode assumption check (guarded) ────────────────────────────────────

@pytest.mark.skipif(not (_SAMPLE.is_file() and ffmpeg_available()),
                    reason="sample clip or ffmpeg not available")
def test_crf_to_vmaf_is_monotonic_on_real_footage(tmp_path):
    """The whole search rests on CRF -> VMAF being monotonic decreasing. Assert
    it on real footage rather than taking it on faith (the measured table is in
    docs/RESEARCH-VMAF-TARGET.md)."""
    from utils.ffmpeg import ffmpeg_path
    from utils.metrics import compute_vmaf

    ref = tmp_path / "ref.mp4"
    subprocess.run(
        [ffmpeg_path(), "-v", "error", "-i", str(_SAMPLE), "-t", "1",
         "-c:v", "libx264", "-crf", "12", "-an", str(ref), "-y"],
        capture_output=True, timeout=120)
    assert ref.is_file()

    scores = []
    for crf in (20, 32, 44):
        dist = tmp_path / f"d{crf}.mp4"
        subprocess.run(
            [ffmpeg_path(), "-v", "error", "-i", str(ref), "-c:v", "libx264",
             "-crf", str(crf), "-preset", "veryfast", "-an", str(dist), "-y"],
            capture_output=True, timeout=120)
        v = compute_vmaf(str(ref), str(dist))
        assert v is not None, "libvmaf should be present in the bundled ffmpeg"
        scores.append(v)
    assert scores == sorted(scores, reverse=True), f"not monotonic: {scores}"
