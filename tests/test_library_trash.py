"""Trash list, restore and purge (roadmap 12.4).

Author: Bloodawn (KheivenD), 2026-11-23 (demo branch, roadmap 12.4).
"""
import json

import pytest

from src.gui.routes import library_bp as lib


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(lib.library_bp)
    monkeypatch.setattr(lib._ps, "allowed_media_roots", lambda: [tmp_path])
    monkeypatch.setattr(lib._cidx, "prune_missing", lambda *a, **k: 0)
    lib._reset_library_cache()
    return app.test_client()


def _post(client, url, body):
    return client.post(url, data=json.dumps(body), content_type="application/json")


def _trash(client, tmp_path, *names):
    paths = []
    for n in names:
        v = tmp_path / n
        v.write_bytes(b"x" * 10)
        paths.append(str(v))
    r = _post(client, "/api/library/delete", {"paths": paths, "folder": str(tmp_path)})
    assert r.status_code == 200
    return r.get_json()["moved"]


def _listing(client, tmp_path):
    return client.get("/api/library/trash", query_string={"folder": str(tmp_path)}).get_json()


def test_list_shows_trashed_videos_with_sizes(client, tmp_path):
    _trash(client, tmp_path, "a.mp4", "b.mp4")
    body = _listing(client, tmp_path)
    assert body["count"] == 2
    assert sorted(i["name"] for i in body["items"]) == ["a.mp4", "b.mp4"]
    assert body["total_bytes"] == 20
    assert all(i["restores_to"] == str(tmp_path.resolve()) for i in body["items"])


def test_list_finds_trash_in_subfolders_and_empty_is_fine(client, tmp_path):
    assert _listing(client, tmp_path)["count"] == 0
    sub = tmp_path / "cam1"
    sub.mkdir()
    (sub / "c.mp4").write_bytes(b"c")
    _post(client, "/api/library/delete", {"paths": [str(sub / "c.mp4")], "folder": str(tmp_path)})
    body = _listing(client, tmp_path)
    assert [i["name"] for i in body["items"]] == ["c.mp4"]
    assert body["items"][0]["restores_to"] == str(sub.resolve())


def test_restore_puts_the_file_back_and_removes_empty_trash(client, tmp_path):
    moved = _trash(client, tmp_path, "a.mp4")
    r = _post(client, "/api/library/trash/restore",
              {"paths": [moved[0]["trash"]], "folder": str(tmp_path)})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert (tmp_path / "a.mp4").read_bytes() == b"x" * 10
    assert not (tmp_path / lib.TRASH_DIRNAME).exists()
    names = [v["name"] for v in client.get(
        "/api/library/videos", query_string={"folder": str(tmp_path), "refresh": "1"}).get_json()["videos"]]
    assert names == ["a.mp4"]


def test_restore_never_overwrites_a_newer_file(client, tmp_path):
    moved = _trash(client, tmp_path, "a.mp4")
    (tmp_path / "a.mp4").write_bytes(b"newer")
    r = _post(client, "/api/library/trash/restore",
              {"paths": [moved[0]["trash"]], "folder": str(tmp_path)})
    assert r.status_code == 200
    assert (tmp_path / "a.mp4").read_bytes() == b"newer"
    restored = r.get_json()["restored"][0]["restored"]
    assert restored != str(tmp_path / "a.mp4")
    assert open(restored, "rb").read() == b"x" * 10


def test_purge_needs_confirm_and_then_erases(client, tmp_path):
    moved = _trash(client, tmp_path, "a.mp4")
    trashed = moved[0]["trash"]
    body = {"paths": [trashed], "folder": str(tmp_path)}
    assert _post(client, "/api/library/trash/purge", body).status_code == 400
    assert _post(client, "/api/library/trash/purge", {**body, "confirm": "yes"}).status_code == 400
    assert (tmp_path / lib.TRASH_DIRNAME / "a.mp4").exists()
    r = _post(client, "/api/library/trash/purge", {**body, "confirm": True})
    assert r.status_code == 200
    assert r.get_json()["freed_bytes"] == 10
    assert not (tmp_path / lib.TRASH_DIRNAME).exists()


def test_only_trashed_videos_can_be_restored_or_purged(client, tmp_path):
    live = tmp_path / "live.mp4"
    live.write_bytes(b"live")
    outside = tmp_path.parent / "outside.mp4"
    outside.write_bytes(b"o")
    for url in ("/api/library/trash/restore", "/api/library/trash/purge"):
        r = _post(client, url, {"paths": [str(live), str(outside), "nope", 5],
                                "folder": str(tmp_path), "confirm": True})
        assert r.status_code == 400
        assert len(r.get_json()["failed"]) == 4
    assert live.read_bytes() == b"live" and outside.exists()


def test_bad_bodies_are_rejected(client):
    for url in ("/api/library/trash/restore", "/api/library/trash/purge"):
        assert _post(client, url, {}).status_code == 400
        assert _post(client, url, {"paths": []}).status_code == 400
        assert _post(client, url, {"paths": ["x"] * 201, "confirm": True}).status_code == 400
