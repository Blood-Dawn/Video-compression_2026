"""
tests/test_upload_limit.py - the configurable per-file upload size cap.

Covers the settings module (default 8 GB, validation, persistence), the
GET/POST /api/upload/limit route (password only), and enforcement on both
upload routes plus the per-chunk memory bound.
"""

import base64
import io
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.app import app as flask_app  # noqa: E402
from gui.routes import files_bp as fbp  # noqa: E402
from gui.routes import ingest_bp as ing  # noqa: E402
from utils import upload_limits as limits  # noqa: E402

GB = 1024 ** 3


@pytest.fixture()
def cfg_file(tmp_path, monkeypatch):
    path = tmp_path / "upload_limits.json"
    monkeypatch.setattr(limits, "config_path", lambda: path)
    return path


@pytest.fixture()
def client(tmp_path, cfg_file, monkeypatch):
    (tmp_path / "uploads").mkdir()
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(fbp, "_upload_dir", lambda: tmp_path / "uploads")
    monkeypatch.setattr(ing, "_upload_dir", lambda: tmp_path / "uploads")
    monkeypatch.setattr(ing, "_tmp_dir", lambda: tmp_path / "tmp")
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


# -- settings module ---------------------------------------------------------


def test_default_is_8_gb_when_nothing_is_stored(cfg_file):
    assert limits.max_upload_gb() == 8.0
    assert limits.max_upload_bytes() == 8 * GB


def test_save_then_read_back(cfg_file):
    ok, err, cfg = limits.save_max_upload_gb(16)
    assert ok and err == ""
    assert cfg["max_upload_gb"] == 16.0 and cfg["default_gb"] == 8.0
    assert limits.max_upload_bytes() == 16 * GB


@pytest.mark.parametrize("bad", [0, -1, 0.01, 2000, "abc", None, True, float("nan"), float("inf")])
def test_invalid_values_are_rejected_and_keep_the_old_cap(cfg_file, bad):
    limits.save_max_upload_gb(4)
    ok, err, cfg = limits.save_max_upload_gb(bad)
    assert not ok and err
    assert cfg["max_upload_gb"] == 4.0


def test_damaged_file_falls_back_to_default(cfg_file):
    cfg_file.write_text("{not json", encoding="utf-8")
    assert limits.max_upload_gb() == 8.0
    cfg_file.write_text('{"max_upload_gb": -5}', encoding="utf-8")
    assert limits.max_upload_gb() == 8.0


# -- route -------------------------------------------------------------------


def test_route_get_and_post(client):
    assert client.get("/api/upload/limit").get_json()["config"]["max_upload_gb"] == 8.0
    r = client.post("/api/upload/limit", json={"max_upload_gb": 12.5})
    assert r.status_code == 200 and r.get_json()["config"]["max_upload_gb"] == 12.5
    assert client.get("/api/upload/limit").get_json()["config"]["max_upload_gb"] == 12.5


def test_route_rejects_bad_input(client):
    assert client.post("/api/upload/limit", json={"max_upload_gb": 0}).status_code == 400
    assert client.post("/api/upload/limit", json={}).status_code == 400
    assert client.post("/api/upload/limit", data="x", content_type="text/plain").status_code == 400
    assert client.get("/api/upload/limit").get_json()["config"]["max_upload_gb"] == 8.0


def test_device_token_cannot_change_the_limit(tmp_path, cfg_file, monkeypatch):
    from flask import Flask

    from gui import device_tokens
    from gui.auth import install_basic_auth

    monkeypatch.setattr(device_tokens, "token_path", lambda: tmp_path / "device_tokens.json")
    app = Flask(__name__)
    app.register_blueprint(ing.ingest_bp)
    install_basic_auth(app, "admin", "secret")
    minted = device_tokens.mint_token("phone")
    token = minted if isinstance(minted, str) else minted[0]
    cl = app.test_client()
    denied = cl.post("/api/upload/limit", headers={"Authorization": f"Bearer {token}"},
                     json={"max_upload_gb": 500})
    assert denied.status_code == 403
    assert limits.max_upload_gb() == 8.0
    basic = base64.b64encode(b"admin:secret").decode("ascii")
    allowed = cl.post("/api/upload/limit", headers={"Authorization": f"Basic {basic}"},
                      json={"max_upload_gb": 500})
    assert allowed.status_code == 200 and limits.max_upload_gb() == 500.0


# -- enforcement -------------------------------------------------------------


def test_one_shot_upload_over_the_cap_is_refused_with_413(client, monkeypatch, tmp_path):
    monkeypatch.setattr(limits, "max_upload_bytes", lambda: 1000)
    monkeypatch.setattr(fbp, "_MULTIPART_OVERHEAD", 0)
    r = client.post("/api/upload", data={"file": (io.BytesIO(b"x" * 5000), "big.mp4")},
                    content_type="multipart/form-data")
    assert r.status_code == 413
    assert "upload limit" in r.get_json()["error"]
    assert list((tmp_path / "uploads").iterdir()) == []


def test_one_shot_upload_without_content_length_is_still_bounded(client, monkeypatch, tmp_path):
    monkeypatch.setattr(limits, "max_upload_bytes", lambda: 1000)
    monkeypatch.setattr(fbp, "_MULTIPART_OVERHEAD", 0)
    body = (b"--B\r\nContent-Disposition: form-data; name=\"file\"; filename=\"big.mp4\"\r\n"
            b"Content-Type: video/mp4\r\n\r\n" + b"x" * 5000 + b"\r\n--B--\r\n")
    # No Content-Length, as with Transfer-Encoding: chunked behind a server
    # that de-chunks the body (wsgi.input_terminated).
    r = client.post("/api/upload", input_stream=io.BytesIO(body),
                    headers={"Content-Type": "multipart/form-data; boundary=B"},
                    environ_overrides={"CONTENT_LENGTH": "", "wsgi.input_terminated": True})
    assert r.status_code == 413
    assert list((tmp_path / "uploads").iterdir()) == []


def test_one_shot_upload_under_the_cap_still_works(client):
    r = client.post("/api/upload", data={"file": (io.BytesIO(b"hello"), "ok.mp4")},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    assert Path(r.get_json()["path"]).read_bytes() == b"hello"


def test_begin_refuses_a_file_over_the_cap(client):
    client.post("/api/upload/limit", json={"max_upload_gb": 0.1})
    r = client.post("/api/upload/begin", json={"name": "a.mp4", "size": int(0.2 * GB)})
    assert r.status_code == 400 and "0.1 GB" in r.get_json()["error"]
    ok = client.post("/api/upload/begin", json={"name": "a.mp4", "size": 1000})
    assert ok.status_code == 200


def test_begin_honours_a_raised_cap(client):
    too_big = 9 * GB
    assert client.post("/api/upload/begin", json={"name": "a.mp4", "size": too_big}).status_code == 400
    client.post("/api/upload/limit", json={"max_upload_gb": 20})
    assert client.post("/api/upload/begin", json={"name": "a.mp4", "size": too_big}).status_code == 200


def test_oversized_chunk_body_is_refused_before_it_is_read(client, monkeypatch):
    monkeypatch.setattr(ing, "_MAX_CHUNK_BYTES", 10)
    uid = client.post("/api/upload/begin", json={"name": "a.mp4", "size": 1000}).get_json()["upload_id"]
    r = client.post(f"/api/upload/chunk?upload_id={uid}&offset=0", data=b"y" * 50)
    assert r.status_code == 413
    ok = client.post(f"/api/upload/chunk?upload_id={uid}&offset=0", data=b"y" * 10)
    assert ok.status_code == 200 and ok.get_json()["offset"] == 10
