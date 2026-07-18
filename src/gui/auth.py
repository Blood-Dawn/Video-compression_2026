"""
src/gui/auth.py

Dashboard authentication for non-localhost binds (M4 TASK 4.4).

The dashboard ships bound to 0.0.0.0 (reachable on the LAN - the NAS/server
scenario), but it has no login, so anyone on the network could open it. That's a
real exposure. This module enforces a simple policy:

  * Bound to localhost (127.0.0.1/::1) -> no auth required (single-user, the
    default desktop case). Auth is still enabled if credentials are supplied.
  * Bound to anything else -> HTTP Basic Auth is REQUIRED. The server refuses to
    start unless either credentials are configured (CLI flags or the
    SVCS_DASHBOARD_USER / SVCS_DASHBOARD_PASSWORD env vars) or the operator
    explicitly opts out with --no-auth.

The decision is pure and isolated (``decide_auth``) so it is unit-testable
without a running server; ``install_basic_auth`` wires the actual before-request
guard onto a Flask app. Auth is deliberately NOT installed inside create_app()  -
only the real server entry point (run_gui) installs it after deciding policy, so
the test suite's in-process client and embedded uses stay unauthenticated.

M0.10 (mobile port) adds a SECOND accepted credential on the same guard:
``Authorization: Bearer <token>``, verified against gui.device_tokens. Basic is
unchanged and remains the browser path. Tokens exist because a credential typed
into a phone leaves the building, and revoking one device must not mean rotating
the password for every client. Minting and revoking deliberately require the
PASSWORD (Basic), never a token, so a stolen token cannot mint successors or
revoke the operator's other devices; that check lives in the routes.

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 4.4 - dashboard auth).
Updated:  Bloodawn (KheivenD), 2026-07-18 (M0.10 - Bearer device tokens).
"""

from __future__ import annotations

import hmac
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple

# Plain stdlib logger rather than importing gui.logging_setup. auth is imported
# very early by both entry points, and taking a dependency on the logging
# module here risks an import cycle for no benefit: logging_setup configures the
# root logger, so this child inherits its handlers and formatting anyway.
log = logging.getLogger("gui.auth")

from flask import Flask, Response, g, request

# Values stashed on flask.g so a route can tell WHICH credential authenticated
# the current request. Token-management routes require SCHEME_BASIC: a stolen
# device token must not be able to mint successors or revoke other devices.
SCHEME_BASIC = "basic"
SCHEME_BEARER = "bearer"
#: Set when no auth guard is installed at all (localhost bind, no credentials).
SCHEME_NONE = "none"


def current_auth_scheme() -> str:
    """Which credential authenticated this request.

    Returns SCHEME_NONE when no guard is installed, which is the open localhost
    case and is deliberately treated as fully privileged, matching the existing
    no-auth model.
    """
    return getattr(g, "svcs_auth_scheme", SCHEME_NONE)

# Hosts that mean "this machine only" - auth optional.
_LOCALHOST_HOSTS = {"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1", ""}

ENV_USER = "SVCS_DASHBOARD_USER"
ENV_PASSWORD = "SVCS_DASHBOARD_PASSWORD"


class AuthConfigError(RuntimeError):
    """Raised when a bind would expose the dashboard but auth isn't configured."""


def is_localhost(host: Optional[str]) -> bool:
    """True if ``host`` binds only the loopback interface."""
    h = (host or "").strip().lower()
    if h in _LOCALHOST_HOSTS:
        return True
    # 127.0.0.0/8 is all loopback.
    return h.startswith("127.")


