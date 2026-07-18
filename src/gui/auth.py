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

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 4.4 - dashboard auth).
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple

from flask import Flask, Response, request

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


def install_basic_auth(app: Flask, username: str, password: str) -> None:
    """Enforce HTTP Basic Auth on every request to ``app``.

    Uses constant-time comparison so the guard doesn't leak the credential via
    timing. Applies to all routes including static assets - the whole dashboard
    is behind the login.
    """
    if not username or not password:
        raise ValueError("username and password are required to enable auth")

    realm = 'Basic realm="SVCS Dashboard", charset="UTF-8"'

    def _unauthorized() -> Response:
        return Response("Authentication required.", 401,
                        {"WWW-Authenticate": realm})

    @app.before_request
    def _require_basic_auth():  # pragma: no cover - exercised via test client
        auth = request.authorization
        if auth is None or auth.type != "basic":
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
            return None
        return _unauthorized()
