"""
tests/security/test_encrypt_confinement.py  (SEC-005, SEC-006)

The /api/encrypt route must apply the same trusted-root confinement /api/decrypt
does: it must refuse a key_file outside the trusted roots (SEC-005), and it must
never write the .enc output to a path outside them - a configured encrypted_dir
that escapes the roots falls back to a sibling Encrypted/ next to the source
(SEC-006).
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import gui.routes.encryption_bp as eb  # noqa: E402

if not eb._CRYPTO_AVAILABLE:
    pytest.skip("cryptography not installed", allow_module_level=True)


@pytest.fixture()
def client():
    from gui.app import app
    return app.test_client()


@pytest.fixture()
def allowed_root(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    # Pin the trusted roots to just `allowed` so the test is deterministic.
    monkeypatch.setattr(eb, "_safe_segment_roots", lambda: [allowed.resolve()])
    return allowed


def test_encrypt_rejects_key_file_outside_roots(client, allowed_root, tmp_path):
    src = allowed_root / "clip.mp4"
    src.write_bytes(b"x" * 256)
    outside_key = tmp_path / "outside" / "camera.key"
    outside_key.parent.mkdir()
    outside_key.write_bytes(b"k" * 32)
    resp = client.post("/api/encrypt",
                       json={"file_path": str(src), "key_file": str(outside_key)})
    assert resp.status_code == 403, "SEC-005: key_file outside trusted roots was read"


def test_encrypt_output_dir_outside_roots_falls_back(client, allowed_root, tmp_path, monkeypatch):
    src = allowed_root / "clip.mp4"
    src.write_bytes(b"y" * 512)
    evil_out = tmp_path / "evil_out"  # outside the trusted roots
    with eb._state_lock:
        cfg = eb._status.setdefault("config", {})
        prev = cfg.get("encrypted_dir")
        cfg["encrypted_dir"] = str(evil_out)
    try:
        resp = client.post("/api/encrypt",
                           json={"file_path": str(src), "password": "pw"})
        assert resp.status_code == 200, resp.get_json()
        enc_path = Path(resp.get_json()["enc_path"]).resolve()
        # The .enc landed under the trusted source folder, NOT under evil_out.
        assert allowed_root.resolve() in enc_path.parents, "SEC-006: .enc escaped the trusted roots"
        assert evil_out.resolve() not in enc_path.parents
    finally:
        with eb._state_lock:
            if prev is None:
                eb._status.get("config", {}).pop("encrypted_dir", None)
            else:
                eb._status["config"]["encrypted_dir"] = prev
