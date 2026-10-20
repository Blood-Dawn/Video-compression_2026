"""A long-lived track keeps a bounded center history without changing its events."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from utils.track_events import EventEngine  # noqa: E402

LINE = {"id": "fence", "line": (0.5, 0.0, 0.5, 1.0)}


def _box(cx: float, cy: float = 0.5, half: float = 0.02) -> tuple:
    return (cx - half, cy - half, cx + half, cy + half)


def test_center_history_stays_bounded_on_a_long_track():
    eng = EventEngine(lines=[LINE])
    for i in range(5000):
        eng.step([_box(0.2 + 0.0001 * (i % 100))], t=i / 30.0)

    assert len(eng.tracks) == 1
    assert len(eng.tracks[0].centers) == 3


def test_crossings_and_direction_match_the_full_path():
    # Walk right across the fence, dwell, then walk back left. Small steps keep
    # one track the whole time, so every crossing belongs to track 1.
    xs = [0.305 + 0.01 * i for i in range(40)]         # 0.305 -> 0.695
    xs += [0.695] * 200
    xs += [0.695 - 0.01 * i for i in range(1, 31)]     # back to 0.395
    eng = EventEngine(lines=[LINE], debounce_s=0.0)
    events = []
    for i, x in enumerate(xs):
        events += eng.step([_box(x)], t=i / 30.0)

    assert [e["side"] for e in events] == ["negative", "positive"]
    assert {e["track_id"] for e in events} == {1}
    # direction() is first center to last center over the whole life:
    # 0.305 -> 0.395 is rightward even though the latest motion is leftward.
    assert eng.tracks[0].direction() == "right"
    assert events[1]["direction"] == "right"
