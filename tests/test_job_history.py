"""
tests/test_job_history.py

R4 Phase 1 (UX research adoption, docs/RESEARCH-UIUX.md findings 1-3):
  * job_history service - record/recent roundtrip, cap, corruption tolerance;
  * GET /api/jobs/recent - returns the persisted entries newest first;
  * pipeline_runner - records a "pipeline" job when a run finishes
    (completed / stopped / error statuses);
  * autocompress scan_once - records one "autocompress" job per pass that
    attempted work (and none for an idle pass), with byte totals, and exposes
    batch_total/batch_done/current_file for the "file N of M" display.

Author: Bloodawn (KheivenD), 2026-07-04 (R4 Phase 1 - job history).
"""

import json
import sys
import threading
import time
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.services import job_history as jh                      # noqa: E402
from gui.services import autocompress_runner as ac              # noqa: E402
from gui.services import pipeline_runner as pr                  # noqa: E402
from utils import compressed_index as cidx                      # noqa: E402
from utils import watchfolder as wf                             # noqa: E402


@pytest.fixture()
def jobs_file(tmp_path, monkeypatch):
    """Point the job-history log (lazy state_file resolution) at tmp."""
    monkeypatch.setattr(jh._paths, "state_file", lambda name: tmp_path / name)
    return tmp_path / "job_history.json"


# ── service ───────────────────────────────────────────────────────────────────

def test_record_and_recent_roundtrip(jobs_file):
    e = jh.record_job("pipeline", label="clip.mp4", started_at=100.0,
                      ended_at=160.5, status="completed",
                      counts={"frames": 10, "segments": 2},
                      bytes_in=1000, bytes_out=100)
    assert e is not None and e["elapsed_s"] == 60.5
    jobs = jh.recent_jobs()
    assert len(jobs) == 1
    j = jobs[0]
    assert j["kind"] == "pipeline" and j["label"] == "clip.mp4"
    assert j["status"] == "completed" and j["counts"]["segments"] == 2
    assert j["bytes_in"] == 1000 and j["bytes_out"] == 100
    assert j["error"] is None


def test_newest_first_and_limit(jobs_file):
    for i in range(5):
        jh.record_job("pipeline", label=f"job{i}")
    jobs = jh.recent_jobs(limit=3)
    assert [j["label"] for j in jobs] == ["job4", "job3", "job2"]


def test_history_is_capped(jobs_file, monkeypatch):
    monkeypatch.setattr(jh, "_MAX_JOBS", 10)
    for i in range(15):
        jh.record_job("pipeline", label=f"job{i}")
    stored = json.loads(jobs_file.read_text())
    assert len(stored) == 10
    assert stored[0]["label"] == "job14"          # newest kept
    assert all(s["label"] != "job0" for s in stored)  # oldest dropped


def test_corrupt_history_treated_as_empty(jobs_file):
    jobs_file.write_text("{not json!!", encoding="utf-8")
    assert jh.recent_jobs() == []
    # And a record over the corrupt file starts a fresh, valid log.
    assert jh.record_job("pipeline", label="fresh") is not None
    assert [j["label"] for j in jh.recent_jobs()] == ["fresh"]


# ── endpoint ──────────────────────────────────────────────────────────────────

def test_api_jobs_recent(jobs_file):
    from gui.app import app
    jh.record_job("autocompress", label="C:/watch", counts={"compressed": 3})
    resp = app.test_client().get("/api/jobs/recent?limit=5")
    assert resp.status_code == 200
    jobs = resp.get_json()["jobs"]
    assert len(jobs) == 1 and jobs[0]["kind"] == "autocompress"
    assert jobs[0]["counts"]["compressed"] == 3


# ── pipeline runner hook ──────────────────────────────────────────────────────

