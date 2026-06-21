"""
tests/security/test_auth_policy.py  (SEC-D4)

Attack the dashboard auth policy and assert it holds:
  * a non-localhost bind without credentials is REFUSED (no silent exposure),
  * Basic-Auth uses a constant-time compare and rejects wrong/empty creds,
  * localhost binds do not require auth (single-user default).
"""

import sys
from pathlib import Path

import pytest
from flask import Flask

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.auth import (  # noqa: E402
    AuthConfigError,
    decide_auth,
    install_basic_auth,
    is_localhost,
)


def test_non_localhost_without_creds_is_refused():
    with pytest.raises(AuthConfigError):
        decide_auth("0.0.0.0", no_auth=False, env={})


def test_non_localhost_with_creds_enables_auth():
    d = decide_auth("0.0.0.0", username="u", password="p", env={})
    assert d.auth_required and d.auth_enabled


def test_localhost_does_not_require_auth():
    d = decide_auth("127.0.0.1", env={})
    assert not d.auth_required
    assert is_localhost("127.0.0.1") and is_localhost("localhost")
    assert not is_localhost("0.0.0.0") and not is_localhost("192.168.1.5")


def _app_with_auth():
    app = Flask(__name__)

    @app.route("/secret")
    def _secret():
        return "ok"

    install_basic_auth(app, "admin", "s3cret")
    return app.test_client()


def test_basic_auth_blocks_anonymous():
    c = _app_with_auth()
    assert c.get("/secret").status_code == 401


def test_basic_auth_rejects_wrong_password():
    c = _app_with_auth()
    assert c.get("/secret", auth=("admin", "nope")).status_code == 401


def test_basic_auth_rejects_empty_credentials():
    c = _app_with_auth()
    assert c.get("/secret", auth=("", "")).status_code == 401


def test_basic_auth_accepts_correct_credentials():
    c = _app_with_auth()
    assert c.get("/secret", auth=("admin", "s3cret")).status_code == 200


def test_install_basic_auth_requires_nonempty_creds():
    app = Flask(__name__)
    with pytest.raises(ValueError):
        install_basic_auth(app, "", "")
