"""
src/utils/camera_frame_cache.py - per-camera "last seen" still frame cache
(Week 3 TASK 3.7).

The zone editor needs something to draw zones/lines over, but SVCS has no
persistent camera registry, a camera only really exists while a pipeline
run is actively reading it. So this module is deliberately just a cache:
a live run throttles a JPEG write here as it goes (see pipeline.py's main
loop), and GET /api/zones/frame (events_bp.py) serves whatever is newest,
falling back to a black placeholder when nothing has ever been captured
for that camera_id yet. Losing this directory loses nothing durable, the
next run repopulates it.

camera_id is expected to already be validated by the caller (events_bp.py's
_CAM_RE / pipeline.py's _sanitize_camera_id both restrict it to
[a-zA-Z0-9_-]{1,64}), but this module re-checks before touching the
filesystem so it is safe to call from anywhere.

Author: Bloodawn (KheivenD), Week 3 (3.7).
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Optional

try:
    from utils.paths import camera_frames_dir
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils.paths import camera_frames_dir

log = logging.getLogger(__name__)

_CAM_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")

# A live run writes at most this often per camera; the zone editor only
# needs "recent enough to line up zones", not every frame.
DEFAULT_WRITE_INTERVAL_S = 2.0

PLACEHOLDER_WIDTH = 640
PLACEHOLDER_HEIGHT = 360


def _safe_id(camera_id: str) -> Optional[str]:
    camera_id = str(camera_id or "")
    return camera_id if _CAM_RE.match(camera_id) else None


def frame_cache_path(camera_id: str) -> Optional[Path]:
    """The on-disk path for one camera's cached still, or None if the id is unsafe."""
    safe = _safe_id(camera_id)
    if safe is None:
        return None
    return camera_frames_dir() / f"{safe}.jpg"


class ThrottledFrameWriter:
    """Per-run helper: call maybe_save() every frame, it decides when to act.

    One instance per pipeline run (one camera_id), so the "last written at"
    clock is per run rather than global, matching how the rest of the
    per-run state in pipeline.py works.
    """

    def __init__(self, camera_id: str, interval_s: float = DEFAULT_WRITE_INTERVAL_S):
        self.camera_id = camera_id
        self.interval_s = max(0.5, float(interval_s))
        self._last_write = 0.0

    def maybe_save(self, frame) -> bool:
        """Save ``frame`` (BGR ndarray) if the interval has elapsed. Best effort."""
        now = time.time()
        if now - self._last_write < self.interval_s:
            return False
        self._last_write = now
        return save_frame(self.camera_id, frame)


def save_frame(camera_id: str, frame) -> bool:
    """Encode and write one BGR frame as this camera's cached still.

    Best effort by design, same contract as event_log.append_events: a
    thumbnail cache miss must never be able to interrupt an encode.
    """
    path = frame_cache_path(camera_id)
    if path is None:
        return False
    try:
        import cv2  # local import: keeps this module importable without cv2
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            return False
        tmp = path.with_suffix(".jpg.tmp")
        tmp.write_bytes(buf.tobytes())
        tmp.replace(path)  # atomic on both POSIX and Windows
        return True
    except Exception as exc:  # noqa: BLE001 - never break a run over a thumbnail
        log.debug("Camera frame cache write skipped for %s: %s", camera_id, exc)
        return False


def load_frame_bytes(camera_id: str) -> Optional[bytes]:
    """The cached JPEG bytes for one camera, or None if nothing is cached yet."""
    path = frame_cache_path(camera_id)
    if path is None or not path.exists():
        return None
    try:
        data = path.read_bytes()
        return data if data else None
    except OSError:
        return None


def placeholder_jpeg_bytes() -> bytes:
    """A solid black JPEG the same shape UIs can expect, for "nothing yet"."""
    import cv2
    import numpy as np
    frame = np.zeros((PLACEHOLDER_HEIGHT, PLACEHOLDER_WIDTH, 3), dtype="uint8")
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
    if not ok:  # pragma: no cover - imencode does not fail on a plain array
        raise RuntimeError("could not encode placeholder frame")
    return buf.tobytes()
