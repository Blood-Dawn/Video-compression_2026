"""
tests/security/test_crypto_hardening.py  (SEC-D2)

Attack the AES-256-GCM implementation and assert it holds:
  * a fresh, unique nonce per encryption (no nonce reuse under one key),
  * a fresh salt per file in password mode,
  * the GCM tag rejects tampered ciphertext (bit-flip),
  * a wrong password/key fails cleanly with NO plaintext written,
  * PBKDF2 uses the intended 600k iterations.
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

enc = pytest.importorskip("utils.encryption")
if not getattr(enc, "_CRYPTO_AVAILABLE", False):
    pytest.skip("cryptography not installed", allow_module_level=True)

NONCE_SIZE = enc.NONCE_SIZE
SALT_SIZE = enc.SALT_SIZE
HEADER_SIZE = enc.HEADER_SIZE


def _write(tmp_path, name="clip.mp4", data=b"the secret footage bytes" * 64):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_nonce_is_unique_per_encryption(tmp_path):
    nonces = set()
    for i in range(25):
        src = _write(tmp_path, f"c{i}.mp4")
        out = enc.encrypt_file(src, password="pw", delete_original=False)
        hdr = out.read_bytes()[:NONCE_SIZE]
        assert hdr not in nonces, "nonce reused across encryptions under the same password"
        nonces.add(hdr)
    assert len(nonces) == 25


def test_salt_is_unique_per_file(tmp_path):
    salts = set()
    for i in range(10):
        src = _write(tmp_path, f"s{i}.mp4")
        out = enc.encrypt_file(src, password="pw", delete_original=False)
        salt = out.read_bytes()[NONCE_SIZE:NONCE_SIZE + SALT_SIZE]
        salts.add(salt)
    assert len(salts) == 10, "salt reused across files in password mode"


def test_tampered_ciphertext_is_rejected(tmp_path):
    src = _write(tmp_path)
    out = enc.encrypt_file(src, password="pw", delete_original=False)
    blob = bytearray(out.read_bytes())
    # Flip a bit in the ciphertext (after the 44-byte header).
    blob[HEADER_SIZE + 1] ^= 0x01
    out.write_bytes(bytes(blob))
    dst = tmp_path / "tampered_out.mp4"
    with pytest.raises(RuntimeError):
        enc.decrypt_file(out, password="pw", output_path=dst)
    assert not dst.exists(), "plaintext was written despite a failed auth tag"


def test_wrong_password_fails_clean(tmp_path):
    src = _write(tmp_path)
    out = enc.encrypt_file(src, password="correct-horse", delete_original=False)
    dst = tmp_path / "wrong_out.mp4"
    with pytest.raises(RuntimeError):
        enc.decrypt_file(out, password="WRONG", output_path=dst)
    assert not dst.exists()


def test_roundtrip_recovers_plaintext(tmp_path):
    data = b"exact bytes must survive" * 100
    src = _write(tmp_path, "rt.mp4", data)
    out = enc.encrypt_file(src, password="pw", delete_original=False)
    dst = tmp_path / "rt_dec.mp4"
    enc.decrypt_file(out, password="pw", output_path=dst)
    assert dst.read_bytes() == data


def test_pbkdf2_iterations_are_600k():
    assert enc.PBKDF2_ITERS == 600_000, "PBKDF2 iteration count regressed below 600k"
