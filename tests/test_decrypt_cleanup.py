"""
tests/test_decrypt_cleanup.py - decrypted plaintext never outlives the download
(planner 11.8, decision: delete the copy once the download finishes).

Reuses the fixtures and helpers of test_encryption_routes.py.

Author: Victor De Souza Teixeira, 2026-11-23 (planner 11.8).
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_encryption_routes import PLAIN, _enc, _keyfile, env  # noqa: F401


def _decrypt(env, enc_path, key_path):
    return env.client.post("/api/decrypt",
                           json={"file_path": str(enc_path), "key_file": str(key_path)})


def test_small_clip_is_returned_and_nothing_is_left_on_disk(env):
    enc_path = _enc(env.allowed)
    key = _keyfile(env.allowed)
    r = _decrypt(env, enc_path, key)
    assert r.status_code == 200
    assert hashlib.sha256(r.data).digest() == hashlib.sha256(PLAIN).digest()
    assert not (env.allowed / "Decrypted").exists()
    assert enc_path.exists()                      # the .enc is never touched


def test_streamed_clip_is_deleted_when_the_response_closes(env):
    env.monkeypatch.setattr(env.eb, "_INLINE_MAX_BYTES", 10)     # force streaming
    env.monkeypatch.setattr(env.eb, "_STREAM_CHUNK", 1000)
    enc_path = _enc(env.allowed)
    key = _keyfile(env.allowed)
    r = _decrypt(env, enc_path, key)
    assert r.status_code == 200
    assert hashlib.sha256(r.data).digest() == hashlib.sha256(PLAIN).digest()
    r.close()
    assert not (env.allowed / "Decrypted").exists()


def test_the_decrypted_path_header_is_gone(env):
    r = _decrypt(env, _enc(env.allowed), _keyfile(env.allowed))
    assert "X-Decrypted-Path" not in r.headers


def test_a_failed_decrypt_leaves_nothing_behind(env):
    enc_path = _enc(env.allowed)
    bad = _keyfile(env.allowed, key=b"\x01" * 32, name="bad.key")
    r = _decrypt(env, enc_path, bad)
    assert r.status_code == 403
    assert not any((env.allowed / "Decrypted").glob("*")) if (env.allowed / "Decrypted").exists() else True


def test_a_neighbouring_clip_in_decrypted_survives_the_cleanup(env):
    """The folder is only removed when empty, and only our own file is deleted."""
    dec = env.allowed / "Decrypted"
    dec.mkdir()
    other = dec / "other.mp4"
    other.write_bytes(b"keep me")
    r = _decrypt(env, _enc(env.allowed), _keyfile(env.allowed))
    assert r.status_code == 200
    assert other.read_bytes() == b"keep me"
    assert not (dec / "clip.mp4").exists()
