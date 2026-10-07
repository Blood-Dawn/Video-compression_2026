"""
tests/test_security_headers.py - PT-02 (pentest 2026-10-03).

The SEC-001 CSRF guard cannot see clickjacking: a framed dashboard's requests
are same-origin. These tests pin the anti-framing and related headers onto
every kind of response the real app sends, and check a route can still set
its own value.

Author: Victor De Souza Teixeira, 2026-10-03 (PT-02 fix).
"""

import sys
from pathlib import Path

import pytest
from flask import Flask

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.security_headers import SECURITY_HEADERS, install_security_headers  # noqa: E402


@pytest.fixture()
def client():
    from gui.app import app
    return app.test_client()


@pytest.mark.parametrize("method,url", [
    ("GET", "/"),                         # the dashboard page itself
    ("GET", "/api/status"),               # JSON API
    ("GET", "/definitely/not/a/route"),   # 404
    ("POST", "/api/push/config"),         # 400 on an empty body
])
def test_every_response_refuses_to_be_framed(client, method, url):
    resp = client.open(url, method=method)
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Referrer-Policy"] == "same-origin"


def test_a_csrf_refusal_also_carries_the_headers(client):
    """The 403 from the CSRF guard is a response too."""
    resp = client.post("/api/push/config", json={},
                       headers={"Origin": "http://evil.example"})
    assert resp.status_code == 403
    assert resp.headers["X-Frame-Options"] == "DENY"


def test_a_route_can_still_set_its_own_value():
    app = Flask(__name__)

    @app.route("/custom")
    def custom():
        return "ok", 200, {"Referrer-Policy": "no-referrer"}

    install_security_headers(app)
    resp = app.test_client().get("/custom")
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert resp.headers["X-Frame-Options"] == SECURITY_HEADERS["X-Frame-Options"]
