"""
tests/test_dashboard_auth.py

Tests dashboard authentication for non-localhost binds (M4 TASK 4.4).

The core acceptance: a non-localhost bind with no credentials and no explicit
opt-out is rejected (the server must not silently expose an unauthenticated
dashboard on the LAN). Plus the localhost-stays-open path, env-var credentials,
the --no-auth override, and the actual Basic-Auth guard (401 without/with-wrong
creds, 200 with correct creds) on a throwaway Flask app.

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 4.4 - dashboard auth).
"""

import base64
import sys
from pathlib import Path

import pytest
from flask import Flask

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.auth import (  # noqa: E402
    ENV_PASSWORD,
    ENV_USER,
    AuthConfigError,
    decide_auth,
    install_basic_auth,
    is_localhost,
    resolve_credentials,
)


# ── is_localhost ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.5", ""])
def test_is_localhost_true(host):
    assert is_localhost(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "10.0.0.2", "myhost"])
def test_is_localhost_false(host):
    assert not is_localhost(host)


# ── decide_auth policy ───────────────────────────────────────────────────────

def test_nonlocalhost_without_credentials_is_rejected():
    """THE acceptance: exposing the dashboard with no auth must be refused."""
    with pytest.raises(AuthConfigError):
        decide_auth("0.0.0.0", no_auth=False, env={})


def test_nonlocalhost_with_credentials_enables_auth():
    d = decide_auth("0.0.0.0", username="admin", password="secret", env={})
    assert d.auth_required and d.auth_enabled
    assert d.username == "admin" and d.password == "secret"


def test_nonlocalhost_no_auth_override_allowed_but_disabled():
    d = decide_auth("0.0.0.0", no_auth=True, env={})
    assert d.auth_required and not d.auth_enabled
    assert d.username is None


def test_localhost_without_credentials_is_open():
    d = decide_auth("127.0.0.1", env={})
    assert not d.auth_required and not d.auth_enabled


def test_localhost_with_credentials_still_enables_auth():
    d = decide_auth("localhost", username="u", password="p", env={})
    assert not d.auth_required and d.auth_enabled


def test_credentials_come_from_env():
    env = {ENV_USER: "envuser", ENV_PASSWORD: "envpass"}
    u, p = resolve_credentials(env=env)
    assert (u, p) == ("envuser", "envpass")
    d = decide_auth("0.0.0.0", env=env)
    assert d.auth_enabled and d.username == "envuser"


def test_partial_credentials_username_only_is_rejected():
    # A username with no password is not usable credentials -> still rejected.
    with pytest.raises(AuthConfigError):
        decide_auth("0.0.0.0", username="admin", password=None, env={})


def test_password_not_in_repr():
    d = decide_auth("0.0.0.0", username="admin", password="topsecret", env={})
    assert "topsecret" not in repr(d)


# ── install_basic_auth guard ─────────────────────────────────────────────────

@pytest.fixture()
def authed_client():
    app = Flask(__name__)

    @app.route("/")
    def index():
        return "ok"

    install_basic_auth(app, "admin", "secret")
    return app.test_client()


def _basic(user, pw):
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_request_without_auth_is_401(authed_client):
    resp = authed_client.get("/")
    assert resp.status_code == 401
    assert "Basic" in resp.headers.get("WWW-Authenticate", "")


def test_request_with_wrong_credentials_is_401(authed_client):
    assert authed_client.get("/", headers=_basic("admin", "nope")).status_code == 401
    assert authed_client.get("/", headers=_basic("root", "secret")).status_code == 401


def test_request_with_correct_credentials_is_200(authed_client):
    resp = authed_client.get("/", headers=_basic("admin", "secret"))
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == "ok"


def test_install_requires_both_parts():
    app = Flask(__name__)
    with pytest.raises(ValueError):
        install_basic_auth(app, "admin", "")
