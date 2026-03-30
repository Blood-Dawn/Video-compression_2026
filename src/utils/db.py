"""
db.py

SQLite metadata index for encoded video segments.
Used by the pipeline to track compressed outputs.

Design notes:
  - All functions accept an explicit db_path argument so tests can use
    in-memory or tmp databases without touching the real metadata.db.
  - WAL journal mode is enabled on every connection for concurrent-read
    safety (multiple cameras, query tools running alongside the pipeline).
  - An index on (camera_id, timestamp) makes query_recent_targets O(log n)
    instead of O(n) as the table grows with weeks of footage.
  - Context managers (with conn:) ensure connections are closed and
    transactions are committed/rolled back even if an exception is raised.
"""

import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple, Union


# Default database path. Override via the db_path argument on every function
# so callers are always explicit. This constant exists only for backward
# compatibility — new code should always pass db_path explicitly.
DB_NAME = "metadata.db"

# Type alias for a row returned from the segments table.
SegmentRow = Tuple[int, str, str, int, int, int, float, str]


def get_connection(db_path: Union[str, Path] = DB_NAME) -> sqlite3.Connection:
    """
    Open a SQLite connection with WAL journal mode enabled.

    WAL (Write-Ahead Logging) allows readers and writers to operate
    concurrently without blocking each other — important when a query
    tool or reporting script runs alongside the encoding pipeline.

    Args:
        db_path: Path to the SQLite database file, or ':memory:' for tests.

    Returns:
        An open sqlite3.Connection in WAL mode.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def initialize_database(db_path: Union[str, Path] = DB_NAME) -> None:
    """
    Create the segments table and performance indexes if they do not exist.

    Safe to call multiple times — all statements use IF NOT EXISTS.
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
                file_path       TEXT    NOT NULL
            )
        """)
        # Index on (camera_id, timestamp) makes query_recent_targets O(log n).
        # Without this, every query is a full table scan — a problem after weeks
        # of footage accumulate thousands of rows.
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_cam_time
            ON segments(camera_id, timestamp)
        """)
        conn.commit()


def insert_segment(
    timestamp: str,
    camera_id: str,
    target_detected: bool,
    roi_count: int,
    file_size: int,
    duration: float,
    file_path: str,
    db_path: Union[str, Path] = DB_NAME,
) -> None:
    """
    Insert one encoded segment into the metadata index.

    Called by ROIEncoder after each successful encode. Each row represents
    one compressed video segment file.

    Args:
        timestamp: UTC timestamp string in '%Y%m%dT%H%M%SZ' format.
        camera_id: Identifier for the camera that produced this segment.
        target_detected: True if at least one foreground object was detected.
        roi_count: Total number of foreground regions across all frames.
        file_size: Compressed file size in bytes.
        duration: Segment duration in seconds.
        file_path: Absolute or relative path to the compressed output file.
        db_path: Path to the SQLite database file.
    """
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO segments (
                timestamp, camera_id, target_detected,
                roi_count, file_size, duration, file_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                camera_id,
                int(target_detected),
                roi_count,
                file_size,
                duration,
                file_path,
            ),
        )
        conn.commit()


def query_recent_targets(
    camera_id: str,
    hours: int = 24,
    db_path: Union[str, Path] = DB_NAME,
) -> List[SegmentRow]:
    """
    Return all segments from a camera where targets were detected in the
    last N hours.

    Uses the (camera_id, timestamp) index for efficient filtering.

    Args:
        camera_id: Camera to filter by.
        hours: Look-back window in hours (default 24).
        db_path: Path to the SQLite database file.

    Returns:
        List of segment rows as tuples:
        (id, timestamp, camera_id, target_detected, roi_count, file_size,
         duration, file_path)
    """
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT * FROM segments
            WHERE camera_id      = ?
              AND target_detected = 1
              AND timestamp      >= datetime('now', ?)
            ORDER BY timestamp DESC
            """,
            (camera_id, f"-{hours} hours"),
        )
        return cursor.fetchall()


def query_segments_by_target_count(
    db_path: Union[str, Path] = DB_NAME,
    limit: int = 50,
) -> List[SegmentRow]:
    """
    Return segments sorted by roi_count descending (most detections first).

    Useful for finding the busiest clips in the archive.

    Args:
        db_path: Path to the SQLite database file.
        limit: Maximum number of rows to return.

    Returns:
        List of segment rows ordered by roi_count descending.
    """
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT * FROM segments
            WHERE target_detected = 1
            ORDER BY roi_count DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cursor.fetchall()


def query_daily_storage_summary(
    db_path: Union[str, Path] = DB_NAME,
) -> List[Tuple[str, str, int, float]]:
    """
    Return daily storage usage grouped by camera and date.

    Useful for operational reporting: "how much did each camera record today?"

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        List of (date, camera_id, total_bytes, total_hours) tuples,
        ordered by date descending.
    """
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT
                substr(timestamp, 1, 8)   AS date,
                camera_id,
                SUM(file_size)            AS total_bytes,
                ROUND(SUM(duration)/3600, 3) AS total_hours
            FROM segments
            GROUP BY date, camera_id
            ORDER BY date DESC, camera_id
            """
        )
        return cursor.fetchall()