def _run_thread(monkeypatch, fake_pipeline, config=None, stop_set=False):
    monkeypatch.setattr(pr, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(pr, "_start_cpu_sampler", lambda *a, **k: None)
    monkeypatch.setattr(pr, "_stop_cpu_sampler", lambda *a, **k: None)
    monkeypatch.setattr(pr, "_save_gui_state", lambda *a, **k: None)
    stop = threading.Event()
    if stop_set:
        stop.set()
    pr._run_pipeline_thread(dict(config or {"input_source": "C:/vids/a.mp4",
                                            "mode": "mode1"}), stop)


def test_pipeline_run_records_completed_job(jobs_file, monkeypatch):
    _run_thread(monkeypatch, lambda **kw: None)
    jobs = jh.recent_jobs()
    assert len(jobs) == 1
    j = jobs[0]
    assert j["kind"] == "pipeline" and j["status"] == "completed"
    assert j["label"] == "a.mp4" and j["counts"]["mode"] == "mode1"
    assert j["started_at"] is not None and j["elapsed_s"] is not None


def test_pipeline_stop_records_stopped_job(jobs_file, monkeypatch):
    _run_thread(monkeypatch, lambda **kw: None, stop_set=True)
    assert jh.recent_jobs()[0]["status"] == "stopped"


def test_pipeline_error_records_error_job(jobs_file, monkeypatch):
    def _boom(**kw):
        raise RuntimeError("encode exploded")
    _run_thread(monkeypatch, _boom)
    j = jh.recent_jobs()[0]
    assert j["status"] == "error" and "encode exploded" in j["error"]


def test_webcam_source_gets_friendly_label(jobs_file, monkeypatch):
    _run_thread(monkeypatch, lambda **kw: None,
                config={"input_source": "0", "mode": "mode0"})
    assert jh.recent_jobs()[0]["label"] == "source 0"


# ── autocompress batch pass ───────────────────────────────────────────────────

@pytest.fixture()
def iso(tmp_path, monkeypatch, jobs_file):
    """Isolate index/persistence and stub encode + verify (mirrors
    tests/test_autocompress.py's fixture)."""
    monkeypatch.setattr(cidx._paths, "state_file", lambda name: tmp_path / name)
    import gui.services.gui_state_persist as gsp
    monkeypatch.setattr(gsp, "_GUI_STATE_FILE", tmp_path / "gui_state.json")

    def _fake_pipeline(input_source, camera_id, output_dir, **kwargs):
        out = Path(output_dir) / f"{camera_id}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"compressed")
        return None

    monkeypatch.setattr(ac, "run_pipeline", _fake_pipeline)
    monkeypatch.setattr(ac, "_verify_output",
                        lambda p: Path(p).is_file() and Path(p).stat().st_size > 0)
    return tmp_path


def _mkvid(path: Path, size: int = 4096) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    old = time.time() - 60
    import os
    os.utime(path, (old, old))
    return path


def test_scan_records_one_batch_job_with_bytes(iso):
    watch = iso / "watch"
    _mkvid(watch / "clip_a.mp4", size=5000)
    _mkvid(watch / "clip_b.mp4", size=3000)

    done = ac.scan_once(str(watch), str(iso / "out"),
                        settle_seconds=0, stable_checks=1)
    assert len(done) == 2

    jobs = [j for j in jh.recent_jobs() if j["kind"] == "autocompress"]
    assert len(jobs) == 1
    j = jobs[0]
    assert j["status"] == "completed"
    assert j["counts"] == {"files": 2, "compressed": 2, "skipped": 0}
    assert j["bytes_in"] == 8000
    assert j["bytes_out"] > 0
    assert j["error"] is None


def test_idle_scan_records_no_job(iso):
    watch = iso / "watch_empty"
    watch.mkdir(parents=True, exist_ok=True)
    assert ac.scan_once(str(watch), str(iso / "out"),
                        settle_seconds=0, stable_checks=1) == []
    assert [j for j in jh.recent_jobs() if j["kind"] == "autocompress"] == []


def test_batch_progress_fields_advance_and_reset(iso, monkeypatch):
    watch = iso / "watch"
    _mkvid(watch / "clip_a.mp4")
    _mkvid(watch / "clip_b.mp4")

    seen = []
    real_process = ac._process_one

    def _spy(src, *a, **kw):
        with ac._ac_lock:
            seen.append((ac._ac_status["batch_total"],
                         ac._ac_status["batch_done"],
                         ac._ac_status["current_file"]))
        return real_process(src, *a, **kw)

    monkeypatch.setattr(ac, "_process_one", _spy)
    ac.scan_once(str(watch), str(iso / "out"), settle_seconds=0, stable_checks=1)

    # During the pass: total=2, done counts up, current_file is the clip name.
    assert seen[0][0] == 2 and seen[0][1] == 0 and seen[0][2].startswith("clip_")
    assert seen[1][1] == 1
    # After the pass: everything reset so the UI stops showing batch progress.
    st = ac.get_status()
    assert st["batch_total"] == 0 and st["batch_done"] == 0
    assert st["current_file"] == ""
