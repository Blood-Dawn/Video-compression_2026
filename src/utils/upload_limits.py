"""
src/utils/upload_limits.py - the per-file size cap for dashboard uploads.

Both upload routes (the one-shot /api/upload and the chunked /api/upload/begin)
refuse files larger than this cap, so one request cannot fill the disk. The
default is 8 GB, matching the cap the chunked route always had. The operator
can raise or lower it from the Settings panel; the value is stored in a small
JSON state file next to the other per-install settings.

Never raises on read: a missing or damaged file means "use the default".
"""

from __future__ import annotations

import json
import os
import threading

try:
    from utils import paths as _paths
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils import paths as _paths

DEFAULT_GB = 8.0
MIN_GB = 0.1
MAX_GB = 1024.0  # 1 TB: a sanity ceiling so a typo cannot disable the cap
CONFIG_FILENAME = "upload_limits.json"
_GB = 1024 * 1024 * 1024

_lock = threading.Lock()


def config_path():
    return _paths.state_file(CONFIG_FILENAME)


def _coerce_gb(value) -> float | None:
    """A float within [MIN_GB, MAX_GB], or None when value is not acceptable."""
    if isinstance(value, bool):
        return None
    try:
        gb = float(value)
    except (TypeError, ValueError):
        return None
    if gb != gb or gb < MIN_GB or gb > MAX_GB:  # NaN fails the first test
        return None
    return gb


def max_upload_gb() -> float:
    """The configured cap in GB, or DEFAULT_GB when unset or unreadable."""
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
        gb = _coerce_gb(data.get("max_upload_gb")) if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 - an unreadable file means "default"
        gb = None
    return DEFAULT_GB if gb is None else gb


def max_upload_bytes() -> int:
    return int(max_upload_gb() * _GB)


def public_config() -> dict:
    gb = max_upload_gb()
    return {
        "max_upload_gb": gb,
        "max_upload_bytes": int(gb * _GB),
        "default_gb": DEFAULT_GB,
        "min_gb": MIN_GB,
        "max_gb": MAX_GB,
    }


def save_max_upload_gb(value) -> "tuple[bool, str, dict]":
    """Validate and persist a new cap. Returns (ok, error, public_config)."""
    gb = _coerce_gb(value)
    if gb is None:
        return (False, f"max_upload_gb must be a number from {MIN_GB:g} to {MAX_GB:g}",
                public_config())
    path = config_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _lock:
        try:
            tmp.write_text(json.dumps({"max_upload_gb": gb}), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            return False, f"could not save: {exc}", public_config()
    return True, "", public_config()


def describe(gb: float) -> str:
    """'8 GB', '0.5 GB', '1.5 GB' without a trailing .0."""
    return f"{gb:g} GB"
