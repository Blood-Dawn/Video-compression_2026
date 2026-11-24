"""SVCS Unlock: headless checks of the unlock and cleanup logic."""
from pathlib import Path

import pytest

from src.utils import svcs_unlock as u
from src.utils.encryption import encrypt_file, generate_key


def _enc(tmp_path, **kw):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"not really video bytes" * 100)
    return src, encrypt_file(src, **kw)


def test_unlock_with_password_roundtrips(tmp_path):
    src, enc = _enc(tmp_path, password="pw-1", delete_original=False)
    out = u.unlock(enc, password="pw-1")
    assert out.read_bytes() == src.read_bytes() and out.name == "clip.mp4"
    assert u.cleanup(out) is True and not out.parent.exists()


def test_unlock_with_keyfile(tmp_path):
    key = generate_key()
    kf = tmp_path / "camera.key"
    kf.write_bytes(key)
    src, enc = _enc(tmp_path, key=key, delete_original=False)
    out = u.unlock(enc, keyfile=str(kf))
    assert out.read_bytes() == src.read_bytes()
    u.cleanup(out)


def test_wrong_password_fails_and_leaves_no_temp(tmp_path):
    import tempfile
    _src, enc = _enc(tmp_path, password="right")
    before = set(Path(tempfile.gettempdir()).glob("svcs_unlock_*"))
    with pytest.raises(Exception):
        u.unlock(enc, password="wrong")
    assert set(Path(tempfile.gettempdir()).glob("svcs_unlock_*")) == before


def test_missing_credential_and_missing_file(tmp_path):
    _src, enc = _enc(tmp_path, password="x")
    with pytest.raises(ValueError):
        u.unlock(enc)
    with pytest.raises(FileNotFoundError):
        u.unlock(tmp_path / "nope.enc", password="x")


def test_cleanup_refuses_foreign_folders(tmp_path):
    f = tmp_path / "keep" / "a.mp4"
    f.parent.mkdir()
    f.write_bytes(b"x")
    assert u.cleanup(f) is False and f.exists()
