"""
tests/test_library_labels.py

The Library shows what was detected in each clip (person, vehicle ...) and
which mode made it, and can filter on both.

Author: Bloodawn (KheivenD), 2026-11-25.
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.services import library_labels as ll  # noqa: E402


def _db(folder: Path, rows):
    conn = sqlite3.connect(folder / "metadata.db")
    conn.execute("CREATE TABLE segments (id INTEGER PRIMARY KEY, file_path TEXT, object_classes TEXT,"
                 " person_count INTEGER, vehicle_count INTEGER)")
    conn.executemany("INSERT INTO segments (file_path, object_classes, person_count, vehicle_count)"
                     " VALUES (?,?,?,?)", rows)
    conn.commit()
    conn.close()


def test_mode_comes_from_the_folder_name():
    assert ll.mode_of(r"C:\out\mode2\cam_00.mp4") == "mode2"
    assert ll.mode_of("/out/demo_mode3/cam.mp4") == "mode3"
    assert ll.mode_of("/out/holiday.mp4") is None
    assert ll.mode_of("/out/mode9/x.mp4") is None


def test_tags_are_friendly_and_deduplicated():
    assert ll.tags_for(["car", "truck", "person"], 1, 2) == ["person", "vehicle"]
    assert ll.tags_for(["dog"], 0, 0) == ["dog"]
    assert ll.tags_for([], 0, 0) == []


def test_attach_reads_the_metadata_db_next_to_the_clip(tmp_path):
    folder = tmp_path / "mode2"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"x")
    (folder / "b.mp4").write_bytes(b"x")
    _db(folder, [(str(folder / "a.mp4"), json.dumps(["person", "car"]), 1, 1),
                 (str(folder / "b.mp4.enc"), "[]", 0, 0)])
    items = [{"path": str(folder / "a.mp4"), "name": "a.mp4"},
             {"path": str(folder / "b.mp4"), "name": "b.mp4"},
             {"path": str(tmp_path / "other.mp4"), "name": "other.mp4"}]
    out = ll.attach(items)
    assert out[0]["labels"] == ["person", "vehicle"] and out[0]["mode"] == "mode2"
    assert out[1]["labels"] == [] and out[1]["mode"] == "mode2"
    assert out[2]["labels"] == [] and out[2]["mode"] is None
    assert "labels" not in items[0]            # inputs are not mutated


def test_a_broken_db_gives_no_labels_instead_of_an_error(tmp_path):
    (tmp_path / "metadata.db").write_bytes(b"not a database")
    (tmp_path / "a.mp4").write_bytes(b"x")
    out = ll.attach([{"path": str(tmp_path / "a.mp4"), "name": "a.mp4"}])
    assert out[0]["labels"] == []


def test_cache_follows_the_db_file(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    _db(tmp_path, [(str(tmp_path / "a.mp4"), '["person"]', 1, 0)])
    item = [{"path": str(tmp_path / "a.mp4"), "name": "a.mp4"}]
    assert ll.attach(item)[0]["labels"] == ["person"]
    conn = sqlite3.connect(tmp_path / "metadata.db")
    conn.execute("UPDATE segments SET object_classes='[\"dog\"]', person_count=0")
    conn.commit()
    conn.close()
    import os, time
    os.utime(tmp_path / "metadata.db", (time.time() + 5, time.time() + 5))
    assert ll.attach(item)[0]["labels"] == ["dog"]


def test_videos_route_attaches_and_filters_labels(tmp_path, monkeypatch):
    import gui.routes.library_bp as lib
    from gui.app import app
    try:
        from gui.services import gui_state_persist as gsp
    except ModuleNotFoundError:  # pragma: no cover
        from src.gui.services import gui_state_persist as gsp
    monkeypatch.setattr(gsp, "_GUI_STATE_FILE", tmp_path / "gui_state.json")
    monkeypatch.setattr(lib._ps, "allowed_media_roots", lambda: [tmp_path])
    m2, m3 = tmp_path / "mode2", tmp_path / "mode3"
    m2.mkdir(); m3.mkdir()
    for f in (m2 / "a.mp4", m2 / "b.mp4", m3 / "c.mp4"):
        f.write_bytes(b"x" * 100)
    _db(m2, [(str(m2 / "a.mp4"), '["person"]', 1, 0), (str(m2 / "b.mp4"), '["car"]', 0, 1)])
    _db(m3, [(str(m3 / "c.mp4"), '["person"]', 1, 0)])
    client = app.test_client()

    def get(**q):
        q["folder"] = str(tmp_path)
        q["refresh"] = "1"
        return client.get("/api/library/videos", query_string=q).get_json()

    body = get()
    by = {v["name"].split("/")[-1]: v for v in body["videos"]}
    assert by["a.mp4"]["labels"] == ["person"] and by["a.mp4"]["mode"] == "mode2"
    assert by["b.mp4"]["labels"] == ["vehicle"]
    assert {v["name"].split("/")[-1] for v in get(label="person")["videos"]} == {"a.mp4", "c.mp4"}
    assert {v["name"].split("/")[-1] for v in get(label="person", mode="mode3")["videos"]} == {"c.mp4"}
    assert get(mode="mode0")["total"] == 0
