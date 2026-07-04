"""
tests/test_retention.py

R4 Phase 3 (docs/RESEARCH-COMPETITORS.md): retention / disk-budget / auto-purge.

This feature DELETES footage, so most tests are safety tests: it only touches
files under the resolved <output_dir>/compressed dir, only known media/.enc
extensions, never a too-fresh file, never anything when disabled or unlimited,
and it prunes the compressed index for what it removed. Plus the policy
round-trip, the endpoints, the estimate, and the auto-compress daemon hook.

Author: Bloodawn (KheivenD), 2026-07-04 (R4 Phase 3 - retention).
"""

import os
import sys
import time
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.services import retention as ret            # noqa: E402
from utils import compressed_index as cidx           # noqa: E402


@pytest.fixture()
def iso(tmp_path, monkeypatch):
    """Isolate the compressed index + gui-state persistence to tmp.

    Also clears the in-memory retention policy in gui.state so a value set by a
    previous test cannot leak (the file is tmp-scoped but _status is a module
    global shared across the process).
    """
    monkeypatch.setattr(cidx._paths, "state_file", lambda name: tmp_path / name)
    import gui.services.gui_state_persist as gsp
    monkeypatch.setattr(gsp, "_GUI_STATE_FILE", tmp_path / "gui_state.json")
    import gui.services.job_history as jh
    monkeypatch.setattr(jh._paths, "state_file", lambda name: tmp_path / name)
    from gui.state import _state_lock, _status
    with _state_lock:
        _status.get("config", {}).pop("retention", None)
    yield tmp_path
    # Teardown: never leave an enabled retention policy in the process-global
    # _status where another test file's real auto-compress daemon could read it.
    with _state_lock:
        _status.get("config", {}).pop("retention", None)


def _mkclip(comp_dir: Path, name: str, age_days: float = 0.0, size: int = 1000):
    comp_dir.mkdir(parents=True, exist_ok=True)
    p = comp_dir / name
    p.write_bytes(b"x" * size)
    when = time.time() - age_days * 86400
    os.utime(p, (when, when))
    return p


# ── policy round-trip ─────────────────────────────────────────────────────────

def test_policy_defaults_disabled(iso):
    pol = ret.get_policy()
    assert pol["enabled"] is False
    assert pol["max_age_days"] == 0 and pol["max_total_gb"] == 0.0


def test_policy_set_and_persist(iso):
    ret.set_policy({"enabled": True, "max_age_days": "7", "max_total_gb": "2.5"})
    pol = ret.get_policy()
    assert pol["enabled"] is True
    assert pol["max_age_days"] == 7
    assert pol["max_total_gb"] == 2.5


def test_policy_clamps_garbage(iso):
    ret.set_policy({"enabled": True, "max_age_days": -5, "max_total_gb": "banana"})
    pol = ret.get_policy()
    assert pol["max_age_days"] == 0          # negative -> 0
    assert pol["max_total_gb"] == 0.0        # unparseable -> unchanged/default


# ── purge: disabled / unlimited are no-ops ────────────────────────────────────

def test_disabled_is_noop(iso):
    comp = cidx.compressed_subdir(iso / "out")
    old = _mkclip(comp, "cam_a.mp4", age_days=100)
    summary = ret.purge_once(str(iso / "out"),
                             policy={"enabled": False, "max_age_days": 1})
    assert summary["ran"] is False
    assert old.exists()


def test_enabled_but_unlimited_is_noop(iso):
    comp = cidx.compressed_subdir(iso / "out")
    old = _mkclip(comp, "cam_a.mp4", age_days=100)
    summary = ret.purge_once(str(iso / "out"),
                             policy={"enabled": True, "max_age_days": 0, "max_total_gb": 0})
    assert summary["ran"] is False
    assert old.exists()


# ── age purge ─────────────────────────────────────────────────────────────────

def test_age_purge_deletes_old_keeps_new(iso):
    comp = cidx.compressed_subdir(iso / "out")
    old = _mkclip(comp, "cam_old.mp4", age_days=10)
    fresh = _mkclip(comp, "cam_new.mp4", age_days=1)   # 1 day old, within limit
    summary = ret.purge_once(str(iso / "out"),
                             policy={"enabled": True, "max_age_days": 7, "max_total_gb": 0})
    assert summary["ran"] and summary["by_age"] == 1
    assert not old.exists()
    assert fresh.exists()


def test_freshness_window_protects_recent_files(iso):
    comp = cidx.compressed_subdir(iso / "out")
    # Age says "delete" (max_age_days effectively 0-ish via tiny age) but the
    # file was just written, so the freshness window must save it.
    just_written = _mkclip(comp, "cam_live.mp4", age_days=0.0)
    summary = ret.purge_once(str(iso / "out"),
                             policy={"enabled": True, "max_age_days": 1, "max_total_gb": 0.000001})
    assert just_written.exists(), "a file inside the freshness window must survive"


# ── size purge (oldest first) ─────────────────────────────────────────────────

