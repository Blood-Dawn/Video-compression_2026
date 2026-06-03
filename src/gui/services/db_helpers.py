"""
src/gui/services/db_helpers.py

metadata.db path resolution and row->dict shaping for the archive/query
routes, extracted from gui/app.py (TASK 1.2).

`_get_archive_db_path` reads the active Flask request's ``archive_dir`` query
arg, so it must run inside a request context (as it always did when it lived in
app.py). `_ROOT` is computed locally from __file__ (repo root) and is only used
as the default-folder fallback, which the GUI test suite never exercises (the
archive routes pass an explicit ``archive_dir``).

Imports gui.state (shared status dict + its lock) and flask.request.

Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - db-helpers extraction).
"""

from pathlib import Path
from urllib.parse import quote

from flask import request

try:
    from gui.state import _state_lock, _status
except ModuleNotFoundError:                # pragma: no cover - import path shim
    from src.gui.state import _state_lock, _status

# Repo root (…/src/gui/services/db_helpers.py -> parents[3]); default fallback only.
_ROOT = Path(__file__).resolve().parents[3]


def _get_db_path() -> Path:
    """Return the metadata.db path from the last-used config, or default."""
    with _state_lock:
        cfg = _status.get("config", {})
    return Path(cfg.get("output_dir", str(_ROOT / "outputs"))) / "metadata.db"


def _get_archive_db_path() -> Path:
    """Return metadata.db from an explicit archive folder, defaulting to outputs/."""
    archive_dir = request.args.get("archive_dir", "").strip()
    if archive_dir:
        return Path(archive_dir).expanduser().resolve() / "metadata.db"
    return (_ROOT / "outputs" / "metadata.db").resolve()


def _rows_to_segment_list(rows, base_dir: Path | None = None) -> list:
    """Convert raw DB tuples to JSON-serialisable dicts."""
    segs = []
    for r in rows:
        # schema: id, timestamp, camera_id, target_detected, roi_count,
        #         file_size, duration, file_path, object_type
        abs_path = Path(r[7])
        if not abs_path.is_absolute() and base_dir is not None:
            abs_path = base_dir / abs_path
        abs_path = abs_path.resolve()
        playable_url = None
        if abs_path.exists() and abs_path.suffix.lower() in {".mp4", ".webm", ".mov", ".avi"}:
            playable_url = f"/api/media?path={quote(str(abs_path))}"
        segs.append({
            "id": r[0],
            "timestamp": r[1],
            "camera_id": r[2],
            "target_detected": bool(r[3]),
            "roi_count": r[4],
            "file_size_kb": round(r[5] / 1024, 1),
            "duration_s": round(r[6], 1),
            "file_path": r[7],
            "object_type": r[8] if len(r) > 8 else "unknown",
            "playable_url": playable_url,
        })
    return segs
