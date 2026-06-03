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
import json
import os
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
def reset_pipeline_state(tmp_path, monkeypatch):
    """
    Reset all shared pipeline state before every test.

    Without this, a test that calls /api/start would leave _status["running"]
    as True and cause the next test's /api/start to return 409.

    DB isolation: /api/segments discovers metadata.db under EVERY candidate
    root — the configured output_dir, the demo's last_output_root, AND a hard
    fallback to <repo>/outputs. Pointing output_dir at tmp_path isn't enough
    on its own (the repo's real outputs/ DB still leaks in), so we also clear
    the demo root and repoint gui_module._ROOT at tmp_path. Now every
    candidate root is an empty temp dir and tests see only the DB they create.
    Author: Bloodawn (KheivenD), 2026-05-31 (M0 TASK 0.3 — DB test isolation).
    """
    monkeypatch.setattr(gui_module, "_ROOT", tmp_path)
    with gui_module._state_lock:
        gui_module._status.update({
            "running": False,
            "start_time": None,
            "config": {"output_dir": str(tmp_path)},
            "frame_count": 0,
            "segment_count": 0,
            "error": None,
        })
    with gui_module._demo_lock:
        gui_module._demo_state["last_output_root"] = ""
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


@pytest.fixture
def archive_dirs(tmp_path):
    """
    Separate active output and archive folders.

    Archive queries should read the explicit archive folder, not the last
    pipeline output_dir stored in GUI state.
    """
    active_dir = tmp_path / "active"
    archive_dir = tmp_path / "archive"
    active_dir.mkdir()
    archive_dir.mkdir()

    initialize_database(active_dir / "metadata.db")
    initialize_database(archive_dir / "metadata.db")

    insert_segment(
        timestamp="20260415T120000Z",
        camera_id="cam_active",
        target_detected=True,
        roi_count=99,
        file_size=100,
        duration=1.0,
        file_path="active.mp4",
        object_type="vehicle",
        db_path=active_dir / "metadata.db",
    )

    segment_file = archive_dir / "archive_seg.mp4"
    segment_file.write_bytes(b"not a real mp4, but enough for URL presence")
    insert_segment(
        timestamp="20260415T130000Z",
        camera_id="cam_archive",
        target_detected=True,
        roi_count=7,
        file_size=segment_file.stat().st_size,
        duration=2.0,
        file_path="archive_seg.mp4",
        object_type="vehicle",
        db_path=archive_dir / "metadata.db",
    )

    return active_dir, archive_dir


@pytest.fixture
def stitched_demo_root(tmp_path):
    root = tmp_path / "demo"
    old_dir = root / "demos_stitched"
    new_dir = root / "demos_stitched_1"
    old_dir.mkdir(parents=True)
    new_dir.mkdir()

    old_video = old_dir / "mode0_demo.mp4"
    new_video = new_dir / "mode0_demo.mp4"
    split_video = new_dir / "demo_splitscreen.mp4"
    old_video.write_bytes(b"old")
    new_video.write_bytes(b"new")
    split_video.write_bytes(b"split")

    old_manifest = old_dir / "manifest.json"
    old_manifest.write_text(json.dumps({
        "modes": ["mode0"],
        "stitched_dir": str(old_dir),
        "outputs": {"mode0": {"standard": str(old_video)}},
    }), encoding="utf-8")

    new_manifest = new_dir / "manifest.json"
    new_manifest.write_text(json.dumps({
        "modes": ["mode0"],
        "stitched_dir": str(new_dir),
        "outputs": {"mode0": {"standard": str(new_video)}},
    }), encoding="utf-8")

    old_time = time.time() - 10
    new_time = time.time()
    os.utime(old_manifest, (old_time, old_time))
    os.utime(new_manifest, (new_time, new_time))

    return root, new_manifest


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

    def test_start_codec_default_is_libsvtav1(self, client, fake_pipeline):
        """Default codec is libsvtav1 (flipped 2026-05-03). ROIEncoder
        auto-falls-back to libx264 at construction time when the running
        ffmpeg doesn't have libsvtav1, so this default is safe even on
        machines without a modern ffmpeg build."""
        resp = client.post("/api/start", json={"input_source": "data/test.mp4"})
        cfg = resp.get_json()["config"]
        assert cfg["codec"] == "libsvtav1"

    def test_start_codec_passthrough(self, client, fake_pipeline):
        """Selected codec must round-trip into the pipeline config — this
        is what makes the GUI's new codec dropdown actually do anything.
        Author: Bloodawn (KheivenD), 2026-05-02."""
        resp = client.post(
            "/api/start",
            json={"input_source": "data/test.mp4", "codec": "libsvtav1"},
        )
        cfg = resp.get_json()["config"]
        assert cfg["codec"] == "libsvtav1"

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


