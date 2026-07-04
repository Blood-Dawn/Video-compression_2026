"""
src/utils/active_outputs.py

Registry of output files an encoder is CURRENTLY writing (R4 Phase 3 review fix).

The ROIEncoder streams a segment directly to its final path inside
``<output_dir>/compressed`` and holds that file open for the whole encode (a
segment can be up to an hour). Retention (gui/services/retention.py) deletes old
clips in that same folder. An mtime "freshness window" is only a heuristic: a
slow encode's output can go untouched for minutes while ffmpeg still holds it
open, and on POSIX ``unlink`` of an open file succeeds silently, so a concurrent
purge could delete a segment mid-write and lose the footage with no error.

This module is the reliable in-flight guard: the encoder registers the path it
is writing (``mark_active``) and clears it when done (``mark_done``, always in a
finally), and retention refuses to delete any path currently in the set. It
lives in ``utils`` (not ``gui``) so the compression layer can import it without
depending on the GUI.

Author: Bloodawn (KheivenD), 2026-07-04 (R4 Phase 3 review - in-flight guard).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Set

_lock = threading.Lock()
_active: Set[str] = set()


def _key(path) -> str:
    try:
        return str(Path(path).resolve())
    except (OSError, ValueError, TypeError):
        return str(path)


def mark_active(path) -> None:
    """Record that ``path`` is being written by an encoder right now."""
    if not path:
        return
    with _lock:
        _active.add(_key(path))


def mark_done(path) -> None:
    """Clear ``path`` from the active set (safe to call more than once)."""
    if not path:
        return
    with _lock:
        _active.discard(_key(path))


def is_active(path) -> bool:
    """True if ``path`` is currently being written (resolved-path match)."""
    if not path:
        return False
    with _lock:
        return _key(path) in _active


def snapshot() -> Set[str]:
    """A copy of the currently-active resolved paths."""
    with _lock:
        return set(_active)
