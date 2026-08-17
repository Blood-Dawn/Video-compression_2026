"""
tests/test_track_events.py - R5 TASK 5.7 acceptance (synthetic tracks only).

From docs/CLAUDE-CODE-R5.md: a synthetic track crossing a defined line raises
exactly ONE line-crossing event; loitering fires only after the dwell
threshold and not before; direction is correct for a known track; a single
object cannot emit a burst of duplicate events (debounce).

Author: Bloodawn (KheivenD), 2026-08-17 (R5 TASK 5.7).
"""

import sys
from pathlib import Path

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils.track_events import EventEngine  # noqa: E402


def _box_at(cx, cy, w=0.06, h=0.10):
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


VERTICAL_LINE = {"id": "gate", "line": (0.5, 0.0, 0.5, 1.0)}
ZONE = {"id": "door", "rect": (0.4, 0.4, 0.7, 0.8)}


def test_track_crossing_line_emits_exactly_one_event():
    eng = EventEngine(lines=[VERTICAL_LINE])
    events = []
    # One object walks left to right across x=0.5 in small steps.
    xs = [0.30, 0.38, 0.44, 0.49, 0.51, 0.56, 0.63, 0.70]
    for i, x in enumerate(xs):
        events.extend(eng.step([_box_at(x, 0.5)], t=i * 0.5))
    crossings = [e for e in events if e["kind"] == "line_crossing"]
    assert len(crossings) == 1
    ev = crossings[0]
    assert ev["geometry_id"] == "gate"
    assert ev["direction"] == "right"
    assert ev["track_id"] == 1  # one continuous track, not N re-detections


def test_no_crossing_no_event():
    eng = EventEngine(lines=[VERTICAL_LINE])
    events = []
    for i, x in enumerate([0.10, 0.20, 0.30, 0.40, 0.45]):
        events.extend(eng.step([_box_at(x, 0.5)], t=i * 0.5))
    assert events == []


def test_loitering_fires_only_after_threshold():
    eng = EventEngine(zones=[ZONE], loiter_s=10.0)
    events = []
    # Object sits inside the zone; frames at 1s spacing.
    for i in range(9):  # t = 0..8, dwell < 10s
        events.extend(eng.step([_box_at(0.55, 0.6)], t=float(i)))
    assert events == []  # not before the threshold
    events.extend(eng.step([_box_at(0.55, 0.6)], t=10.0))
    loiters = [e for e in events if e["kind"] == "loitering"]
    assert len(loiters) == 1
    assert loiters[0]["geometry_id"] == "door"
    assert loiters[0]["dwell_s"] >= 10.0


def test_leaving_zone_resets_dwell():
    eng = EventEngine(zones=[ZONE], loiter_s=5.0)
    events = []
    for i in range(4):  # inside t=0..3
        events.extend(eng.step([_box_at(0.55, 0.6)], t=float(i)))
    events.extend(eng.step([_box_at(0.10, 0.6)], t=4.0))  # steps out
    for i in range(5, 9):  # back inside t=5..8 (dwell restarts at 5)
        events.extend(eng.step([_box_at(0.55, 0.6)], t=float(i)))
    assert events == []  # 8 - 5 = 3s < 5s threshold after the reset


def test_direction_up_for_upward_track():
    eng = EventEngine(lines=[{"id": "h", "line": (0.0, 0.5, 1.0, 0.5)}])
    events = []
    for i, y in enumerate([0.8, 0.7, 0.6, 0.52, 0.48, 0.4]):
        events.extend(eng.step([_box_at(0.5, y)], t=i * 0.5))
    crossings = [e for e in events if e["kind"] == "line_crossing"]
    assert len(crossings) == 1
    assert crossings[0]["direction"] == "up"


def test_debounce_blocks_burst_from_one_object():
    # Object oscillates across the line rapidly; debounce_s collapses the
    # burst to one event within the window.
    eng = EventEngine(lines=[VERTICAL_LINE], debounce_s=10.0)
    events = []
    xs = [0.45, 0.55, 0.45, 0.55, 0.45, 0.55]
    for i, x in enumerate(xs):
        events.extend(eng.step([_box_at(x, 0.5)], t=i * 0.5))
    assert len([e for e in events if e["kind"] == "line_crossing"]) == 1


def test_class_filter_gates_events():
    eng = EventEngine(lines=[VERTICAL_LINE], class_filter=["person"])
    events = []
    for i, x in enumerate([0.45, 0.55]):
        events.extend(eng.step([_box_at(x, 0.5)], t=float(i), labels=["car"]))
    assert events == []  # car filtered out
    eng2 = EventEngine(lines=[VERTICAL_LINE], class_filter=["person"])
    events2 = []
    for i, x in enumerate([0.45, 0.55]):
        events2.extend(eng2.step([_box_at(x, 0.5)], t=float(i), labels=["person"]))
    assert len(events2) == 1


def test_two_objects_get_two_tracks():
    eng = EventEngine(lines=[VERTICAL_LINE], debounce_s=0.0)
    events = []
    for i, (xa, xb) in enumerate([(0.45, 0.44), (0.55, 0.43), (0.65, 0.42)]):
        events.extend(eng.step(
            [_box_at(xa, 0.3), _box_at(xb, 0.8)], t=float(i)))
    crossings = [e for e in events if e["kind"] == "line_crossing"]
    assert len(crossings) == 1  # only object A crossed
    ids = {t.track_id for t in eng.tracks}
    assert len(ids) == 2
