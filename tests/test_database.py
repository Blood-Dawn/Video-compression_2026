"""
test_database.py

Tests for src/utils/db.py.
Covers: initialize_database, insert_segment, query_recent_targets,
        query_segments_by_target_count, query_daily_storage_summary.

All tests use the tmp_db or seeded_db fixtures from conftest.py which
create isolated SQLite databases in pytest's tmp_path — no side effects
on outputs/metadata.db.
"""

import pytest
from utils.db import (
    initialize_database,
    insert_segment,
    query_recent_targets,
    query_segments_by_target_count,
    query_daily_storage_summary,
    get_connection,
)


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

class TestInitializeDatabase:
    def test_creates_db_file(self, tmp_db, tmp_path):
        """initialize_database should create the file on disk."""
        assert (tmp_path / "test.db").exists()

    def test_idempotent(self, tmp_db):
        """Calling initialize_database twice must not raise or duplicate tables."""
        initialize_database(tmp_db)   # second call
        with get_connection(tmp_db) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='segments'"
            ).fetchall()
        assert len(rows) == 1

    def test_index_created(self, tmp_db):
        """The (camera_id, timestamp) index must be present for O(log n) queries."""
        with get_connection(tmp_db) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_cam_time'"
            ).fetchall()
        assert len(rows) == 1

    def test_wal_mode(self, tmp_db):
        """get_connection must enable WAL journal mode for concurrent access."""
        with get_connection(tmp_db) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"


# ---------------------------------------------------------------------------
# Insert and basic retrieval
# ---------------------------------------------------------------------------

class TestInsertSegment:
    def test_single_insert_returns_one_row(self, tmp_db):
        insert_segment(
            timestamp="20260101T000000Z",
            camera_id="cam_01",
            target_detected=True,
            roi_count=3,
            file_size=12345,
            duration=60.0,
            file_path="out.mp4",
            db_path=tmp_db,
        )
        rows = query_recent_targets("cam_01", hours=9999, db_path=tmp_db)
        assert len(rows) == 1

    def test_multiple_inserts_no_duplicates(self, tmp_db):
        """Inserting N rows should yield exactly N rows — no silent de-duplication."""
        for i in range(3):
            insert_segment(
                timestamp=f"202601010{i}0000Z",
                camera_id="cam_01",
                target_detected=True,
                roi_count=i,
                file_size=1000 * (i + 1),
                duration=10.0,
                file_path=f"seg_{i}.mp4",
                db_path=tmp_db,
            )
        rows = query_recent_targets("cam_01", hours=9999, db_path=tmp_db)
        assert len(rows) == 3

    def test_row_values_stored_correctly(self, tmp_db):
        insert_segment(
            timestamp="20260315T120000Z",
            camera_id="cam_02",
            target_detected=True,
            roi_count=7,
            file_size=999_999,
            duration=45.5,
            file_path="/abs/path/seg.mp4",
            db_path=tmp_db,
        )
        rows = query_recent_targets("cam_02", hours=9999, db_path=tmp_db)
        assert len(rows) == 1
        row = rows[0]
        # (id, timestamp, camera_id, target_detected, roi_count, file_size, duration, file_path)
        assert row[1] == "20260315T120000Z"
        assert row[2] == "cam_02"
        assert row[3] == 1          # target_detected stored as int
        assert row[4] == 7          # roi_count
        assert row[5] == 999_999    # file_size
        assert abs(row[6] - 45.5) < 0.01
        assert row[7] == "/abs/path/seg.mp4"

    def test_target_detected_false_stored_as_zero(self, tmp_db):
        insert_segment(
            timestamp="20260101T000000Z",
            camera_id="cam_bg",
            target_detected=False,
            roi_count=0,
            file_size=5000,
            duration=60.0,
            file_path="bg.mp4",
            db_path=tmp_db,
        )
        with get_connection(tmp_db) as conn:
            row = conn.execute("SELECT target_detected FROM segments").fetchone()
        assert row[0] == 0


