"""
tests/test_encryption_routes.py - characterization of /api/keygen, /api/encrypt
and /api/decrypt, plus a known-answer test of the .enc file format.

Planner 11.8 (docs/ENCRYPTION-CLEANUP-PLAN.md, issue #53), Step 0. The two
route handlers are being split into helpers; these tests pin what a caller can
observe today (every status code, error message, response header and file on
disk) so the split is provably behavior-preserving.

Deliberately NOT pinned here, because planner 11.8 changes them on purpose and
tests/test_decrypt_cleanup.py covers the new behavior:
  * the plaintext copy left in Decrypted/ and the X-Decrypted-Path header
  * (removed in step 4) the TypeError fallback in /api/encrypt; see test_encrypt_a_type_error_is_a_normal_500

Password mode runs PBKDF2 at 600,000 iterations (about half a second per
call), so only one test uses it; the rest use raw keys.

Author: Victor De Souza Teixeira, 2026-11-23 (planner 11.8).
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import gui.app as gui_module  # noqa: E402
from utils import encryption as enc  # noqa: E402

KEY = bytes(range(32))
PLAIN = b"surveillance-segment-bytes " * 300   # 8,100 bytes


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Trusted root = tmp_path/allowed. A second folder sits outside it."""
    import gui.routes.encryption_bp as eb
    if not eb._CRYPTO_AVAILABLE:
        pytest.skip("cryptography not installed")
    allowed = (tmp_path / "allowed").resolve()
    allowed.mkdir()
    outside = (tmp_path / "outside").resolve()
    outside.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(eb, "_safe_segment_roots", lambda: [allowed])
    monkeypatch.setitem(gui_module._status, "config", {"output_dir": str(out)})
    gui_module.app.config["TESTING"] = True
    return SimpleNamespace(eb=eb, allowed=allowed, outside=outside, out=out,
                           client=gui_module.app.test_client(), monkeypatch=monkeypatch)


def _plain(folder: Path, name="clip.mp4", data=PLAIN) -> Path:
    p = folder / name
    p.write_bytes(data)
    return p


def _enc(folder: Path, name="clip.mp4", data=PLAIN, key=KEY, password=None) -> Path:
    src = _plain(folder, name, data)
    return enc.encrypt_file(src, password=password, key=None if password else key,
                            delete_original=False, output_path=folder / (name + ".enc"))


def _keyfile(folder: Path, key=KEY, name="camera.key") -> Path:
    p = folder / name
    p.write_bytes(key)
    return p


# ── /api/keygen ──────────────────────────────────────────────────────────────


def test_keygen_writes_a_32_byte_key_into_the_output_folder(env):
    r = env.client.post("/api/keygen", json={})
    assert r.status_code == 200
    body = r.get_json()
    assert body["size"] == 32
    assert Path(body["path"]) == (env.out / "camera.key").resolve()
    assert len((env.out / "camera.key").read_bytes()) == 32


def test_keygen_appends_the_key_extension(env):
    r = env.client.post("/api/keygen", json={"filename": "lobby"})
    assert Path(r.get_json()["path"]).name == "lobby.key"


def test_keygen_strips_directories_from_the_filename(env):
    r = env.client.post("/api/keygen", json={"filename": "../../escape.key"})
    assert r.status_code == 200
    assert Path(r.get_json()["path"]) == (env.out / "escape.key").resolve()


def test_keygen_refuses_an_unsafe_filename(env):
    r = env.client.post("/api/keygen", json={"filename": "bad name!.key"})
    assert r.status_code == 400
    assert r.get_json()["error"].startswith("Unsafe filename")


# ── 503 when cryptography is missing ─────────────────────────────────────────


@pytest.mark.parametrize("route", ["/api/keygen", "/api/encrypt", "/api/decrypt"])
def test_503_when_cryptography_is_not_installed(env, route):
    env.monkeypatch.setattr(env.eb, "_CRYPTO_AVAILABLE", False)
    r = env.client.post(route, json={"file_path": "x", "password": "p"})
    assert r.status_code == 503
    assert "cryptography" in r.get_json()["error"]


