"""
utils.db.schema  -  Connection bootstrap and DDL for the segments table.

This module owns everything that defines the *shape* of the database:
- Opening a sqlite3 connection in WAL mode.
- Creating the ``segments`` table on first run.
- Idempotent ALTER TABLE migrations for columns added in later versions
  (object_type, sharpness, the v2 enhanced-metadata block, etc.).

Anything that reads or writes rows lives in ``utils.db.queries``.

Author: Bloodawn (KheivenD), 2026-05-14 (audit split).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Union

from utils.db import DB_NAME


@contextmanager
def get_connection(db_path: Union[str, Path] = DB_NAME) -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection (WAL mode) as a closing context manager.

    WAL (Write-Ahead Logging) allows readers and writers to operate
    concurrently without blocking each other. Important when a query
    tool or reporting script runs alongside the encoding pipeline.

    IMPORTANT: a bare ``sqlite3.Connection`` used as ``with conn:`` only
    commits/rolls back the transaction - it does NOT close the
    connection. That left a connection (and the WAL ``-wal``/``-shm``
    sidecar files) open after every DB call, which on Windows locked the
    database file and broke temp-dir cleanup (WinError 32) and could lock
    the live DB in the running app. This context manager commits on
    success, rolls back on error, and always closes the connection.

    Usage (unchanged for all existing callers):
        with get_connection(db_path) as conn:
            conn.execute(...)

    Args:
        db_path: Path to the SQLite database file, or ':memory:' for tests.

    Yields:
        An open sqlite3.Connection in WAL mode, closed on block exit.

    Author: Bloodawn (KheivenD), 2026-05-31 (M0 TASK 0.3 - close leaked
    connections; fixes WinError 32 on Windows).
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database(db_path: Union[str, Path] = DB_NAME) -> None:
    """Create the segments table and performance indexes if they do not exist.

    Safe to call multiple times. All statements use IF NOT EXISTS, and
    column additions are guarded by a PRAGMA table_info check so the
    function can be re-run against an old database without errors.
    Should be called once at pipeline startup before any inserts.

    Args:
        db_path: Path to the SQLite database file.
    """
    with get_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS segments (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TEXT    NOT NULL,
                camera_id       TEXT    NOT NULL,
                target_detected INTEGER NOT NULL DEFAULT 0,
                roi_count       INTEGER NOT NULL DEFAULT 0,
                file_size       INTEGER NOT NULL DEFAULT 0,
                duration        REAL    NOT NULL DEFAULT 0.0,
                file_path       TEXT    NOT NULL,
                object_type     TEXT    NOT NULL DEFAULT 'unknown'
            )
        """)

        # Idempotent column additions for databases upgraded from M1.
        # Reading PRAGMA table_info once is cheaper than swallowing
        # repeated OperationalError on duplicate columns.
        cursor = conn.execute("PRAGMA table_info(segments)")
        columns = [col[1] for col in cursor.fetchall()]

        if "object_type" not in columns:
            conn.execute("ALTER TABLE segments ADD COLUMN object_type TEXT DEFAULT 'unknown'")

        if "avg_sharpness" not in columns:
            conn.execute("ALTER TABLE segments ADD COLUMN avg_sharpness REAL DEFAULT NULL")

        if "sharpness_label" not in columns:
            conn.execute("ALTER TABLE segments ADD COLUMN sharpness_label TEXT DEFAULT NULL")

        if "hidden" not in columns:
            conn.execute("ALTER TABLE segments ADD COLUMN hidden INTEGER DEFAULT 0")

        # ── Enhanced metadata (v2) ────────────────────────────────────────
        # object_classes: JSON array of distinct COCO classes detected,
        # e.g. ["car","person"]
        if "object_classes" not in columns:
            conn.execute("ALTER TABLE segments ADD COLUMN object_classes TEXT DEFAULT NULL")

        # dominant_color: most common color in detected ROI crops
        # (Cody's HSV approach).
        if "dominant_color" not in columns:
            conn.execute("ALTER TABLE segments ADD COLUMN dominant_color TEXT DEFAULT NULL")

        # scene_type: highway | intersection | parking | street | unknown
        if "scene_type" not in columns:
            conn.execute("ALTER TABLE segments ADD COLUMN scene_type TEXT DEFAULT 'unknown'")

        # time_of_day: day | night | dusk_dawn  (derived from timestamp hour)
        if "time_of_day" not in columns:
            conn.execute("ALTER TABLE segments ADD COLUMN time_of_day TEXT DEFAULT NULL")

        # vehicle_count / person_count: per-segment object tallies.
        if "vehicle_count" not in columns:
            conn.execute("ALTER TABLE segments ADD COLUMN vehicle_count INTEGER DEFAULT 0")

        if "person_count" not in columns:
            conn.execute("ALTER TABLE segments ADD COLUMN person_count INTEGER DEFAULT 0")

        # Index on (camera_id, timestamp) makes query_recent_targets O(log n).
        # Without this, every query is a full table scan. A problem after
        # weeks of footage accumulate thousands of rows.
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_cam_time
            ON segments(camera_id, timestamp)
        """)
        conn.commit()
