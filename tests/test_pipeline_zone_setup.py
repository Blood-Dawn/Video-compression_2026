"""Pins _load_zone_event_setup, the zone/event config block taken out of run_pipeline."""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pipeline import pipeline as pl  # noqa: E402
from utils import zones_config  # noqa: E402


def _cfg(**over):
    base = {"exclude": [], "lines": [], "zones": [], "loiter_s": 30.0, "class_filter": []}
    base.update(over)
    return base


def test_no_config_gives_masks_off_and_no_engine(monkeypatch):
    monkeypatch.setattr(zones_config, "load_camera_config", lambda cid: _cfg())
    zone_cfg, engine, zone_filter, append_events = pl._load_zone_event_setup("cam")
    assert zone_cfg == _cfg()
    assert engine is None
    assert callable(zone_filter) and callable(append_events)


def test_exclude_only_config_keeps_masks_but_no_engine(monkeypatch):
    monkeypatch.setattr(zones_config, "load_camera_config",
                        lambda cid: _cfg(exclude=[[0.1, 0.1, 0.4, 0.4]]))
    zone_cfg, engine, _, _ = pl._load_zone_event_setup("cam")
    assert zone_cfg["exclude"] == [[0.1, 0.1, 0.4, 0.4]]
    assert engine is None


def test_line_config_arms_the_event_engine(monkeypatch):
    monkeypatch.setattr(zones_config, "load_camera_config",
                        lambda cid: _cfg(lines=[{"id": "gate", "line": [0.5, 0.0, 0.5, 1.0]}],
                                         class_filter=["person"]))
    zone_cfg, engine, _, _ = pl._load_zone_event_setup("cam")
    assert engine is not None
    assert zone_cfg["lines"][0]["id"] == "gate"


def test_a_failing_config_read_disables_the_feature_only(monkeypatch):
    def boom(cid):
        raise RuntimeError("corrupt config")

    monkeypatch.setattr(zones_config, "load_camera_config", boom)
    zone_cfg, engine, _, _ = pl._load_zone_event_setup("cam")
    assert zone_cfg is None and engine is None


def test_the_camera_id_is_passed_through(monkeypatch):
    seen = []
    monkeypatch.setattr(zones_config, "load_camera_config",
                        lambda cid: seen.append(cid) or _cfg())
    pl._load_zone_event_setup("front_door")
    assert seen == ["front_door"]
