"""/api/segments after the files_bp cleanup.

Covers the nested-root walk (a metadata.db under two candidate roots is found
once) and the min_roi_count fix: a non-numeric value used to add the SQL filter
without its bound parameter, so every database query failed and the route
silently returned no segments at all.

Author: Bloodawn (KheivenD), 2026-10-13 (perf sweep).
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import gui.app as gui_module  # noqa: E402
from gui.app import app as flask_app  # noqa: E402
from gui.routes import files_bp  # noqa: E402
from utils.db import initialize_database, insert_segment  # noqa: E402


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """Output dir with one segment, nested one level under a second root."""
    out = tmp_path / "outer" / "inner"
    out.mkdir(parents=True)
    db = out / "metadata.db"
    initialize_database(db)
    insert_segment(timestamp="20260415T120000Z", camera_id="cam_01",
                   target_detected=True, roi_count=3, file_size=512_000,
                   duration=60.0, file_path="cam_01_seg1.mp4", db_path=db)
    monkeypatch.setattr(files_bp, "_ROOT", tmp_path / "empty")
    with gui_module._state_lock:
        old_cfg = gui_module._status.get("config")
        gui_module._status["config"] = {"output_dir": str(out)}
    with gui_module._demo_lock:
        old_demo = gui_module._demo_state.get("last_output_root", "")
        gui_module._demo_state["last_output_root"] = str(tmp_path / "outer")
    yield out
    with gui_module._state_lock:
        gui_module._status["config"] = old_cfg
    with gui_module._demo_lock:
        gui_module._demo_state["last_output_root"] = old_demo


def _get(query=""):
    with flask_app.test_client() as c:
        return c.get(f"/api/segments{query}").get_json()


def test_db_under_two_nested_roots_is_listed_once(seeded):
    body = _get()
    assert body["db_count"] == 1
    assert len(body["segments"]) == 1


def test_non_numeric_min_rois_is_ignored_not_fatal(seeded):
    assert len(_get("?min_roi_count=abc")["segments"]) == 1


def test_numeric_min_rois_still_filters(seeded):
    assert len(_get("?min_roi_count=3")["segments"]) == 1
    assert _get("?min_roi_count=4")["segments"] == []
