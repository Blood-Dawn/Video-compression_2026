"""
src/gui/services/security_alerts.py

Security cam alerts that say what was seen.

When a clip from a paired phone finishes compressing, this looks at what the
detector recorded for it and, if there is something worth knowing, writes one
alert ("Person detected", "Vehicle detected", "Motion detected") and sends it
as a push through the existing ntfy setup. The alert keeps the output path, so
the Security cam tab can show a snapshot of the clip next to it.

Rules, kept simple on purpose:
  * a person or vehicle label gives that alert, with the labels as tags;
  * no label but a motion-keeping mode (1, 2 or 3) produced output: "Motion detected";
  * mode 0 records everything, so with no label there is nothing to say.

State file ``security_alerts.json``: a list of
  {"when": epoch seconds, "name": source file name, "output": path,
   "labels": ["person", ...], "title": "Person detected"}
newest first, capped at 50.

Author: Bloodawn (KheivenD), 2026-11-25.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from urllib.parse import quote

ALERTS_FILE = "security_alerts.json"
MAX_ALERTS = 50
_lock = threading.Lock()

_PUSH_TAGS = {"person": "bust_in_silhouette", "vehicle": "car"}


def title_for(labels: list, mode: str) -> str | None:
    """The alert headline, or None when there is nothing to report."""
    has_p, has_v = "person" in labels, "vehicle" in labels
    if has_p and has_v:
        return "Person and vehicle detected"
    if has_p:
        return "Person detected"
    if has_v:
        return "Vehicle detected"
    if labels:
        return labels[0].capitalize() + " detected"
    if mode in ("mode1", "mode2", "mode3"):
        return "Motion detected"
    return None


def _file():
    try:
        from utils.paths import state_file
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.utils.paths import state_file
    return state_file(ALERTS_FILE)


def _load() -> list:
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def recent_alerts(limit: int = 10) -> list:
    """Newest alerts first, with a thumbnail URL when the clip still exists."""
    out = []
    for a in _load()[:limit]:
        row = {"when": a.get("when"), "name": a.get("name", ""),
               "title": a.get("title", ""), "labels": list(a.get("labels") or [])}
        output = a.get("output") or ""
        if output and Path(output).is_file():
            row["thumb"] = "/api/library/thumb?path=" + quote(output, safe="")
        out.append(row)
    return out


def _labels_for(output: str) -> list:
    try:
        from gui.services import library_labels
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.gui.services import library_labels
    try:
        return list(library_labels.attach([{"path": output}])[0]["labels"])
    except Exception:  # noqa: BLE001 - alerts must never break a compress
        return []


def make_alert(record: dict, labels: list) -> dict | None:
    """Pure: the alert dict for one finished clip, or None."""
    title = title_for(labels, str(record.get("mode") or ""))
    if not title:
        return None
    return {
        "when": float(record.get("when") or time.time()),
        "name": Path(str(record.get("source") or "")).name,
        "output": str(record.get("output") or ""),
        "labels": list(labels),
        "title": title,
    }


def record_alert(alert: dict, push: bool = True) -> None:
    with _lock:
        alerts = _load()
        alerts.insert(0, alert)
        try:
            _file().write_text(json.dumps(alerts[:MAX_ALERTS]), encoding="utf-8")
        except OSError:
            pass
    if push:
        try:
            try:
                from utils import push_notify
            except ModuleNotFoundError:  # pragma: no cover - import path shim
                from src.utils import push_notify
            tags = ",".join(_PUSH_TAGS[t] for t in alert["labels"] if t in _PUSH_TAGS) or "movie_camera"
            push_notify.publish("Security cam: " + alert["title"], alert["name"], tags=tags)
        except Exception:  # noqa: BLE001 - a push failure is not a compress failure
            pass


def maybe_alert(record: dict, phone_folder: Path | None) -> dict | None:
    """Called after a clip is compressed. Alerts only for clips from the phone folder."""
    try:
        if phone_folder is None:
            return None
        src_parent = Path(str(record.get("source") or "")).resolve().parent
        if src_parent != Path(phone_folder).resolve():
            return None
        alert = make_alert(record, _labels_for(str(record.get("output") or "")))
        if alert:
            record_alert(alert)
        return alert
    except Exception:  # noqa: BLE001
        return None
