"""
tests/test_push_endpoint_isolation.py - one device cannot touch another's
push endpoint (planner 6.10, security review of 6.9).

Outcome: "Confirmation that one device cannot register or read another
device's endpoint." Every test here is device B attacking device A. Findings
and reasoning: docs/security/PUSH-ENDPOINT-REVIEW-2026-10.md.

Author: Victor De Souza Teixeira, 2026-10-06 (planner 6.10).
"""

import base64
import sys
import threading
from pathlib import Path

import pytest
from flask import Flask

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui import device_tokens                       # noqa: E402
from gui.auth import install_basic_auth             # noqa: E402
from gui.routes.push_bp import push_bp              # noqa: E402
from gui.routes.tokens_bp import tokens_bp          # noqa: E402

A_ENDPOINT = "http://192.168.1.50:8080/upDEVICEA?up=1"
B_ENDPOINT = "http://192.168.1.50:8080/upDEVICEB?up=1"
EVIL = "http://192.168.1.66:9999/attacker"


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(device_tokens, "token_path", lambda: tmp_path / "device_tokens.json")


@pytest.fixture()
def api():
    app = Flask(__name__)
    app.register_blueprint(push_bp)
    app.register_blueprint(tokens_bp)
    install_basic_auth(app, "admin", "secret")
    return app.test_client()


@pytest.fixture()
def two_devices(api):
    """Device A has registered an endpoint; device B is the attacker."""
    a_secret, a = device_tokens.mint_token("owner phone")
    b_secret, b = device_tokens.mint_token("stolen phone")
    resp = api.put("/api/push/endpoint", json={"endpoint": A_ENDPOINT},
                   headers={"Authorization": f"Bearer {a_secret}"})
    assert resp.status_code == 200
    return {"a": a, "a_h": {"Authorization": f"Bearer {a_secret}"},
            "b": b, "b_h": {"Authorization": f"Bearer {b_secret}"}}


def _a_untouched(d):
    assert device_tokens.get_push_endpoint(d["a"].id) == A_ENDPOINT


# ── reading ──────────────────────────────────────────────────────────────────


def test_b_reads_only_its_own_empty_endpoint(api, two_devices):
    got = api.get("/api/push/endpoint", headers=two_devices["b_h"])
    assert got.get_json() == {"endpoint": "", "registered": False}
    assert "DEVICEA" not in got.get_data(as_text=True)


@pytest.mark.parametrize("qs", ["id", "device_id", "token_id", "device", "for"])
def test_b_cannot_name_a_in_the_query_string(api, two_devices, qs):
    url = f"/api/push/endpoint?{qs}={two_devices['a'].id}"
    got = api.get(url, headers=two_devices["b_h"])
    assert "DEVICEA" not in got.get_data(as_text=True)


def test_b_cannot_list_devices_to_find_a(api, two_devices):
    """The device list is password-only, and even it never carries the URL."""
    assert api.get("/api/auth/tokens", headers=two_devices["b_h"]).status_code == 403


def test_no_response_b_can_reach_contains_a_endpoint(api, two_devices):
    for method, url in (("GET", "/api/push/endpoint"), ("GET", "/api/push/config"),
                        ("GET", "/api/auth/tokens"), ("DELETE", "/api/push/endpoint")):
        body = api.open(url, method=method, headers=two_devices["b_h"]).get_data(as_text=True)
        assert "DEVICEA" not in body, f"{method} {url} leaked A's endpoint"


# ── writing ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("field", ["id", "device_id", "token_id", "device", "owner"])
def test_b_cannot_name_a_in_the_body(api, two_devices, field):
    body = {"endpoint": EVIL, field: two_devices["a"].id}
    resp = api.put("/api/push/endpoint", json=body, headers=two_devices["b_h"])
    assert resp.status_code == 200          # it succeeded... for B
    _a_untouched(two_devices)
    assert device_tokens.get_push_endpoint(two_devices["b"].id) == EVIL


def test_b_cannot_name_a_in_the_query_string_on_write(api, two_devices):
    url = f"/api/push/endpoint?id={two_devices['a'].id}"
    api.put(url, json={"endpoint": EVIL}, headers=two_devices["b_h"])
    _a_untouched(two_devices)


def test_b_delete_never_clears_a(api, two_devices):
    api.delete(f"/api/push/endpoint?id={two_devices['a'].id}", headers=two_devices["b_h"])
    _a_untouched(two_devices)


def test_b_cannot_use_a_route_shaped_like_a_per_device_path(api, two_devices):
    """There is no /api/push/endpoint/<id>; it must not quietly exist."""
    resp = api.put(f"/api/push/endpoint/{two_devices['a'].id}", json={"endpoint": EVIL},
                   headers=two_devices["b_h"])
    assert resp.status_code == 404
    _a_untouched(two_devices)


# ── identity cannot leak between requests or be forged ───────────────────────


def test_a_device_identity_does_not_survive_into_the_next_request(api, two_devices):
    """flask.g is per request: a password request right after A's must not act as A."""
    api.get("/api/push/endpoint", headers=two_devices["a_h"])
    basic = {"Authorization": "Basic " + base64.b64encode(b"admin:secret").decode("ascii")}
    resp = api.put("/api/push/endpoint", json={"endpoint": EVIL}, headers=basic)
    assert resp.status_code == 403
    _a_untouched(two_devices)


@pytest.mark.parametrize("forged", [
    "svcs_",                       # bare prefix
    "svcs_" + "A" * 43,            # well-formed but never issued
    "svcs_xyz svcs_abc",           # two tokens in one header
])
def test_forged_tokens_are_401(api, two_devices, forged):
    resp = api.put("/api/push/endpoint", json={"endpoint": EVIL},
                   headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401
    _a_untouched(two_devices)


def test_a_revoked_device_cannot_overwrite_after_the_fact(api, two_devices):
    device_tokens.revoke_token(two_devices["a"].id)
    resp = api.put("/api/push/endpoint", json={"endpoint": EVIL}, headers=two_devices["a_h"])
    assert resp.status_code == 401
    assert device_tokens.get_push_endpoint(two_devices["a"].id) is None


# ── the store itself ─────────────────────────────────────────────────────────


def test_an_authenticated_request_does_not_drop_endpoints(api, two_devices):
    """verify_token rewrites the store to stamp last_used_at. That rewrite
    must carry every device's endpoint through, not only the caller's."""
    for _ in range(3):
        api.get("/api/push/endpoint", headers=two_devices["b_h"])
    _a_untouched(two_devices)


def test_concurrent_writes_from_two_devices_never_cross(api, two_devices):
    """Read-modify-write under the store lock: 2 x 40 interleaved writes."""
    errors = []

    def hammer(headers, endpoint):
        try:
            for _ in range(40):
                r = api.put("/api/push/endpoint", json={"endpoint": endpoint}, headers=headers)
                if r.status_code != 200:
                    errors.append(r.status_code)
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    ta = threading.Thread(target=hammer, args=(two_devices["a_h"], A_ENDPOINT))
    tb = threading.Thread(target=hammer, args=(two_devices["b_h"], B_ENDPOINT))
    ta.start(); tb.start(); ta.join(); tb.join()
    assert errors == []
    _a_untouched(two_devices)
    assert device_tokens.get_push_endpoint(two_devices["b"].id) == B_ENDPOINT
