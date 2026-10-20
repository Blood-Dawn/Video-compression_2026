"""
src/gui/auth.py

Dashboard authentication for non-localhost binds (M4 TASK 4.4).

The dashboard ships bound to 0.0.0.0 (reachable on the LAN for the NAS/server
scenario), so it needs a login. This module enforces a simple policy:

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

The same guard also accepts ``Authorization: Bearer <token>``, verified against
gui.device_tokens, so one phone can be revoked without rotating the password.
Minting and revoking require the PASSWORD (Basic), never a token, so a stolen
token cannot mint successors or revoke other devices; that check lives in the
routes.

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 4.4 - dashboard auth).
Updated:  Bloodawn (KheivenD), 2026-07-18 (M0.10 - Bearer device tokens).
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Mapping

# Stdlib logger, not gui.logging_setup: auth is imported very early and that
# risks an import cycle. The root logger's handlers apply to this child anyway.
log = logging.getLogger("gui.auth")

from flask import Flask, Response, g, request

# Values stashed on flask.g so a route can tell WHICH credential authenticated
# the current request. Token-management routes require SCHEME_BASIC: a stolen
# device token must not be able to mint successors or revoke other devices.
SCHEME_BASIC = "basic"
SCHEME_BEARER = "bearer"
#: Set when no auth guard is installed at all (localhost bind, no credentials).
SCHEME_NONE = "none"


def current_device_id() -> str | None:
    """The id of the device token that authenticated this request, or None.

    None for a Basic request and for the open localhost case. Routes that act
    on "this device" must use this, never an id supplied in the request.
    """
    return getattr(g, "svcs_device_id", None)


def current_auth_scheme() -> str:
    """Which credential authenticated this request.

    Returns SCHEME_NONE when no guard is installed (the open localhost case),
    which is deliberately treated as fully privileged.
    """
    return getattr(g, "svcs_auth_scheme", SCHEME_NONE)

# Hosts that mean "this machine only" - auth optional.
_LOCALHOST_HOSTS = {"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1", ""}

ENV_USER = "SVCS_DASHBOARD_USER"
ENV_PASSWORD = "SVCS_DASHBOARD_PASSWORD"


class AuthConfigError(RuntimeError):
    """Raised when a bind would expose the dashboard but auth isn't configured."""


def is_localhost(host: str | None) -> bool:
    """True if ``host`` binds only the loopback interface."""
    h = (host or "").strip().lower()
    return h in _LOCALHOST_HOSTS or h.startswith("127.")  # 127.0.0.0/8 is loopback


