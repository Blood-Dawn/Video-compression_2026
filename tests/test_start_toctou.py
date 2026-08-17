"""
tests/test_start_toctou.py - M4: /api/start single-slot claim + job registry.

The running-check and the thread spawn in /api/start used to be ~100 lines
apart with no re-check, so two near-simultaneous POSTs (a phone retrying on a
flaky link) could both start worker threads. The slot is now claimed
atomically under the state lock; the second caller gets 409. The route also
returns a job_id that /api/status carries while running and the job history
records when finished.

The worker stub here deliberately NEVER sets running=True itself: under the
old code both POSTs would then return 200 (the race window made permanent),
so these tests are the regression proof for the claim semantics.

Author: Bloodawn (KheivenD), 2026-08-16 (M4 job registry + TOCTOU).
"""

import sys
import threading
import time
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.app import app as flask_app  # noqa: E402
from gui.routes import pipeline_bp as pbp  # noqa: E402
from gui.services import pipeline_runner as pr  # noqa: E402
from gui.state import _state_lock, _status  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    """Test client with a worker stub that parks until released."""
    release = threading.Event()

    def _stub_worker(config, stop_event):
        # Park; crucially, do NOT touch _status["running"] on entry, so the
        # route's own claim is the only thing standing between two POSTs.
        release.wait(timeout=10)
        with _state_lock:
            _status["running"] = False

    monkeypatch.setattr(pbp, "_run_pipeline_thread", _stub_worker)
    flask_app.config["TESTING"] = True
    with _state_lock:
        _status["running"] = False
        _status["error"] = None
    pr._pipeline_thread = None
    with flask_app.test_client() as c:
        yield c, release
    # Cleanup: release the parked worker and clear state for other tests.
    release.set()
    if pr._pipeline_thread is not None:
        pr._pipeline_thread.join(timeout=5)
    with _state_lock:
        _status["running"] = False
    pr._pipeline_thread = None


def test_second_start_is_refused_and_only_one_worker_runs(client):
    c, release = client
    r1 = c.post("/api/start", json={"input_source": "0", "camera_id": "cam_a"})
    assert r1.status_code == 200
    r2 = c.post("/api/start", json={"input_source": "0", "camera_id": "cam_b"})
    assert r2.status_code == 409
    assert "already running" in r2.get_json()["error"].lower()
    # Exactly one pipeline-worker thread exists.
    workers = [t for t in threading.enumerate() if t.name == "pipeline-worker"]
    assert len(workers) == 1
    release.set()
    workers[0].join(timeout=5)


def test_start_returns_job_id_and_status_carries_it(client):
    c, release = client
    r = c.post("/api/start", json={"input_source": "0", "camera_id": "cam_a"})
    body = r.get_json()
    assert r.status_code == 200
    job_id = body["job_id"]
    assert isinstance(job_id, str) and len(job_id) == 12
    assert body["config"]["job_id"] == job_id
    st = c.get("/api/status").get_json()
    assert st["running"] is True
    assert st["job_id"] == job_id
    release.set()


def test_slot_frees_after_worker_finishes(client):
    c, release = client
    r1 = c.post("/api/start", json={"input_source": "0", "camera_id": "cam_a"})
    assert r1.status_code == 200
    release.set()
    # Wait for the stub to clear running.
    deadline = time.time() + 5
    while time.time() < deadline:
        if not c.get("/api/status").get_json()["running"]:
            break
        time.sleep(0.05)
    if pr._pipeline_thread is not None:
        pr._pipeline_thread.join(timeout=5)
    r2 = c.post("/api/start", json={"input_source": "0", "camera_id": "cam_b"})
    assert r2.status_code == 200
    assert r2.get_json()["job_id"] != r1.get_json()["job_id"]