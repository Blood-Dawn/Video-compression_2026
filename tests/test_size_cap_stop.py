"""Size cap: stop compressing and notify (policy on_full), plus job outputs."""
import json
from pathlib import Path

import pytest

from src.gui.services import retention as ret
from src.gui.services import job_history


def _make_comp(tmp_path, sizes):
    comp = tmp_path / "compressed"
    comp.mkdir()
    for i, n in enumerate(sizes):
        (comp / f"c{i}.mp4").write_bytes(b"x" * n)
    return tmp_path


def test_default_on_full_is_stop(monkeypatch):
    monkeypatch.setattr("src.gui.services.gui_state_persist.get_retention_config", lambda: {})
    assert ret.get_policy()["on_full"] == "stop"


def test_set_policy_accepts_only_known_on_full(monkeypatch):
    saved = {}
    monkeypatch.setattr("src.gui.services.gui_state_persist.get_retention_config", lambda: dict(saved))
    monkeypatch.setattr("src.gui.services.gui_state_persist.set_retention_config", lambda c: saved.update(c))
    assert ret.set_policy({"on_full": "delete_oldest"})["on_full"] == "delete_oldest"
    assert ret.set_policy({"on_full": "banana"})["on_full"] == "stop"


def test_cap_status_stops_when_full(tmp_path):
    out = _make_comp(tmp_path, [600_000, 600_000])
    pol = {"enabled": True, "max_total_gb": 0.001, "on_full": "stop"}   # 1,000,000 bytes
    cs = ret.cap_status(str(out), pol)
    assert cs["stop"] is True and cs["used_bytes"] == 1_200_000


def test_cap_status_not_full_or_other_modes(tmp_path):
    out = _make_comp(tmp_path, [100])
    assert ret.cap_status(str(out), {"enabled": True, "max_total_gb": 0.001, "on_full": "stop"})["stop"] is False
    full = _make_comp(tmp_path / "b", [2_000_000]) if (tmp_path / "b").mkdir() is None else None
    assert ret.cap_status(str(full), {"enabled": True, "max_total_gb": 0.001, "on_full": "delete_oldest"})["stop"] is False
    assert ret.cap_status(str(full), {"enabled": False, "max_total_gb": 0.001, "on_full": "stop"})["stop"] is False
    assert ret.cap_status(str(full), {"enabled": True, "max_total_gb": 0, "on_full": "stop"})["stop"] is False


def test_stop_mode_never_deletes_by_size(tmp_path):
    out = _make_comp(tmp_path, [600_000, 600_000])
    import os, time
    old = time.time() - 3600
    for p in (out / "compressed").iterdir():
        os.utime(p, (old, old))
    ret.purge_once(str(out), {"enabled": True, "max_age_days": 0, "max_total_gb": 0.001, "on_full": "stop"})
    assert len(list((out / "compressed").iterdir())) == 2


def test_record_job_keeps_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(job_history, "_jobs_file", lambda: tmp_path / "jh.json")
    e = job_history.record_job("pipeline", label="x", outputs=["a.mp4", "b.mp4.enc"])
    assert e["outputs"] == ["a.mp4", "b.mp4.enc"]
    assert job_history.recent_jobs(1)[0]["outputs"] == ["a.mp4", "b.mp4.enc"]
