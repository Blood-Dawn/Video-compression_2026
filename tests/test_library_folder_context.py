"""
tests/test_library_folder_context.py - explicit folder context on library
file/thumb serving (mobile fix, 2026-08-16).

Multiple clients share the server-global "last library folder". When the
desktop browses elsewhere, a phone's already-listed paths fall out of
allowed_media_roots() mid-session and /api/library/file 400s. The routes now
accept an explicit ``folder`` context: a video strictly inside that folder is
served even when the global folder has moved on, which is the same exposure an
authed client already has via /api/library/videos?folder=... but without the
cross-client race.

Author: Bloodawn (KheivenD), 2026-08-16 (mobile M4 playback fix).
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.app import app as flask_app  # noqa: E402
from gui.routes.library_bp import _safe_video  # noqa: E402


@pytest.fixture()
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def _fake_mp4(folder: Path, name: str = "clip.mp4") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    # ftyp box header so the file is a plausible mp4; content is irrelevant,
    # the route streams bytes without validating them.
    p.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64)
    return p


def test_context_folder_serves_video_outside_global_roots(tmp_path, client):
    video = _fake_mp4(tmp_path / "phone_folder")
    r = client.get(
        "/api/library/file",
        query_string={"path": str(video), "folder": str(tmp_path / "phone_folder")},
    )
    assert r.status_code == 200
    assert r.data.startswith(b"\x00\x00\x00\x18ftyp")


def test_no_context_keeps_the_old_confinement(tmp_path, client):
    # Same file, no folder context: must be refused unless it happens to sit
    # under an allowed media root (a fresh tmp dir does not).
    video = _fake_mp4(tmp_path / "phone_folder")
    r = client.get("/api/library/file", query_string={"path": str(video)})
    assert r.status_code == 400


def test_path_outside_context_folder_rejected(tmp_path, client):
    video = _fake_mp4(tmp_path / "elsewhere")
    r = client.get(
        "/api/library/file",
        query_string={"path": str(video), "folder": str(tmp_path / "phone_folder")},
    )
    assert r.status_code == 400


def test_traversal_out_of_context_rejected(tmp_path, client):
    video = _fake_mp4(tmp_path)  # parent of the claimed context
    ctx = tmp_path / "sub"
    ctx.mkdir()
    sneaky = str(ctx / ".." / video.name)
    r = client.get(
        "/api/library/file", query_string={"path": sneaky, "folder": str(ctx)},
    )
    assert r.status_code == 400


def test_nonexistent_context_rejected(tmp_path, client):
    video = _fake_mp4(tmp_path / "phone_folder")
    r = client.get(
        "/api/library/file",
        query_string={"path": str(video), "folder": str(tmp_path / "missing")},
    )
    assert r.status_code == 400


def test_non_video_suffix_rejected_even_in_context(tmp_path, client):
    folder = tmp_path / "phone_folder"
    folder.mkdir()
    not_video = folder / "secrets.txt"
    not_video.write_text("hunter2")
    r = client.get(
        "/api/library/file",
        query_string={"path": str(not_video), "folder": str(folder)},
    )
    assert r.status_code == 400


def test_hls_working_segments_excluded_from_listing(tmp_path, client):
    """Transient live-stream chunks under <root>/hls/ must not list as
    compressible originals; an explicit listing OF an hls folder still works."""
    root = tmp_path / "lib"
    (root / "hls" / "cam_x").mkdir(parents=True)
    _fake_mp4(root, "real_clip.mp4")
    hls_seg = root / "hls" / "cam_x" / "playlist1.ts"
    hls_seg.write_bytes(b"\x47" * 400)  # ts sync bytes
    r = client.get("/api/library/videos",
                   query_string={"folder": str(root), "refresh": "1"})
    names = [v["name"] for v in r.get_json()["videos"]]
    assert "real_clip.mp4" in names
    assert not any("playlist1.ts" in n for n in names)
    # Explicitly browsing the hls folder itself still lists its segments.
    r2 = client.get("/api/library/videos",
                    query_string={"folder": str(root / "hls"), "refresh": "1"})
    names2 = [v["name"] for v in r2.get_json()["videos"]]
    assert any("playlist1.ts" in n for n in names2)


def test_safe_video_unit_context(tmp_path):
    video = _fake_mp4(tmp_path / "ctx")
    assert _safe_video(str(video), str(tmp_path / "ctx")) is not None
    assert _safe_video(str(video), str(tmp_path / "other")) is None
    assert _safe_video(str(video), "") is None  # not under any allowed root
