"""Encrypted clip listing and download for the phone.

Author: Bloodawn (KheivenD), 2026-11-24.
"""
import pytest

from src.gui.routes import library_bp as lib


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(lib.library_bp)
    monkeypatch.setattr(lib._ps, "allowed_media_roots", lambda: [tmp_path])
    lib._reset_library_cache()
    return app.test_client()


def test_lists_only_enc_files_newest_first(client, tmp_path):
    (tmp_path / "a.enc").write_bytes(b"1" * 50)
    (tmp_path / "b.mp4").write_bytes(b"2")
    sub = tmp_path / "cam"
    sub.mkdir()
    (sub / "c.enc").write_bytes(b"3" * 70)
    body = client.get("/api/library/encrypted", query_string={"folder": str(tmp_path)}).get_json()
    assert body["count"] == 2
    assert sorted(i["name"] for i in body["items"]) == ["a.enc", "c.enc"]
    assert {i["size"] for i in body["items"]} == {50, 70}


def test_trash_is_not_listed(client, tmp_path):
    t = tmp_path / ".svcs_trash"
    t.mkdir()
    (t / "gone.enc").write_bytes(b"x")
    body = client.get("/api/library/encrypted", query_string={"folder": str(tmp_path)}).get_json()
    assert body["count"] == 0


def test_download_returns_exact_bytes(client, tmp_path):
    data = bytes(range(256)) * 4
    f = tmp_path / "clip.enc"
    f.write_bytes(data)
    r = client.get("/api/library/enc_file", query_string={"path": str(f), "folder": str(tmp_path)})
    assert r.status_code == 200
    assert r.data == data


def test_download_refuses_non_enc_and_outside_files(client, tmp_path):
    mp4 = tmp_path / "v.mp4"
    mp4.write_bytes(b"x")
    assert client.get("/api/library/enc_file", query_string={"path": str(mp4)}).status_code == 400
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as other:
        out = pathlib.Path(other) / "evil.enc"
        out.write_bytes(b"secret")
        r = client.get("/api/library/enc_file", query_string={"path": str(out)})
        assert r.status_code == 400
    r = client.get("/api/library/enc_file", query_string={"path": str(tmp_path / ".." / "x.enc")})
    assert r.status_code == 400


def test_listing_refuses_a_folder_outside_the_media_roots(client, tmp_path):
    import tempfile
    with tempfile.TemporaryDirectory() as other:
        r = client.get("/api/library/encrypted", query_string={"folder": other})
        assert r.status_code == 400