# ── /api/decrypt: every error path ───────────────────────────────────────────


def test_decrypt_requires_file_path(env):
    r = env.client.post("/api/decrypt", json={"password": "p"})
    assert (r.status_code, r.get_json()) == (400, {"error": "file_path is required"})


def test_decrypt_requires_a_credential(env):
    r = env.client.post("/api/decrypt", json={"file_path": str(env.allowed / "a.enc")})
    assert (r.status_code, r.get_json()) == (
        400, {"error": "Either password or key_file is required"})


def test_decrypt_refuses_a_path_outside_the_trusted_folders(env):
    target = _enc(env.outside)
    r = env.client.post("/api/decrypt", json={"file_path": str(target), "password": "p"})
    assert r.status_code == 403
    msg = r.get_json()["error"]
    assert msg.startswith("file_path is outside the trusted folders. Allowed: ")
    assert str(env.allowed) in msg


def test_decrypt_a_missing_file_is_404_and_names_only_the_file(env):
    r = env.client.post("/api/decrypt",
                        json={"file_path": str(env.allowed / "gone.mp4.enc"), "password": "p"})
    assert (r.status_code, r.get_json()) == (404, {"error": "File not found: gone.mp4.enc"})


def test_decrypt_only_accepts_dot_enc(env):
    plain = _plain(env.allowed)
    r = env.client.post("/api/decrypt", json={"file_path": str(plain), "password": "p"})
    assert (r.status_code, r.get_json()) == (
        400, {"error": "Only .enc files can be decrypted via this endpoint"})


def test_decrypt_refuses_a_key_file_outside_the_trusted_folders(env):
    target = _enc(env.allowed)
    stray = _keyfile(env.outside)
    r = env.client.post("/api/decrypt", json={"file_path": str(target), "key_file": str(stray)})
    assert (r.status_code, r.get_json()) == (
        403, {"error": "key_file is outside the trusted folders"})


def test_decrypt_an_unreadable_key_file_is_400(env):
    target = _enc(env.allowed)
    r = env.client.post("/api/decrypt",
                        json={"file_path": str(target), "key_file": str(env.allowed)})
    assert r.status_code == 400
    assert r.get_json()["error"].startswith("Cannot read key file: ")


def test_decrypt_with_the_wrong_key_is_403_and_leaves_no_plaintext(env):
    target = _enc(env.allowed)
    wrong = _keyfile(env.allowed, key=bytes(32), name="wrong.key")
    r = env.client.post("/api/decrypt", json={"file_path": str(target), "key_file": str(wrong)})
    assert r.status_code == 403
    assert "authentication failed" in r.get_json()["error"]
    assert list((env.allowed / "Decrypted").iterdir()) == []


def test_decrypt_a_tampered_file_is_403_and_leaves_no_plaintext(env):
    target = _enc(env.allowed)
    blob = bytearray(target.read_bytes())
    blob[enc.HEADER_SIZE + 10] ^= 0x01                 # flip one ciphertext bit
    target.write_bytes(bytes(blob))
    good = _keyfile(env.allowed)
    r = env.client.post("/api/decrypt", json={"file_path": str(target), "key_file": str(good)})
    assert r.status_code == 403
    assert list((env.allowed / "Decrypted").iterdir()) == []


def test_decrypt_a_truncated_file_is_403(env):
    target = _enc(env.allowed)
    target.write_bytes(target.read_bytes()[:-20])
    good = _keyfile(env.allowed)
    r = env.client.post("/api/decrypt", json={"file_path": str(target), "key_file": str(good)})
    assert r.status_code == 403
    assert list((env.allowed / "Decrypted").iterdir()) == []


def test_decrypt_a_file_shorter_than_the_header_is_500(env):
    """Pinned as it is today: ValueError from decrypt_file reaches the generic handler."""
    target = env.allowed / "short.mp4.enc"
    target.write_bytes(b"x" * 10)
    good = _keyfile(env.allowed)
    r = env.client.post("/api/decrypt", json={"file_path": str(target), "key_file": str(good)})
    assert r.status_code == 500
    assert r.get_json()["error"].startswith("Decryption failed: decrypt_file: file too short")


