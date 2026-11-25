"""
src/gui/services/library_labels.py

What was detected in each compressed clip, for the Library grid.

The pipeline records every segment it writes in a metadata.db next to the
output (object_classes is a JSON list such as ["person","car"]). The Library
lists files by walking folders, so this module joins the two: for a video it
looks for a metadata.db in the same folder or up to two folders above, and
matches the segment by file name.

Each db is read once and cached until its modified time changes, so a page of
200 clips costs a handful of small queries, not 200.

Author: Bloodawn (KheivenD), 2026-11-25.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path

_MODE_RE = re.compile(r"(?:^|[\\/_ .-])(mode[0-3])(?:$|[\\/_ .-])", re.IGNORECASE)

_lock = threading.Lock()
# db path -> (mtime, {file name lower: (classes tuple, person_count, vehicle_count)})
_cache: dict[str, tuple[float, dict]] = {}

# Names the pipeline writes that mean the same thing to a person.
_FRIENDLY = {"car": "vehicle", "truck": "vehicle", "bus": "vehicle",
             "motorcycle": "vehicle", "motorbike": "vehicle", "bicycle": "bicycle"}


def mode_of(path: str) -> str | None:
    """mode0..mode3 when the path or file name says which mode made the clip."""
    m = _MODE_RE.search(str(path))
    return m.group(1).lower() if m else None


def _norm_name(name: str) -> str:
    n = Path(str(name).replace("\\", "/")).name.lower()
    return n[:-4] if n.endswith(".enc") else n


def _load_db(db: Path) -> dict:
    try:
        mtime = db.stat().st_mtime
    except OSError:
        return {}
    key = str(db)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
    index: dict = {}
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=2)
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(segments)")}
            if "object_classes" in cols:
                person = "COALESCE(person_count,0)" if "person_count" in cols else "0"
                vehicle = "COALESCE(vehicle_count,0)" if "vehicle_count" in cols else "0"
                rows = conn.execute(
                    f"SELECT file_path, COALESCE(object_classes,'[]'), {person}, {vehicle} FROM segments")
                for fp, raw, pc, vc in rows:
                    try:
                        classes = [str(c) for c in json.loads(raw or "[]")]
                    except (ValueError, TypeError):
                        classes = []
                    index[_norm_name(fp)] = (tuple(classes), int(pc or 0), int(vc or 0))
        finally:
            conn.close()
    except sqlite3.Error:
        index = {}
    with _lock:
        _cache[key] = (mtime, index)
    return index


def _db_for(folder: Path) -> list[Path]:
    out = []
    for d in (folder, folder.parent, folder.parent.parent):
        db = d / "metadata.db"
        if db.is_file():
            out.append(db)
    return out


def tags_for(classes, person_count: int = 0, vehicle_count: int = 0) -> list[str]:
    """Short, human tags: person, vehicle, plus any other class by name."""
    tags: list[str] = []

    def add(t):
        if t and t not in tags:
            tags.append(t)

    if person_count > 0:
        add("person")
    if vehicle_count > 0:
        add("vehicle")
    for c in classes:
        c = c.strip().lower()
        add(_FRIENDLY.get(c, c))
    return tags


def attach(items: list[dict]) -> list[dict]:
    """Return copies of ``items`` with ``labels`` (list of tags) and ``mode``."""
    per_dir: dict[str, dict] = {}
    out = []
    for it in items:
        c = dict(it)
        c["mode"] = mode_of(it.get("path", ""))
        c["labels"] = []
        out.append(c)
    for c in out:
        p = Path(c.get("path", ""))
        key = str(p.parent)
        if key not in per_dir:
            merged: dict = {}
            for db in reversed(_db_for(p.parent)):     # nearest db wins
                merged.update(_load_db(db))
            per_dir[key] = merged
        hit = per_dir[key].get(_norm_name(p.name))
        if hit:
            classes, pc, vc = hit
            c["labels"] = tags_for(classes, pc, vc)
    return out
