"""
tests/test_perf_guisvcjs_equivalence.py

Behavior checks for the gui/services performance pass: each optimized helper
must give the same answers as the code it replaced.

Author: Bloodawn (KheivenD), 2026-10-13 (perf pass).
"""

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.services import autocompress_runner as acr  # noqa: E402
from gui.services import cpu_sampler  # noqa: E402
from gui.services import path_safety as ps  # noqa: E402
from gui.services import retention as ret  # noqa: E402


def _old_finite_int(value, default, lo, hi):
    """The pre-refactor retention._finite_int, kept verbatim as the oracle."""
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        f = float(value)
        if f != f or f in (float("inf"), float("-inf")):
            return default
        return max(lo, min(hi, int(f)))
    except (TypeError, ValueError, OverflowError):
        return default


@pytest.mark.parametrize("value", [
    None, "", "  ", "7", "7.9", "-3", "-0.5", "3650", "3651", "1e300", "1e400",
    "inf", "-inf", "nan", "abc", 0, 1, True, False, 12.5, -12.5, 10 ** 30,
    float("inf"), float("nan"), [], {}, object(),
])
def test_finite_int_matches_previous_implementation(value):
    assert ret._finite_int(value, 42, 0, 3650) == _old_finite_int(value, 42, 0, 3650)


def test_camera_outputs_only_returns_this_cameras_files(tmp_path):
    for name in ("auto_a_seg1.mp4", "auto_a_seg2.mp4", "auto_b_seg1.mp4", "other.mp4"):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "auto_a_dir").mkdir()

    found = {p.name for p in acr._camera_outputs(tmp_path, "auto_a")}

    assert found == {"auto_a_seg1.mp4", "auto_a_seg2.mp4"}


def _old_confine(path, roots):
    p = Path(path).resolve()
    for root in roots:
        if ps.is_within(p, root):
            return p
    raise ValueError(p)


def test_confine_to_allowed_matches_is_within_loop(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    (a / "sub").mkdir(parents=True)
    b.mkdir()
    roots = [a, str(b), tmp_path / "missing"]
    candidates = [
        a, a / "sub", a / "sub" / "clip.mp4", b / "x.mp4",
        tmp_path / "c" / "x.mp4", a / ".." / "b" / "y.mp4", a / ".." / "z.mp4",
    ]
    for c in candidates:
        try:
            expected = _old_confine(c, roots)
        except ValueError:
            with pytest.raises(ValueError):
                ps.confine_to_allowed(c, roots)
            assert ps.is_path_allowed(c, roots) is False
        else:
            assert ps.confine_to_allowed(c, roots) == expected
            assert ps.is_path_allowed(c, roots) is True


class _StopAfter:
    """Stand-in for the sampler's stop Event: set after ``n`` checks, no waiting."""

    def __init__(self, n):
        self.n = n

    def is_set(self):
        self.n -= 1
        return self.n < 0

    def wait(self, timeout=None):
        return False


class _FakePsutil:
    def __init__(self, readings):
        self.readings = list(readings)

    def cpu_percent(self, interval=None):
        value = self.readings.pop(0)
        if value is None:
            raise OSError("sensor glitch")
        return value

    def virtual_memory(self):
        class _Mem:
            percent = 50.0
            used = 1024 * 1024 * 1024
            total = 4 * 1024 * 1024 * 1024
        return _Mem()

    def sensors_battery(self):
        return None


def test_cpu_sampler_stats_match_a_plain_sample_list(tmp_path, monkeypatch):
    readings = [12.5, None, 80.0, 3.25, 47.0]
    good = [r for r in readings if r is not None]
    monkeypatch.setattr(cpu_sampler, "_psutil", _FakePsutil(readings))
    monkeypatch.setattr(cpu_sampler, "_cpu_sampler_stop", _StopAfter(len(readings)))
    monkeypatch.setattr(cpu_sampler, "_MODE_AVG_FILE", tmp_path / "mode_cpu_avgs.json")
    monkeypatch.setitem(cpu_sampler._power_state, "mode_avgs", {})

    cpu_sampler._cpu_sampler_loop("mode_test", output_dir=str(tmp_path))

    stats = json.loads((tmp_path / "cpu_stats.json").read_text())
    assert stats["samples"] == len(good)
    assert stats["avg"] == round(sum(good) / len(good), 1)
    assert stats["max"] == round(max(good), 1)
    assert stats["min"] == round(min(good), 1)
    saved = json.loads((tmp_path / "mode_cpu_avgs.json").read_text())
    assert saved["mode_test"] == {
        "cpu_sum": sum(good), "n": len(good), "avg": round(sum(good) / len(good), 1),
    }


def test_cpu_sampler_writes_nothing_without_samples(tmp_path, monkeypatch):
    monkeypatch.setattr(cpu_sampler, "_psutil", _FakePsutil([None, None]))
    monkeypatch.setattr(cpu_sampler, "_cpu_sampler_stop", _StopAfter(2))
    monkeypatch.setattr(cpu_sampler, "_MODE_AVG_FILE", tmp_path / "mode_cpu_avgs.json")
    monkeypatch.setitem(cpu_sampler._power_state, "mode_avgs", {})

    cpu_sampler._cpu_sampler_loop("mode_test", output_dir=str(tmp_path))

    assert not (tmp_path / "cpu_stats.json").exists()
    assert not (tmp_path / "mode_cpu_avgs.json").exists()