def test_decrypt_an_unexpected_crash_is_500(env):
    target = _enc(env.allowed)
    good = _keyfile(env.allowed)

    def boom(*a, **k):
        raise KeyError("boom")
    env.monkeypatch.setattr(env.eb, "_decrypt_file", boom)
    r = env.client.post("/api/decrypt", json={"file_path": str(target), "key_file": str(good)})
    assert r.status_code == 500
    assert r.get_json()["error"].startswith("Decryption failed: ")


def test_decrypt_when_decrypted_folder_cannot_be_created_is_500(env):
    target = _enc(env.allowed)
    (env.allowed / "Decrypted").write_bytes(b"i am a file, not a folder")
    good = _keyfile(env.allowed)
    r = env.client.post("/api/decrypt", json={"file_path": str(target), "key_file": str(good)})
    assert r.status_code == 500
    assert r.get_json()["error"].startswith("Could not create Decrypted/ folder: ")


# ── /api/decrypt: what a successful call returns ─────────────────────────────


def test_decrypt_returns_the_exact_plaintext_with_download_headers(env):
    target = _enc(env.allowed)
    good = _keyfile(env.allowed)
    r = env.client.post("/api/decrypt", json={"file_path": str(target), "key_file": str(good)})
    assert r.status_code == 200
    assert r.get_data() == PLAIN
    assert r.mimetype == "video/mp4"
    assert r.headers["Content-Length"] == str(len(PLAIN))
    assert r.headers["Content-Disposition"] == 'attachment; filename="clip.mp4"'


def test_decrypt_streams_large_clips_and_sends_the_same_bytes(env):
    target = _enc(env.allowed)
    good = _keyfile(env.allowed)
    env.monkeypatch.setattr(env.eb, "_INLINE_MAX_BYTES", 10)     # force the streaming branch
    env.monkeypatch.setattr(env.eb, "_STREAM_CHUNK", 1000)
    r = env.client.post("/api/decrypt", json={"file_path": str(target), "key_file": str(good)})
    assert r.status_code == 200
    assert r.get_data() == PLAIN
    assert r.headers["Content-Length"] == str(len(PLAIN))


def test_decrypt_never_deletes_the_encrypted_file(env):
    target = _enc(env.allowed)
    before = target.read_bytes()
    good = _keyfile(env.allowed)
    env.client.post("/api/decrypt", json={"file_path": str(target), "key_file": str(good)})
    assert target.read_bytes() == before


def test_decrypt_replaces_a_stale_copy_from_an_earlier_run(env):
    target = _enc(env.allowed)
    good = _keyfile(env.allowed)
    stale_dir = env.allowed / "Decrypted"
    stale_dir.mkdir()
    (stale_dir / "clip.mp4").write_bytes(b"STALE")
    r = env.client.post("/api/decrypt", json={"file_path": str(target), "key_file": str(good)})
    assert r.get_data() == PLAIN


def test_password_mode_round_trip(env):
    target = _enc(env.allowed, password="correct horse battery staple")
    r = env.client.post("/api/decrypt", json={"file_path": str(target),
                                              "password": "correct horse battery staple"})
    assert r.status_code == 200 and r.get_data() == PLAIN
    bad = env.client.post("/api/decrypt", json={"file_path": str(target), "password": "nope"})
    assert bad.status_code == 403


# ── /api/encrypt ─────────────────────────────────────────────────────────────


def test_encrypt_requires_file_path(env):
    r = env.client.post("/api/encrypt", json={"password": "p"})
    assert (r.status_code, r.get_json()) == (400, {"error": "file_path is required"})


def test_encrypt_requires_a_credential(env):
    r = env.client.post("/api/encrypt", json={"file_path": str(env.allowed / "a.mp4")})
    assert (r.status_code, r.get_json()) == (
        400, {"error": "Either password or key_file is required"})


