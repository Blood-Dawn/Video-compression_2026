"""
tests/test_metadata_search.py

Metadata and search: only camera classes are stored, each clip remembers when
a class first appears, search results carry that moment, and STOP on a live
camera lets the pipeline save its last segment instead of killing it.

Author: Bloodawn (KheivenD), 2026-11-25.
"""
import json
import threading
import time

from flask import Flask

from detection.object_filter import STORED_CLASSES, storable
from gui.services.nl_query import _with_seek, search
from utils.db.queries import insert_segment
from utils.db.schema import initialize_database


def test_only_camera_classes_are_stored():
    assert storable({"person", "cow", "chair", "car", "dog"}) == {"person", "car", "dog"}
    assert storable({"cow", "kite"}) == set()
    assert "cow" not in STORED_CLASSES


def test_seek_uses_the_class_in_the_phrase():
    row = {"detection_times": json.dumps({"person": 3.2, "car": 11.0})}
    assert _with_seek(dict(row), ["car"])["seek_seconds"] == 11.0
    assert _with_seek(dict(row), ["person"])["seek_seconds"] == 3.2
    assert _with_seek(dict(row), [])["seek_seconds"] == 3.2        # earliest of anything


def test_seek_is_none_for_clips_without_timings():
    assert _with_seek({"detection_times": None}, ["car"])["seek_seconds"] is None
    assert _with_seek({"detection_times": "not json"}, [])["seek_seconds"] is None


def test_search_returns_the_moment(tmp_path):
    db = tmp_path / "metadata.db"
    initialize_database(str(db))
    insert_segment(
        timestamp="20261125T201500Z", camera_id="cam1", target_detected=True,
        roi_count=3, file_size=1000, duration=15.0, file_path="a.mp4",
        object_type="vehicle", object_classes='["car","person"]',
        detection_times=json.dumps({"person": 2.5, "car": 9.0}),
        db_path=str(db),
    )
    res = search("car", str(db))
    assert res["count"] == 1
    seg = res["segments"][0]
    assert seg["seek_seconds"] == 9.0
    assert "detection_times" not in seg


class _FakeEncoder:
    def __init__(self):
        self.aborted = threading.Event()

    def abort_segment(self):
        self.aborted.set()


def _stop_client(monkeypatch, source, grace=0.3):
    from gui.routes import pipeline_bp as bp
    from gui.services import pipeline_runner as runner
    from gui.state import _state_lock, _status

    app = Flask(__name__)
    app.register_blueprint(bp.pipeline_bp)
    enc = _FakeEncoder()
    monkeypatch.setattr(runner, "_active_encoder", enc)
    monkeypatch.setattr(runner, "_stop_event", threading.Event())
    monkeypatch.setattr(bp, "_LIVE_STOP_GRACE_SECONDS", grace)
    with _state_lock:
        _status["running"] = True
        _status["last_config"] = {"input_source": source}
    return app.test_client(), enc, (_state_lock, _status)


def test_stop_on_a_file_aborts_the_pipe_at_once(monkeypatch):
    client, enc, (lock, status) = _stop_client(monkeypatch, "clip.mp4")
    try:
        assert client.post("/api/stop").status_code == 200
        assert enc.aborted.is_set()
    finally:
        with lock:
            status["running"] = False


def test_stop_on_a_live_url_waits_before_aborting(monkeypatch):
    client, enc, (lock, status) = _stop_client(monkeypatch, "rtsp://127.0.0.1:8554/live")
    try:
        assert client.post("/api/stop").status_code == 200
        assert not enc.aborted.is_set()          # still saving the last segment
        assert enc.aborted.wait(2.0)             # but a stuck encoder is aborted after the grace
    finally:
        with lock:
            status["running"] = False


def test_stop_on_a_live_url_leaves_a_finished_save_alone(monkeypatch):
    client, enc, (lock, status) = _stop_client(monkeypatch, "rtsp://127.0.0.1:8554/live")
    assert client.post("/api/stop").status_code == 200
    with lock:
        status["running"] = False                 # the pipeline finished saving
    time.sleep(0.6)
    assert not enc.aborted.is_set()


def test_hourly_counts_group_people_and_vehicles(tmp_path):
    from datetime import datetime, timezone
    from gui.services.db_helpers import hourly_detection_counts

    db = tmp_path / "metadata.db"
    initialize_database(str(db))
    # 2026-11-25 14:00 UTC, three clips: person only, vehicle only, both.
    stamp = "20261125T140000Z"
    local_hour = datetime(2026, 11, 25, 14, 0, tzinfo=timezone.utc).astimezone().hour
    for pc, vc in ((1, 0), (0, 1), (1, 1)):
        insert_segment(
            timestamp=stamp, camera_id="cam1", target_detected=True, roi_count=1,
            file_size=10, duration=5.0, file_path="x.mp4",
            person_count=pc, vehicle_count=vc, db_path=str(db),
        )
    out = hourly_detection_counts(db)
    assert out["clips"] == 3
    row = out["hours"][local_hour]
    assert row == {"hour": local_hour, "people": 2, "vehicles": 2}
    assert sum(h["people"] for h in out["hours"]) == 2


def test_hourly_counts_on_a_missing_database_are_zero(tmp_path):
    from gui.services.db_helpers import hourly_detection_counts

    out = hourly_detection_counts(tmp_path / "nope.db")
    assert out["clips"] == 0
    assert len(out["hours"]) == 24
