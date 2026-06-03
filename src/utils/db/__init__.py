"""
utils.db  -  SQLite metadata index for encoded video segments.

This package used to be a single 333-line ``utils/db.py``. The 2026-05-14
audit flagged it as a code-smell because schema definition and query
helpers had no clean boundary, making it hard to reason about which
functions ran DDL vs. plain reads. The split is purely structural - no
behavior change.

Layout::

    utils/db/
        __init__.py    ← re-exports the public surface (this file)
        schema.py      ← get_connection() + initialize_database() + DDL
        queries.py     ← insert_segment() + query_* helpers

Every prior caller still imports the same names: ``from utils.db import
insert_segment`` works exactly as before, because they're re-exported
here. New code can pick the narrower import if it wants to make intent
visible::

    from utils.db.schema import initialize_database
    from utils.db.queries import insert_segment, query_recent_targets

Design notes (preserved from the original module):
  - All functions accept an explicit ``db_path`` argument so tests can
    use in-memory or tmp databases without touching the real metadata.db.
  - WAL journal mode is enabled on every connection for concurrent-read
    safety (multiple cameras, query tools running alongside the pipeline).
  - An index on (camera_id, timestamp) makes query_recent_targets
    O(log n) instead of O(n) as the table grows with weeks of footage.

Author: Bloodawn (KheivenD), 2026-05-14 (audit split).
"""

from __future__ import annotations

from typing import Tuple

# ── Shared constants ──────────────────────────────────────────────────────
# Default database filename. Override via the db_path argument on every
# function so callers are always explicit. This constant exists only for
# backward compatibility; new code should pass db_path explicitly.
DB_NAME = "metadata.db"

# Type alias for a row returned from the segments table.
# (id, timestamp, camera_id, target_detected, roi_count, file_size,
#  duration, file_path, object_type) + the v2 enhanced-metadata columns
# are appended on the right; we keep the alias narrow for callers that
# only consume the legacy columns.
SegmentRow = Tuple[int, str, str, int, int, int, float, str, str]


# ── Public re-exports ─────────────────────────────────────────────────────
# Import order matters: schema first (queries depends on get_connection).
from utils.db.schema import get_connection, initialize_database  # noqa: E402
from utils.db.queries import (  # noqa: E402
    insert_segment,
    query_recent_targets,
    query_segments_by_target_count,
    query_daily_storage_summary,
    query_by_type,
)

__all__ = [
    "DB_NAME",
    "SegmentRow",
    "get_connection",
    "initialize_database",
    "insert_segment",
    "query_recent_targets",
    "query_segments_by_target_count",
    "query_daily_storage_summary",
    "query_by_type",
]