def test_encrypt_refuses_a_path_outside_the_trusted_folders(env):
    src = _plain(env.outside)
    r = env.client.post("/api/encrypt", json={"file_path": str(src), "password": "p"})
    assert r.status_code == 403
    assert r.get_json()["error"].startswith("file_path is outside the trusted folders. Allowed: ")
    assert not (env.outside / "Encrypted").exists()


def test_encrypt_a_missing_file_is_404(env):
    r = env.client.post("/api/encrypt",
                        json={"file_path": str(env.allowed / "gone.mp4"), "password": "p"})
    assert (r.status_code, r.get_json()) == (404, {"error": "File not found: gone.mp4"})


def test_encrypt_refuses_an_already_encrypted_file(env):
    target = _enc(env.allowed)
    r = env.client.post("/api/encrypt", json={"file_path": str(target), "password": "p"})
    assert (r.status_code, r.get_json()) == (400, {"error": "File is already encrypted (.enc)"})


def test_encrypt_refuses_a_key_file_outside_the_trusted_folders(env):
    src = _plain(env.allowed)
    stray = _keyfile(env.outside)
    r = env.client.post("/api/encrypt", json={"file_path": str(src), "key_file": str(stray)})
    assert (r.status_code, r.get_json()) == (
        403, {"error": "key_file is outside the trusted folders"})
    assert not (env.allowed / "Encrypted").exists()


def test_encrypt_an_unreadable_key_file_is_400(env):
    src = _plain(env.allowed)
    r = env.client.post("/api/encrypt", json={"file_path": str(src), "key_file": str(env.allowed)})
    assert r.status_code == 400
    assert r.get_json()["error"].startswith("Cannot read key file: ")


def test_encrypt_a_key_file_of_the_wrong_size_is_400(env):
    src = _plain(env.allowed)
    short = _keyfile(env.allowed, key=b"too short", name="short.key")
    r = env.client.post("/api/encrypt", json={"file_path": str(src), "key_file": str(short)})
    assert r.status_code == 400
    assert "32" in r.get_json()["error"]


def test_encrypt_an_unexpected_crash_is_500(env):
    src = _plain(env.allowed)
    good = _keyfile(env.allowed)

    def boom(*a, **k):
        raise OSError("disk on fire")
    env.monkeypatch.setattr(env.eb, "_encrypt_file", boom)
    r = env.client.post("/api/encrypt", json={"file_path": str(src), "key_file": str(good)})
    assert (r.status_code, r.get_json()) == (500, {"error": "Encryption failed: disk on fire"})


def test_encrypt_when_encrypted_folder_cannot_be_created_is_500(env):
    src = _plain(env.allowed)
    (env.allowed / "Encrypted").write_bytes(b"i am a file, not a folder")
    good = _keyfile(env.allowed)
    r = env.client.post("/api/encrypt", json={"file_path": str(src), "key_file": str(good)})
    assert r.status_code == 500
    assert r.get_json()["error"].startswith("Could not create Encrypted/ folder: ")


def test_encrypt_writes_a_sibling_encrypted_folder_and_keeps_the_original(env):
    src = _plain(env.allowed)
    good = _keyfile(env.allowed)
    r = env.client.post("/api/encrypt", json={"file_path": str(src), "key_file": str(good)})
    assert r.status_code == 200
    body = r.get_json()
    enc_path = env.allowed / "Encrypted" / "clip.mp4.enc"
    assert Path(body["enc_path"]) == enc_path
    assert body["original_kept"] is True
    assert Path(body["original_path"]) == src
    assert body["size_kb"] == int(enc_path.stat().st_size / 1024)
    assert src.read_bytes() == PLAIN                              # original untouched
    assert enc_path.stat().st_size == enc.HEADER_SIZE + len(PLAIN)
    assert enc.decrypt_file(enc_path, key=KEY, output_path=env.allowed / "back.mp4"
                            ).read_bytes() == PLAIN


def test_encrypt_uses_the_encrypted_folder_chosen_in_setup(env):
    vault = env.allowed / "vault"
    env.monkeypatch.setitem(gui_module._status, "config",
                            {"output_dir": str(env.out), "encrypted_dir": str(vault)})
    src = _plain(env.allowed)
    good = _keyfile(env.allowed)
    r = env.client.post("/api/encrypt", json={"file_path": str(src), "key_file": str(good)})
    assert r.status_code == 200
    assert Path(r.get_json()["enc_path"]) == vault / "clip.mp4.enc"


