import os
import tempfile
import pytest
from src.utils.db import (
    initialize_database,
    insert_segment,
    query_by_type,
    query_segments_by_target_count,
    query_daily_storage_summary,
)

@pytest.fixture
def temp_db():
    db_fd, db_path = tempfile.mkstemp()
    os.close(db_fd)

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

    os.remove(db_path)


def test_query_by_type_vehicle(temp_db):
    results = query_by_type("vehicle", db_path=temp_db)
    assert len(results) == 1
    assert results[0][-1] == "vehicle"


def test_query_by_type_person(temp_db):
    results = query_by_type("person", db_path=temp_db)
    assert len(results) == 1
    assert results[0][-1] == "person"

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