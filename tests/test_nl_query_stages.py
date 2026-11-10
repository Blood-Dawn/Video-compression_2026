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


def test_between_window_orders_the_hours_and_removes_its_words():
    left, clauses, params, explain = _run(nq._parse_time_windows, "red car between 5pm and 9am")
    assert params == [9, 17] and explain == {"hours": [9, 17]}
    assert "between" not in left and "red car" in left and len(clauses) == 1


def test_after_and_before_accept_minutes_and_am_pm():
    _, _, params, explain = _run(nq._parse_time_windows, "after 6:30 pm before 8")
    assert params == [18, 8] and explain == {"after_hour": 18, "before_hour": 8}


def test_no_time_words_leaves_everything_alone():
    assert _run(nq._parse_time_windows, "red car") == ("red car", [], [], {})


def test_iso_date_and_relative_days():
    left, clauses, params, explain = _run(nq._parse_dates, "clips 2026-05-01 here")
    assert params == ["2026-05-01"] and explain == {"date": "2026-05-01"} and "2026" not in left
    _, _, params, explain = _run(nq._parse_dates, "yesterday")
    assert params == [(date.today() - timedelta(days=1)).isoformat()]
    _, _, params, _ = _run(nq._parse_dates, "today")
    assert params == [date.today().isoformat()]


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
