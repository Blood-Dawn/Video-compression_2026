"""
src/gui/secret_key.py - the persisted Flask SECRET_KEY.

The key signs session cookies. It lives in a state file so sessions survive a
restart. Two properties matter:

  * the file is created with owner-only permissions from the first byte, not
    written world-readable and chmod-ed afterwards (a window on POSIX), and
  * a damaged key (empty, truncated, or otherwise shorter than 32 bytes) is
    never used. It is replaced with a fresh random key, which only signs users
    out.
"""

from __future__ import annotations

import os
from pathlib import Path

MIN_KEY_BYTES = 32


def _create_exclusive(path: Path, key: bytes) -> bool:
    """Create ``path`` holding ``key`` with mode 0600. False if it exists."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    return True


def _replace_atomically(path: Path, key: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    _create_exclusive(tmp, key)
    os.replace(tmp, path)


def load_or_create_secret_key(path: Path) -> bytes:
    """Return the stored key, creating or repairing the file as needed."""
    path = Path(path)
    try:
        key = path.read_bytes()
        if len(key) >= MIN_KEY_BYTES:
            return key
        damaged = True
    except FileNotFoundError:
        damaged = False
    new_key = os.urandom(MIN_KEY_BYTES)
    if damaged:
        _replace_atomically(path, new_key)
        return new_key
    if _create_exclusive(path, new_key):
        return new_key
    # Another process created it between our read and create: use theirs.
    existing = path.read_bytes()
    if len(existing) >= MIN_KEY_BYTES:
        return existing
    _replace_atomically(path, new_key)
    return new_key
