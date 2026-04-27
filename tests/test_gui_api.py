"""
tests/test_gui_api.py

GUI regression tests for src/gui/app.py.

Tests HTTP status codes, JSON response shapes, and state transitions for:
  GET  /api/status
  POST /api/start
  POST /api/stop
  GET  /api/segments
  GET  /api/storage

The pipeline worker thread is replaced with a controlled fake so no video
files, FFmpeg, or OpenCV are required to run these tests.

Author: KD
"""

import sys
import time
import threading
from pathlib import Path

import pytest

# Make sure src/ is importable
SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import gui.app as gui_module
from gui.app import app as flask_app
from utils.db import initialize_database, insert_segment


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Flask test client with TESTING mode on."""
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_pipeline_state(tmp_path):
    """
    Reset all shared pipeline state before every test.

    Without this, a test that calls /api/start would leave _status["running"]
    as True and cause the next test's /api/start to return 409.

    output_dir is pointed at tmp_path (no metadata.db there) so tests that
    expect an empty/missing DB don't accidentally find a real outputs/ DB.
    """
    with gui_module._state_lock:
        gui_module._status.update({
            "running": False,
            "start_time": None,
            "config": {"output_dir": str(tmp_path)},
            "frame_count": 0,
            "segment_count": 0,
            "error": None,
        })
    gui_module._pipeline_thread = None
    gui_module._stop_event = None
    yield
    # Teardown: stop any thread started during the test
    if gui_module._stop_event:
        gui_module._stop_event.set()
    if gui_module._pipeline_thread and gui_module._pipeline_thread.is_alive():
        gui_module._pipeline_thread.join(timeout=2)


@pytest.fixture
def fake_pipeline(monkeypatch):
    """
    Replace _run_pipeline_thread with a fake that sets running=True,
    waits for the stop_event, then sets running=False.

    This lets start/stop state-transition tests work without any real video.
    """
    def _fake(config, stop_event):
        with gui_module._state_lock:
            gui_module._status["running"] = True
            gui_module._status["config"] = config
            gui_module._status["start_time"] = time.time()
        stop_event.wait()
        with gui_module._state_lock:
            gui_module._status["running"] = False

    monkeypatch.setattr(gui_module, "_run_pipeline_thread", _fake)


@pytest.fixture
def db_with_segments(tmp_path):
    """
    Temp SQLite DB with two segments — one with a target, one without.
    Returns the tmp_path so tests can point output_dir at it.
    """
    db_path = tmp_path / "metadata.db"
    initialize_database(db_path)
    insert_segment(
        timestamp="20260415T120000Z",
        camera_id="cam_01",
        target_detected=True,
        roi_count=3,
        file_size=512_000,
        duration=60.0,
        file_path="cam_01_seg1.mp4",
        db_path=db_path,
    )
    insert_segment(
        timestamp="20260415T121000Z",
        camera_id="cam_01",
        target_detected=False,
        roi_count=0,
        file_size=64_000,
        duration=60.0,
        file_path="cam_01_seg2.mp4",
        db_path=db_path,
    )
    return tmp_path


# ---------------------------------------------------------------------------
# /api/status
# ---------------------------------------------------------------------------

class TestApiStatus:
    def test_returns_200(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200

    def test_json_shape_when_idle(self, client):
        resp = client.get("/api/status")
        data = resp.get_json()
        assert isinstance(data, dict)
        # Required keys
        for key in ("running", "frame_count", "segment_count", "error",
                    "elapsed_seconds", "fps"):
            assert key in data, f"Missing key: {key}"

    def test_not_running_by_default(self, client):
        data = client.get("/api/status").get_json()
        assert data["running"] is False

    def test_elapsed_and_fps_are_none_when_idle(self, client):
        data = client.get("/api/status").get_json()
        assert data["elapsed_seconds"] is None
        assert data["fps"] is None


# ---------------------------------------------------------------------------
# /api/start
# ---------------------------------------------------------------------------

class TestApiStart:
    def test_start_returns_200_and_ok(self, client, fake_pipeline):
        resp = client.post(
            "/api/start",
            json={"input_source": "data/test.mp4", "camera_id": "cam_test"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

    def test_start_response_includes_config(self, client, fake_pipeline):
        resp = client.post(
            "/api/start",
            json={"input_source": "data/test.mp4", "camera_id": "cam_test",
                  "mode": "mode1"},
        )
        data = resp.get_json()
        assert "config" in data
        assert data["config"]["camera_id"] == "cam_test"
        assert data["config"]["mode"] == "mode1"

    def test_start_default_config_values(self, client, fake_pipeline):
        resp = client.post("/api/start", json={})
        data = resp.get_json()
        cfg = data["config"]
        assert cfg["bg_method"] == "MOG2"
        assert cfg["mode"] == "mode0"
        assert cfg["enhance"] is False
        assert cfg["encrypt"] is False

    def test_double_start_returns_409(self, client, fake_pipeline):
        client.post("/api/start", json={"input_source": "data/test.mp4"})
        # Wait briefly for the fake thread to set running=True
        time.sleep(0.05)
        resp = client.post("/api/start", json={"input_source": "data/test.mp4"})
        assert resp.status_code == 409
        data = resp.get_json()
        assert "error" in data

    def test_start_sets_running_true(self, client, fake_pipeline):
        client.post("/api/start", json={"input_source": "data/test.mp4"})
        time.sleep(0.05)
        data = client.get("/api/status").get_json()
        assert data["running"] is True


# ---------------------------------------------------------------------------
# /api/stop
# ---------------------------------------------------------------------------

class TestApiStop:
    def test_stop_when_not_running_returns_409(self, client):
        resp = client.post("/api/stop")
        assert resp.status_code == 409
        assert "error" in resp.get_json()

    def test_stop_returns_200_and_ok(self, client, fake_pipeline):
        client.post("/api/start", json={"input_source": "data/test.mp4"})
        time.sleep(0.05)
        resp = client.post("/api/stop")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_stop_sets_running_false(self, client, fake_pipeline):
        client.post("/api/start", json={"input_source": "data/test.mp4"})
        time.sleep(0.05)
        client.post("/api/stop")
        # Give thread time to observe stop_event and set running=False
        time.sleep(0.1)
        data = client.get("/api/status").get_json()
        assert data["running"] is False

    def test_full_start_stop_cycle(self, client, fake_pipeline):
        """Start → confirm running → stop → confirm idle."""
        client.post("/api/start", json={"input_source": "data/test.mp4"})
        time.sleep(0.05)
        assert client.get("/api/status").get_json()["running"] is True

        client.post("/api/stop")
        time.sleep(0.1)
        assert client.get("/api/status").get_json()["running"] is False


# ---------------------------------------------------------------------------
# /api/segments
# ---------------------------------------------------------------------------

class TestApiSegments:
    def test_returns_200(self, client):
        resp = client.get("/api/segments")
        assert resp.status_code == 200

    def test_empty_list_when_no_db(self, client):
        data = client.get("/api/segments").get_json()
        assert "segments" in data
        assert data["segments"] == []

    def test_returns_segments_from_db(self, client, db_with_segments):
        # Point the app's config at our temp db directory
        with gui_module._state_lock:
            gui_module._status["config"]["output_dir"] = str(db_with_segments)

        data = client.get("/api/segments").get_json()
        assert len(data["segments"]) == 2

    def test_segment_shape(self, client, db_with_segments):
        with gui_module._state_lock:
            gui_module._status["config"]["output_dir"] = str(db_with_segments)

        segs = client.get("/api/segments").get_json()["segments"]
        seg = segs[0]
        for key in ("timestamp", "camera_id", "target_detected",
                    "roi_count", "file_size_kb", "duration_s",
                    "file_path", "object_type"):
            assert key in seg, f"Missing key in segment: {key}"

    def test_segments_ordered_newest_first(self, client, db_with_segments):
        with gui_module._state_lock:
            gui_module._status["config"]["output_dir"] = str(db_with_segments)

        segs = client.get("/api/segments").get_json()["segments"]
        timestamps = [s["timestamp"] for s in segs]
        assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# /api/storage
# ---------------------------------------------------------------------------

class TestApiStorage:
    def test_returns_200(self, client):
        resp = client.get("/api/storage")
        assert resp.status_code == 200

    def test_available_false_when_no_db(self, client):
        data = client.get("/api/storage").get_json()
        assert data["available"] is False

    def test_returns_stats_when_db_exists(self, client, db_with_segments):
        with gui_module._state_lock:
            gui_module._status["config"]["output_dir"] = str(db_with_segments)

        data = client.get("/api/storage").get_json()
        assert data["available"] is True

    def test_storage_shape(self, client, db_with_segments):
        with gui_module._state_lock:
            gui_module._status["config"]["output_dir"] = str(db_with_segments)

        data = client.get("/api/storage").get_json()
        for key in ("total_segments", "total_bytes", "total_mb",
                    "segments_with_targets", "total_roi_detections",
                    "total_duration_hours"):
            assert key in data, f"Missing key in storage response: {key}"

    def test_segment_counts_are_correct(self, client, db_with_segments):
        with gui_module._state_lock:
            gui_module._status["config"]["output_dir"] = str(db_with_segments)

        data = client.get("/api/storage").get_json()
        assert data["total_segments"] == 2
        assert data["segments_with_targets"] == 1

    def test_total_bytes_is_correct(self, client, db_with_segments):
        with gui_module._state_lock:
            gui_module._status["config"]["output_dir"] = str(db_with_segments)

        data = client.get("/api/storage").get_json()
        assert data["total_bytes"] == 512_000 + 64_000
        assert data["total_mb"] == round((512_000 + 64_000) / 1e6, 2)