def resolve_credentials(
    username: str | None = None,
    password: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[str | None, str | None]:
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
    username: str | None = None
    password: str | None = field(default=None, repr=False)  # never logged


def decide_auth(
    host: str,
    no_auth: bool = False,
    username: str | None = None,
    password: str | None = None,
    env: Mapping[str, str] | None = None,
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


# Failed-auth throttle. The shipping config binds 0.0.0.0, so the credential
# check is reachable from the network, and a device token can be guessed at
# without a username. Hand-rolled because flask-limiter is not a dependency and
# adding one just to count integers widens the supply chain surface.
_FAIL_WINDOW_S = 300.0     # sliding window over which failures accumulate
_FAIL_MAX = 10             # failures per window per IP before lockout
_LOCKOUT_S = 300.0         # how long a locked-out IP stays locked out
# Bounds the table against a spoofed-IP flood; far above real LAN client counts.
_MAX_TRACKED_IPS = 1024

_CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")

_fail_lock = threading.Lock()
#: ip -> list of monotonic failure timestamps within the window
_fail_times: dict[str, list] = {}
#: ip -> monotonic time at which the lockout expires
_locked_until: dict[str, float] = {}


def _client_ip() -> str:
    """Client identity for throttling: the socket peer only.

    X-Forwarded-For is not trusted: nothing sets up ProxyFix, so the header is
    attacker-controlled and would let one attacker dodge the limit.
    """
    return request.remote_addr or "unknown"


def _reset_throttle() -> None:
    """Clear all throttle state. For tests and for a clean process start."""
    with _fail_lock:
        _fail_times.clear()
        _locked_until.clear()


def _is_locked_out(ip: str, now: float | None = None) -> bool:
    now = now if now is not None else time.monotonic()
    with _fail_lock:
        until = _locked_until.get(ip)
        if until is None:
            return False
        if now >= until:
            _locked_until.pop(ip, None)
            _fail_times.pop(ip, None)
            return False
        return True


def _record_failure(ip: str, now: float | None = None) -> bool:
    """Record one failed attempt. Returns True if this trips a lockout."""
    now = now if now is not None else time.monotonic()
    with _fail_lock:
        if len(_fail_times) >= _MAX_TRACKED_IPS and ip not in _fail_times:
            # Table full: drop the oldest entry rather than refuse to track,
            # so a flood cannot buy immunity for a real attacker.
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


def is_private_bind(host: str) -> bool:
    """True if ``host`` is loopback or a private/link-local range.

    Private means reachable only from networks the operator plausibly controls:
    loopback, RFC1918, RFC4193 unique-local, link-local, and the 100.64.0.0/10
    CGNAT block that Tailscale uses.

    0.0.0.0 and :: are NOT private: they bind every interface, which on a
    machine with a public IP means the dashboard is on the public internet.
    """
    h = (host or "").strip().lower()
    if h in _LOCALHOST_HOSTS:
        return True
    try:
        addr = ipaddress.ip_address(h)
    except ValueError:
        # A hostname: classifying it needs DNS, so treat it as not private. A
        # false warning is cheaper than silently publishing surveillance footage.
        return False
    if addr.is_unspecified:          # 0.0.0.0 / :: - every interface
        return False
    if addr.is_loopback or addr.is_private or addr.is_link_local:
        return True
    # Python reports Tailscale's 100.64.0.0/10 (RFC 6598) as neither private nor
    # global; without this check we would warn about the VPN we recommend.
    return addr.version == 4 and addr in _CGNAT_NET


def bind_exposure_warning(host: str) -> str | None:
    """Return a warning for a bind that may expose the dashboard, else None.

    The dashboard serves recorded video of real people over plain HTTP, so a
    start that reaches beyond the local machine should say so out loud.
    """
    if is_private_bind(host):
        return None
    return (
        f"Binding to {host!r} may expose this dashboard beyond your local "
        "network.\n"
        "           It serves recorded video of real people over plain HTTP, "
        "so the password\n"
        "           is sent in cleartext on every request. Prefer a VPN "
        "(WireGuard / Tailscale)\n"
        "           or a reverse proxy with real TLS. Do NOT forward this "
        "port on your router."
    )


def _presented_bearer() -> str | None:
    """Return the Bearer token on this request, or None.

    Parsed by hand because Werkzeug's ``request.authorization`` only models
    some schemes. Never logged.
    """
    header = request.headers.get("Authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip() or None


def install_basic_auth(app: Flask, username: str, password: str) -> None:
    """Enforce authentication on every request to ``app``.

    Accepts EITHER of two credentials:

      * ``Authorization: Basic`` with the configured username and password
        (the browser path), or
      * ``Authorization: Bearer <token>`` matching a live device token (the
        mobile path).

    Both comparisons are constant-time. Applies to all routes including static
    assets, media and the HLS routes an Android player fetches on its own
    connection.
    """
    if not username or not password:
        raise ValueError("username and password are required to enable auth")
    user_bytes = username.encode("utf-8")
    pass_bytes = password.encode("utf-8")

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

        Logs the source address but never the attempted credential, so the log
        shows probing without becoming a place secrets are written down.
        """
        if _record_failure(ip):
            log.warning("Auth: locking out %s for %ds after %d failed attempts in %ds.",
                        ip, int(_LOCKOUT_S), _FAIL_MAX, int(_FAIL_WINDOW_S))
            return _too_many()
        log.warning("Auth: failed attempt from %s.", ip)
        return _unauthorized()

    @app.before_request
    def _require_basic_auth():  # pragma: no cover - exercised via test client
        ip = _client_ip()
        # Locked-out addresses are refused before any credential is examined.
        if _is_locked_out(ip):
            return _too_many()

        # Bearer first: a mobile client always sends it, so Basic is skipped
        # for every .ts segment fetch.
        presented = _presented_bearer()
        if presented is not None:
            try:
                from gui.device_tokens import verify_token
            except ModuleNotFoundError:  # pragma: no cover - import path shim
                from src.gui.device_tokens import verify_token
            # Never log `presented`, and never echo it in the response.
            rec = verify_token(presented)
            if rec is not None:
                g.svcs_auth_scheme = SCHEME_BEARER
                g.svcs_device_id = rec.id
                _record_success(ip)
                return None
            return _fail(ip)

        auth = request.authorization
        if auth is None or auth.type != "basic":
            # Not counted as a failure: browsers send one unauthenticated
            # request and retry after the 401, so counting it would lock out
            # ordinary users on first load.
            return _unauthorized()
        # Compare UTF-8 bytes: hmac.compare_digest raises TypeError on
        # non-ASCII str, which would turn every request into a 500 for an
        # operator whose password has an accent.
        user_ok = hmac.compare_digest((auth.username or "").encode("utf-8"), user_bytes)
        pass_ok = hmac.compare_digest((auth.password or "").encode("utf-8"), pass_bytes)
        if user_ok and pass_ok:
            g.svcs_auth_scheme = SCHEME_BASIC
            _record_success(ip)
            return None
        return _fail(ip)
