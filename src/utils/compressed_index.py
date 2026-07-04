"""
src/utils/compressed_index.py

"Already compressed" index for auto-compress (R3.1a).

A small persistent JSON index, under the app-data dir, that answers "have we
already compressed this source video, and where is the output?" so the
auto-compress daemon never recompresses a clip it already did (and never
recompresses its own outputs). It is keyed by a source SIGNATURE built from the
absolute path + size + mtime, so replacing a file at the same path (different
content) invalidates the entry and the file is treated as new.

Public API:
  signature(source) -> str
  record(source, output, preset, mode=None) -> dict
  lookup(source) -> entry | None      (only if the current signature matches)
  is_compressed(source) -> bool       (entry matches AND output still exists)
  classify(path) -> "original" | "compressed"
  compressed_subdir(output_dir, create=True) -> Path

Every function accepts an optional ``index_path`` so tests can isolate the file.

Author: Bloodawn (KheivenD), 2026-06-05 (R3.1a - already-compressed index).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

try:
    from utils import paths as _paths
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils import paths as _paths

INDEX_FILENAME = "compressed_index.json"
# The dedicated subfolder name auto-compress writes outputs into. Anything under
# a folder with this name is classified "compressed" without needing the index.
COMPRESSED_DIRNAME = "compressed"
SCHEMA_VERSION = 1

# Serialises read-modify-write of the index across threads (the auto-compress
# daemon's record() and retention's prune_missing() can run concurrently).
_index_lock = threading.Lock()


def _index_file(index_path: Optional[Path] = None) -> Path:
    return Path(index_path) if index_path is not None else _paths.state_file(INDEX_FILENAME)


def _load(index_path: Optional[Path] = None) -> dict:
    p = _index_file(index_path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("entries"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"schema": SCHEMA_VERSION, "entries": {}}


def _save(data: dict, index_path: Optional[Path] = None) -> None:
    p = _index_file(index_path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:  # pragma: no cover - best effort; never crash a compress
        pass


def _resolved(source) -> Path:
    return Path(source).resolve()


def signature(source) -> str:
    """Return a stable signature for a source file: ``<path>|<size>|<mtime>``.

    The signature changes whenever the file at that path is replaced (size or
    mtime differs), so a re-saved clip is treated as a new file. Returns a
    path-only signature if the file is missing (so lookups simply miss).
    """
    p = _resolved(source)
    try:
        st = p.stat()
        return f"{p}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        return f"{p}|0|0"


def record(source, output, preset: Optional[str] = None,
           mode: Optional[str] = None, when: Optional[float] = None,
           index_path: Optional[Path] = None) -> dict:
    """Record that ``source`` was compressed to ``output``. Returns the entry."""
    sig = signature(source)
    entry = {
        "source": str(_resolved(source)),
        "signature": sig,
        "output": str(_resolved(output)),
        "preset": preset,
        "mode": mode,
        "when": when if when is not None else time.time(),
    }
    # Locked read-modify-write so a concurrent prune_missing()/record() cannot
    # clobber the file and lose entries.
    with _index_lock:
        data = _load(index_path)
        data["entries"][sig] = entry
        _save(data, index_path)
    return entry


def prune_missing(index_path: Optional[Path] = None) -> int:
    """Drop entries whose recorded output file no longer exists. Returns count.

    Locked read-modify-write (shares ``_index_lock`` with ``record``), so
    retention's post-purge pruning never races the auto-compress daemon's
    recording. Best effort - never raises.
    """
    try:
        with _index_lock:
            data = _load(index_path)
            entries = data.get("entries", {})
            dead = [sig for sig, e in entries.items()
                    if not Path(e.get("output", "")).is_file()]
            if not dead:
                return 0
            for sig in dead:
                entries.pop(sig, None)
            _save(data, index_path)
            return len(dead)
    except Exception:  # noqa: BLE001 - best effort
        return 0


def lookup(source, index_path: Optional[Path] = None):
    """Return the recorded entry for ``source`` if its CURRENT signature matches,
    else None. (A replaced file has a new signature and will not match.)"""
    data = _load(index_path)
    return data["entries"].get(signature(source))


def is_compressed(source, index_path: Optional[Path] = None) -> bool:
    """True only if a matching entry exists AND its output file still exists.

    If the recorded output was deleted, the source is treated as not-compressed
    so it can be redone.
    """
    entry = lookup(source, index_path)
    if not entry:
        return False
    out = entry.get("output", "")
    try:
        return bool(out) and Path(out).is_file()
    except OSError:
        return False


def classify(path, index_path: Optional[Path] = None) -> str:
    """Classify a path as "compressed" or "original".

    A path is "compressed" if it lives under a ``compressed`` folder (where
    auto-compress writes), or if the index recorded it as an output. Everything
    else is an "original".
    """
    p = _resolved(path)
    if COMPRESSED_DIRNAME in {part.lower() for part in p.parts}:
        return "compressed"
    data = _load(index_path)
    target = str(p)
    for entry in data["entries"].values():
        if entry.get("output") == target:
            return "compressed"
    return "original"


def compressed_subdir(output_dir, create: bool = True) -> Path:
    """Return ``<output_dir>/compressed`` (the auto-compress output location).

    Kept separate from the watched source set so the daemon never recompresses
    its own outputs.
    """
    d = Path(output_dir) / COMPRESSED_DIRNAME
    if create:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:  # pragma: no cover
            pass
    return d
