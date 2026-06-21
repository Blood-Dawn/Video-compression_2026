"""
tests/security/test_path_traversal.py  (SEC-002, SEC-003, SEC-004, SEC-015)

Attack the file-serving routes with absolute paths / traversal pointing OUTSIDE
the operator's media folders and assert they are refused, while a file INSIDE an
allowed root is still served. This pins the central `path_safety.confine_to_allowed`
confinement so a route can never again stream an arbitrary file off the host.
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import gui.services.path_safety as ps  # noqa: E402
import gui.routes.files_bp as fb  # noqa: E402
import gui.routes.library_bp as lib  # noqa: E402


@pytest.fixture()
def client():
    from gui.app import app
    return app.test_client()


@pytest.fixture()
def media_setup(tmp_path, monkeypatch):
    """An allowed media root with one real video, plus a secret video OUTSIDE it."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    inside = allowed / "ok.mp4"
    inside.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 4000)  # plausible mp4-ish
    outside = tmp_path / "secret" / "private.mp4"
    outside.parent.mkdir()
    outside.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"TOP SECRET FOOTAGE" * 50)
    monkeypatch.setattr(ps, "allowed_media_roots", lambda: [allowed])
    return {"allowed": allowed, "inside": inside, "outside": outside}


# ── pure helper ───────────────────────────────────────────────────────────────

def test_confine_to_allowed_accepts_inside_and_rejects_outside(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    f = root / "a.mp4"
    f.write_bytes(b"x")
    assert ps.confine_to_allowed(f, [root]) == f.resolve()
    with pytest.raises(ValueError):
        ps.confine_to_allowed(tmp_path / "elsewhere.mp4", [root])
    # Traversal that escapes the root is rejected even though it resolves.
    with pytest.raises(ValueError):
        ps.confine_to_allowed(root / ".." / "escape.mp4", [root])


# ── /api/media (SEC-002) ───────────────────────────────────────────────────────

def test_api_media_serves_inside_root(client, media_setup):
    resp = client.get("/api/media", query_string={"path": str(media_setup["inside"])})
    assert resp.status_code in (200, 206)


def test_api_media_rejects_outside_root(client, media_setup):
    resp = client.get("/api/media", query_string={"path": str(media_setup["outside"])})
    assert resp.status_code == 403, "arbitrary video outside media roots must be refused"


def test_api_media_rejects_absolute_system_path(client, media_setup):
    # A real system file with a video-ish extension would still be refused.
    for target in (r"C:\Windows\win.ini", "/etc/passwd"):
        resp = client.get("/api/media", query_string={"path": target})
        assert resp.status_code in (403, 404)


# ── /api/library/file|meta|thumb (SEC-003) ─────────────────────────────────────

def test_library_file_rejects_outside_root(client, media_setup):
    resp = client.get("/api/library/file", query_string={"path": str(media_setup["outside"])})
    assert resp.status_code == 400, "library file must refuse a clip outside the media roots"


def test_library_meta_rejects_outside_root(client, media_setup):
    resp = client.get("/api/library/meta", query_string={"path": str(media_setup["outside"])})
    assert resp.status_code == 400


def test_library_file_serves_inside_root(client, media_setup):
    resp = client.get("/api/library/file", query_string={"path": str(media_setup["inside"])})
    assert resp.status_code in (200, 206)


# ── /media/<path> (SEC-004): no source / DB disclosure ─────────────────────────

def test_media_path_refuses_source_and_db(client):
    # These exist under the repo root but are NOT media -> must 404.
    for rel in ("src/utils/encryption.py", "pyproject.toml", "uv.lock"):
        assert client.get("/media/" + rel).status_code == 404


# ── /api/media_debug (SEC-015): not an existence oracle ────────────────────────

def test_media_debug_does_not_leak_arbitrary_paths(client, media_setup):
    body = client.get("/api/media_debug",
                      query_string={"path": str(media_setup["outside"])}).get_json()
    assert body.get("allowed") is False
    assert body.get("would_serve") is False
    assert "resolved" not in body, "media_debug must not echo a resolved path outside roots"