def test_encrypt_ignores_a_setup_folder_outside_the_trusted_roots(env):
    """SEC-006: an escaping encrypted_dir falls back to a sibling Encrypted/."""
    env.monkeypatch.setitem(gui_module._status, "config",
                            {"output_dir": str(env.out), "encrypted_dir": str(env.outside / "vault")})
    src = _plain(env.allowed)
    good = _keyfile(env.allowed)
    r = env.client.post("/api/encrypt", json={"file_path": str(src), "key_file": str(good)})
    assert r.status_code == 200
    assert Path(r.get_json()["enc_path"]) == env.allowed / "Encrypted" / "clip.mp4.enc"
    assert not (env.outside / "vault").exists()


def test_encrypt_records_a_database_row_when_a_database_exists(env):
    from utils.db import initialize_database
    db = env.out / "metadata.db"
    initialize_database(db)
    env.monkeypatch.setattr(env.eb, "_get_db_path", lambda: db)
    src = _plain(env.allowed)
    good = _keyfile(env.allowed)
    r = env.client.post("/api/encrypt", json={"file_path": str(src), "key_file": str(good)})
    assert r.status_code == 200
    import sqlite3
    con = sqlite3.connect(str(db))
    rows = con.execute("SELECT file_path, object_type FROM segments").fetchall()
    con.close()
    assert rows == [(r.get_json()["enc_path"], "unknown")]


# ── the file format itself (known answer) ────────────────────────────────────


def test_enc_file_format_known_answer(tmp_path):
    """Bytes 0-11 nonce, 12-27 salt (zeros in raw key mode), 28-43 tag, 44+
    ciphertext. The expected bytes come from the cryptography library's own
    AESGCM, not from encryption.py, so this pins the format rather than the
    implementation."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = bytes(range(100, 112))
    real_urandom = os.urandom

    def fixed_nonce(n):
        return nonce if n == enc.NONCE_SIZE else real_urandom(n)

    src = tmp_path / "seg.mp4"
    src.write_bytes(PLAIN)
    out = tmp_path / "seg.mp4.enc"
    original = enc.os.urandom
    enc.os.urandom = fixed_nonce
    try:
        enc.encrypt_file(src, key=KEY, delete_original=False, output_path=out)
    finally:
        enc.os.urandom = original

    sealed = AESGCM(KEY).encrypt(nonce, PLAIN, None)             # ciphertext || tag
    ciphertext, tag = sealed[:-16], sealed[-16:]
    assert out.read_bytes() == nonce + bytes(16) + tag + ciphertext


def test_a_file_encrypted_by_independent_code_decrypts(tmp_path):
    """The other half of compatibility: files that did not come from encrypt_file."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = bytes(range(12))
    sealed = AESGCM(KEY).encrypt(nonce, PLAIN, None)
    blob = nonce + bytes(16) + sealed[-16:] + sealed[:-16]
    src = tmp_path / "foreign.mp4.enc"
    src.write_bytes(blob)
    assert enc.decrypt_file(src, key=KEY, output_path=tmp_path / "out.mp4").read_bytes() == PLAIN


def test_encrypt_a_type_error_is_a_normal_500(env):
    """The old output_path-less fallback is gone: a TypeError is just a failure."""
    src = _plain(env.allowed)
    key = _keyfile(env.allowed)

    def boom(*a, **k):
        raise TypeError("unexpected keyword")
    calls = []

    def counting_boom(*a, **k):
        calls.append(1)
        boom()
    env.monkeypatch.setattr(env.eb, "_encrypt_file", counting_boom)
    r = env.client.post("/api/encrypt", json={"file_path": str(src), "key_file": str(key)})
    assert len(calls) == 1          # no retry through a fallback
    assert r.status_code == 500
    assert r.get_json()["error"].startswith("Encryption failed: ")
    assert src.exists()