def resolve_credentials(
    username: Optional[str] = None,
    password: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve credentials from explicit args, falling back to env vars."""
    env = os.environ if env is None else env
    u = (username or env.get(ENV_USER) or "").strip() or None
    p = password or env.get(ENV_PASSWORD) or None
    return u, p


@dataclass(frozen=True)
class AuthDecision:
    """Outcome of the auth policy for a given bind.

    auth_required: the bind is non-localhost, so auth *should* protect it.
    auth_enabled:  Basic Auth will actually be enforced (credentials present).
    A non-localhost bind with auth_required and not auth_enabled means the
    operator explicitly chose --no-auth (exposed, unauthenticated).
    """
    host: str
    auth_required: bool
    auth_enabled: bool
    username: Optional[str] = None
    password: Optional[str] = field(default=None, repr=False)  # never logged


def decide_auth(
    host: str,
    no_auth: bool = False,
    username: Optional[str] = None,
    password: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> AuthDecision:
    """Decide the auth policy for a bind, or raise AuthConfigError.

    Raises AuthConfigError when binding beyond localhost without credentials and
    without an explicit --no-auth opt-out - the server must not silently expose
    an unauthenticated dashboard on the network.
    """
    user, pw = resolve_credentials(username, password, env)
    have_creds = bool(user and pw)

    if is_localhost(host):
        # Single-machine: auth optional, enabled only if creds were supplied.
        return AuthDecision(host, auth_required=False, auth_enabled=have_creds,
                            username=user if have_creds else None,
                            password=pw if have_creds else None)

    # Non-localhost bind: auth is required.
    if have_creds:
        return AuthDecision(host, auth_required=True, auth_enabled=True,
                            username=user, password=pw)
    if no_auth:
        # Operator explicitly accepted the risk.
        return AuthDecision(host, auth_required=True, auth_enabled=False)

    raise AuthConfigError(
        f"Refusing to start: binding to {host!r} exposes the dashboard beyond "
        "this machine, but no credentials are set. Either set "
        f"{ENV_USER} and {ENV_PASSWORD} (or pass --username/--password), bind to "
        "127.0.0.1 for local-only access, or pass --no-auth to run without "
        "authentication (NOT recommended on an untrusted network)."
    )


# ── Failed-auth throttle (M0.2) ──────────────────────────────────────────────
# Before this there was no counter, no delay, no lockout, and no logging of a
# failed attempt. run_gui defaults --host to 0.0.0.0 and the Dockerfile passes
# it explicitly, so an unthrottled credential endpoint is the SHIPPING
# configuration, not a hypothetical. Adding device tokens raises the stakes:
# a token is a bearer secret that an attacker can guess at, in principle,
# without a username.
#
# Deliberately hand-rolled. flask-limiter is not in pyproject or uv.lock, and
# pulling a dependency in to count integers would widen the license and supply
# chain surface of an AGPL project for no gain.
_FAIL_WINDOW_S = 300.0     # sliding window over which failures accumulate
_FAIL_MAX = 10             # failures per window per IP before lockout
_LOCKOUT_S = 300.0         # how long a locked-out IP stays locked out
# Bound the table so a spoofed-IP flood cannot grow it without limit. Well above
# any plausible number of real clients on a home or small-office LAN.
_MAX_TRACKED_IPS = 1024

_fail_lock = threading.Lock()
#: ip -> list of monotonic failure timestamps within the window
_fail_times: Dict[str, list] = {}
#: ip -> monotonic time at which the lockout expires
_locked_until: Dict[str, float] = {}


def _client_ip() -> str:
    """Best-effort client identity for throttling.

    Uses the socket peer only. X-Forwarded-For is deliberately NOT trusted:
    nothing in this app sets up ProxyFix, so the header is attacker-controlled
    and honoring it would let one attacker spread their attempts across
    unlimited fake identities and never trip the limit.
    """
    return request.remote_addr or "unknown"


def _reset_throttle() -> None:
    """Clear all throttle state. For tests and for a clean process start."""
    with _fail_lock:
        _fail_times.clear()
        _locked_until.clear()


def _is_locked_out(ip: str, now: Optional[float] = None) -> bool:
    now = now if now is not None else time.monotonic()
    with _fail_lock:
        until = _locked_until.get(ip)
        if until is None:
            return False
        if now >= until:
            # Lockout served: forget it and give the client a clean slate.
            _locked_until.pop(ip, None)
            _fail_times.pop(ip, None)
            return False
        return True


def _record_failure(ip: str, now: Optional[float] = None) -> bool:
    """Record one failed attempt. Returns True if this trips a lockout."""
    now = now if now is not None else time.monotonic()
    with _fail_lock:
        if len(_fail_times) >= _MAX_TRACKED_IPS and ip not in _fail_times:
            # Table is full of other addresses. Drop the oldest tracked entry
            # rather than refusing to track, so a flood cannot buy immunity for
            # a genuine attacker by filling the table first.
            oldest = min(_fail_times, key=lambda k: _fail_times[k][-1])
            _fail_times.pop(oldest, None)
        times = [t for t in _fail_times.get(ip, []) if now - t < _FAIL_WINDOW_S]
        times.append(now)
        _fail_times[ip] = times
        if len(times) >= _FAIL_MAX:
            _locked_until[ip] = now + _LOCKOUT_S
            _fail_times.pop(ip, None)
            return True
        return False


def _record_success(ip: str) -> None:
    """Clear the failure history for an address that just authenticated."""
    with _fail_lock:
        _fail_times.pop(ip, None)


def _presented_bearer() -> Optional[str]:
    """Return the Bearer token on this request, or None.

    Parsed by hand rather than via ``request.authorization`` because Werkzeug
    only populates that for schemes it models, and the value must be read
    verbatim. Never logged.
    """
    header = request.headers.get("Authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip() or None


def install_basic_auth(app: Flask, username: str, password: str) -> None:
    """Enforce authentication on every request to ``app``.

    Accepts EITHER of two credentials:

      * ``Authorization: Basic`` with the configured username and password (the
        browser path, unchanged since TASK 4.4), or
      * ``Authorization: Bearer <token>`` matching a live device token (M0.10,
        the mobile path).

    Both comparisons are constant-time so the guard does not leak a credential
    via timing. Applies to all routes including static assets: the whole
    dashboard is behind the login, and that deliberately includes the media and
    HLS routes an Android player fetches on its own connection.

    The name is kept for compatibility with existing call sites and tests.
    """
    if not username or not password:
        raise ValueError("username and password are required to enable auth")

    # Advertise both schemes so a client knows a token is acceptable.
    realm = ('Basic realm="SVCS Dashboard", charset="UTF-8", '
             'Bearer realm="SVCS Dashboard"')

    def _unauthorized() -> Response:
        return Response("Authentication required.", 401,
                        {"WWW-Authenticate": realm})

    def _too_many() -> Response:
        return Response("Too many failed authentication attempts.", 429,
                        {"Retry-After": str(int(_LOCKOUT_S))})

    def _fail(ip: str) -> Response:
        """Record a failed attempt and return the right refusal.

        Logs the source address but NEVER the attempted credential, per the
        house rule. That is the whole value of the log line: an operator can
        see they are being probed without the log itself becoming a place
        passwords and tokens are written down.
        """
        locked = _record_failure(ip)
        if locked:
            log.warning(
                f"Auth: locking out {ip} for {int(_LOCKOUT_S)}s after "
                f"{_FAIL_MAX} failed attempts in {int(_FAIL_WINDOW_S)}s.")
            return _too_many()
        log.warning(f"Auth: failed attempt from {ip}.")
        return _unauthorized()

    @app.before_request
    def _require_basic_auth():  # pragma: no cover - exercised via test client
        ip = _client_ip()
        # Locked-out addresses are refused before any credential is examined,
        # so a lockout also stops the comparison work itself.
        if _is_locked_out(ip):
            return _too_many()

        # ── Bearer device token (M0.10) ──
        # Checked first because a mobile client always sends Bearer, so this
        # avoids running the Basic path for every .ts segment fetch.
        presented = _presented_bearer()
        if presented is not None:
            try:
                from gui.device_tokens import verify_token
            except ModuleNotFoundError:  # pragma: no cover - import path shim
                from src.gui.device_tokens import verify_token
            # Never log `presented`, and never echo it in the response.
            if verify_token(presented) is not None:
                g.svcs_auth_scheme = SCHEME_BEARER
                _record_success(ip)
                return None
            return _fail(ip)

        auth = request.authorization
        if auth is None or auth.type != "basic":
            # A request carrying NO credential at all is not counted as a
            # failure. Browsers routinely fire one unauthenticated request and
            # then retry with credentials after the 401, so counting these
            # would lock out ordinary users on their first page load.
            return _unauthorized()
        # Compare UTF-8 BYTES, not str. hmac.compare_digest raises TypeError on
        # str operands containing non-ASCII, and the client half of each compare
        # is attacker-controlled: with str operands, any unauthenticated caller
        # who sends a non-ASCII password turns every request into a 500 plus a
        # logged traceback (no error handler is registered), and a legitimate
        # operator whose password has an accent can never log in. Bytes also
        # match the charset="UTF-8" this realm already advertises, and keep the
        # comparison constant-time.
        user_ok = hmac.compare_digest((auth.username or "").encode("utf-8"),
                                      username.encode("utf-8"))
        pass_ok = hmac.compare_digest((auth.password or "").encode("utf-8"),
                                      password.encode("utf-8"))
        if user_ok and pass_ok:
            g.svcs_auth_scheme = SCHEME_BASIC
            _record_success(ip)
            return None
        return _fail(ip)
