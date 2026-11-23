"""Pins the stage functions taken out of nl_query.parse."""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.services import nl_query as nq  # noqa: E402


def _run(stage, text):
    clauses, params, explain = [], [], {}
    left = stage(text, clauses, params, explain)
    return left, clauses, params, explain


def test_between_window_removes_its_words_and_keeps_the_order():
    left, clauses, params, explain = _run(nq._parse_time_windows, "red car between 9am and 5pm")
    assert params == [9, 17] and explain == {"hours": [9, 17]}
    assert "between" not in left and "red car" in left and len(clauses) == 1
    assert " OR " not in clauses[0]


def test_between_window_wraps_through_midnight():
    _, clauses, params, explain = _run(nq._parse_time_windows, "between 9pm and 5am")
    assert params == [21, 5] and explain == {"hours": [21, 5]}
    assert " OR " in clauses[0]


def test_after_does_not_swallow_a_date():
    left, clauses, _, _ = _run(nq._parse_time_windows, "after 2026-11-01")
    assert clauses == [] and "2026-11-01" in left


def test_last_n_days_and_this_week():
    _, clauses, params, explain = _run(nq._parse_dates, "cars last 7 days")
    assert params == [(date.today() - timedelta(days=6)).strftime("%Y%m%d")] and clauses[0].endswith(">= ?")
    assert "since" in explain
    _, _, params, _ = _run(nq._parse_dates, "this week")
    assert params == [(date.today() - timedelta(days=6)).strftime("%Y%m%d")]


@pytest.mark.parametrize("text", ["show camera footage", "camera red car", "cam people"])
def test_camera_word_alone_is_not_a_camera_id(text):
    _, clauses, _, explain = _run(nq._parse_camera, text)
    assert clauses == [] and "camera" not in explain


def test_after_and_before_accept_minutes_and_am_pm():
    _, _, params, explain = _run(nq._parse_time_windows, "after 6:30 pm before 8")
    assert params == [18, 8] and explain == {"after_hour": 18, "before_hour": 8}


def test_no_time_words_leaves_everything_alone():
    assert _run(nq._parse_time_windows, "red car") == ("red car", [], [], {})


def test_iso_date_and_relative_days():
    left, clauses, params, explain = _run(nq._parse_dates, "clips 2026-05-01 here")
    assert params == ["20260501"] and explain == {"date": "2026-05-01"} and "2026" not in left
    _, _, params, explain = _run(nq._parse_dates, "yesterday")
    assert params == [(date.today() - timedelta(days=1)).strftime("%Y%m%d")]
    _, _, params, _ = _run(nq._parse_dates, "today")
    assert params == [date.today().strftime("%Y%m%d")]


@pytest.mark.parametrize("text,cam", [("cam2", "2"), ("camera 3", "3"), ("camera_north", "north"),
    ("cam-a1", "-a1")])   # pinned quirk: the hyphen is part of the matched name
def test_camera_forms(text, cam):
    left, clauses, params, explain = _run(nq._parse_camera, text)
    assert params == [cam] and explain == {"camera": cam} and left.strip() == ""


@pytest.mark.parametrize("text,col,op,n", [
    ("more than 2 people", "person_count", ">", 2), ("over 5 cars", "vehicle_count", ">", 5),
    ("at least 3 vehicles", "vehicle_count", ">=", 3), ("at least 0 persons", "person_count", ">=", 0)])
def test_count_comparisons(text, col, op, n):
    left, clauses, params, explain = _run(nq._parse_counts, text)
    assert clauses == [f"{col} {op} ?"] and params == [n] and explain == {"count": {col: f"{op} {n}"}}
    assert left.strip() == ""


def test_word_filters_map_known_words_and_return_the_rest():
    color = next(iter(nq._COLOR_WORDS))
    clauses, params, explain = [], [], {}
    free = nq._parse_word_filters(f"{color} the zzzunknown", clauses, params, explain)
    assert free == ["zzzunknown"]
    assert explain["colors"] == [nq._COLOR_WORDS[color]] and nq._COLOR_WORDS[color] in params


def test_parse_composes_the_stages_in_order():
    out = nq.parse("Red car between 9am and 5pm cam2 at least 2 people xyzzy")
    assert out["explain"]["hours"] == [9, 17] and out["explain"]["camera"] == "2"
    assert out["explain"]["count"] == {"person_count": ">= 2"}
    assert out["params"][-4:] == ["xyzzy"] * 4          # unknown word falls through to free text
    assert nq.parse(None) == nq.parse("")


def test_time_filters_work_on_the_pipelines_compact_timestamps(tmp_path):
    """Real rows look like 20260315T213000Z; strftime() cannot read those."""
    import sqlite3
    from datetime import datetime
    db = tmp_path / "ts.db"
    today = date.today().strftime("%Y%m%d")
    stamps = {"night": f"{today}T233000Z", "noon": f"{today}T120000Z", "early": f"{today}T040000Z",
              "old": "20200101T233000Z", "iso_night": f"{date.today().isoformat()}T22:15:00Z"}
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE segments (id INTEGER PRIMARY KEY, timestamp TEXT, camera_id TEXT, file_path TEXT, "
                 "hidden INTEGER, object_classes TEXT, dominant_color TEXT, scene_type TEXT, time_of_day TEXT, "
                 "object_type TEXT, person_count INTEGER, vehicle_count INTEGER, duration REAL, file_size INTEGER)")
    for name, ts in stamps.items():
        conn.execute("INSERT INTO segments (timestamp, camera_id, file_path, hidden) VALUES (?,?,?,0)", (ts, "cam1", name))
    conn.commit()

    def ids(q):
        c, p = [], []
        left = nq._parse_time_windows(q, c, p, {})
        nq._parse_dates(left, c, p, {})
        where = " AND ".join(c) or "1=1"
        return {r[0] for r in conn.execute(f"SELECT file_path FROM segments WHERE {where}", p)}

    assert ids("after 9pm") == {"night", "old", "iso_night"}
    assert ids("between 9pm and 5am") == {"night", "early", "old", "iso_night"}
    c, p = [], []
    nq._parse_dates("today", c, p, {})
    got = {r[0] for r in conn.execute(f"SELECT file_path FROM segments WHERE {c[0]}", p)}
    assert got == {"night", "noon", "early", "iso_night"}
    conn.close()
