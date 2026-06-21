"""
src/gui/csrf.py

Same-origin CSRF guard for the dashboard (SEC-001).

The dashboard has no CSRF tokens and its state-changing routes are plain POSTs.
Because it binds the LAN and the browser auto-replays any cached Basic-Auth, a
malicious web page the operator visits could drive `/api/start`,
`/api/autocompress/start` (with `delete_original` -> footage deletion),
`/api/decrypt`, `/api/setup/reset`, etc. cross-site.

Mitigation: reject any UNSAFE-method request whose `Origin` (or, failing that,
`Referer`) is present and does NOT match the request host. A browser always
sends `Origin` on cross-origin (and on same-origin non-GET) requests, so a
cross-site POST is blocked while the dashboard's own same-origin `fetch()` (whose
Origin matches the host) passes. Requests with neither header (the test client,
curl, native tools) are treated as same-origin and allowed, so this adds no
token plumbing and breaks no legitimate non-browser client.

Author: Bloodawn (KheivenD), 2026-06-21 (security audit - SEC-001 CSRF).
"""

from __future__ import annotations

from urllib.parse import urlparse

from flask import Flask, Response, request

# Methods that cannot change state need no CSRF check.
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def _netloc(url: str) -> str:
    """Return the lower-cased host[:port] of a URL, or '' if unparseable."""
    try:
        return urlparse(url or "").netloc.lower()
    except (ValueError, TypeError):  # pragma: no cover - defensive
        return ""


def is_cross_origin(origin, referer, host) -> bool:
    """True if this looks like a cross-origin browser request (a CSRF risk).

    Prefers ``Origin``; falls back to ``Referer``. With neither header the
    request is treated as same-origin (non-browser client) and allowed.
    """
    host = (host or "").lower()
    if origin:
        return _netloc(origin) != host
    if referer:
        return _netloc(referer) != host
    return False


def install_csrf_protection(app: Flask) -> None:
    """Install the same-origin guard as a before-request hook on ``app``."""

    @app.before_request
    def _csrf_guard():  # pragma: no cover - exercised via the test client
        if request.method in _SAFE_METHODS:
            return None
        if is_cross_origin(request.headers.get("Origin"),
                           request.headers.get("Referer"),
                           request.host):
            return Response("Cross-origin request blocked (CSRF).", 403)
        return None
