"""
src/utils/zones_config.py - per-camera zones and behavior-event config
(R5 TASKS 5.6 + 5.7).

One JSON file in the app-data dir holds, per camera id:

    {
      "exclude": [[x1,y1,x2,y2], ...],       # ignore motion here (5.6)
      "lines":   [{"id": "gate", "line": [x1,y1,x2,y2]}, ...],   # 5.7
      "zones":   [{"id": "door", "rect": [x1,y1,x2,y2]}, ...],   # loiter 5.7
      "loiter_s": 30.0,
      "class_filter": ["person"]             # empty = all classes
    }

All geometry is NORMALIZED (0..1 of frame size) so a config survives
resolution changes. Exclude zones serve BOTH goals from the R5 spec: they
cut false events AND shrink files, because a region dropped here never
reaches the ROI encoder as foreground.

Lives in utils (not gui/services) because the PIPELINE reads it per run and
the core must not import the GUI layer.

Author: Bloodawn (KheivenD), 2026-08-17 (R5 TASKS 5.6/5.7).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

try:
    from utils.paths import state_file
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils.paths import state_file

_FILE_NAME = "zones_config.json"
_lock = threading.Lock()


def _config_path(path_override: Optional[Path] = None) -> Path:
    return Path(path_override) if path_override else state_file(_FILE_NAME)


def _load_all(path_override: Optional[Path] = None) -> dict:
    p = _config_path(path_override)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_camera_config(camera_id: str, path_override: Optional[Path] = None) -> dict:
    """The stored config for one camera, with every key defaulted."""
    cfg = _load_all(path_override).get(str(camera_id), {})
    return {
        "exclude": list(cfg.get("exclude", [])),
        "lines": list(cfg.get("lines", [])),
        "zones": list(cfg.get("zones", [])),
        "loiter_s": float(cfg.get("loiter_s", 30.0)),
        "class_filter": list(cfg.get("class_filter", [])),
    }


def save_camera_config(camera_id: str, cfg: dict,
                       path_override: Optional[Path] = None) -> dict:
    """Validate + persist one camera's config. Returns the stored shape.

    Geometry values are clamped into 0..1; junk entries are dropped rather
    than stored, so the pipeline never has to defend against them again.
    """
    def _clamp(v):
        try:
            return min(1.0, max(0.0, float(v)))
        except (TypeError, ValueError):
            return None

    def _quad(vals):
        if not isinstance(vals, (list, tuple)) or len(vals) != 4:
            return None
        out = [_clamp(v) for v in vals]
        return None if None in out else out

    clean = {"exclude": [], "lines": [], "zones": [],
             "loiter_s": 30.0, "class_filter": []}
    for rect in cfg.get("exclude", []) or []:
        q = _quad(rect)
        if q:
            clean["exclude"].append(q)
    for ln in cfg.get("lines", []) or []:
        if isinstance(ln, dict):
            q = _quad(ln.get("line"))
            if q and str(ln.get("id", "")).strip():
                clean["lines"].append({"id": str(ln["id"]).strip(), "line": q})
    for zn in cfg.get("zones", []) or []:
        if isinstance(zn, dict):
            q = _quad(zn.get("rect"))
            if q and str(zn.get("id", "")).strip():
                clean["zones"].append({"id": str(zn["id"]).strip(), "rect": q})
    try:
        clean["loiter_s"] = min(3600.0, max(1.0, float(cfg.get("loiter_s", 30.0))))
    except (TypeError, ValueError):
        clean["loiter_s"] = 30.0
    clean["class_filter"] = [str(c).strip().lower()
                             for c in (cfg.get("class_filter") or [])
                             if str(c).strip()][:20]

    with _lock:
        data = _load_all(path_override)
        data[str(camera_id)] = clean
        p = _config_path(path_override)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return clean


def filter_regions(regions, exclude_rects, frame_w: int, frame_h: int):
    """Drop regions whose CENTER lies inside any normalized exclude rect.

    ``regions`` carry pixel-space .x/.y/.w/.h (the pipeline's Region shape).
    A region dropped here never becomes foreground: no event, no ROI bits,
    which is the 5.6 double win (fewer false alerts AND smaller files).
    """
    if not exclude_rects or frame_w <= 0 or frame_h <= 0:
        return list(regions)
    kept = []
    for r in regions:
        cx = (r.x + r.w / 2.0) / float(frame_w)
        cy = (r.y + r.h / 2.0) / float(frame_h)
        excluded = False
        for rect in exclude_rects:
            x1, y1, x2, y2 = rect
            if min(x1, x2) <= cx <= max(x1, x2) and min(y1, y2) <= cy <= max(y1, y2):
                excluded = True
                break
        if not excluded:
            kept.append(r)
    return kept
