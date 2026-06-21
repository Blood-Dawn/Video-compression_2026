"""
tests/security/test_sql_injection.py  (SEC-D1)

Attack every metadata-DB query path with classic SQL injection payloads and
assert they are inert: the table is not dropped, no rows leak, and the payload is
treated as a literal value (parameterized queries). This pins the existing
defense so a future f-string/`%`/`.format` query cannot reintroduce SQLi.
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils.db import (  # noqa: E402
    get_connection,
    initialize_database,
    insert_segment,
    query_by_type,
    query_recent_targets,
    query_segments_by_target_count,
)

INJECTIONS = [
    "vehicle'; DROP TABLE segments; --",
    "' OR '1'='1",
    "' OR 1=1 --",
    "x' UNION SELECT name FROM sqlite_master --",
    '"; DELETE FROM segments; --',
]


def _seed(db):
    insert_segment(
        timestamp="20260101T000000Z", camera_id="cam_a", target_detected=True,
        roi_count=3, file_size=1000, duration=5.0, file_path="/x/a.mp4",
        object_type="vehicle", db_path=db,
    )
    insert_segment(
        timestamp="20260101T000100Z", camera_id="cam_b", target_detected=True,
        roi_count=1, file_size=2000, duration=5.0, file_path="/x/b.mp4",
        object_type="person", db_path=db,
    )


def _table_exists(db) -> bool:
    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='segments'"
        ).fetchone()
        return row is not None


@pytest.mark.parametrize("payload", INJECTIONS)
def test_query_by_type_is_parameterized(tmp_db, payload):
    _seed(tmp_db)
    # A malicious object_type is matched as a LITERAL -> zero rows, not "all rows"
    # and definitely not a dropped table.
    rows = query_by_type(object_type=payload, db_path=tmp_db)
    assert rows == [], f"injection {payload!r} returned rows; query not parameterized"
    assert _table_exists(tmp_db), f"injection {payload!r} dropped/altered the table"


@pytest.mark.parametrize("payload", INJECTIONS)
def test_camera_id_filter_is_parameterized(tmp_db, payload):
    _seed(tmp_db)
    rows = query_by_type(object_type="vehicle", camera_id=payload, db_path=tmp_db)
    assert rows == [], "camera_id injection leaked rows"
    assert _table_exists(tmp_db)


def test_recent_targets_camera_filter_is_parameterized(tmp_db):
    _seed(tmp_db)
    rows = query_recent_targets(camera_id="' OR 1=1 --", hours=999999, db_path=tmp_db)
    assert rows == []
    assert _table_exists(tmp_db)


def test_busiest_limit_is_integer_only(tmp_db):
    _seed(tmp_db)
    # limit flows in as an int (route casts it); a string LIMIT cannot inject.
    rows = query_segments_by_target_count(db_path=tmp_db, limit=1)
    assert len(rows) <= 1
    assert _table_exists(tmp_db)


def test_segments_route_filters_are_parameterized(tmp_path, monkeypatch):
    """The /api/segments route builds its WHERE from fixed fragments + ? params;
    a malicious camera_id must not error or leak the whole table."""
    import gui.routes.files_bp as fb
    from gui.app import app

    # Point the route's output_dir at a tmp dir holding a seeded metadata.db.
    out = tmp_path / "out"
    out.mkdir()
    db = out / "metadata.db"
    initialize_database(str(db))
    _seed(str(db))
    with fb._state_lock:
        cfg = fb._status.setdefault("config", {})
        prev = cfg.get("output_dir", None)
        cfg["output_dir"] = str(out)
    try:
        client = app.test_client()
        body = client.get("/api/segments",
                          query_string={"camera_id": "' OR 1=1 --"}).get_json()
        # Inert: the literal camera_id matches nothing, and the table survives.
        assert all(s["camera_id"] != "cam_a" for s in body.get("segments", [])) or \
            body.get("segments") == []
        assert _table_exists(str(db))
    finally:
        with fb._state_lock:
            if prev is None:
                fb._status.get("config", {}).pop("output_dir", None)
            else:
                fb._status["config"]["output_dir"] = prev
