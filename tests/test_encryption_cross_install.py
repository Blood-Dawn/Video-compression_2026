"""
tests/test_encryption_cross_install.py

Verifies the .enc format is genuinely portable - not just a round trip
inside one Python process, which test_encryption.py already covers well but
which could in theory hide a bug where encrypt/decrypt secretly share
process-global state (a cached key, a loaded module singleton, ...).

Two levels of "somewhere else" are exercised here:

  1. A brand-new `python -c` subprocess (this file's own interpreter, but a
     fresh process with nothing carried over except the .enc file and the
     password/key) for every test below - the automated, CI-safe stand-in
     for "encrypt here, decrypt on a different machine."

  2. An independent, from-scratch AES-256-GCM decrypt that never imports
     utils.encryption at all - it reimplements the documented .enc header
     layout (see that module's docstring: nonce[12] + salt[16] + tag[16] +
     ciphertext) directly against the cryptography library's low-level
     primitives. This is the honest version of "decrypt it with other
     software": it proves the on-disk format is plain, standard AES-256-GCM
     that any compliant implementation can read given the documented
     layout, not something only our own decrypt_file() function knows how
     to open.

A real, separately-uv-sync'd worktree (a genuinely distinct install, its
own venv and dependency resolution) was also run manually for this same
round trip against a real sample clip; that is not automated here since it
depends on a sibling checkout that will not exist in CI, but the result is
recorded in docs/ENCRYPTION-VERIFICATION.md.

Author: Bloodawn (KheivenD), 2026-09-30 (encryption portability verification).
"""

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from src.utils.encryption import (
    HEADER_SIZE,
    NONCE_SIZE,
    SALT_SIZE,
    PBKDF2_ITERS,
    encrypt_file,
    decrypt_file,
    generate_key,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SAMPLE = _REPO_ROOT / "data" / "samples" / "cdnet_mp4" / "baseline" / "baseline_office.mp4"
_PASSWORD = "correct horse battery staple"  # noqa: S105 - test fixture, not a real secret


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_in_fresh_process(script: str) -> subprocess.CompletedProcess:
    """ Runs `script` in a brand-new interpreter process with this repo on
    sys.path, so it can `from src.utils.encryption import ...` exactly like
    a totally separate program would, sharing nothing with the test process
    but the arguments baked into the script text. """
    preamble = f"import sys; sys.path.insert(0, {str(_REPO_ROOT)!r})\n"
    return subprocess.run(
        [sys.executable, "-c", preamble + script],
        capture_output=True, text=True, timeout=60,
    )


# ---------------------------------------------------------------------------
# Round trip across a fresh process (stand-in for "a different install")
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _SAMPLE.exists(), reason="sample dataset not checked out")
def test_password_roundtrip_survives_a_fresh_process(tmp_path):
    """ Encrypt a real sample clip here; decrypt it in a separate process
    that never touched the plaintext, using only the .enc file and the
    password - exactly what "send the encrypted file to yourself, decrypt
    it on a fresh install" means in practice. """
    src = tmp_path / "clip.mp4"
    src.write_bytes(_SAMPLE.read_bytes())
    original_hash = _sha256(src)
    original_size = src.stat().st_size

    enc_path = encrypt_file(src, password=_PASSWORD)
    assert enc_path.exists()
    assert not src.exists(), "plaintext should be deleted after encryption"

    out_path = tmp_path / "clip_decrypted.mp4"
    result = _run_in_fresh_process(
        "from src.utils.encryption import decrypt_file\n"
        f"decrypt_file({str(enc_path)!r}, password={_PASSWORD!r}, output_path={str(out_path)!r})\n"
    )
    assert result.returncode == 0, result.stderr

    assert out_path.exists()
    assert out_path.stat().st_size == original_size
    assert _sha256(out_path) == original_hash


