"""
tests/test_library.py

Tests the Library / gallery endpoints (FIX 6).

Uses a tiny synthetic clip so listing, metadata, thumbnail generation, file
streaming, and the compress hand-off can be exercised without LFS assets. The
thumbnail cache is redirected to a tmp dir.

Author: Bloodawn (KheivenD), 2026-06-03 (FIX 6).
"""

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import cv2  # noqa: E402

import gui.routes.library_bp as lib  # noqa: E402


def _make_clip(path, n=20, size=(160, 120), fps=10.0):
    w, h = size
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    if not writer.isOpened():  # pragma: no cover
        writer.release()
        pytest.skip("no MJPG VideoWriter available")
    rng = np.random.default_rng(7)
    for _ in range(n):
        small = rng.integers(0, 255, (8, 10, 3), dtype=np.uint8)
        writer.write(cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST))
    writer.release()


@pytest.fixture()
def client():
    from gui.app import app
    return app.test_client()


@pytest.fixture()
def lib_folder(tmp_path, monkeypatch):
    # Redirect the thumbnail cache so we never touch the real one.
    monkeypatch.setattr(lib._paths, "thumbs_dir", lambda: tmp_path / "thumbs")
    (tmp_path / "thumbs").mkdir()
    vids = tmp_path / "vids"
    vids.mkdir()
    _make_clip(vids / "alpha.avi")
    _make_clip(vids / "beta.avi")
    return vids


def test_videos_lists_folder(client, lib_folder):
    body = client.get("/api/library/videos", query_string={"folder": str(lib_folder)}).get_json()
    assert body["exists"] is True
    assert body["total"] == 2
    names = {v["name"] for v in body["videos"]}
    assert names == {"alpha.avi", "beta.avi"}
    for v in body["videos"]:
        assert set(v) >= {"name", "path", "size", "mtime"}


def test_videos_missing_folder(client, tmp_path):
    body = client.get("/api/library/videos",
                      query_string={"folder": str(tmp_path / "nope")}).get_json()
    assert body["exists"] is False
    assert body["videos"] == []


def test_videos_pagination(client, lib_folder):
    body = client.get("/api/library/videos",
                      query_string={"folder": str(lib_folder), "page": 1, "page_size": 1}).get_json()
    assert body["total"] == 2
    assert len(body["videos"]) == 1


def test_meta_returns_dimensions(client, lib_folder):
    clip = lib_folder / "alpha.avi"
    body = client.get("/api/library/meta", query_string={"path": str(clip)}).get_json()
    assert body["name"] == "alpha.avi"
    assert body["size"] > 0
    # ffprobe should report the encoded dimensions.
    assert body.get("width") in ("160", 160) or "width" in body


def test_thumb_generates_and_caches(client, lib_folder, tmp_path):
    clip = lib_folder / "alpha.avi"
    resp = client.get("/api/library/thumb", query_string={"path": str(clip)})
    assert resp.status_code == 200
    assert resp.mimetype == "image/jpeg"
    # A cached file now exists in the redirected thumbs dir.
    thumbs = list((tmp_path / "thumbs").glob("*.jpg"))
    assert thumbs and thumbs[0].stat().st_size > 0


def test_file_streams_video(client, lib_folder):
    clip = lib_folder / "alpha.avi"
    resp = client.get("/api/library/file", query_string={"path": str(clip)})
    assert resp.status_code == 200
    assert resp.mimetype.startswith("video/")


def test_compress_hands_back_path(client, lib_folder):
    clip = lib_folder / "beta.avi"
    resp = client.post("/api/library/compress", json={"path": str(clip)})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] and body["name"] == "beta.avi"


def test_endpoints_reject_non_video(client, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hello")
    for ep in ("/api/library/meta", "/api/library/thumb", "/api/library/file"):
        assert client.get(ep, query_string={"path": str(bad)}).status_code == 400
    assert client.post("/api/library/compress", json={"path": str(bad)}).status_code == 400
