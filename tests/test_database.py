import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.db import initialize_database, insert_segment, query_recent_targets


def test_database_creation(tmp_path):
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    assert db_path.exists()


def test_insert_and_query(tmp_path):
    db_path = tmp_path / "test.db"
    initialize_database(db_path)

    insert_segment(
        timestamp="2026-01-01T00:00:00",
        camera_id="cam_test",
        target_detected=True,
        roi_count=3,
        file_size=12345,
        duration=60,
        file_path="test.mp4",
        db_path=db_path,
    )

    rows = query_recent_targets("cam_test", hours=9999, db_path=db_path)

    assert len(rows) == 1
