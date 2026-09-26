"""
src/utils/event_webhook.py - generic outbound webhook for jobs and events
(Week 3 TASK 3.9).

push_notify.py posts to a self-hosted ntfy topic for phone alerts. This
module is the more general sibling: a plain JSON POST to whatever URL the
operator points it at (their own server, a Discord/Slack incoming webhook,
a SIEM ingest endpoint, anything that accepts a POST). It deliberately
REUSES push_notify.is_safe_push_url rather than re-deriving the same SSRF
judgement calls twice: loopback and RFC1918 are legitimate (a self-hosted
receiver is the common case), the cloud-metadata surface is refused, and a
non-http(s) scheme, embedded credentials, or an unresolvable/refused host
are all refused up front, matching push_notify exactly.

Rules this module keeps, same shape as push_notify.py's:

* OFF by default. An empty URL makes every publish call a no-op.
* No third-party default. The operator supplies their own URL.
* Never blocks a run. One daemon worker behind a bounded queue; a full
  queue drops the message rather than slowing the encode that raised it.
* No secrets in the payload beyond what events.jsonl / job_history already
  hold (event kind, camera id, class label, job stats). No plate text, no
  file paths, no stream credentials.
* Optional HMAC-SHA256 signing. When a secret is configured, the raw JSON
  body is signed and sent as the ``X-SVCS-Signature`` header
  (``sha256=<hex>``), the same convention GitHub/Stripe-style webhooks use,
  so a receiver can verify the POST actually came from this SVCS instance
  and was not forged or replayed with different content. The secret itself
  is never sent, only the signature it produces.

Config lives in its own state file for the same reason push_notify's does:
it may hold a signing secret, and gui_state.json's contract is "paths, no
secrets".

Author: Bloodawn (KheivenD), Week 3 (3.9).
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
from pathlib import Path

try:
    from utils import paths as _paths
    from utils.push_notify import is_safe_push_url, pin_resolution, validate_push_url
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils import paths as _paths
    from src.utils.push_notify import is_safe_push_url, pin_resolution, validate_push_url

log = logging.getLogger(__name__)

CONFIG_FILENAME = "webhook_config.json"

_MAX_QUEUE = 64
_MAX_PER_BATCH = 5
_POST_TIMEOUT_S = 3.0

DEFAULT_CONFIG = {
    "enabled": False,
    "url": "",
    "secret": "",
    "on_jobs": True,
    "on_events": True,
}


# ── config ───────────────────────────────────────────────────────────────────


def config_path() -> Path:
    """Resolved lazily, same reasoning as push_notify.config_path()."""
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
    cfg["on_jobs"] = bool(data.get("on_jobs", True))
    cfg["on_events"] = bool(data.get("on_events", True))
    return cfg


def public_config(cfg: dict = None) -> dict:
    """The config as an API may echo it: the secret becomes a boolean."""
    cfg = dict(cfg if cfg is not None else load_config())
    secret = cfg.pop("secret", "")
    cfg["has_secret"] = bool(secret)
    return cfg


def save_config(data: dict) -> "tuple[bool, str, dict]":
    """Validate and persist a config. Returns (ok, error, public_config).

    Same "omit the key to keep the stored secret" contract as push_notify's
    save_config, for the same reason: the dashboard must be able to re-save
    the other fields without ever having been given the secret back.
    """
    if not isinstance(data, dict):
        return False, "Request body must be a JSON object", public_config()
    current = load_config()
    enabled = bool(data.get("enabled", current["enabled"]))
    url = str(data.get("url", current["url"]) or "").strip()
    on_jobs = bool(data.get("on_jobs", current["on_jobs"]))
    on_events = bool(data.get("on_events", current["on_events"]))
    if "secret" in data:
        secret = str(data.get("secret") or "").strip()
    else:
        secret = current["secret"]

    if url:
        ok, why = is_safe_push_url(url)
        if not ok:
            return False, why, public_config(current)
    elif enabled:
        return False, "a webhook URL is required to turn this on", public_config(current)

    cfg = {"enabled": enabled, "url": url, "secret": secret,
           "on_jobs": on_jobs, "on_events": on_events}
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


# ── signing + posting ─────────────────────────────────────────────────────────


def sign_body(body: bytes, secret: str) -> str:
    """``sha256=<hex>`` HMAC of ``body``, or "" when no secret is configured."""
    if not secret:
        return ""
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A 3xx becomes an error instead of a second, unvalidated request."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _post(cfg: dict, event_type: str, payload: dict,
          timeout: float = _POST_TIMEOUT_S) -> "tuple[bool, str]":
    """One synchronous JSON POST to the configured URL. Returns (ok, detail)."""
    url = cfg.get("url", "")
    # validate_push_url (not is_safe_push_url) so the connection below can be
    # pinned to the exact addresses that were just validated, closing the
    # SEC-017 DNS-rebinding gap (see push_notify.pin_resolution's docstring).
    ok, why, addrs, host = validate_push_url(url)
    if not ok:
        return False, why
    body_obj = {"event": event_type, "sent_at": time.time(), "data": payload}
    body = json.dumps(body_obj, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "SVCS-webhook")
    sig = sign_body(body, cfg.get("secret") or "")
    if sig:
        req.add_header("X-SVCS-Signature", sig)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with pin_resolution(host, addrs):
            with opener.open(req, timeout=timeout) as resp:
                code = getattr(resp, "status", None) or resp.getcode()
        return (200 <= int(code) < 300), f"HTTP {code}"
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            return False, f"HTTP {exc.code} redirect refused"
        return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, f"could not reach the webhook: {exc}"


# ── the fire-and-forget worker (same shape as push_notify's) ─────────────────

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
        item = _queue.get()
        try:
            cfg, event_type, payload = item
            ok, detail = _post(cfg, event_type, payload)
            if not ok:
                log.warning("Webhook not delivered: %s", detail)
        except Exception as exc:  # noqa: BLE001 - a publish must never die loudly
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


def publish(event_type: str, payload: dict, cfg: dict = None) -> bool:
    """Queue one delivery. False when disabled, unconfigured, or queue full."""
    cfg = cfg if cfg is not None else load_config()
    if not cfg.get("enabled") or not cfg.get("url"):
        return False
    _ensure_worker()
    try:
        _adjust_inflight(1)
        _queue.put_nowait((dict(cfg), event_type, payload))
        return True
    except queue.Full:
        _adjust_inflight(-1)
        log.warning("Webhook queue full, dropped: %s", event_type)
        return False


def send_test(url: str = None, secret: str = None) -> "tuple[bool, str]":
    """Post a test payload synchronously so a UI button can report the truth.

    Accepts an UNSAVED url/secret, same reasoning as push_notify.send_test:
    an operator should be able to prove a URL works before committing to it.
    """
    cfg = load_config()
    if url is not None:
        cfg = dict(cfg)
        cfg["url"] = str(url or "").strip()
        if secret is not None:
            cfg["secret"] = str(secret or "").strip()
    if not cfg.get("url"):
        return False, "no webhook URL is configured"
    return _post(cfg, "test", {"message": "Webhook is wired up. This is a test "
                               "delivery from your SVCS server."})


# ── the two publish entry points, mirroring push_notify's shape ─────────────


def publish_events(events: list, camera_id: str = "") -> int:
    """Deliver behavior events. Returns how many deliveries were queued.

    Best effort in every direction, same contract as push_notify.publish_events:
    the caller is the encode loop and must never learn that a delivery failed.
    """
    if not events:
        return 0
    try:
        cfg = load_config()
        if not cfg.get("enabled") or not cfg.get("on_events"):
            return 0
        sent = 0
        for ev in list(events)[:_MAX_PER_BATCH]:
            if not isinstance(ev, dict):
                continue
            payload = dict(ev)
            payload.setdefault("camera_id", camera_id)
            if publish("event", payload, cfg=cfg):
                sent += 1
        return sent
    except Exception as exc:  # noqa: BLE001
        log.debug("Event webhook skipped: %s", exc)
        return 0


def publish_job(entry: dict) -> bool:
    """Deliver one finished job entry. Best effort, never raises."""
    if not isinstance(entry, dict):
        return False
    try:
        cfg = load_config()
        if not cfg.get("enabled") or not cfg.get("on_jobs"):
            return False
        return publish("job", dict(entry), cfg=cfg)
    except Exception as exc:  # noqa: BLE001
        log.debug("Job webhook skipped: %s", exc)
        return False
