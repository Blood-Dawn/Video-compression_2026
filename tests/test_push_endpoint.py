"""
tests/test_push_endpoint.py - a device registers its own push endpoint (planner 6.9).

Outcome: "Device tokens can carry a push endpoint for the native path." These
run the real route behind the real auth guard, with real minted tokens, so
the device identity comes from the same code path production uses.

The cross-device rules (6.10) live in test_push_endpoint_isolation.py.

Author: Victor De Souza Teixeira, 2026-10-06 (planner 6.9).
"""

import base64
import json
import sys
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

ENDPOINT = "https://ntfy.example.org/upAbC123?up=1"
LAN_ENDPOINT = "http://192.168.1.50:8080/upXyZ789?up=1"


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    store = tmp_path / "device_tokens.json"
    monkeypatch.setattr(device_tokens, "token_path", lambda: store)
    return store


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    """No test may depend on real DNS. example.org names get a public address;
    anything else fails to resolve, which the guard reports and refuses."""
    from utils import push_notify

    def fake_getaddrinfo(host, *_a, **_k):
        if str(host).endswith("example.org"):
            return [(2, 1, 6, "", ("93.184.216.34", 0))]
        raise OSError("no such host")
    monkeypatch.setattr(push_notify.socket, "getaddrinfo", fake_getaddrinfo)


@pytest.fixture()
def api():
    app = Flask(__name__)
    app.register_blueprint(push_bp)
    app.register_blueprint(tokens_bp)
    install_basic_auth(app, "admin", "secret")
    return app.test_client()


def _basic():
    return {"Authorization": "Basic " + base64.b64encode(b"admin:secret").decode("ascii")}


def _bearer(secret):
    return {"Authorization": f"Bearer {secret}"}


@pytest.fixture()
def phone():
    secret, rec = device_tokens.mint_token("Pixel 8")
    return secret, rec


# ── the happy path ───────────────────────────────────────────────────────────


def test_a_new_device_has_no_endpoint(api, phone):
    secret, _ = phone
    got = api.get("/api/push/endpoint", headers=_bearer(secret)).get_json()
    assert got == {"endpoint": "", "registered": False}


@pytest.mark.parametrize("endpoint", [ENDPOINT, LAN_ENDPOINT])
def test_a_device_registers_and_reads_back_its_endpoint(api, phone, endpoint):
    secret, rec = phone
    resp = api.put("/api/push/endpoint", json={"endpoint": endpoint}, headers=_bearer(secret))
    assert resp.status_code == 200 and resp.get_json() == {"ok": True, "registered": True}
    got = api.get("/api/push/endpoint", headers=_bearer(secret)).get_json()
    assert got == {"endpoint": endpoint, "registered": True}
    assert device_tokens.get_push_endpoint(rec.id) == endpoint


def test_re_registering_replaces_the_endpoint(api, phone):
    secret, rec = phone
    api.put("/api/push/endpoint", json={"endpoint": ENDPOINT}, headers=_bearer(secret))
    api.put("/api/push/endpoint", json={"endpoint": LAN_ENDPOINT}, headers=_bearer(secret))
    assert device_tokens.get_push_endpoint(rec.id) == LAN_ENDPOINT


def test_delete_clears_it(api, phone):
    secret, rec = phone
    api.put("/api/push/endpoint", json={"endpoint": ENDPOINT}, headers=_bearer(secret))
    resp = api.delete("/api/push/endpoint", headers=_bearer(secret))
    assert resp.get_json() == {"ok": True, "registered": False}
    assert device_tokens.get_push_endpoint(rec.id) is None


def test_the_endpoint_survives_a_reload_of_the_store(api, phone, isolated_store):
    secret, rec = phone
    api.put("/api/push/endpoint", json={"endpoint": ENDPOINT}, headers=_bearer(secret))
    stored = json.loads(isolated_store.read_text(encoding="utf-8"))
    assert stored["tokens"][0]["push_endpoint"] == ENDPOINT
    assert device_tokens.list_tokens()[0].push_endpoint == ENDPOINT


