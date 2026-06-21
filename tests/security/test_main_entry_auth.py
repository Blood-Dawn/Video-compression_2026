"""
tests/security/test_main_entry_auth.py  (SEC-010)

Running `python src/gui/app.py` / `python -m gui.app` must NOT expose the
dashboard unauthenticated on the LAN. The module's serve path now funnels through
`_resolve_serve_auth`, which mirrors run_gui's policy: a non-localhost bind with
no credentials raises AuthConfigError (so the process refuses to start), and a
bind with credentials installs Basic-Auth.
"""

import sys
from pathlib import Path

import pytest
from flask import Flask

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.app import _resolve_serve_auth  # noqa: E402
from gui.auth import AuthConfigError  # noqa: E402


def _throwaway_app():
    app = Flask(__name__)

    @app.route("/ping")
    def _ping():
        return "pong"

    return app


def test_non_localhost_without_creds_refuses():
    app = _throwaway_app()
    with pytest.raises(AuthConfigError):
        _resolve_serve_auth(app, "0.0.0.0", env={})


def test_localhost_without_creds_is_allowed_no_auth():
    app = _throwaway_app()
    decision = _resolve_serve_auth(app, "127.0.0.1", env={})
    assert not decision.auth_required
    # No auth installed -> the route is reachable anonymously.
    assert app.test_client().get("/ping").status_code == 200


def test_non_localhost_with_creds_installs_auth():
    app = _throwaway_app()
    env = {"SVCS_DASHBOARD_USER": "admin", "SVCS_DASHBOARD_PASSWORD": "s3cret"}
    decision = _resolve_serve_auth(app, "0.0.0.0", env=env)
    assert decision.auth_required and decision.auth_enabled
    c = app.test_client()
    assert c.get("/ping").status_code == 401  # anonymous blocked
    assert c.get("/ping", auth=("admin", "s3cret")).status_code == 200