# ---------------------------------------------------------------------------
# /api/demo/status — ROADMAP 5.3
# ---------------------------------------------------------------------------
#
# These tests verify the contract the front-end relies on for the in-browser
# demo viewer: /api/demo/status echoes the in-memory _demo_state dict, and a
# successful run populates `result.split_screen` plus per-mode URLs already
# rewritten as `/api/media?path=…`. The front-end (_demoNotifyDone +
# _demoRenderResults in index.html) consumes that shape directly to render
# the inline result panel and the "Watch Now" notification action.
#
# Author: Bloodawn (KheivenD)
# ---------------------------------------------------------------------------

class TestApiDemoStatus:
    """Sanity checks for /api/demo/status used by the in-GUI demo viewer."""

    @pytest.fixture(autouse=True)
    def _reset_demo_state(self):
        """Snapshot _demo_state and restore after each test in this class."""
        with gui_module._demo_lock:
            saved = dict(gui_module._demo_state)
        yield
        with gui_module._demo_lock:
            gui_module._demo_state.clear()
            gui_module._demo_state.update(saved)

    def test_returns_200(self, client):
        resp = client.get("/api/demo/status")
        assert resp.status_code == 200

    def test_idle_shape(self, client):
        """When idle the response must still be a dict with `running` defined."""
        with gui_module._demo_lock:
            gui_module._demo_state.update(
                running=False, status="idle", result=None, error=None,
            )
        data = client.get("/api/demo/status").get_json()
        assert isinstance(data, dict)
        assert "running" in data

    def test_done_result_exposes_playable_urls(self, client):
        """
        Simulate a finished demo run with split-screen + per-mode outputs.

        The front-end (`_demoCollectPlayables` in index.html) expects:
          result.split_screen  – string URL or None
          result.videos        – { mode: { view: url|null } }
        Every URL must already start with `/api/media?path=` so the
        operator can play inline without hitting the local file system.
        """
        fake_result = {
            "manifest_path": "/tmp/demo_comp/manifest.json",
            "modes": ["mode0", "mode1"],
            "videos": {
                "mode0": {"standard": "/api/media?path=%2Ftmp%2Fdemo_comp%2Fmode0.mp4"},
                "mode1": {"standard": "/api/media?path=%2Ftmp%2Fdemo_comp%2Fmode1.mp4"},
            },
            "split_screen": "/api/media?path=%2Ftmp%2Fdemo_comp%2Fdemo_splitscreen.mp4",
        }
        with gui_module._demo_lock:
            gui_module._demo_state.update(
                running=False, status="done", error=None, result=fake_result,
            )

        data = client.get("/api/demo/status").get_json()
        assert data["status"] == "done"
        assert data["running"] is False
        result = data["result"]
        assert result["split_screen"].startswith("/api/media?path=")
        for mode in ("mode0", "mode1"):
            url = result["videos"][mode]["standard"]
            assert url and url.startswith("/api/media?path=")

    def test_error_state_round_trips(self, client):
        """An errored run must still respond 200 and surface the error string."""
        with gui_module._demo_lock:
            gui_module._demo_state.update(
                running=False, status="error",
                error="manifest.json not found after demo run",
                result=None,
            )
        data = client.get("/api/demo/status").get_json()
        assert data["status"] == "error"
        assert "manifest.json" in (data.get("error") or "")


