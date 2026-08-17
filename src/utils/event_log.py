"""
src/utils/event_log.py - behavior-event persistence (R5 TASK 5.7).

Events append to <output_dir>/events.jsonl so they travel WITH the footage
they describe, exactly like metadata.db does. One JSON object per line:

    {"kind": "line_crossing", "camera_id": "cam_00", "t": 12.5,
     "wall_time": "...", "track_id": 3, "label": "person",
     "geometry_id": "gate", "direction": "right"}

Best-effort by design: recording an event must never fail the encode that
observed it. No PII beyond the class label is ever written (no crops, no
plate text), honoring the security round's rules.

Author: Bloodawn (KheivenD), 2026-08-17 (R5 TASK 5.7).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

EVENTS_FILENAME = "events.jsonl"
_lock = threading.Lock()


def append_events(output_dir, events: list, camera_id: str = "") -> int:
    """Append events (list of dicts) for one camera. Returns count written."""
    if not events:
        return 0
    path = Path(output_dir) / EVENTS_FILENAME
    written = 0
    try:
        with _lock, open(path, "a", encoding="utf-8", newline="\n") as fh:
            for ev in events:
                rec = dict(ev)
                rec.setdefault("camera_id", camera_id)
                rec.setdefault(
                    "wall_time",
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                )
                fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
                written += 1
    except OSError:
        return written
    return written


def read_recent(output_dir, limit: int = 100) -> list:
    """Newest-first tail of the events file. Missing file = empty list."""
    path = Path(output_dir) / EVENTS_FILENAME
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(out) >= max(1, int(limit)):
            break
    return out
