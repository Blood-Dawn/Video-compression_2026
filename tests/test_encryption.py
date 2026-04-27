"""
tests/test_encryption.py

Round-trip and security tests for AES-256-GCM encryption in src/utils/encryption.py.

Covers:
- Password and raw-key encrypt/decrypt round-trips
- .enc file is written; plaintext is deleted after encryption
- Wrong password raises RuntimeError (auth tag mismatch)
- Tampered ciphertext raises RuntimeError (bit-flip detection)
- Bad arguments raise ValueError
- Header constants match actual file layout
"""

import os
import pytest
from pathlib import Path

from src.utils.encryption import (
    encrypt_file,
    decrypt_file,
    generate_key,
    derive_key,
    NONCE_SIZE,
    SALT_SIZE,
    TAG_SIZE,
    KEY_SIZE,
    HEADER_SIZE,
    _ZERO_SALT,
)

PAYLOAD = b"fake surveillance video data " * 200  # ~6 KB of dummy content


@pytest.fixture()
def tmp_mp4(tmp_path: Path) -> Path:
    """Write a small fake video file and return its path."""
    p = tmp_path / "segment_001.mp4"
    p.write_bytes(PAYLOAD)
    return p


# ---------------------------------------------------------------------------
# Round-trip: password mode
# ---------------------------------------------------------------------------

class TestPasswordMode:
    def test_encrypt_creates_enc_file(self, tmp_mp4: Path) -> None:
        enc = encrypt_file(tmp_mp4, password="test-pass", delete_original=False)
        assert enc.exists()
        assert enc.suffix == ".enc"

    def test_original_deleted_by_default(self, tmp_mp4: Path) -> None:
        encrypt_file(tmp_mp4, password="test-pass")
        assert not tmp_mp4.exists()

    def test_decrypt_recovers_plaintext(self, tmp_mp4: Path, tmp_path: Path) -> None:
        enc = encrypt_file(tmp_mp4, password="correct-horse")
        out = tmp_path / "recovered.mp4"
        decrypt_file(enc, password="correct-horse", output_path=out)
        assert out.read_bytes() == PAYLOAD

    def test_wrong_password_raises(self, tmp_mp4: Path) -> None:
        enc = encrypt_file(tmp_mp4, password="right")
        with pytest.raises(RuntimeError, match="authentication failed|decryption failed"):
            decrypt_file(enc, password="wrong")

    def test_enc_file_larger_than_plaintext(self, tmp_mp4: Path) -> None:
        enc = encrypt_file(tmp_mp4, password="pw", delete_original=False)
        assert enc.stat().st_size > tmp_mp4.stat().st_size

    def test_header_size_matches_constants(self, tmp_mp4: Path) -> None:
        enc = encrypt_file(tmp_mp4, password="pw", delete_original=False)
        raw = enc.read_bytes()
        # Nonce + Salt + Tag should occupy exactly HEADER_SIZE bytes
        assert len(raw) >= HEADER_SIZE
        assert HEADER_SIZE == NONCE_SIZE + SALT_SIZE + TAG_SIZE

    def test_salt_is_nonzero_in_password_mode(self, tmp_mp4: Path) -> None:
        enc = encrypt_file(tmp_mp4, password="pw", delete_original=False)
        raw = enc.read_bytes()
        salt = raw[NONCE_SIZE:NONCE_SIZE + SALT_SIZE]
        assert salt != _ZERO_SALT


# ---------------------------------------------------------------------------
# Round-trip: raw-key mode
# ---------------------------------------------------------------------------

