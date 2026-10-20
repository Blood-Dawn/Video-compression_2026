"""
utils.db.queries  -  Read and write operations against the segments table.

Anything that defines table shape lives in ``utils.db.schema``. This
module is strictly DML - INSERT, SELECT, ORDER BY, GROUP BY.

Author: Bloodawn (KheivenD), 2026-05-14 (audit split).
"""

from __future__ import annotations

from pathlib import Path

from utils.db import DB_NAME, SegmentRow
from utils.db.schema import get_connection


def insert_segment(
    timestamp: str,
    camera_id: str,
    target_detected: bool,
    roi_count: int,
    file_size: int,
    duration: float,
    file_path: str,
    object_type: str = "unknown",
    avg_sharpness: float | None = None,
    sharpness_label: str | None = None,
    object_classes: str | None = None,   # JSON array string, e.g. '["car","person"]'
    dominant_color: str | None = None,   # e.g. "blue", "white"
    scene_type: str = "unknown",            # highway | intersection | parking | street
    time_of_day: str | None = None,      # day | night | dusk_dawn
    vehicle_count: int = 0,
    person_count: int = 0,
    pose_verified_person_count: int = 0,
    db_path: str | Path = DB_NAME,
) -> None:
    """Insert one encoded segment into the metadata index.

    Called by ROIEncoder after each successful encode. Each row
    represents one compressed video segment file.

    Args:
        timestamp: UTC timestamp string in '%Y%m%dT%H%M%SZ' format.
        camera_id: Identifier for the camera that produced this segment.
        target_detected: True if at least one foreground object was detected.
        roi_count: Total number of foreground regions across all frames.
        file_size: Compressed file size in bytes.
        duration: Segment duration in seconds.
        file_path: Absolute or relative path to the compressed output file.
        object_type: COCO class label for the primary object, or 'unknown'.
        avg_sharpness: Mean Laplacian variance across detected target ROIs.
                       None for background-only segments.
        sharpness_label: Human-readable perceptual resolution label,
                         e.g. "~720p (sharp)". None for background-only segments.
        object_classes: JSON array string of all distinct COCO classes seen.
        dominant_color: Most common ROI color (HSV-binned label).
        scene_type: One of highway / intersection / parking / street / unknown.
        time_of_day: One of day / night / dusk_dawn.
        vehicle_count: Tally of vehicle-class detections in this segment.
        person_count: Tally of person-class detections in this segment.
        pose_verified_person_count: Tally of person detections in this
            segment whose bounding box was additionally confirmed by
            YOLO pose/keypoint estimation (planner 6.11), not just the
            bbox classifier. Counts pose-confirmed person regions summed
            across frames, so use it as a yes/no filter (> 0), not as a
            comparison against person_count.
        db_path: Path to the SQLite database file.
    """
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO segments (
                timestamp, camera_id, target_detected,
                roi_count, file_size, duration, file_path, object_type,
                avg_sharpness, sharpness_label,
                object_classes, dominant_color, scene_type,
                time_of_day, vehicle_count, person_count,
                pose_verified_person_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                camera_id,
                int(target_detected),
                roi_count,
                file_size,
                duration,
                file_path,
                object_type,
                avg_sharpness,
                sharpness_label,
                object_classes,
                dominant_color,
                scene_type,
                time_of_day,
                vehicle_count,
                person_count,
                pose_verified_person_count,
            ),
        )
        conn.commit()


def query_recent_targets(
    camera_id: str,
    hours: int = 24,
    db_path: str | Path = DB_NAME,
) -> list[SegmentRow]:
    """Return all segments from a camera where targets were detected in the
    last N hours.

    Uses the (camera_id, timestamp) index for efficient filtering. The
    cutoff is formatted like the stored timestamps ('%Y%m%dT%H%M%SZ', UTC)
    because the comparison is a plain string comparison.

    Args:
        camera_id: Camera to filter by.
        hours: Look-back window in hours (default 24).
        db_path: Path to the SQLite database file.

    Returns:
        List of segment rows, ordered by timestamp descending.
    """
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT * FROM segments
            WHERE camera_id      = ?
              AND target_detected = 1
              AND timestamp      >= strftime('%Y%m%dT%H%M%SZ', 'now', ?)
            ORDER BY timestamp DESC
            """,
            (camera_id, f"-{hours} hours"),
        )
        return cursor.fetchall()


def query_segments_by_target_count(
    db_path: str | Path = DB_NAME,
    limit: int = 50,
) -> list[SegmentRow]:
    """Return segments sorted by roi_count descending (most detections first).

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
    db_path: str | Path = DB_NAME,
) -> list[tuple[str, str, int, float]]:
    """Return daily storage usage grouped by camera and date.

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


def query_by_type(
    object_type: str | list[str],
    camera_id: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    min_roi_count: int | None = None,
    db_path: str | Path = DB_NAME,
) -> list[SegmentRow]:
    """Query segments filtered by object type, camera, time range, and ROI count.

    ``object_type`` may be a single string or a list of strings for
    multi-type queries.
    """
    # A single base class (person/vehicle/animal) must also match combo
    # labels ("person+vehicle", "vehicle+animal", "person+animal" - the
    # only combos _label_from_classes() ever produces), not just an exact
    # object_type equality. That equality check used to silently hide
    # every mixed-type segment from a "people only"/"vehicles only" query
    # (planner 6.11). An explicit combo string (e.g. "person+vehicle") or
    # a multi-type list still gets the exact-match/IN behaviour.
    _base_classes = {"person", "vehicle", "animal"}
    if isinstance(object_type, list):
        placeholders = ",".join(["?"] * len(object_type))
        query = f"SELECT * FROM segments WHERE object_type IN ({placeholders})"
        params: list = list(object_type)
    elif object_type in _base_classes:
        query = (
            "SELECT * FROM segments WHERE (object_type = ?"
            " OR object_type LIKE ? OR object_type LIKE ?)"
        )
        params = [object_type, f"{object_type}+%", f"%+{object_type}"]
    else:
        query = "SELECT * FROM segments WHERE object_type = ?"
        params = [object_type]

    if camera_id:
        query += " AND camera_id = ?"
        params.append(camera_id)

    if start_time:
        query += " AND timestamp >= ?"
        params.append(start_time)

    if end_time:
        query += " AND timestamp <= ?"
        params.append(end_time)

    if min_roi_count is not None:
        query += " AND roi_count >= ?"
        params.append(min_roi_count)

    query += " ORDER BY timestamp DESC"

    with get_connection(db_path) as conn:
        cursor = conn.execute(query, params)
        return cursor.fetchall()