def test_size_purge_oldest_first_until_under_budget(iso):
    comp = cidx.compressed_subdir(iso / "out")
    # 3 files x 1000 bytes, all older than the freshness window; budget ~1500 B.
    a = _mkclip(comp, "cam_1.mp4", age_days=5, size=1000)
    b = _mkclip(comp, "cam_2.mp4", age_days=3, size=1000)
    c = _mkclip(comp, "cam_3.mp4", age_days=1, size=1000)
    budget_gb = 1500 / 1_000_000_000
    summary = ret.purge_once(str(iso / "out"),
                             policy={"enabled": True, "max_age_days": 0, "max_total_gb": budget_gb})
    assert summary["by_size"] == 2           # must drop the two oldest
    assert not a.exists() and not b.exists()
    assert c.exists()                        # newest kept


# ── safety: confinement + extension filter ────────────────────────────────────

def test_never_touches_files_outside_compressed_dir(iso):
    comp = cidx.compressed_subdir(iso / "out")
    _mkclip(comp, "cam_old.mp4", age_days=100)
    # An original sitting next to the output dir (NOT under compressed/).
    original = _mkclip(iso / "out", "original.mp4", age_days=100)
    ret.purge_once(str(iso / "out"),
                   policy={"enabled": True, "max_age_days": 1, "max_total_gb": 0})
    assert original.exists(), "files outside compressed/ must never be purged"


def test_only_media_extensions_purged(iso):
    comp = cidx.compressed_subdir(iso / "out")
    _mkclip(comp, "cam_old.mp4", age_days=100)
    keep_txt = _mkclip(comp, "notes.txt", age_days=100)
    keep_db = _mkclip(comp, "metadata.db", age_days=100)
    ret.purge_once(str(iso / "out"),
                   policy={"enabled": True, "max_age_days": 1, "max_total_gb": 0})
    assert keep_txt.exists() and keep_db.exists()


def test_encrypted_output_is_purgeable(iso):
    comp = cidx.compressed_subdir(iso / "out")
    enc = _mkclip(comp, "cam_a.mp4.enc", age_days=100)
    ret.purge_once(str(iso / "out"),
                   policy={"enabled": True, "max_age_days": 1, "max_total_gb": 0})
    assert not enc.exists()


def test_missing_compressed_dir_is_safe(iso):
    # No compressed/ dir at all: ran False, no crash.
    summary = ret.purge_once(str(iso / "nonexistent"),
                             policy={"enabled": True, "max_age_days": 1})
    assert summary["ran"] is False
    assert summary["errors"] == []


# ── index pruning ─────────────────────────────────────────────────────────────

def test_purge_prunes_dead_index_entries(iso):
    comp = cidx.compressed_subdir(iso / "out")
    src = _mkclip(iso / "watch", "src.mp4", age_days=100)
    out = _mkclip(comp, "cam_out.mp4", age_days=100)
    cidx.record(src, out)
    assert cidx.lookup(src) is not None
    ret.purge_once(str(iso / "out"),
                   policy={"enabled": True, "max_age_days": 1, "max_total_gb": 0})
    assert not out.exists()
    # The index entry whose output was deleted must be pruned.
    assert cidx.lookup(src) is None


# ── estimate ──────────────────────────────────────────────────────────────────

def test_estimate_reports_disk_and_usage(iso):
    comp = cidx.compressed_subdir(iso / "out")
    _mkclip(comp, "cam_a.mp4", age_days=1, size=2_000_000)
    est = ret.estimate(str(iso / "out"))
    assert est["available"] is True
    assert est["free_gb"] is not None and est["free_gb"] > 0
    assert est["used_gb"] is not None


# ── endpoints ─────────────────────────────────────────────────────────────────

def test_retention_endpoints(iso, monkeypatch):
    from gui.app import app
    # Point the route's output dir at our tmp so a purge is scoped to tmp.
    import gui.routes.autocompress_bp as bp
    monkeypatch.setattr(bp, "_output_dir", lambda: str(iso / "out"))
    client = app.test_client()

    # GET returns policy + estimate.
    r = client.get("/api/retention")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] and "policy" in body and "estimate" in body

    # POST sets the policy.
    r = client.post("/api/retention", json={"enabled": True, "max_age_days": 3})
    assert r.status_code == 200
    assert r.get_json()["policy"]["max_age_days"] == 3

    # purge_now runs (no footage yet -> ran True but deleted 0, or ran per dir).
    comp = cidx.compressed_subdir(iso / "out")
    _mkclip(comp, "cam_old.mp4", age_days=100)
    r = client.post("/api/retention/purge_now")
    assert r.status_code == 200
    assert r.get_json()["summary"]["deleted"] == 1


def test_daemon_calls_retention_after_scan(iso, monkeypatch):
    """The auto-compress loop must enforce retention after each pass."""
    import gui.services.autocompress_runner as ac
    called = {}
    monkeypatch.setattr(ac, "_enforce_retention",
                        lambda output_dir: called.setdefault("dir", output_dir))
    # Drive one loop body via a stop event set after the first scan.
    import threading
    stop = threading.Event()

    def _fake_scan(*a, **k):
        stop.set()   # end the loop after one pass
        return []
    monkeypatch.setattr(ac, "scan_once", _fake_scan)
    ac._run_autocompress_thread(
        {"folder": str(iso / "watch"), "output_dir": str(iso / "out"),
         "mode": "mode0", "poll_interval": 2}, stop)
    assert called.get("dir") == str(iso / "out")
