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


def _is_empty_db_error(exc: Exception) -> bool:
    """True when a query failed only because metadata.db has no tables yet.

    sqlite3.connect() creates an empty file for any path whose folder exists,
    so a metadata.db can exist before the pipeline has ever initialized it
    (a fresh install whose output folder was made by Setup or a script). That
    means "nothing recorded yet", not a server error.
    Author: Bloodawn (KheivenD), 2026-09-24 (cleanup sweep).
    """
    return "no such table" in str(exc).lower()


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
        if abs_path.suffix.lower() in {".mp4", ".webm", ".mov", ".avi"} and abs_path.exists():
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


def hourly_detection_counts(db_path) -> dict:
    """How many clips had people and vehicles in them, by hour of the local day.

    Reads ``timestamp`` (UTC, ``YYYYmmddTHHMMSSZ``), ``person_count`` and
    ``vehicle_count`` from the segments table. Those two counts say whether a
    class was seen in the clip, so the chart is "clips with a person" and
    "clips with a vehicle" per hour, not a headcount. Hours are converted to the
    machine's local time so 9pm shows as 21. Never raises: an unreadable or
    empty database returns zeros.
    """
    import sqlite3
    from datetime import datetime, timezone

    people = [0] * 24
    vehicles = [0] * 24
    clips = 0
    try:
        conn = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True, timeout=2)
        try:
            rows = conn.execute(
                "SELECT timestamp, COALESCE(person_count,0), COALESCE(vehicle_count,0)"
                " FROM segments WHERE hidden IS NULL OR hidden = 0").fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        rows = []
    for ts, pc, vc in rows:
        try:
            when = datetime.strptime(str(ts), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone()
        except ValueError:
            continue
        clips += 1
        if pc:
            people[when.hour] += 1
        if vc:
            vehicles[when.hour] += 1
    return {
        "clips": clips,
        "hours": [{"hour": h, "people": people[h], "vehicles": vehicles[h]} for h in range(24)],
    }
