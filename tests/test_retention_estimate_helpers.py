"""Pins the helpers taken out of retention.estimate."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.services import retention as ret  # noqa: E402

GB = ret._GB


def _write(p: Path, size: int, mtime: float):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    os.utime(p, (mtime, mtime))


def test_folder_usage_of_a_missing_folder(tmp_path):
    assert ret._folder_usage(tmp_path / "nope") == (0, None, None)


def test_folder_usage_sums_sizes_and_finds_the_time_span(tmp_path):
    _write(tmp_path / "a.mp4", 100, 1000.0)
    _write(tmp_path / "sub" / "b.mkv", 200, 3000.0)
    _write(tmp_path / "c.mp4.enc", 300, 2000.0)
    _write(tmp_path / "notes.txt", 999, 5000.0)       # not purgeable media
    assert ret._folder_usage(tmp_path) == (600, 1000.0, 3000.0)


def test_growth_prefers_history(monkeypatch):
    monkeypatch.setattr(ret, "_bytes_per_day_from_history", lambda: 123.0)
    assert ret._estimate_bytes_per_day(10**9, 1000.0, 1000.0 + 10 * 86400.0) == 123.0


def test_growth_falls_back_to_size_over_age(monkeypatch):
    monkeypatch.setattr(ret, "_bytes_per_day_from_history", lambda: None)
    assert ret._estimate_bytes_per_day(1000, 1000.0, 1000.0 + 2 * 86400.0) == 500.0


def test_growth_span_is_at_least_an_hour(monkeypatch):
    monkeypatch.setattr(ret, "_bytes_per_day_from_history", lambda: None)
    assert ret._estimate_bytes_per_day(100, 1000.0, 1001.0) == 100 * 24


@pytest.mark.parametrize("used,oldest,newest", [(0, None, None), (100, 5.0, 5.0), (100, None, None)])
def test_growth_unknown_without_a_usable_span(monkeypatch, used, oldest, newest):
    monkeypatch.setattr(ret, "_bytes_per_day_from_history", lambda: None)
    assert ret._estimate_bytes_per_day(used, oldest, newest) is None


def _usage(free_gb):
    return SimpleNamespace(free=free_gb * GB)


@pytest.mark.parametrize("bpd", [None, 0, -5])
def test_headroom_needs_a_positive_growth_rate(bpd):
    assert ret._headroom_days(bpd, 0, _usage(10), {"enabled": False}) is None


def test_headroom_from_free_disk_only():
    assert ret._headroom_days(GB, 0, _usage(10), {"enabled": False}) == 10.0


def test_headroom_takes_the_tighter_of_budget_and_disk():
    pol = {"enabled": True, "max_total_gb": 4}
    assert ret._headroom_days(GB, GB, _usage(50), pol) == 3.0      # budget 4 GB - 1 GB used
    assert ret._headroom_days(GB, GB, _usage(2), pol) == 2.0       # disk is tighter


def test_headroom_budget_alone_and_over_budget():
    pol = {"enabled": True, "max_total_gb": 4}
    assert ret._headroom_days(GB, 0, None, pol) == 4.0
    assert ret._headroom_days(GB, 9 * GB, None, pol) == 0.0


def test_headroom_none_when_no_limit_applies():
    assert ret._headroom_days(GB, 0, None, {"enabled": False, "max_total_gb": 4}) is None
    assert ret._headroom_days(GB, 0, None, {"enabled": True, "max_total_gb": 0}) is None
