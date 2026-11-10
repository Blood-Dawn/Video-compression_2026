"""Pins the helpers taken out of retention.purge_once (all in temp folders)."""

import os
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.services import retention as ret  # noqa: E402

NOW = 2_000_000_000.0
DAY = 86400


class Active:
    def __init__(self, *paths):
        self.p = {str(Path(x).resolve()) for x in paths}

    def snapshot(self):
        return set(self.p)

    def is_active(self, path):
        return str(Path(path).resolve()) in self.p


def _file(folder: Path, name: str, size: int, age_days: float) -> Path:
    p = folder / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    t = NOW - age_days * DAY
    os.utime(p, (t, t))
    return p.resolve()


@pytest.fixture()
def comp(tmp_path, monkeypatch):
    monkeypatch.setattr(ret, "_active_outputs", None)
    d = tmp_path / "compressed"
    d.mkdir()
    return d.resolve()


def _summary():
    return {"ran": True, "deleted": 0, "freed_bytes": 0, "by_age": 0, "by_size": 0, "errors": []}


def test_candidates_are_oldest_first_with_sizes(comp):
    _file(comp, "new.mp4", 10, 2)
    _file(comp, "old.mp4", 20, 30)
    _file(comp, "mid.mp4.enc", 30, 10)
    got = ret._purge_candidates(comp, NOW)
    assert [(p.name, s) for p, s, _ in got] == [("old.mp4", 20), ("mid.mp4.enc", 30), ("new.mp4", 10)]


def test_candidates_skip_fresh_files_and_non_media(comp):
    _file(comp, "fresh.mp4", 10, 0.0001)
    _file(comp, "notes.txt", 10, 90)
    _file(comp, "ok.mp4", 10, 5)
    assert [p.name for p, _, _ in ret._purge_candidates(comp, NOW)] == ["ok.mp4"]


def test_candidates_skip_files_an_encoder_is_writing(comp, monkeypatch):
    busy = _file(comp, "busy.mp4", 10, 40)
    _file(comp, "idle.mp4", 10, 40)
    monkeypatch.setattr(ret, "_active_outputs", Active(busy))
    assert [p.name for p, _, _ in ret._purge_candidates(comp, NOW)] == ["idle.mp4"]


def test_age_purge_deletes_only_older_than_the_cutoff(comp):
    old = _file(comp, "old.mp4", 100, 30)
    keep = _file(comp, "keep.mp4", 100, 3)
    s = _summary()
    gone = ret._purge_by_age(ret._purge_candidates(comp, NOW), comp, NOW - 7 * DAY, s)
    assert gone == {old} and not old.exists() and keep.exists()
    assert (s["deleted"], s["by_age"], s["by_size"], s["freed_bytes"]) == (1, 1, 0, 100)


def test_age_purge_with_nothing_old_deletes_nothing(comp):
    _file(comp, "a.mp4", 100, 1)
    s = _summary()
    assert ret._purge_by_age(ret._purge_candidates(comp, NOW), comp, NOW - 7 * DAY, s) == set()
    assert s["deleted"] == 0


def test_size_purge_removes_oldest_first_until_under_budget(comp):
    a = _file(comp, "a.mp4", 400, 30)
    b = _file(comp, "b.mp4", 400, 20)
    c = _file(comp, "c.mp4", 400, 10)
    s, gone = _summary(), set()
    ret._purge_by_size(ret._purge_candidates(comp, NOW), gone, comp, 800, s)
    assert gone == {a} and not a.exists() and b.exists() and c.exists()
    assert (s["deleted"], s["by_size"], s["freed_bytes"]) == (1, 1, 400)


def test_size_purge_ignores_what_the_age_pass_already_removed(comp):
    a = _file(comp, "a.mp4", 400, 30)
    b = _file(comp, "b.mp4", 400, 20)
    s = _summary()
    stats = ret._purge_candidates(comp, NOW)
    gone = ret._purge_by_age(stats, comp, NOW - 25 * DAY, s)
    ret._purge_by_size(stats, gone, comp, 100, s)
    assert gone == {a, b} and (s["by_age"], s["by_size"]) == (1, 1)


def test_size_purge_stops_at_once_when_already_within_budget(comp):
    a = _file(comp, "a.mp4", 100, 30)
    s, gone = _summary(), set()
    ret._purge_by_size(ret._purge_candidates(comp, NOW), gone, comp, 10_000, s)
    assert gone == set() and a.exists()


def test_a_file_that_cannot_be_deleted_is_not_counted(comp, monkeypatch):
    a = _file(comp, "a.mp4", 100, 30)
    monkeypatch.setattr(ret, "_delete", lambda p, d: 0)
    s = _summary()
    assert ret._purge_by_age(ret._purge_candidates(comp, NOW), comp, NOW - DAY, s) == set()
    assert a.exists() and s["deleted"] == 0


def test_a_file_that_vanished_counts_as_deleted(comp, monkeypatch):
    a = _file(comp, "a.mp4", 100, 30)

    def vanish(p, d):
        p.unlink()
        return 0          # _delete reports 0 bytes, but the file is gone

    monkeypatch.setattr(ret, "_delete", vanish)
    s = _summary()
    assert ret._purge_by_age(ret._purge_candidates(comp, NOW), comp, NOW - DAY, s) == {a}
    assert s["deleted"] == 1 and s["freed_bytes"] == 0