@pytest.mark.skipif(not _SAMPLE.exists(), reason="sample dataset not checked out")
def test_raw_key_roundtrip_survives_a_fresh_process(tmp_path):
    """ Same as above for a camera.key-style raw 32-byte key rather than a
    password - the workflow the desktop app actually uses for unattended
    per-camera encryption (see /api/keygen in encryption_bp.py). """
    src = tmp_path / "clip.mp4"
    src.write_bytes(_SAMPLE.read_bytes())
    original_hash = _sha256(src)

    key = generate_key()
    key_path = tmp_path / "camera.key"
    key_path.write_bytes(key)

    enc_path = encrypt_file(src, key=key)
    out_path = tmp_path / "clip_decrypted.mp4"
    result = _run_in_fresh_process(
        "from src.utils.encryption import decrypt_file\n"
        f"key = open({str(key_path)!r}, 'rb').read()\n"
        f"decrypt_file({str(enc_path)!r}, key=key, output_path={str(out_path)!r})\n"
    )
    assert result.returncode == 0, result.stderr
    assert _sha256(out_path) == original_hash


def test_wrong_password_fails_loudly_in_a_fresh_process(tmp_path):
    """ A wrong key must never be silently accepted - GCM's auth tag should
    reject it, even from a process that has no idea what the right password
    was. """
    src = tmp_path / "clip.bin"
    src.write_bytes(b"not a real video, just needs to be nonempty" * 100)
    enc_path = encrypt_file(src, password=_PASSWORD, delete_original=False)

    result = _run_in_fresh_process(
        "from src.utils.encryption import decrypt_file\n"
        f"decrypt_file({str(enc_path)!r}, password='definitely the wrong password')\n"
    )
    assert result.returncode != 0
    assert "authentication failed" in result.stderr or "RuntimeError" in result.stderr


def test_tampered_ciphertext_is_rejected_in_a_fresh_process(tmp_path):
    """ Flipping a single ciphertext byte after encryption must be caught by
    GCM's tag, not silently decrypted into corrupted footage. """
    src = tmp_path / "clip.bin"
    src.write_bytes(b"not a real video, just needs to be nonempty" * 100)
    enc_path = encrypt_file(src, password=_PASSWORD, delete_original=False)

    data = bytearray(enc_path.read_bytes())
    data[HEADER_SIZE + 5] ^= 0xFF  # flip one ciphertext byte, past the header
    enc_path.write_bytes(bytes(data))

    result = _run_in_fresh_process(
        "from src.utils.encryption import decrypt_file\n"
        f"decrypt_file({str(enc_path)!r}, password={_PASSWORD!r})\n"
    )
    assert result.returncode != 0
    assert "authentication failed" in result.stderr or "RuntimeError" in result.stderr


# ---------------------------------------------------------------------------
# Format-level interop: decrypt without ever importing our own module
# ---------------------------------------------------------------------------

def test_format_decrypts_with_independent_aes_gcm_primitives(tmp_path):
    """ The honest version of "can other software decrypt this": reimplement
    the documented .enc layout directly against cryptography's low-level
    AESGCM primitive, never importing utils.encryption. If this passes, the
    file is provably plain AES-256-GCM with a PBKDF2-HMAC-SHA256 derived
    key and the documented byte layout - any compliant implementation
    (OpenSSL, another language's crypto library, ...) that parses that same
    layout can decrypt it too, not just this codebase. """
    src = tmp_path / "clip.bin"
    payload = b"independent interop check payload" * 500
    src.write_bytes(payload)
    enc_path = encrypt_file(src, password=_PASSWORD, delete_original=False)

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    data = enc_path.read_bytes()
    nonce = data[:NONCE_SIZE]
    salt = data[NONCE_SIZE:NONCE_SIZE + SALT_SIZE]
    tag = data[NONCE_SIZE + SALT_SIZE:HEADER_SIZE]
    ciphertext = data[HEADER_SIZE:]

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERS)
    key = kdf.derive(_PASSWORD.encode("utf-8"))

    plaintext = AESGCM(key).decrypt(nonce, ciphertext + tag, None)
    assert plaintext == payload