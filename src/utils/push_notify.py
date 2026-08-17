"""
src/utils/push_notify.py - closed-app push to a self-hosted ntfy topic
(R6 TRACK C1).

The M5 phone notifications only fire while the app process is alive. This
module closes that gap without handing anything to a third-party push
service: the SERVER posts a short message to an ntfy topic the operator
hosts, and the phone's ntfy client (or any UnifiedPush distributor) wakes up
and shows it even when SVCS itself is fully closed.

Rules this module keeps:

* OFF by default. An empty topic URL makes every publish call a no-op, so a
  stock install never opens a socket it was not asked to open.
* No third-party default. Nothing is baked in; the operator types their own
  URL or no push happens at all.
* SSRF-aware but LAN-friendly. A self-hosted ntfy normally lives on
  127.0.0.1 or a 192.168.x.x box, so the pipeline's input-source guard
  (SEC-013) is exactly backwards here: loopback and RFC1918 are the
  LEGITIMATE targets. What stays refused is the cloud-metadata surface
  (link-local 169.254.0.0/16 and fe80::/10, the Alibaba 100.100.100.100
  literal, the AWS IPv6 IMDS address, the metadata.* hostnames), every
  scheme that is not http or https, and credentials smuggled into the URL.
  Redirects are never followed, so a permitted host cannot bounce the
  request onto a refused one, and hostnames are checked AFTER resolution so
  a friendly name pointing at 169.254.169.254 is refused too.
* Never blocks a run. Publishing happens on one daemon worker behind a
  bounded queue; a full queue drops the message rather than slowing the
  encode that raised it. An ntfy server that is down costs a log line.
* No secrets in the payload. Titles and bodies carry the event kind, camera
  id, and class label only, the same fields events.jsonl already holds.
  Plate text, file paths, and stream credentials never reach it. Header
  values are stripped of control characters so a crafted label cannot
  inject a header.

Config lives in its own state file rather than gui_state.json, because it
may hold an ntfy access token and gui_state.json's contract is "paths, no
secrets". The file is written 0o600 the same way device_tokens.json is.

Author: Bloodawn (KheivenD), 2026-08-17 (R6 TRACK C1).
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import queue
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

try:
    from utils import paths as _paths
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils import paths as _paths

log = logging.getLogger(__name__)

CONFIG_FILENAME = "push_config.json"

# Bounded so an event storm can never grow memory or slow the encode.
_MAX_QUEUE = 64
# Most events a single append_events call may publish before it summarises.
_MAX_PER_BATCH = 5
_POST_TIMEOUT_S = 3.0

DEFAULT_CONFIG = {
    "enabled": False,
    "topic_url": "",
    "token": "",
    "on_jobs": True,
    "on_events": True,
    "priority": "",          # "" = per-message default (events high, jobs normal)
}

_VALID_PRIORITIES = {"", "min", "low", "default", "high", "urgent"}

# Hostnames that only ever mean a cloud instance-metadata endpoint.
_BLOCKED_HOSTS = {
    "metadata", "metadata.google.internal", "metadata.goog",
    "instance-data", "instance-data.ec2.internal",
}

# Literals that sit INSIDE otherwise-allowed ranges and so need naming.
# 100.100.100.100 is Alibaba's metadata service inside CGNAT space;
# fd00:ec2::254 is the AWS IMDS IPv6 address inside unique-local space.
_BLOCKED_IPS = {
    ipaddress.ip_address("100.100.100.100"),
    ipaddress.ip_address("fd00:ec2::254"),
}


# ── config ───────────────────────────────────────────────────────────────────


def config_path() -> Path:
    """Resolved lazily, not at import, so a test can point it somewhere safe.

    The suite patches THIS function rather than utils.paths.state_file: a
    developer with push turned on must not have their own topic notified by
    a test run, and patching the shared paths module would reach further
    than this one file.
    """
    return _paths.state_file(CONFIG_FILENAME)


def load_config() -> dict:
    """The stored push config merged over the defaults. Never raises."""
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
    cfg["topic_url"] = str(data.get("topic_url", "") or "").strip()
    cfg["token"] = str(data.get("token", "") or "").strip()
    cfg["on_jobs"] = bool(data.get("on_jobs", True))
    cfg["on_events"] = bool(data.get("on_events", True))
    prio = str(data.get("priority", "") or "").strip().lower()
    cfg["priority"] = prio if prio in _VALID_PRIORITIES else ""
    return cfg


def public_config(cfg: dict = None) -> dict:
    """The config as an API may echo it: the token becomes a boolean."""
    cfg = dict(cfg if cfg is not None else load_config())
    token = cfg.pop("token", "")
    cfg["has_token"] = bool(token)
    return cfg


def save_config(data: dict) -> "tuple[bool, str, dict]":
    """Validate and persist a config. Returns (ok, error, public_config).

    A topic URL is only required when the feature is being turned ON, so an
    operator can clear the switch without also clearing the URL they typed.
    ``token`` is left untouched when the caller omits the key entirely, which
    is how the dashboard re-saves the other fields without having to hold a
    secret it deliberately never received.
    """
    if not isinstance(data, dict):
        return False, "Request body must be a JSON object", public_config()
    current = load_config()
    enabled = bool(data.get("enabled", current["enabled"]))
    topic_url = str(data.get("topic_url", current["topic_url"]) or "").strip()
    on_jobs = bool(data.get("on_jobs", current["on_jobs"]))
    on_events = bool(data.get("on_events", current["on_events"]))
    prio = str(data.get("priority", current["priority"]) or "").strip().lower()
    if prio not in _VALID_PRIORITIES:
        return False, f"priority must be one of {sorted(_VALID_PRIORITIES - {''})}", public_config(current)
    if "token" in data:
        token = str(data.get("token") or "").strip()
    else:
        token = current["token"]

    if topic_url:
        ok, why = is_safe_push_url(topic_url)
        if not ok:
            return False, why, public_config(current)
    elif enabled:
        return False, "a topic URL is required to turn push on", public_config(current)

    cfg = {"enabled": enabled, "topic_url": topic_url, "token": token,
           "on_jobs": on_jobs, "on_events": on_events, "priority": prio}
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
        return False, f"could not save push config: {exc}", public_config(current)
    return True, "", public_config(cfg)


# ── URL safety ───────────────────────────────────────────────────────────────


def _addresses_for(host: str) -> "tuple[list, str]":
    """Every IP a host resolves to, or ([], reason). Literals skip DNS."""
    try:
        return [ipaddress.ip_address(host)], ""
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return [], "topic host does not resolve"
    out = []
    for info in infos:
        try:
            out.append(ipaddress.ip_address(info[4][0]))
        except (ValueError, IndexError):
            continue
    if not out:
        return [], "topic host does not resolve"
    return out, ""


def _address_refused(ip) -> str:
    """Why this address may not be posted to, or "" if it is fine."""
    if getattr(ip, "ipv4_mapped", None):
        # ::ffff:169.254.169.254 must be judged as the v4 address it wraps.
        ip = ip.ipv4_mapped
    if ip in _BLOCKED_IPS:
        return "blocked cloud-metadata address"
    if ip.is_loopback:
        # Checked BEFORE the reserved test on purpose: Python counts ::1 as
        # reserved (it sits inside ::/8), and a loopback ntfy is the single
        # most common way to run this feature.
        return ""
    if ip.is_link_local:            # 169.254.0.0/16 and fe80::/10
        return "blocked link-local address"
    if ip.is_multicast:
        return "blocked multicast address"
    if ip.is_unspecified:
        return "blocked unspecified address"
    if ip.is_reserved:
        return "blocked reserved address"
    return ""


def is_safe_push_url(url) -> "tuple[bool, str]":
    """Validate an ntfy topic URL. Returns (ok, reason).

    Allows http and https to loopback, RFC1918 / unique-local, and public
    hosts, because a self-hosted ntfy is legitimately any of those. Refuses
    other schemes, URL-embedded credentials, a missing topic path, the
    cloud-metadata hostnames and addresses, and anything whose DNS answer
    lands on a refused address.
    """
    s = str(url or "").strip()
    if not s:
        return False, "empty topic URL"
    if len(s) > 2048:
        return False, "topic URL is too long"
    try:
        parsed = urlparse(s)
    except ValueError:
        return False, "topic URL could not be parsed"
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, f"scheme not allowed: {scheme or 'none'}"
    if parsed.username or parsed.password:
        return False, "credentials in the URL are not allowed, use the token field"
    try:
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False, "topic URL host could not be parsed"
    if not host:
        return False, "no host in the topic URL"
    if host in _BLOCKED_HOSTS:
        return False, "blocked cloud-metadata host"
    if not (parsed.path or "").strip("/"):
        return False, "no topic in the URL path, for example http://192.168.1.50:8080/svcs-alerts"
    addrs, why = _addresses_for(host)
    if why:
        return False, why
    for ip in addrs:
        refused = _address_refused(ip)
        if refused:
            return False, refused
    return True, ""


# ── posting ──────────────────────────────────────────────────────────────────


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A 3xx becomes an error instead of a second, unvalidated request."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _header_safe(value: str, limit: int = 200) -> str:
    """Header-safe text: no control characters, latin-1 clean, bounded.

    ntfy carries the title, tags, and priority as HTTP HEADERS, so a newline
    in a class label or camera id would be a header-injection primitive.
    """
    out = []
    for ch in str(value or ""):
        code = ord(ch)
        if code < 32 or code == 127:
            continue
        out.append(ch if code < 127 else "?")
    return "".join(out)[:limit].strip()


def _post(cfg: dict, title: str, message: str, tags: str = "",
          priority: str = "", timeout: float = _POST_TIMEOUT_S) -> "tuple[bool, str]":
    """One synchronous POST to the configured topic. Returns (ok, detail)."""
    url = cfg.get("topic_url", "")
    ok, why = is_safe_push_url(url)
    if not ok:
        return False, why
    body = str(message or "").encode("utf-8")[:4096]
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "text/plain; charset=utf-8")
    req.add_header("User-Agent", "SVCS")
    if title:
        req.add_header("Title", _header_safe(title))
    if tags:
        req.add_header("Tags", _header_safe(tags, 120))
    effective = cfg.get("priority") or priority
    if effective:
        req.add_header("Priority", _header_safe(effective, 16))
    token = cfg.get("token") or ""
    if token:
        req.add_header("Authorization", "Bearer " + _header_safe(token, 512))
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
        return (200 <= int(code) < 300), f"HTTP {code}"
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            return False, f"HTTP {exc.code} redirect refused"
        return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, f"could not reach the topic: {exc}"


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
        item = _queue.get()
        try:
            cfg, title, message, tags, priority = item
            ok, detail = _post(cfg, title, message, tags, priority)
            if not ok:
                log.warning("Push not delivered: %s", detail)
        except Exception as exc:  # noqa: BLE001 - a publish must never die loudly
            log.warning("Push worker error: %s", exc)
        finally:
            _adjust_inflight(-1)
            _queue.task_done()


def _ensure_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        threading.Thread(target=_worker_loop, name="svcs-push",
                         daemon=True).start()
        _worker_started = True


def flush(timeout: float = 3.0) -> bool:
    """Wait for queued pushes to finish. Test helper; returns True if drained."""
    deadline = time.time() + max(0.0, float(timeout))
    while time.time() < deadline:
        with _inflight_lock:
            if _inflight == 0 and _queue.empty():
                return True
        time.sleep(0.01)
    with _inflight_lock:
        return _inflight == 0 and _queue.empty()


def publish(title: str, message: str, tags: str = "", priority: str = "",
            cfg: dict = None) -> bool:
    """Queue one push. False when disabled, unconfigured, or the queue is full."""
    cfg = cfg if cfg is not None else load_config()
    if not cfg.get("enabled") or not cfg.get("topic_url"):
        return False
    _ensure_worker()
    try:
        _adjust_inflight(1)
        _queue.put_nowait((dict(cfg), title, message, tags, priority))
        return True
    except queue.Full:
        _adjust_inflight(-1)
        log.warning("Push queue full, dropped: %s", title)
        return False


def send_test(topic_url: str = None, token: str = None) -> "tuple[bool, str]":
    """Post a test message synchronously so a UI button can report the truth.

    Accepts an UNSAVED topic URL so an operator can prove a URL reaches their
    ntfy before committing it, which is the order people actually work in.
    """
    cfg = load_config()
    if topic_url is not None:
        cfg = dict(cfg)
        cfg["topic_url"] = str(topic_url or "").strip()
        if token is not None:
            cfg["token"] = str(token or "").strip()
    if not cfg.get("topic_url"):
        return False, "no topic URL is configured"
    return _post(cfg, "SVCS test", "Push is wired up. This is a test message "
                 "from your SVCS server.", tags="white_check_mark")


# ── message shaping ──────────────────────────────────────────────────────────


def _event_message(ev: dict) -> "tuple[str, str, str]":
    """(title, message, tags) for one behavior event."""
    kind = str(ev.get("kind") or "event")
    label = str(ev.get("label") or "").strip() or "object"
    cam = str(ev.get("camera_id") or "").strip()
    gid = str(ev.get("geometry_id") or "").strip()
    where = f" on {cam}" if cam else ""
    if kind == "line_crossing":
        direction = str(ev.get("direction") or "").strip()
        heading = f" heading {direction}" if direction else ""
        at = f" at {gid}" if gid else ""
        return ("SVCS: line crossed",
                f"A {label} crossed{at}{heading}{where}.", "rotating_light")
    if kind == "loitering":
        dwell = ev.get("dwell_s")
        for_s = f" for {int(float(dwell))}s" if dwell is not None else ""
        at = f" in {gid}" if gid else ""
        return ("SVCS: loitering",
                f"A {label} is loitering{at}{for_s}{where}.", "eyes")
    return ("SVCS: " + kind.replace("_", " "),
            f"A {label} raised {kind.replace('_', ' ')}{where}.", "bell")


def _human_bytes(n: int) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def _job_message(entry: dict) -> "tuple[str, str, str]":
    """(title, message, tags) for one finished job."""
    status = str(entry.get("status") or "completed").lower()
    label = str(entry.get("label") or "").strip() or "a run"
    elapsed = entry.get("elapsed_s")
    took = f" in {elapsed}s" if elapsed else ""
    if status == "error":
        err = str(entry.get("error") or "").strip()
        detail = f": {err}" if err else ""
        return ("SVCS: compression failed", f"{label} failed{took}{detail}", "x")
    if status == "stopped":
        return ("SVCS: compression stopped", f"{label} was stopped{took}.", "warning")
    bin_, bout = int(entry.get("bytes_in") or 0), int(entry.get("bytes_out") or 0)
    saved = ""
    if bin_ > 0 and bout > 0:
        pct = max(0.0, (1.0 - (bout / bin_)) * 100.0)
        saved = f", {_human_bytes(bin_)} to {_human_bytes(bout)}, {pct:.0f} percent saved"
    return ("SVCS: compression finished", f"{label} finished{took}{saved}.",
            "white_check_mark")


# ── the two publish entry points ─────────────────────────────────────────────


def publish_events(events: list, camera_id: str = "") -> int:
    """Push behavior events. Returns how many messages were queued.

    Best effort in every direction: disabled config, a bad URL, or a full
    queue all return quietly. The caller is the encode loop and must never
    learn that a notification failed.
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
            title, message, tags = _event_message(payload)
            if publish(title, message, tags, priority="high", cfg=cfg):
                sent += 1
        extra = len(events) - _MAX_PER_BATCH
        if extra > 0:
            publish("SVCS: more events",
                    f"{extra} further event(s) were recorded in the same batch.",
                    "bell", priority="default", cfg=cfg)
        return sent
    except Exception as exc:  # noqa: BLE001
        log.debug("Event push skipped: %s", exc)
        return 0


def publish_job(entry: dict) -> bool:
    """Push one finished job entry. Best effort, never raises."""
    if not isinstance(entry, dict):
        return False
    try:
        cfg = load_config()
        if not cfg.get("enabled") or not cfg.get("on_jobs"):
            return False
        title, message, tags = _job_message(entry)
        return publish(title, message, tags, priority="default", cfg=cfg)
    except Exception as exc:  # noqa: BLE001
        log.debug("Job push skipped: %s", exc)
        return False
