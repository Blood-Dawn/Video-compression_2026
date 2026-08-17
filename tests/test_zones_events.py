"""
tests/test_zones_events.py - R5 TASK 5.6 (zone masks) + 5.7 API surface.

Covers: config round-trip with validation/clamping, the exclude-region
filter (a masked region yields no foreground and no events), event-log
persistence, and the /api/zones + /api/events/recent routes.

Author: Bloodawn (KheivenD), 2026-08-17 (R5 TASKS 5.6/5.7).
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.app import app as flask_app  # noqa: E402
from utils import event_log, zones_config  # noqa: E402
from utils.track_events import EventEngine  # noqa: E402


def _region(x, y, w, h):
    return SimpleNamespace(x=x, y=y, w=w, h=h)


# ── config round-trip ────────────────────────────────────────────────────────

def test_config_roundtrip_and_validation(tmp_path):
    p = tmp_path / "zones.json"
    stored = zones_config.save_camera_config("cam1", {
        "exclude": [[0.0, 0.0, 0.5, 0.5], [2.0, -1.0, 0.9, 0.9], "junk"],
        "lines": [{"id": "gate", "line": [0.5, 0, 0.5, 1]}, {"id": "", "line": [0, 0, 1, 1]}],
        "zones": [{"id": "door", "rect": [0.4, 0.4, 0.7, 0.8]}],
        "loiter_s": 999999, "class_filter": ["Person", "  ", "car"],
    }, path_override=p)
    assert len(stored["exclude"]) == 2          # junk dropped
    assert stored["exclude"][1] == [1.0, 0.0, 0.9, 0.9]  # clamped into 0..1
    assert [l["id"] for l in stored["lines"]] == ["gate"]  # empty id dropped
    assert stored["loiter_s"] == 3600.0          # capped
    assert stored["class_filter"] == ["person", "car"]
    loaded = zones_config.load_camera_config("cam1", path_override=p)
    assert loaded == stored
    # Unknown camera gets pure defaults.
    assert zones_config.load_camera_config("nope", path_override=p)["exclude"] == []


# ── the 5.6 acceptance: masked region produces nothing ───────────────────────

def test_masked_region_yields_no_foreground_and_no_events():
    # Frame 1000x1000. Exclude the left half; a region in it must vanish,
    # one outside must survive.
    excl = [[0.0, 0.0, 0.5, 1.0]]
    inside = _region(100, 400, 100, 100)    # center (0.15, 0.45) -> excluded
    outside = _region(700, 400, 100, 100)   # center (0.75, 0.45) -> kept
    kept = zones_config.filter_regions([inside, outside], excl, 1000, 1000)
    assert kept == [outside]

    # And through the event engine: a track crossing a line INSIDE the
    # excluded area never produces an event because its regions were dropped
    # before tracking.
    eng = EventEngine(lines=[{"id": "g", "line": (0.25, 0.0, 0.25, 1.0)}])
    events = []
    for i, x_px in enumerate([200, 240, 260, 300]):  # crosses x=0.25 in pixels
        regions = zones_config.filter_regions(
            [_region(x_px, 450, 60, 100)], excl, 1000, 1000)
        boxes = [(r.x / 1000, r.y / 1000, (r.x + r.w) / 1000, (r.y + r.h) / 1000)
                 for r in regions]
        events.extend(eng.step(boxes, t=float(i)))
    assert events == []


def test_no_excludes_passthrough():
    regions = [_region(10, 10, 5, 5)]
    assert zones_config.filter_regions(regions, [], 100, 100) == regions


# ── event log ────────────────────────────────────────────────────────────────

def test_event_log_roundtrip(tmp_path):
    n = event_log.append_events(tmp_path, [
        {"kind": "line_crossing", "track_id": 1, "t": 1.0, "geometry_id": "g"},
        {"kind": "loitering", "track_id": 2, "t": 9.0, "geometry_id": "d"},
    ], camera_id="cam9")
    assert n == 2
    recent = event_log.read_recent(tmp_path, limit=10)
    assert len(recent) == 2
    assert recent[0]["kind"] == "loitering"      # newest first
    assert recent[0]["camera_id"] == "cam9"
    assert "wall_time" in recent[0]
    assert event_log.read_recent(tmp_path / "missing") == []


# ── routes ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def test_zones_route_roundtrip(client, tmp_path, monkeypatch):
    monkeypatch.setattr(zones_config, "_config_path",
                        lambda path_override=None: tmp_path / "zones.json")
    r = client.post("/api/zones", json={
        "camera_id": "cam_rt",
        "exclude": [[0, 0, 0.3, 0.3]],
        "lines": [{"id": "gate", "line": [0.5, 0, 0.5, 1]}],
    })
    assert r.status_code == 200
    assert r.get_json()["config"]["lines"][0]["id"] == "gate"
    r2 = client.get("/api/zones", query_string={"camera_id": "cam_rt"})
    assert r2.status_code == 200
    assert r2.get_json()["config"]["exclude"] == [[0, 0, 0.3, 0.3]]


def test_zones_route_rejects_bad_camera(client):
    assert client.get("/api/zones", query_string={"camera_id": "../etc"}).status_code == 400
    assert client.post("/api/zones", json={"camera_id": ""}).status_code == 400


def test_events_recent_route_shape(client):
    r = client.get("/api/events/recent")
    assert r.status_code == 200
    body = r.get_json()
    assert "events" in body and isinstance(body["events"], list)