class TestRawKeyMode:
    def test_decrypt_recovers_plaintext(self, tmp_mp4: Path, tmp_path: Path) -> None:
        key = generate_key()
        enc = encrypt_file(tmp_mp4, key=key)
        out = tmp_path / "recovered.mp4"
        decrypt_file(enc, key=key, output_path=out)
        assert out.read_bytes() == PAYLOAD

    def test_wrong_key_raises(self, tmp_mp4: Path) -> None:
        key = generate_key()
        enc = encrypt_file(tmp_mp4, key=key)
        with pytest.raises(RuntimeError, match="authentication failed|decryption failed"):
            decrypt_file(enc, key=generate_key())

    def test_salt_is_zero_in_raw_key_mode(self, tmp_mp4: Path) -> None:
        enc = encrypt_file(tmp_mp4, key=generate_key(), delete_original=False)
        raw = enc.read_bytes()
        salt = raw[NONCE_SIZE:NONCE_SIZE + SALT_SIZE]
        assert salt == _ZERO_SALT

    def test_each_encryption_produces_different_output(self, tmp_path: Path) -> None:
        p1 = tmp_path / "a.mp4"
        p2 = tmp_path / "b.mp4"
        p1.write_bytes(PAYLOAD)
        p2.write_bytes(PAYLOAD)
        key = generate_key()
        enc1 = encrypt_file(p1, key=key, delete_original=False)
        enc2 = encrypt_file(p2, key=key, delete_original=False)
        # Different nonces → different ciphertexts even for identical plaintext
        assert enc1.read_bytes() != enc2.read_bytes()


# ---------------------------------------------------------------------------
# Bit-flip / tamper detection (GCM auth tag)
# ---------------------------------------------------------------------------

class TestTamperDetection:
    def test_flipped_ciphertext_bit_raises(self, tmp_mp4: Path) -> None:
        key = generate_key()
        enc = encrypt_file(tmp_mp4, key=key, delete_original=False)
        raw = bytearray(enc.read_bytes())
        # Flip a bit in the ciphertext (after the header)
        raw[HEADER_SIZE] ^= 0x01
        enc.write_bytes(bytes(raw))
        with pytest.raises(RuntimeError, match="authentication failed|decryption failed"):
            decrypt_file(enc, key=key)

    def test_truncated_ciphertext_raises(self, tmp_mp4: Path) -> None:
        key = generate_key()
        enc = encrypt_file(tmp_mp4, key=key, delete_original=False)
        raw = enc.read_bytes()
        enc.write_bytes(raw[:-10])  # chop last 10 bytes
        with pytest.raises((RuntimeError, ValueError)):
            decrypt_file(enc, key=key)

    def test_flipped_tag_byte_raises(self, tmp_mp4: Path) -> None:
        key = generate_key()
        enc = encrypt_file(tmp_mp4, key=key, delete_original=False)
        raw = bytearray(enc.read_bytes())
        tag_start = NONCE_SIZE + SALT_SIZE
        raw[tag_start] ^= 0xFF
        enc.write_bytes(bytes(raw))
        with pytest.raises(RuntimeError, match="authentication failed|decryption failed"):
            decrypt_file(enc, key=key)


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------

class TestArgValidation:
    def test_no_key_or_password_raises(self, tmp_mp4: Path) -> None:
        with pytest.raises(ValueError, match="requires either"):
            encrypt_file(tmp_mp4)

    def test_both_key_and_password_raises(self, tmp_mp4: Path) -> None:
        with pytest.raises(ValueError, match="not both"):
            encrypt_file(tmp_mp4, password="pw", key=generate_key())

    def test_wrong_key_length_raises(self, tmp_mp4: Path) -> None:
        with pytest.raises(ValueError, match="exactly 32 bytes"):
            encrypt_file(tmp_mp4, key=b"short")

    def test_missing_input_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            encrypt_file(tmp_path / "nonexistent.mp4", password="pw")

    def test_file_too_short_raises(self, tmp_path: Path) -> None:
        enc = tmp_path / "bad.enc"
        enc.write_bytes(b"tooshort")
        with pytest.raises(ValueError, match="too short"):
            decrypt_file(enc, password="pw")


# ---------------------------------------------------------------------------
# generate_key / derive_key helpers
# ---------------------------------------------------------------------------

class TestKeyHelpers:
    def test_generate_key_is_32_bytes(self) -> None:
        assert len(generate_key()) == KEY_SIZE

    def test_generate_key_is_random(self) -> None:
        assert generate_key() != generate_key()

    def test_derive_key_is_32_bytes(self) -> None:
        salt = os.urandom(SALT_SIZE)
        assert len(derive_key("password", salt)) == KEY_SIZE

    def test_derive_key_is_deterministic(self) -> None:
        salt = os.urandom(SALT_SIZE)
        assert derive_key("pw", salt) == derive_key("pw", salt)

    def test_derive_key_differs_with_different_salt(self) -> None:
        assert derive_key("pw", os.urandom(16)) != derive_key("pw", os.urandom(16))
