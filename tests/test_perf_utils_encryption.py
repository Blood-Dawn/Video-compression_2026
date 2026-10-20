"""The streamed encrypt/decrypt keeps the on-disk .enc format and its safety rules."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

pytest.importorskip("cryptography")

from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402

from utils import encryption as enc  # noqa: E402


def _one_shot_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """The layout the pre-streaming code wrote: nonce | zero salt | tag | ciphertext."""
    nonce = os.urandom(enc.NONCE_SIZE)
    sealed = AESGCM(key).encrypt(nonce, plaintext, None)  # ciphertext + tag
    ciphertext, tag = sealed[:-enc.TAG_SIZE], sealed[-enc.TAG_SIZE:]
    return nonce + b"\x00" * enc.SALT_SIZE + tag + ciphertext


@pytest.mark.parametrize("size", [0, 1, enc._CHUNK_SIZE - 1, enc._CHUNK_SIZE, 3 * enc._CHUNK_SIZE + 7])
def test_streamed_output_matches_one_shot_layout(tmp_path, size):
    key = enc.generate_key()
    payload = os.urandom(size)
    src = tmp_path / "seg.mp4"
    src.write_bytes(payload)

    out = enc.encrypt_file(src, key=key)

    data = out.read_bytes()
    assert len(data) == enc.HEADER_SIZE + size
    nonce, tag = data[:enc.NONCE_SIZE], data[enc.NONCE_SIZE + enc.SALT_SIZE:enc.HEADER_SIZE]
    assert AESGCM(key).decrypt(nonce, data[enc.HEADER_SIZE:] + tag, None) == payload
    assert not src.exists()
    assert not list(tmp_path.glob("*.part"))


def test_decrypts_files_written_by_the_one_shot_layout(tmp_path):
    key = enc.generate_key()
    payload = os.urandom(2 * enc._CHUNK_SIZE + 123)
    blob = tmp_path / "old.mp4.enc"
    blob.write_bytes(_one_shot_encrypt(payload, key))

    out = enc.decrypt_file(blob, key=key)

    assert out == tmp_path / "old.mp4"
    assert out.read_bytes() == payload


def test_tampered_file_leaves_no_plaintext_behind(tmp_path):
    key = enc.generate_key()
    src = tmp_path / "seg.mp4"
    src.write_bytes(os.urandom(enc._CHUNK_SIZE + 50))
    out = enc.encrypt_file(src, key=key)
    raw = bytearray(out.read_bytes())
    raw[-1] ^= 0x01
    out.write_bytes(bytes(raw))

    with pytest.raises(RuntimeError, match="authentication failed"):
        enc.decrypt_file(out, key=key)

    assert not (tmp_path / "seg.mp4").exists()
    assert not list(tmp_path.glob("*.part"))


def test_password_round_trip_in_place(tmp_path):
    src = tmp_path / "clip.mp4"
    payload = os.urandom(5000)
    src.write_bytes(payload)

    out = enc.encrypt_file(src, password="pw", delete_original=False, output_path=tmp_path / "x.enc")

    assert src.read_bytes() == payload
    assert enc.decrypt_file(out, password="pw", output_path=tmp_path / "back.mp4").read_bytes() == payload


def test_decrypt_onto_open_target_succeeds(tmp_path):
    """A second decrypt works while the first plaintext is still held open
    (on Windows os.replace would raise PermissionError there)."""
    src = tmp_path / "clip.bin"
    src.write_bytes(b"hello world" * 1000)
    enc_path = enc.encrypt_file(src, password="pw", delete_original=True)
    out = enc.decrypt_file(enc_path, password="pw")
    with open(out, "rb") as held:
        out2 = enc.decrypt_file(enc_path, password="pw")
        assert out2 == out
        assert held.read(5) == b"hello"
    assert out.read_bytes() == b"hello world" * 1000
    assert not list(tmp_path.glob("*.part"))
