"""
tests/test_chunked_upload.py - R6 Track B (the M4 resumable-ingest tail).

Proves the resume semantics that motivated the protocol: a stale offset gets
409 + the real offset and the client continues from there; a hash mismatch
discards the part; finish verifies size, hash, and a decodable stream before
anything lands in the uploads folder.

Author: Bloodawn (KheivenD), 2026-08-17 (R6 Track B).
"""

import hashlib
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.app import app as flask_app  # noqa: E402
from gui.routes import ingest_bp as ing  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ing, "_tmp_dir", lambda: tmp_path / "tmp" or tmp_path)
    (tmp_path / "tmp").mkdir(exist_ok=True)
    monkeypatch.setattr(ing, "_upload_dir", lambda: tmp_path / "uploads")
    (tmp_path / "uploads").mkdir(exist_ok=True)
    monkeypatch.setattr(ing, "_verify_video", lambda p: True)
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


PAYLOAD = b"fake-video-bytes-" * 200  # 3400 bytes


def _begin(c, name="clip.mp4", size=len(PAYLOAD)):
    r = c.post("/api/upload/begin", json={"name": name, "size": size})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["upload_id"]


def test_full_upload_roundtrip(client):
    uid = _begin(client)
    half = len(PAYLOAD) // 2
    r1 = client.post(f"/api/upload/chunk?upload_id={uid}&offset=0",
                     data=PAYLOAD[:half])
    assert r1.get_json()["offset"] == half
    r2 = client.post(f"/api/upload/chunk?upload_id={uid}&offset={half}",
                     data=PAYLOAD[half:])
    assert r2.get_json()["offset"] == len(PAYLOAD)
    fin = client.post("/api/upload/finish", json={
        "upload_id": uid, "sha256": hashlib.sha256(PAYLOAD).hexdigest()})
    body = fin.get_json()
    assert fin.status_code == 200 and body["ok"] is True
    assert Path(body["path"]).read_bytes() == PAYLOAD


def test_stale_offset_conflict_is_the_resume_path(client):
    uid = _begin(client)
    client.post(f"/api/upload/chunk?upload_id={uid}&offset=0", data=PAYLOAD[:100])
    # Client thinks it is at 0 again after a dropped connection.
    r = client.post(f"/api/upload/chunk?upload_id={uid}&offset=0", data=PAYLOAD[:100])
    assert r.status_code == 409
    assert r.get_json()["offset"] == 100
    # Status agrees, and continuing from the reported offset works.
    st = client.get(f"/api/upload/status?upload_id={uid}")
    assert st.get_json()["offset"] == 100
    r2 = client.post(f"/api/upload/chunk?upload_id={uid}&offset=100",
                     data=PAYLOAD[100:])
    assert r2.get_json()["offset"] == len(PAYLOAD)


def test_hash_mismatch_discards_the_part(client):
    uid = _begin(client)
    client.post(f"/api/upload/chunk?upload_id={uid}&offset=0", data=PAYLOAD)
    fin = client.post("/api/upload/finish", json={
        "upload_id": uid, "sha256": "ab" * 32})
    assert fin.status_code == 400
    assert "discarded" in fin.get_json()["error"]
    assert client.get(f"/api/upload/status?upload_id={uid}").status_code == 404


def test_incomplete_finish_reports_offset(client):
    uid = _begin(client)
    client.post(f"/api/upload/chunk?upload_id={uid}&offset=0", data=PAYLOAD[:50])
    fin = client.post("/api/upload/finish", json={
        "upload_id": uid, "sha256": hashlib.sha256(PAYLOAD).hexdigest()})
    assert fin.status_code == 400
    assert fin.get_json()["offset"] == 50


def test_overflow_and_bad_ext_and_unknown_id(client):
    uid = _begin(client, size=10)
    r = client.post(f"/api/upload/chunk?upload_id={uid}&offset=0", data=b"x" * 11)
    assert r.status_code == 413
    assert client.post("/api/upload/begin",
                       json={"name": "evil.exe", "size": 10}).status_code == 400
    assert client.get("/api/upload/status?upload_id=zz").status_code == 404
    assert client.post("/api/upload/finish",
                       json={"upload_id": "deadbeef" * 3, "sha256": ""}).status_code == 404


def test_name_is_sanitized_to_leaf(client):
    uid = _begin(client, name="..\\..\\escape\\clip.mp4")
    client.post(f"/api/upload/chunk?upload_id={uid}&offset=0", data=PAYLOAD)
    fin = client.post("/api/upload/finish", json={
        "upload_id": uid, "sha256": hashlib.sha256(PAYLOAD).hexdigest()})
    assert fin.status_code == 200
    assert fin.get_json()["filename"] == "clip.mp4"


def test_unverified_video_rejected(client, monkeypatch):
    monkeypatch.setattr(ing, "_verify_video", lambda p: False)
    uid = _begin(client)
    client.post(f"/api/upload/chunk?upload_id={uid}&offset=0", data=PAYLOAD)
    fin = client.post("/api/upload/finish", json={
        "upload_id": uid, "sha256": hashlib.sha256(PAYLOAD).hexdigest()})
    assert fin.status_code == 400
    assert "decodable" in fin.get_json()["error"]
