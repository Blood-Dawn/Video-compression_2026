import pytest
from src.utils.db import (
    initialize_database,
    insert_segment,
    query_by_type,
    query_segments_by_target_count,
    query_daily_storage_summary,
)

@pytest.fixture
def temp_db(tmp_path):
    # Use pytest's tmp_path (project basetemp=.pytest_tmp) instead of the
    # system %TEMP% + manual os.remove(). On Windows the manual remove hit
    # WinError 32 because a SQLite handle was still open at teardown; letting
    # pytest clean up (with ignore-cleanup-errors) avoids the lock war.
    # Author: Bloodawn (KheivenD), 2026-05-31 (M0 TASK 0.3 - Windows handle fix).
    db_path = str(tmp_path / "metadata.db")

    initialize_database(db_path)

    insert_segment(
        timestamp="20260412T180000Z",
        camera_id="cam_01",
        target_detected=True,
        roi_count=15,
        file_size=1000,
        duration=5.0,
        file_path="file1.mp4",
        object_type="vehicle",
        db_path=db_path,
    )

    insert_segment(
        timestamp="20260412T181000Z",
        camera_id="cam_01",
        target_detected=True,
        roi_count=5,
        file_size=800,
        duration=5.0,
        file_path="file2.mp4",
        object_type="person",
        db_path=db_path,
    )

    insert_segment(
        timestamp="20260412T182000Z",
        camera_id="cam_02",
        target_detected=False,
        roi_count=0,
        file_size=500,
        duration=5.0,
        file_path="file3.mp4",
        object_type="unknown",
        db_path=db_path,
    )

    yield db_path
    # No manual cleanup - tmp_path is removed by pytest.


_OBJECT_TYPE_COL = 8  # SELECT * column order: id,timestamp,camera_id,target_detected,roi_count,file_size,duration,file_path,object_type,...


def test_query_by_type_vehicle(temp_db):
    results = query_by_type("vehicle", db_path=temp_db)
    assert len(results) == 1
    assert results[0][_OBJECT_TYPE_COL] == "vehicle"


def test_query_by_type_person(temp_db):
    results = query_by_type("person", db_path=temp_db)
    assert len(results) == 1
    assert results[0][_OBJECT_TYPE_COL] == "person"

def test_query_segments_by_target_count(temp_db):
    results = query_segments_by_target_count(db_path=temp_db)

    assert results[0][4] >= results[1][4]


def test_daily_storage_summary(temp_db):
    results = query_daily_storage_summary(db_path=temp_db)

    assert len(results) > 0
    date, camera_id, total_bytes, total_hours = results[0]

    assert isinstance(date, str)
    assert isinstance(camera_id, str)
    assert total_bytes > 0
    assert total_hours > 0


def test_sql_injection_protection(temp_db):
    malicious_input = "vehicle'; DROP TABLE segments; --"
    results = query_by_type(malicious_input, db_path=temp_db)

    assert isinstance(results, list)

# ── Planner 6.11: combo-label search gap ──────────────────────────────────
# A segment tagged "person+vehicle" (both classes seen in the same segment -
# see detection/object_filter.py's _label_from_classes()) used to be
# invisible to a single-class "Person" or "Vehicle" filter pick, because
# query_by_type() did a strict object_type == ? equality check. That is
# exactly the "search only people or vehicles" gap the user flagged.

@pytest.fixture
def temp_db_with_combo(tmp_path):
    db_path = str(tmp_path / "metadata.db")
    initialize_database(db_path)

    insert_segment(
        timestamp="20261007T120000Z",
        camera_id="cam_01",
        target_detected=True,
        roi_count=4,
        file_size=900,
        duration=5.0,
        file_path="combo.mp4",
        object_type="person+vehicle",
        db_path=db_path,
    )
    insert_segment(
        timestamp="20261007T121000Z",
        camera_id="cam_01",
        target_detected=True,
        roi_count=2,
        file_size=400,
        duration=5.0,
        file_path="animal.mp4",
        object_type="animal",
        db_path=db_path,
    )
    yield db_path


def test_query_by_type_person_matches_combo_label(temp_db_with_combo):
    results = query_by_type("person", db_path=temp_db_with_combo)
    paths = {r[7] for r in results}
    assert "combo.mp4" in paths


def test_query_by_type_vehicle_matches_combo_label(temp_db_with_combo):
    results = query_by_type("vehicle", db_path=temp_db_with_combo)
    paths = {r[7] for r in results}
    assert "combo.mp4" in paths


def test_query_by_type_animal_does_not_match_combo_label(temp_db_with_combo):
    results = query_by_type("animal", db_path=temp_db_with_combo)
    paths = {r[7] for r in results}
    assert "combo.mp4" not in paths
    assert "animal.mp4" in paths


def test_query_by_type_explicit_combo_string_is_exact(temp_db_with_combo):
    """An explicit combo pick (e.g. the "Person + Vehicle" dropdown option)
    must still behave as an exact match, not widen to single-class rules."""
    results = query_by_type("person+vehicle", db_path=temp_db_with_combo)
    paths = {r[7] for r in results}
    assert paths == {"combo.mp4"}


def test_query_by_type_list_form_unaffected(temp_db_with_combo):
    """The list-of-types form (object_type IN (...)) keeps its own behaviour
    and is not routed through the new single-class combo matching."""
    results = query_by_type(["animal"], db_path=temp_db_with_combo)
    paths = {r[7] for r in results}
    assert paths == {"animal.mp4"}


# ── Planner 6.11: pose_verified_person_count column ───────────────────────

def test_insert_segment_pose_verified_person_count_defaults_to_zero(tmp_path):
    db_path = str(tmp_path / "metadata.db")
    initialize_database(db_path)
    insert_segment(
        timestamp="20261007T130000Z",
        camera_id="cam_01",
        target_detected=True,
        roi_count=1,
        file_size=100,
        duration=5.0,
        file_path="nopose.mp4",
        object_type="person",
        db_path=db_path,
    )
    results = query_by_type("person", db_path=db_path)
    assert len(results) == 1
    assert results[0][-1] == 0  # pose_verified_person_count is the last column


def test_insert_segment_pose_verified_person_count_is_stored(tmp_path):
    db_path = str(tmp_path / "metadata.db")
    initialize_database(db_path)
    insert_segment(
        timestamp="20261007T130500Z",
        camera_id="cam_01",
        target_detected=True,
        roi_count=1,
        file_size=100,
        duration=5.0,
        file_path="withpose.mp4",
        object_type="person",
        person_count=1,
        pose_verified_person_count=1,
        db_path=db_path,
    )
    results = query_by_type("person", db_path=db_path)
    assert len(results) == 1
    assert results[0][-1] == 1


def test_schema_migration_adds_pose_column_to_old_database(tmp_path):
    """initialize_database() must be safe to re-run against a database that
    predates the pose_verified_person_count column (same idempotent-ALTER
    pattern already used for vehicle_count/person_count)."""
    import sqlite3

    db_path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE segments (
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
        """
    )
    conn.commit()
    conn.close()

    # Must not raise even though this old table has none of the v2 columns.
    initialize_database(db_path)

    conn = sqlite3.connect(db_path)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(segments)").fetchall()]
    conn.close()
    assert "pose_verified_person_count" in cols
