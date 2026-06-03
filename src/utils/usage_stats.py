"""
src/utils/usage_stats.py

Opt-in anonymous usage statistics (M5 TASK 5.2).

A SEPARATE channel from crash reporting (utils.crash_reporting). It records a
tiny amount of product-shaping signal - which presets and codecs people use,
whether encodes succeed, the *category* of errors, and which camera-ingestion
path is in use (RTSP/ONVIF vs watch-folder vs bridge) - and nothing else.

Hard privacy guarantees, enforced in code (not just by policy):
  * **Default OFF.** Consent is unknown on first run; nothing is collected or
    sent until the user explicitly opts in. An env kill-switch
    (SVCS_DISABLE_USAGE_STATS) forces off even if consent was given.
  * **No footage, file contents, paths, or filenames.** Every event passes
    through a per-event field whitelist, and any value that looks like a path,
    URL, email, or IP is dropped - so even a mislabelled field can't leak one.
  * **No PII and no reinstall-surviving identifiers.** No machine ID, no user
    name, no UUID. Categorical fields are coerced to a fixed vocabulary or
    "other".
  * **No SaaS by default.** With consent given, events append to a local JSONL
    file; they are only POSTed anywhere if the operator sets an explicit
    endpoint (SVCS_USAGE_STATS_URL). The casual install never phones home.

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 5.2 - opt-in usage stats).
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Callable, Dict, Optional, Set

_log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
ENV_OPT_OUT = "SVCS_DISABLE_USAGE_STATS"   # hard kill-switch (forces off)
ENV_URL = "SVCS_USAGE_STATS_URL"           # optional sink; unset => local only
_CONSENT_FILE = "usage_consent.json"
_EVENTS_FILE = "usage_events.jsonl"

# Per-event whitelist: ONLY these fields may ever appear in a payload.
_ALLOWED_FIELDS: Dict[str, Set[str]] = {
    "encode": {"preset", "mode", "codec", "success",
               "error_category", "ingestion_path"},
    "session": {"event"},
}

# Categorical vocabularies. A value outside its set is coerced to "other"
# (or "unknown"), so a stray free-text value can't ride along.
_VOCAB: Dict[str, Set[str]] = {
    "mode": {"mode0", "mode1", "mode2", "mode3"},
    "codec": {"auto", "libx264", "libsvtav1", "libaom-av1"},
    "ingestion_path": {"rtsp", "onvif", "watchfolder", "bridge",
                       "upload", "file", "demo", "unknown"},
    "error_category": {"none", "decode", "encode", "io",
                       "detection", "timeout", "unknown"},
    "event": {"app_start", "app_stop"},
}

# Looks-like-PII guard: path separators, Windows drive, URL scheme, email, IPv4.
_PII_RE = re.compile(
    r"""(
        [/\\]                 # any path separator
      | ^[A-Za-z]:            # windows drive letter
      | ://                   # url scheme
      | @                     # email-ish
      | \b\d{1,3}(\.\d{1,3}){3}\b   # ipv4
    )""",
    re.VERBOSE,
)

# Overridable sink (tests set this); None => _default_emit.
_SINK: Optional[Callable[[dict], None]] = None


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _consent_path(path: Optional[Path] = None) -> Path:
    if path is not None:
        return Path(path)
    try:
        from utils.paths import state_file
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.utils.paths import state_file
    return state_file(_CONSENT_FILE)


def read_consent(path: Optional[Path] = None) -> Optional[bool]:
    """Return the stored consent: True/False, or None if never answered."""
    p = _consent_path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        val = data.get("consent")
        return bool(val) if isinstance(val, bool) else None
    except (OSError, ValueError):
        return None


def set_consent(value: bool, path: Optional[Path] = None) -> None:
    """Persist the user's consent decision (first-run screen / settings toggle)."""
    p = _consent_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"consent": bool(value), "schema": SCHEMA_VERSION}),
                 encoding="utf-8")


def is_enabled(path: Optional[Path] = None) -> bool:
    """True only if the user opted in AND the env kill-switch isn't set."""
    if _truthy(ENV_OPT_OUT):
        return False
    return read_consent(path) is True


def _looks_like_pii(value: str) -> bool:
    return bool(_PII_RE.search(value))


def _coerce(field: str, value):
    """Coerce one field to a safe, allowed value (or drop it by returning _DROP)."""
    if field == "success":
        return bool(value)
    if field in _VOCAB:
        v = str(value).strip().lower()
        if v in _VOCAB[field]:
            return v
        return "unknown" if "unknown" in _VOCAB[field] else "other"
    if field == "preset":
        # Validate against the real preset registry; anything else -> "other".
        try:
            from pipeline.presets import PRESETS
        except ModuleNotFoundError:  # pragma: no cover - import path shim
            from src.pipeline.presets import PRESETS
        v = str(value).strip()
        return v if v in PRESETS else "other"
    # Any other string: keep only if it doesn't look like PII/a path.
    if isinstance(value, str):
        return value if not _looks_like_pii(value) else None
    return None


_DROP = object()


def sanitize_event(event_type: str, fields: dict) -> dict:
    """Build the exact payload that may be transmitted for an event.

    Drops unknown event types' free fields to the whitelist, coerces
    categoricals, scrubs anything path/PII-shaped, and stamps the schema. The
    output is the ONLY thing that ever leaves the process.
    """
    allowed = _ALLOWED_FIELDS.get(event_type, set())
    out = {"schema": SCHEMA_VERSION, "event_type": event_type}
    for key in allowed:
        if key not in fields or fields[key] is None:
            continue
        coerced = _coerce(key, fields[key])
        if coerced is None:        # dropped as PII/unusable
            continue
        out[key] = coerced
    return out


def _default_emit(payload: dict) -> None:
    """Append the event locally; POST only if an explicit endpoint is set."""
    try:
        from utils.paths import state_file
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.utils.paths import state_file
    try:
        with state_file(_EVENTS_FILE).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except OSError as exc:  # pragma: no cover - disk issues must not crash
        _log.debug("usage_stats: local write failed: %s", exc)

    url = os.environ.get(ENV_URL, "").strip()
    if not url:
        return
    try:  # pragma: no cover - network, opt-in endpoint only
        import urllib.request
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        urllib.request.urlopen(req, timeout=3).close()
    except Exception as exc:  # noqa: BLE001 - telemetry must never raise
        _log.debug("usage_stats: post failed: %s", exc)


def record_event(event_type: str, path: Optional[Path] = None, **fields) -> Optional[dict]:
    """Record an event IF the user opted in; otherwise a strict no-op.

    Returns the sanitized payload that was emitted, or None if usage stats are
    disabled (nothing is built, written, or sent). Never raises.
    """
    if not is_enabled(path):
        return None
    try:
        payload = sanitize_event(event_type, fields)
        (_SINK or _default_emit)(payload)
        return payload
    except Exception as exc:  # noqa: BLE001 - telemetry must never crash a caller
        _log.debug("usage_stats: record failed: %s", exc)
        return None
