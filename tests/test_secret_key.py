"""The persisted Flask SECRET_KEY: created owner-only, damaged keys replaced."""

import os
import stat
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.secret_key import MIN_KEY_BYTES, load_or_create_secret_key  # noqa: E402


def test_missing_file_is_created_with_a_32_byte_key(tmp_path):
    p = tmp_path / "flask_secret"
    key = load_or_create_secret_key(p)
    assert len(key) == MIN_KEY_BYTES and p.read_bytes() == key


def test_existing_good_key_is_reused(tmp_path):
    p = tmp_path / "flask_secret"
    first = load_or_create_secret_key(p)
    assert load_or_create_secret_key(p) == first


@pytest.mark.parametrize("bad", [b"", b"short", b"x" * 31])
def test_damaged_key_is_replaced_not_used(tmp_path, bad):
    p = tmp_path / "flask_secret"
    p.write_bytes(bad)
    key = load_or_create_secret_key(p)
    assert key != bad and len(key) == MIN_KEY_BYTES
    assert p.read_bytes() == key
    assert not (tmp_path / "flask_secret.tmp").exists()


def test_a_longer_existing_key_is_kept(tmp_path):
    p = tmp_path / "flask_secret"
    p.write_bytes(b"k" * 64)
    assert load_or_create_secret_key(p) == b"k" * 64


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not meaningful on Windows")
def test_file_is_owner_only_from_creation(tmp_path):
    p = tmp_path / "flask_secret"
    load_or_create_secret_key(p)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_file_is_created_exclusively_with_mode_0600(tmp_path, monkeypatch):
    """The mode is passed at creation, so there is no readable-then-chmod window."""
    seen = {}
    real_open = os.open

    def spy(path, flags, mode=0o777, *a, **k):
        seen["mode"] = mode
        seen["excl"] = bool(flags & os.O_EXCL)
        return real_open(path, flags, mode, *a, **k)

    monkeypatch.setattr(os, "open", spy)
    load_or_create_secret_key(tmp_path / "flask_secret")
    assert seen == {"mode": 0o600, "excl": True}


def test_app_uses_a_valid_key():
    from gui.app import app
    assert len(app.config["SECRET_KEY"]) >= MIN_KEY_BYTES
