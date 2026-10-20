"""query_recent_targets honors its look-back window; migrations add every column."""

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from utils.db import initialize_database, insert_segment, query_recent_targets  # noqa: E402
from utils.db.schema import _ADDED_COLUMNS  # noqa: E402


def _stamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")  # the format every encoder writes


def _insert(db, ts):
    insert_segment(timestamp=ts, camera_id="cam", target_detected=True, roi_count=1,
                   file_size=1, duration=1.0, file_path=f"{ts}.mp4", db_path=db)


def test_rows_older_than_the_window_are_excluded_within_the_same_year(tmp_path):
    db = tmp_path / "m.db"
    initialize_database(db)
    now = datetime.now(timezone.utc)
    recent = _stamp(now - timedelta(hours=1))
    stale = _stamp(now - timedelta(hours=72))
    _insert(db, recent)
    _insert(db, stale)

    rows = query_recent_targets("cam", hours=24, db_path=db)

    assert [r[1] for r in rows] == [recent]


def test_old_database_gets_every_added_column(tmp_path):
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE segments (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,"
            " camera_id TEXT NOT NULL, target_detected INTEGER NOT NULL DEFAULT 0,"
            " roi_count INTEGER NOT NULL DEFAULT 0, file_size INTEGER NOT NULL DEFAULT 0,"
            " duration REAL NOT NULL DEFAULT 0.0, file_path TEXT NOT NULL)"
        )
    conn.close()

    initialize_database(db)
    initialize_database(db)

    with sqlite3.connect(db) as conn:
        cols = [c[1] for c in conn.execute("PRAGMA table_info(segments)")]
    conn.close()
    assert cols[8:] == [name for name, _ in _ADDED_COLUMNS]
