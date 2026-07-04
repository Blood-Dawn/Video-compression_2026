"""
src/gui/services/job_history.py

Persistent job history (R4 Phase 1 - UX research adoption).

NN/g's long-running-work guidance (docs/RESEARCH-UIUX.md findings 2 and 3):
keep a persistent, visible record of jobs so operators can audit work after
interruptions, and give an explicit completion summary (start, stop, elapsed,
what happened). This module is the storage half: a tiny JSON log in the app
state dir, one entry per finished run - manual pipeline runs and auto-compress
batch passes both land here. The UI reads it via GET /api/jobs/recent.

History is a UX aid, not a ledger: every public function is best-effort and
never raises, because a failed history write must never break a compression
run or a route.

Author: Bloodawn (KheivenD), 2026-07-04 (R4 Phase 1 - job history).
"""

from __future__ import annotations

import json
import threading
import time
from typing import List, Optional

try:
    from utils import paths as _paths
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils import paths as _paths

# Keep the log bounded; 100 finished runs is far more than the UI ever shows.
_MAX_JOBS = 100

_jobs_lock = threading.Lock()


def _jobs_file():
    """One JSON file next to gui_state.json / the Flask secret.

    Resolved lazily (not at import) so tests that monkeypatch
    ``utils.paths.state_file`` isolate this log too, exactly like the
    compressed index does.
    """
    return _paths.state_file("job_history.json")


def _load() -> List[dict]:
    try:
        f = _jobs_file()
        if not f.exists():
            return []
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001 - unreadable history is treated as empty
        return []


def record_job(
    kind: str,
    label: str = "",
    started_at: Optional[float] = None,
    ended_at: Optional[float] = None,
    status: str = "completed",
    counts: Optional[dict] = None,
    bytes_in: int = 0,
    bytes_out: int = 0,
    error: Optional[str] = None,
) -> Optional[dict]:
    """Append one finished job to the history. Returns the entry, or None.

    kind: "pipeline" (a manual run) or "autocompress" (one batch pass).
    status: "completed" | "stopped" | "error".
    counts: small dict of what happened (frames/segments or files/skipped).
    bytes_in / bytes_out: source vs output sizes when known (0 = unknown).
    """
    try:
        now = time.time()
        entry = {
            "kind": str(kind),
            "label": str(label or ""),
            "started_at": float(started_at) if started_at else None,
            "ended_at": float(ended_at) if ended_at else now,
            "elapsed_s": (round(float(ended_at or now) - float(started_at), 1)
                          if started_at else None),
            "status": str(status or "completed"),
            "counts": dict(counts) if isinstance(counts, dict) else {},
            "bytes_in": int(bytes_in or 0),
            "bytes_out": int(bytes_out or 0),
            "error": str(error) if error else None,
        }
        with _jobs_lock:
            jobs = _load()
            jobs.insert(0, entry)
            del jobs[_MAX_JOBS:]
            f = _jobs_file()
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
        return entry
    except Exception:  # noqa: BLE001 - history must never break a run
        return None


def recent_jobs(limit: int = 20) -> List[dict]:
    """Return the newest ``limit`` job entries (newest first). Never raises."""
    try:
        limit = max(1, min(int(limit), _MAX_JOBS))
    except (TypeError, ValueError):
        limit = 20
    with _jobs_lock:
        return _load()[:limit]
