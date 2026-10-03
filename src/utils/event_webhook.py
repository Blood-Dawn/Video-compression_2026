"""
src/utils/event_webhook.py - machine-readable event webhook (planner 4.9, D4).

The ntfy push in push_notify.py tells a HUMAN that something happened. This
module tells another SYSTEM (a VMS, Home Assistant, Node-RED, a SIEM): when
behavior events are recorded, it POSTs them as JSON to a URL the operator
configured. Spec: docs/plans/WEBHOOK-EMITTER-SPEC.md.

Rules this module keeps:

* OFF by default. A stock install never opens this socket.
* Same SSRF guard as push. The URL goes through
  push_notify.check_outbound_url, so there is one list of refused
  cloud-metadata hosts and addresses, not two that drift apart. Loopback and
  RFC1918 stay allowed because a self-hosted receiver lives there. Unlike an
  ntfy topic, a webhook URL does not need a path.
* Re-validated at send time, redirects never followed.
* Field allowlist. Each event is rebuilt from EVENT_FIELDS only, so plate
  text, crops, file paths, or stream URLs a future detector attaches never
  leave the machine. This protects OUTBOUND delivery only; events.jsonl is a
  separate concern (see docs/plans/BLOCKERS.md).
* Optional HMAC-SHA256 signature over "<timestamp>.<body>" so a receiver can
  prove a delivery came from this install, unaltered, and reject replays.
  The secret is write-only: no API ever echoes it.
* Fire and forget. One daemon worker behind a bounded queue, a two second
  socket timeout, no retries. The events are already durable on disk, and a
  notifier must never be able to slow or fail the encode that raised them.

Config lives in its own 0o600 state file, never in gui_state.json, because it
may hold the signing secret.

Author: Victor De Souza Teixeira, 2026-10-03 (planner 4.9).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import queue
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    from utils import paths as _paths
    from utils import push_notify as _push
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils import paths as _paths
    from src.utils import push_notify as _push

log = logging.getLogger(__name__)

CONFIG_FILENAME = "webhook_config.json"
SCHEMA_VERSION = 1

_MAX_QUEUE = 64
_MAX_EVENTS_PER_POST = 20
_MAX_BODY_BYTES = 64 * 1024
_POST_TIMEOUT_S = 2.0

# The only keys an event may carry off the machine. Mirrors the fields
# event_log.py documents for events.jsonl.
EVENT_FIELDS = (
    "kind", "camera_id", "t", "wall_time", "track_id", "label",
    "geometry_id", "direction", "dwell_s",
)

DEFAULT_CONFIG = {
    "enabled": False,
    "url": "",
    "secret": "",
}


# ── config ───────────────────────────────────────────────────────────────────


def config_path() -> Path:
    """Resolved lazily so the test suite can point it at a temp directory."""
    return _paths.state_file(CONFIG_FILENAME)


def load_config() -> dict:
    """The stored webhook config merged over the defaults. Never raises."""
    cfg = dict(DEFAULT_CONFIG)
    try:
        path = config_path()
        if not path.exists():
            return cfg
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return cfg
    except Exception:  # noqa: BLE001 - an unreadable config means "off"
        return cfg
    cfg["enabled"] = bool(data.get("enabled", False))
    cfg["url"] = str(data.get("url", "") or "").strip()
    cfg["secret"] = str(data.get("secret", "") or "").strip()
    return cfg


def public_config(cfg: dict = None) -> dict:
    """The config as an API may echo it: the secret becomes a boolean."""
    cfg = dict(cfg if cfg is not None else load_config())
    secret = cfg.pop("secret", "")
    cfg["has_secret"] = bool(secret)
    return cfg


def save_config(data: dict) -> "tuple[bool, str, dict]":
    """Validate and persist a config. Returns (ok, error, public_config).

    A URL is only required when turning the webhook ON. Omitting the
    ``secret`` key keeps the stored one; ``"secret": ""`` clears it.
    """
    if not isinstance(data, dict):
        return False, "Request body must be a JSON object", public_config()
    current = load_config()
    enabled = bool(data.get("enabled", current["enabled"]))
    url = str(data.get("url", current["url"]) or "").strip()
    if "secret" in data:
        secret = str(data.get("secret") or "").strip()
    else:
        secret = current["secret"]

    if url:
        ok, why = is_safe_webhook_url(url)
        if not ok:
            return False, why, public_config(current)
    elif enabled:
        return False, "a webhook URL is required to turn the webhook on", public_config(current)

    cfg = {"enabled": enabled, "url": url, "secret": secret}
    try:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(cfg)
        payload["saved_at"] = time.time()
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(path, 0o600)   # may be a no-op on Windows; best effort
        except OSError:
            pass
    except OSError as exc:
        return False, f"could not save webhook config: {exc}", public_config(current)
    return True, "", public_config(cfg)


# ── URL safety ───────────────────────────────────────────────────────────────


def is_safe_webhook_url(url) -> "tuple[bool, str]":
    """The push SSRF guard, minus the "topic path required" rule."""
    return _push.check_outbound_url(url, require_path=False, label="webhook",
                                    credential_field="secret field")


# ── payload ──────────────────────────────────────────────────────────────────


def _clean_event(ev: dict, camera_id: str) -> dict:
    """Rebuild one event from the allowlist only."""
    out = {k: ev[k] for k in EVENT_FIELDS if k in ev}
    if not out.get("camera_id") and camera_id:
        out["camera_id"] = camera_id
    return out


def build_payload(events: list, camera_id: str = "") -> "bytes | None":
    """The JSON body for one delivery, or None when there is nothing to send.

    At most _MAX_EVENTS_PER_POST events go out; the rest are counted in
    ``dropped`` (they are still in events.jsonl). A body over the cap is
    refused whole rather than truncated into invalid JSON.
    """
    clean = [_clean_event(ev, camera_id) for ev in (events or [])
             if isinstance(ev, dict)]
    if not clean:
        return None
    sent = clean[:_MAX_EVENTS_PER_POST]
    body = json.dumps({
        "source": "svcs",
        "schema": SCHEMA_VERSION,
        "sent_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "camera_id": camera_id,
        "events": sent,
        "dropped": len(clean) - len(sent),
    }, separators=(",", ":"), default=str).encode("utf-8")
    if len(body) > _MAX_BODY_BYTES:
        log.warning("Webhook body over %d bytes, not sent", _MAX_BODY_BYTES)
        return None
    return body


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """``sha256=<hex>`` of HMAC-SHA256(secret, timestamp + "." + body)."""
    mac = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body,
                   hashlib.sha256)
    return "sha256=" + mac.hexdigest()


# ── posting ──────────────────────────────────────────────────────────────────


def _post(cfg: dict, body: bytes, timeout: float = _POST_TIMEOUT_S) -> "tuple[bool, str]":
    """One synchronous POST. Returns (ok, detail). Never echoes the response body."""
    url = cfg.get("url", "")
    ok, why = is_safe_webhook_url(url)
    if not ok:
        return False, why
    timestamp = str(int(time.time()))
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "SVCS-Webhook")
    req.add_header("X-SVCS-Delivery", str(uuid.uuid4()))
    req.add_header("X-SVCS-Timestamp", timestamp)
    secret = cfg.get("secret") or ""
    if secret:
        req.add_header("X-SVCS-Signature", sign(secret, timestamp, body))
    opener = urllib.request.build_opener(_push._NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
        return (200 <= int(code) < 300), f"HTTP {code}"
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            return False, f"HTTP {exc.code} redirect refused"
        return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, f"could not reach the webhook: {exc}"


# ── the fire-and-forget worker ───────────────────────────────────────────────

_queue: "queue.Queue" = queue.Queue(maxsize=_MAX_QUEUE)
_worker_lock = threading.Lock()
_worker_started = False
_inflight_lock = threading.Lock()
_inflight = 0


def _adjust_inflight(delta: int) -> None:
    global _inflight
    with _inflight_lock:
        _inflight += delta


def _worker_loop() -> None:
    while True:
        cfg, body = _queue.get()
        try:
            ok, detail = _post(cfg, body)
            if not ok:
                log.warning("Webhook not delivered: %s", detail)
        except Exception as exc:  # noqa: BLE001 - a delivery must never die loudly
            log.warning("Webhook worker error: %s", exc)
        finally:
            _adjust_inflight(-1)
            _queue.task_done()


def _ensure_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        threading.Thread(target=_worker_loop, name="svcs-webhook",
                         daemon=True).start()
        _worker_started = True


def flush(timeout: float = 3.0) -> bool:
    """Wait for queued deliveries to finish. Test helper; True if drained."""
    deadline = time.time() + max(0.0, float(timeout))
    while time.time() < deadline:
        with _inflight_lock:
            if _inflight == 0 and _queue.empty():
                return True
        time.sleep(0.01)
    with _inflight_lock:
        return _inflight == 0 and _queue.empty()


def emit_events(events: list, camera_id: str = "") -> bool:
    """Queue one delivery for a batch of events. Returns True if queued.

    Best effort in every direction: disabled, unconfigured, nothing to send,
    or a full queue all return False quietly. The caller is the encode loop.
    """
    if not events:
        return False
    try:
        cfg = load_config()
        if not cfg.get("enabled") or not cfg.get("url"):
            return False
        body = build_payload(events, camera_id)
        if body is None:
            return False
        _ensure_worker()
        _adjust_inflight(1)
        try:
            _queue.put_nowait((dict(cfg), body))
            return True
        except queue.Full:
            _adjust_inflight(-1)
            log.warning("Webhook queue full, delivery dropped")
            return False
    except Exception as exc:  # noqa: BLE001
        log.debug("Webhook emit skipped: %s", exc)
        return False


def send_test(url: str = None, secret: str = None) -> "tuple[bool, str]":
    """Deliver one synthetic event synchronously so a UI can report the truth.

    Accepts an UNSAVED url so an operator can prove it works before saving.
    Only a status line comes back, never the receiver's body, so this cannot
    be used to read pages on the operator's network.
    """
    cfg = load_config()
    if url is not None:
        cfg = dict(cfg)
        cfg["url"] = str(url or "").strip()
        if secret is not None:
            cfg["secret"] = str(secret or "").strip()
    if not cfg.get("url"):
        return False, "no webhook URL is configured"
    body = build_payload([{"kind": "test", "label": "test"}], camera_id="svcs-test")
    return _post(cfg, body)
