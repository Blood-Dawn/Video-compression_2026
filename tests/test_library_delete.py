"""POST /api/library/delete moves videos to a recoverable trash folder."""
import json
from pathlib import Path

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


def _post(client, body):
    return client.post("/api/library/delete", data=json.dumps(body),
                       content_type="application/json")


def test_moves_file_to_trash_and_keeps_bytes(client, tmp_path):
    v = tmp_path / "a.mp4"
    v.write_bytes(b"x" * 10)
    r = _post(client, {"paths": [str(v)], "folder": str(tmp_path)})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True and not body["failed"]
    assert not v.exists()
    trashed = tmp_path / lib.TRASH_DIRNAME / "a.mp4"
    assert trashed.read_bytes() == b"x" * 10


def test_trashed_video_is_not_listed(client, tmp_path):
    keep = tmp_path / "keep.mp4"
    gone = tmp_path / "gone.mp4"
    keep.write_bytes(b"k")
    gone.write_bytes(b"g")
    _post(client, {"paths": [str(gone)], "folder": str(tmp_path)})
    r = client.get("/api/library/videos", query_string={"folder": str(tmp_path), "refresh": "1"})
    names = [v["name"] for v in r.get_json()["videos"]]
    assert names == ["keep.mp4"]


def test_name_collision_keeps_both(client, tmp_path):
    for payload in (b"1", b"2"):
        v = tmp_path / "same.mp4"
        v.write_bytes(payload)
        assert _post(client, {"paths": [str(v)], "folder": str(tmp_path)}).status_code == 200
    files = sorted(p.name for p in (tmp_path / lib.TRASH_DIRNAME).iterdir())
    assert len(files) == 2


def test_rejects_non_video_and_outside_paths(client, tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("hi")
    outside = tmp_path.parent / "elsewhere.mp4"
    outside.write_bytes(b"o")
    try:
        r = _post(client, {"paths": [str(txt), str(outside)]})
        assert r.status_code == 400
        assert len(r.get_json()["failed"]) == 2
        assert txt.exists() and outside.exists()
    finally:
        outside.unlink()


def test_bad_bodies(client):
    assert _post(client, {}).status_code == 400
    assert _post(client, {"paths": []}).status_code == 400
    assert _post(client, {"paths": "x"}).status_code == 400
    assert _post(client, {"paths": ["a.mp4"] * (lib._MAX_DELETE_BATCH + 1)}).status_code == 400


def test_partial_success_reports_both(client, tmp_path):
    good = tmp_path / "good.mp4"
    good.write_bytes(b"g")
    r = _post(client, {"paths": [str(good), str(tmp_path / "missing.mp4")],
                       "folder": str(tmp_path)})
    body = r.get_json()
    assert r.status_code == 200
    assert len(body["moved"]) == 1 and len(body["failed"]) == 1
    assert body["ok"] is False