def test_a_store_written_before_6_9_still_loads(isolated_store):
    """Existing installs have records with no push_endpoint key at all."""
    secret, rec = device_tokens.mint_token("old phone")
    data = json.loads(isolated_store.read_text(encoding="utf-8"))
    for t in data["tokens"]:
        t.pop("push_endpoint", None)
    isolated_store.write_text(json.dumps(data), encoding="utf-8")
    loaded = device_tokens.list_tokens()
    assert len(loaded) == 1 and loaded[0].push_endpoint is None
    assert device_tokens.verify_token(secret) is not None


# ── who may call it ──────────────────────────────────────────────────────────


def test_no_credential_is_401(api):
    assert api.get("/api/push/endpoint").status_code == 401
    assert api.put("/api/push/endpoint", json={"endpoint": ENDPOINT}).status_code == 401


def test_the_password_is_refused_because_it_has_no_device_identity(api):
    for method in ("get", "put", "delete"):
        resp = getattr(api, method)("/api/push/endpoint", json={"endpoint": ENDPOINT},
                                    headers=_basic())
        assert resp.status_code == 403, method
        assert "paired device" in resp.get_json()["error"]


def test_a_revoked_token_cannot_register(api, phone):
    secret, rec = phone
    device_tokens.revoke_token(rec.id)
    resp = api.put("/api/push/endpoint", json={"endpoint": ENDPOINT}, headers=_bearer(secret))
    assert resp.status_code == 401


# ── what may be registered ───────────────────────────────────────────────────


@pytest.mark.parametrize("bad", [
    "http://169.254.169.254/latest/meta-data/",
    "http://100.100.100.200/latest/",
    "http://metadata.google.internal/x",
    "http://[::ffff:169.254.169.254]/x",
    "http://rebind.example.net/x",       # does not resolve: refused, not guessed
    "file:///etc/passwd",
    "gopher://192.168.1.5/x",
    "https://user:pw@ntfy.example.org/up1",
    "",
])
def test_unsafe_endpoints_are_refused_and_nothing_is_stored(api, phone, bad):
    secret, rec = phone
    resp = api.put("/api/push/endpoint", json={"endpoint": bad}, headers=_bearer(secret))
    assert resp.status_code == 400
    assert device_tokens.get_push_endpoint(rec.id) is None


def test_a_non_object_body_is_refused(api, phone):
    secret, _ = phone
    resp = api.put("/api/push/endpoint", data="[1]", content_type="application/json",
                   headers=_bearer(secret))
    assert resp.status_code == 400


# ── the operator's view and revocation ───────────────────────────────────────


def test_the_device_list_shows_a_boolean_never_the_url(api, phone):
    secret, _ = phone
    api.put("/api/push/endpoint", json={"endpoint": ENDPOINT}, headers=_bearer(secret))
    listing = api.get("/api/auth/tokens", headers=_basic())
    assert listing.status_code == 200
    assert ENDPOINT not in listing.get_data(as_text=True)
    assert listing.get_json()["tokens"][0]["has_push_endpoint"] is True


def test_revoking_a_device_drops_its_endpoint(api, phone):
    secret, rec = phone
    api.put("/api/push/endpoint", json={"endpoint": ENDPOINT}, headers=_bearer(secret))
    assert device_tokens.push_targets() == [(rec.id, ENDPOINT)]
    device_tokens.revoke_token(rec.id)
    assert device_tokens.push_targets() == []
    assert device_tokens.list_tokens()[0].push_endpoint is None


def test_push_targets_skip_expired_devices(monkeypatch):
    secret, rec = device_tokens.mint_token("short-lived", ttl_days=1)
    device_tokens.set_push_endpoint(rec.id, ENDPOINT)
    assert device_tokens.push_targets() == [(rec.id, ENDPOINT)]
    monkeypatch.setattr(device_tokens, "_utc_now_iso", lambda: "2999-01-01 00:00:00")
    assert device_tokens.push_targets() == []
