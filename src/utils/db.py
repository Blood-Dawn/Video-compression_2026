"""
db.py

SQLite metadata index for encoded video segments.
Used by the pipeline to track compressed outputs.
"""

import sqlite3
from pathlib import Path
from datetime import datetime


DB_NAME = "metadata.db"


def get_connection(db_path=DB_NAME):
    return sqlite3.connect(db_path)


def initialize_database(db_path=DB_NAME):
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS segments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        camera_id TEXT,
        target_detected INTEGER,
        roi_count INTEGER,
        file_size INTEGER,
        duration REAL,
        file_path TEXT
    )
    """)

    conn.commit()
    conn.close()


def insert_segment(
    timestamp,
    camera_id,
    target_detected,
    roi_count,
    file_size,
    duration,
    file_path,
    db_path=DB_NAME,
):
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO segments (
        timestamp,
        camera_id,
        target_detected,
        roi_count,
        file_size,
        duration,
        file_path
    )
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        timestamp,
        camera_id,
        int(target_detected),
        roi_count,
        file_size,
        duration,
        file_path,
    ))

    conn.commit()
    conn.close()


def query_recent_targets(camera_id, hours=24, db_path=DB_NAME):
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("""
    SELECT * FROM segments
    WHERE camera_id = ?
    AND target_detected = 1
    AND timestamp >= datetime('now', ?)
    """, (camera_id, f"-{hours} hours"))

    rows = cur.fetchall()
    conn.close()
    return rows
