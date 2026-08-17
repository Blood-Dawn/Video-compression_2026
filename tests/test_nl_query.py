"""
tests/test_nl_query.py - R5 TASK 5.4 (structured natural-language search).

Acceptance from docs/CLAUDE-CODE-R5.md: at least ten phrases mapping to the
correct filters (class, color, time-of-day, absolute date, camera), unknown
terms degrade to a free-text match instead of erroring, and a phrase full of
SQL metacharacters cannot alter the query (parameterization).

Author: Bloodawn (KheivenD), 2026-08-16 (R5 TASK 5.4).
"""

from pathlib import Path

import pytest

from gui.services.nl_query import parse, search  # noqa: E402
from utils.db.schema import get_connection, initialize_database  # noqa: E402


# ── parser: the ten-phrase acceptance table ──────────────────────────────────

CASES = [
    ("red car", {"colors": ["red"], "classes": ["car"]}),
    ("person at night", {"classes": ["person"], "time_of_day": ["night"]}),
    ("blue truck on the highway", {"colors": ["blue"], "classes": ["truck"], "scenes": ["highway"]}),
    ("cars after 9pm", {"classes": ["car"], "after_hour": 21}),
    ("people before 7am", {"classes": ["person"], "before_hour": 7}),
    ("vehicles between 9pm and 11pm", {"classes": ["car"], "hours": [21, 23]}),
    ("person on 2026-08-01", {"classes": ["person"], "date": "2026-08-01"}),
    ("white car on cam2", {"colors": ["white"], "classes": ["car"], "camera": "2"}),
    ("dog in the parking lot", {"classes": ["dog"], "scenes": ["parking"], "free_text": ["lot"]}),
    ("more than 2 people on the street", {"count": {"person_count": "> 2"}, "scenes": ["street"]}),
    ("bicycle in the morning", {"classes": ["bicycle"], "hours": [5, 12]}),
]


@pytest.mark.parametrize("phrase,expected", CASES)
def test_parser_maps_phrase_to_filters(phrase, expected):
    got = parse(phrase)["explain"]
    for key, value in expected.items():
        assert got.get(key) == value, f"{phrase!r}: {key} -> {got.get(key)!r}, wanted {value!r}"


def test_unknown_terms_degrade_to_free_text_not_error():
    got = parse("floofy zorble near the gate")
    assert "free_text" in got["explain"]
    assert "zorble" in got["explain"]["free_text"]
    assert got["clauses"], "unknown words must still produce a LIKE clause"


# ── DB-level: correctness and SQL safety ─────────────────────────────────────

@pytest.fixture()
def seeded_db(tmp_path: Path) -> str:
    db = tmp_path / "meta.db"
    initialize_database(db)
    rows = [
        # timestamp, camera, path, object_type, classes, color, scene, tod, p, v
        ("2026-08-01 21:30:00", "cam2", "a.mp4", "vehicle", '["car"]', "red", "street", "night", 0, 1),
        ("2026-08-01 09:00:00", "cam1", "b.mp4", "vehicle", '["car"]', "blue", "highway", "day", 0, 1),
        ("2026-08-02 22:15:00", "cam2", "c.mp4", "person", '["person"]', None, "street", "night", 3, 0),
        ("2026-08-02 10:00:00", "cam3", "d.mp4", "person", '["person","dog"]', None, "parking", "day", 1, 0),
    ]
    with get_connection(db) as conn:
        for ts, cam, path, otype, classes, color, scene, tod, p, v in rows:
            conn.execute(
                "INSERT INTO segments (timestamp, camera_id, file_path, object_type,"
                " object_classes, dominant_color, scene_type, time_of_day,"
                " person_count, vehicle_count, target_detected, roi_count,"
                " file_size, duration) VALUES (?,?,?,?,?,?,?,?,?,?,1,1,1000,10.0)",
                (ts, cam, path, otype, classes, color, scene, tod, p, v),
            )
    return str(db)


def test_search_red_car_after_9pm_on_cam2(seeded_db):
    result = search("red car after 9pm on cam2", seeded_db)
    assert result["count"] == 1
    assert result["segments"][0]["file_path"] == "a.mp4"


def test_search_people_at_night(seeded_db):
    result = search("people at night", seeded_db)
    assert result["count"] == 1
    assert result["segments"][0]["file_path"] == "c.mp4"


def test_search_date_filter(seeded_db):
    result = search("person on 2026-08-02", seeded_db)
    paths = {s["file_path"] for s in result["segments"]}
    assert paths == {"c.mp4", "d.mp4"}


def test_search_count_filter(seeded_db):
    result = search("more than 2 people", seeded_db)
    assert result["count"] == 1
    assert result["segments"][0]["person_count"] == 3


def test_sql_metacharacters_cannot_alter_query(seeded_db):
    hostile = "'; DROP TABLE segments;--"
    result = search(hostile, seeded_db)
    assert result["count"] == 0  # nothing matches, nothing breaks
    # The table must still exist and still hold every row.
    import sqlite3
    conn = sqlite3.connect(seeded_db)
    try:
        n = conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
    finally:
        conn.close()
    assert n == 4


def test_hidden_rows_are_excluded(seeded_db):
    import sqlite3
    conn = sqlite3.connect(seeded_db)
    try:
        conn.execute("UPDATE segments SET hidden = 1 WHERE file_path = 'a.mp4'")
        conn.commit()
    finally:
        conn.close()
    result = search("red car", seeded_db)
    assert result["count"] == 0
