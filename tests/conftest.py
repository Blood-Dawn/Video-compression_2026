"""
conftest.py

Pytest configuration shared across all test modules.

Adds src/ to sys.path so every test file can import local modules with
    from utils.db import ...
    from compression.roi_encoder import ...
without duplicating the sys.path.insert boilerplate.

Fixtures that are used by multiple test files (e.g. tmp_db, tiny_frames)
also live here to avoid repetition.
"""

import sys
from pathlib import Path
import numpy as np
import pytest

# Make src/ importable from any test file.
SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils.db import initialize_database, insert_segment  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    """Return a path to a freshly initialised, empty SQLite database."""
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    return db_path


@pytest.fixture
def seeded_db(tmp_db):
    """
    Database pre-populated with three segments across two cameras.

    cam_a: two target segments (recent timestamps)
    cam_b: one background-only segment
    """
    insert_segment(
        timestamp="20260101T000000Z",
        camera_id="cam_a",
        target_detected=True,
        roi_count=2,
        file_size=100_000,
        duration=60.0,
        file_path="cam_a_seg1.mp4",
        db_path=tmp_db,
    )
    insert_segment(
        timestamp="20260101T010000Z",
        camera_id="cam_a",
        target_detected=True,
        roi_count=5,
        file_size=200_000,
        duration=60.0,
        file_path="cam_a_seg2.mp4",
        db_path=tmp_db,
    )
    insert_segment(
        timestamp="20260101T000000Z",
        camera_id="cam_b",
        target_detected=False,
        roi_count=0,
        file_size=50_000,
        duration=60.0,
        file_path="cam_b_seg1.mp4",
        db_path=tmp_db,
    )
    return tmp_db


@pytest.fixture
def tiny_frames():
    """
    A list of 10 tiny (16x16) BGR frames — just enough to test encoding
    without the overhead of realistic video dimensions.
    """
    rng = np.random.default_rng(42)
    return [
        rng.integers(0, 256, (16, 16, 3), dtype=np.uint8)
        for _ in range(10)
    ]