# ---------------------------------------------------------------------------
# query_recent_targets
# ---------------------------------------------------------------------------

class TestQueryRecentTargets:
    def test_excludes_other_cameras(self, seeded_db):
        """Only rows for the requested camera_id should be returned."""
        rows = query_recent_targets("cam_a", hours=9999, db_path=seeded_db)
        assert all(r[2] == "cam_a" for r in rows)

    def test_excludes_background_only_segments(self, seeded_db):
        """
        cam_b has one segment with target_detected=False.
        query_recent_targets must exclude it.
        """
        rows = query_recent_targets("cam_b", hours=9999, db_path=seeded_db)
        assert len(rows) == 0

    def test_empty_db_returns_empty_list(self, tmp_db):
        rows = query_recent_targets("cam_missing", hours=24, db_path=tmp_db)
        assert rows == []

    def test_hours_zero_returns_empty(self, tmp_db):
        """hours=0 means look-back window is zero — no rows should qualify."""
        insert_segment(
            timestamp="20200101T000000Z",   # definitely in the past
            camera_id="cam_01",
            target_detected=True,
            roi_count=1,
            file_size=1000,
            duration=10.0,
            file_path="old.mp4",
            db_path=tmp_db,
        )
        rows = query_recent_targets("cam_01", hours=0, db_path=tmp_db)
        assert rows == []

    def test_results_ordered_newest_first(self, seeded_db):
        """Results must be ordered by timestamp DESC."""
        rows = query_recent_targets("cam_a", hours=9999, db_path=seeded_db)
        assert len(rows) == 2
        assert rows[0][1] > rows[1][1]   # first row is more recent


# ---------------------------------------------------------------------------
# query_segments_by_target_count (Milestone 2)
# ---------------------------------------------------------------------------

class TestQuerySegmentsByTargetCount:
    def test_returns_highest_roi_first(self, seeded_db):
        rows = query_segments_by_target_count(db_path=seeded_db, limit=10)
        assert len(rows) >= 2
        # roi_count column (index 4) should be descending
        roi_counts = [r[4] for r in rows]
        assert roi_counts == sorted(roi_counts, reverse=True)

    def test_excludes_background_only_rows(self, seeded_db):
        """cam_b's background segment (roi_count=0) must not appear."""
        rows = query_segments_by_target_count(db_path=seeded_db, limit=100)
        assert all(r[3] == 1 for r in rows)

    def test_limit_is_respected(self, tmp_db):
        for i in range(5):
            insert_segment(
                timestamp=f"2026010{i+1}T000000Z",
                camera_id="cam_01",
                target_detected=True,
                roi_count=i + 1,
                file_size=1000,
                duration=10.0,
                file_path=f"s{i}.mp4",
                db_path=tmp_db,
            )
        rows = query_segments_by_target_count(db_path=tmp_db, limit=2)
        assert len(rows) == 2

    def test_empty_db_returns_empty(self, tmp_db):
        assert query_segments_by_target_count(db_path=tmp_db) == []


# ---------------------------------------------------------------------------
# query_daily_storage_summary (Milestone 2)
# ---------------------------------------------------------------------------

class TestQueryDailyStorageSummary:
    def test_aggregates_by_date_and_camera(self, seeded_db):
        """
        seeded_db has cam_a (2 segs) and cam_b (1 seg), all on the same date.
        Summary should have 2 rows: one per camera.
        """
        rows = query_daily_storage_summary(db_path=seeded_db)
        cameras = {r[1] for r in rows}
        assert "cam_a" in cameras
        assert "cam_b" in cameras

    def test_total_bytes_correct(self, seeded_db):
        """cam_a has two segments of 100k and 200k bytes — sum should be 300k."""
        rows = query_daily_storage_summary(db_path=seeded_db)
        cam_a_row = next(r for r in rows if r[1] == "cam_a")
        assert cam_a_row[2] == 300_000

    def test_empty_db_returns_empty(self, tmp_db):
        assert query_daily_storage_summary(db_path=tmp_db) == []