class TestApiDemoHistory:
    """Smoke check that /api/demo/history responds with a JSON list."""

    def test_returns_200_and_list(self, client, tmp_path):
        # Point the search roots at an empty tmp folder so we don't depend on
        # whatever demo runs actually exist on the developer's machine.
        with gui_module._state_lock:
            gui_module._status["config"]["output_dir"] = str(tmp_path)
        with gui_module._demo_lock:
            gui_module._demo_state["last_output_root"] = str(tmp_path)

        resp = client.get("/api/demo/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# /api/hls/latency — ROADMAP 5.1 (rolling end-to-end latency)
# ---------------------------------------------------------------------------
#
# These tests exercise the latency response shape and the bookkeeping the
# annotator thread does on every new .ts segment. We don't spin up FFmpeg
# here — the watcher logic is exercised by manipulating the deques directly
# the same way the watcher would, then asserting the API surfaces a coherent
# rolling average.
#
# Author: Bloodawn (KheivenD)
# ---------------------------------------------------------------------------

class TestApiHlsLatency:
    """Cover the HLS latency endpoint added in ROADMAP 5.1."""

    @pytest.fixture(autouse=True)
    def _reset_hls_state(self):
        """Snapshot _hls_state and the latency deques, restore after."""
        with gui_module._hls_lock:
            saved_state = dict(gui_module._hls_state)
            saved_frames = list(gui_module._hls_frame_ts_dq)
            saved_segs   = list(gui_module._hls_segment_latencies)
        yield
        with gui_module._hls_lock:
            gui_module._hls_state.clear()
            gui_module._hls_state.update(saved_state)
            gui_module._hls_frame_ts_dq.clear()
            gui_module._hls_frame_ts_dq.extend(saved_frames)
            gui_module._hls_segment_latencies.clear()
            gui_module._hls_segment_latencies.extend(saved_segs)

    def test_returns_200_when_idle(self, client):
        resp = client.get("/api/hls/latency")
        assert resp.status_code == 200

    def test_idle_payload_shape(self, client):
        """Every documented field must appear in the JSON, even when idle."""
        with gui_module._hls_lock:
            gui_module._hls_state.update(
                running=False, stream_start_time=None,
                ingest_latency_s=None, latency_avg_s=None,
                latency_last_s=None, latency_samples=0,
                latency_window=20,
            )
        data = client.get("/api/hls/latency").get_json()
        for key in (
            "stream_start_time", "ingest_latency_s",
            "latency_avg_s", "latency_last_s",
            "latency_samples", "latency_window",
            "measuring",
        ):
            assert key in data, f"Missing field in /api/hls/latency response: {key}"
        assert data["measuring"] is False  # not running, so not measuring

    def test_measuring_true_when_running_with_no_samples(self, client):
        """While the stream is up but no chunk has flushed yet, measuring=True."""
        with gui_module._hls_lock:
            gui_module._hls_state.update(
                running=True, stream_start_time=time.time(),
                ingest_latency_s=None, latency_avg_s=None,
                latency_last_s=None, latency_samples=0,
            )
        data = client.get("/api/hls/latency").get_json()
        assert data["measuring"] is True

    def test_rolling_avg_reported_after_samples_arrive(self, client):
        """
        Simulate the watcher thread pushing per-segment latencies and verify
        the API exposes the averaged value with the matching sample count.
        """
        # Pretend three segments flushed with latencies 0.9 / 1.1 / 1.0
        with gui_module._hls_lock:
            gui_module._hls_segment_latencies.clear()
            gui_module._hls_segment_latencies.extend([0.9, 1.1, 1.0])
            avg = sum(gui_module._hls_segment_latencies) / len(gui_module._hls_segment_latencies)
            gui_module._hls_state.update(
                running=True, stream_start_time=time.time(),
                ingest_latency_s=2.5,
                latency_avg_s=round(avg, 3),
                latency_last_s=1.0,
                latency_samples=3,
            )
        data = client.get("/api/hls/latency").get_json()
        assert data["ingest_latency_s"] == 2.5
        assert data["latency_avg_s"] == round(avg, 3)
        assert data["latency_last_s"] == 1.0
        assert data["latency_samples"] == 3
        # Rolling avg present, so the front-end stops showing "measuring…"
        assert data["measuring"] is False

    def test_latency_window_default_is_twenty(self, client):
        """
        The rolling deque is bounded to maxlen=20; the API should expose this
        same window so the front-end can label its display ("over last 20").
        """
        data = client.get("/api/hls/latency").get_json()
        assert data["latency_window"] == 20
        assert gui_module._hls_segment_latencies.maxlen == 20


# ---------------------------------------------------------------------------
# /api/enhance/plates — AI plate reader (Bloodawn / KheivenD, 2026-05-02)
# ---------------------------------------------------------------------------
#
# These tests confirm the routing/validation contract the GUI's READ PLATES
# button relies on. The PlateReader pipeline itself is exercised in
# tests/test_plate_reader.py with synthetic videos and a stub OCR backend —
# we deliberately don't pull PaddleOCR / EasyOCR weights into CI here.

class TestApiPlateReader:
    """Validation + status checks for /api/enhance/plates."""

    def test_status_returns_200_and_shape(self, client):
        resp = client.get("/api/enhance/plates/status")
        assert resp.status_code == 200
        data = resp.get_json()
        for key in ("ocr_backend", "ocr_available", "sr_backend",
                    "sr_available", "sr_scale", "device_request"):
            assert key in data, f"Missing key in plate-reader status: {key}"

    def test_run_requires_file_path(self, client):
        """Empty body must surface a 400 with a clear error message."""
        resp = client.post("/api/enhance/plates", json={})
        assert resp.status_code == 400
        body = resp.get_json() or {}
        assert "file_path" in (body.get("error") or "")

    def test_run_404_when_missing(self, client, tmp_path):
        """Absent file must return 404 instead of crashing."""
        bogus = tmp_path / "does_not_exist.mp4"
        resp = client.post("/api/enhance/plates", json={"file_path": str(bogus)})
        assert resp.status_code == 404

    def test_run_rejects_enc_files(self, client, tmp_path):
        """Encrypted segments must be decrypted by the operator first."""
        enc = tmp_path / "fake.mp4.enc"
        enc.write_bytes(b"\x00" * 64)
        resp = client.post("/api/enhance/plates", json={"file_path": str(enc)})
        assert resp.status_code == 400
        # The error message must mention decryption so the operator knows
        # what to do — otherwise the 400 is unhelpful.
        msg = (resp.get_json() or {}).get("error", "").lower()
        assert "decrypt" in msg


# ---------------------------------------------------------------------------
# /api/enhance/benchmark — SR strategy comparison (Bloodawn / KheivenD)
# ---------------------------------------------------------------------------

class TestApiEnhanceBenchmark:
    """Validation contract for the SR comparison endpoint.

    The benchmark logic itself is exercised in
    tests/test_enhancement_benchmark.py with a stub Enhancer; here we just
    confirm the route's input validation matches the documented contract.
    """

    def test_requires_file_path(self, client):
        resp = client.post("/api/enhance/benchmark",
                           json={"roi_box": [0, 0, 10, 10]})
        assert resp.status_code == 400
        assert "file_path" in (resp.get_json().get("error") or "")

    def test_requires_roi_box_list(self, client, tmp_path):
        p = tmp_path / "x.mp4"
        p.write_bytes(b"\x00")
        resp = client.post("/api/enhance/benchmark",
                           json={"file_path": str(p)})
        assert resp.status_code == 400
        assert "roi_box" in (resp.get_json().get("error") or "")

    def test_404_on_missing_file(self, client, tmp_path):
        resp = client.post("/api/enhance/benchmark",
                           json={"file_path": str(tmp_path / "no.mp4"),
                                 "roi_box": [0, 0, 10, 10]})
        assert resp.status_code == 404

    def test_rejects_enc_files(self, client, tmp_path):
        enc = tmp_path / "a.mp4.enc"
        enc.write_bytes(b"\x00")
        resp = client.post("/api/enhance/benchmark",
                           json={"file_path": str(enc),
                                 "roi_box": [0, 0, 10, 10]})
        assert resp.status_code == 400
        assert "decrypt" in (resp.get_json().get("error") or "").lower()


# ---------------------------------------------------------------------------
# OneDrive routing audit regression tests (Bloodawn / KheivenD)
# ---------------------------------------------------------------------------

class TestDefaultOutputDir:
    """Regression for the output-dir resolution order, updated for the
    2026-05-14 productization change. New order:
      1. persisted absolute output_dir (highest priority)
      2. cloud sync root — ONLY when the user opts in (prefer_cloud_output)
      3. platform videos folder (~/Videos/SVCS etc.)
      4. repo outputs/ (last-resort dev fallback)
    OneDrive is no longer the implicit default.
    """

    def _clear_persisted(self):
        # The autouse fixture seeds an absolute output_dir; clear it so the
        # lower-priority branches (cloud / videos) are exercised.
        with gui_module._state_lock:
            gui_module._status["config"]["output_dir"] = ""

    def test_default_output_dir_uses_cloud_when_opted_in(self, monkeypatch, tmp_path):
        self._clear_persisted()
        cloud = tmp_path / "FakeOneDrive"
        cloud.mkdir()
        with gui_module._state_lock:
            gui_module._status["config"]["prefer_cloud_output"] = True
        # TASK 1.2: _default_output_dir + _detect_cloud_root live in
        # gui.services.cloud_detection now; patch the detector there so the
        # call inside _default_output_dir (resolved via that module) sees it.
        monkeypatch.setattr(
            "gui.services.cloud_detection._detect_cloud_root",
            lambda: (cloud, "FakeOneDrive", "https://example/test"),
        )
        result = gui_module._default_output_dir()
        assert result == str(cloud / gui_module._CLOUD_SUBFOLDER)

    def test_default_output_dir_ignores_cloud_when_not_opted_in(self, monkeypatch, tmp_path):
        # Cloud is opt-in: even with a cloud root present, without the flag
        # the default must fall through to the platform videos folder.
        self._clear_persisted()
        fake_videos = tmp_path / "Videos" / "SVCS"
        # _detect_cloud_root lives in the cloud_detection service (TASK 1.2);
        # not opted in here so it is never called, but patch the real home.
        monkeypatch.setattr(
            "gui.services.cloud_detection._detect_cloud_root",
            lambda: (tmp_path / "FakeOneDrive", "FakeOneDrive", "https://example/test"),
        )
        monkeypatch.setattr(gui_module._paths, "default_videos_dir", lambda: fake_videos)
        result = gui_module._default_output_dir()
        assert result == str(fake_videos)


# ---------------------------------------------------------------------------
# CRF override passthrough — added 2026-05-02 with the Mode 3 redo.
# ---------------------------------------------------------------------------

class TestStartCrfPassthrough:
    """User-supplied CRF must round-trip into the pipeline config so the
    new sidebar field actually controls encoder quality."""

    def test_default_crf_is_none(self, client, fake_pipeline):
        """No CRF in the request body means 'use the mode default'.
        The config dict stores None so run_pipeline can resolve it
        based on mode."""
        resp = client.post("/api/start", json={"input_source": "data/test.mp4"})
        cfg = resp.get_json()["config"]
        assert cfg["crf"] is None

    def test_crf_passthrough(self, client, fake_pipeline):
        resp = client.post(
            "/api/start",
            json={"input_source": "data/test.mp4", "crf": 35},
        )
        cfg = resp.get_json()["config"]
        assert cfg["crf"] == 35

    def test_blank_crf_string_treated_as_none(self, client, fake_pipeline):
        """The GUI sends an empty string when the user leaves the CRF input
        blank. Backend must coerce that to None, not crash on int('')."""
        resp = client.post(
            "/api/start",
            json={"input_source": "data/test.mp4", "crf": ""},
        )
        cfg = resp.get_json()["config"]
        assert cfg["crf"] is None
