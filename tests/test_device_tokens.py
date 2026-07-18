"""
tests/test_device_tokens.py

M0.10: per-device access tokens for the mobile client.

Covers the store (mint / verify / revoke / expire), the auth guard's acceptance
of Bearer alongside Basic, and the privilege rule that matters most: a device
token must NOT be able to mint successors or revoke other devices, because
otherwise a stolen phone both persists and locks the owner out.

Also pins the two properties that make a leaked token file survivable:
the secret is never persisted (only its SHA-256), and the public view never
exposes the hash.

Author: Bloodawn (KheivenD), 2026-07-18 (M0.10).
"""

import base64
import json
import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui import device_tokens                                   # noqa: E402
from gui.auth import install_basic_auth                         # noqa: E402
from gui.routes.tokens_bp import tokens_bp                      # noqa: E402


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Point the token store at a temp file so tests never touch real state."""
    store = tmp_path / "device_tokens.json"
    monkeypatch.setattr(device_tokens, "token_path", lambda: store)
    return store


def _basic(user, pw):
    blob = base64.b64encode(f"{user}:{pw}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {blob}"}


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


# ── the store ─────────────────────────────────────────────────────────────────

def test_mint_returns_a_prefixed_secret_and_verifies(isolated_store):
    secret, rec = device_tokens.mint_token("Pixel 8")
    assert secret.startswith(device_tokens.TOKEN_PREFIX)
    assert rec.label == "Pixel 8"
    assert device_tokens.verify_token(secret) is not None


def test_secret_is_never_persisted(isolated_store):
    """A leaked token file must not yield working credentials."""
    secret, _ = device_tokens.mint_token("Pixel 8")
    raw = isolated_store.read_text(encoding="utf-8")
    assert secret not in raw, "the token secret was written to disk"
    assert device_tokens.token_hash(secret) in raw, "expected the hash on disk"


def test_public_view_withholds_the_hash(isolated_store):
    """The listing must not enable an offline guessing attack."""
    _, rec = device_tokens.mint_token("Pixel 8")
    pub = rec.to_public()
    assert "sha256" not in pub
    assert set(pub) == {"id", "label", "created_at", "last_used_at",
                        "expires_at", "revoked", "expired"}


def test_wrong_token_does_not_verify(isolated_store):
    device_tokens.mint_token("Pixel 8")
    assert device_tokens.verify_token("svcs_not-a-real-token") is None


def test_value_without_the_prefix_is_rejected(isolated_store):
    secret, _ = device_tokens.mint_token("Pixel 8")
    stripped = secret[len(device_tokens.TOKEN_PREFIX):]
    assert device_tokens.verify_token(stripped) is None


@pytest.mark.parametrize("junk", ["", None, "Bearer", "svcs_", "  "])
def test_junk_never_verifies(isolated_store, junk):
    device_tokens.mint_token("Pixel 8")
    assert device_tokens.verify_token(junk) is None


def test_revoked_token_stops_verifying(isolated_store):
    secret, rec = device_tokens.mint_token("Pixel 8")
    assert device_tokens.verify_token(secret) is not None
    assert device_tokens.revoke_token(rec.id) is True
    assert device_tokens.verify_token(secret) is None


def test_revoking_one_device_leaves_the_others(isolated_store):
    """The whole point of tokens: cut off one phone, not every client."""
    a_secret, a = device_tokens.mint_token("lost phone")
    b_secret, _ = device_tokens.mint_token("laptop")
    device_tokens.revoke_token(a.id)
    assert device_tokens.verify_token(a_secret) is None
    assert device_tokens.verify_token(b_secret) is not None


def test_revoke_all(isolated_store):
    s1, _ = device_tokens.mint_token("a")
    s2, _ = device_tokens.mint_token("b")
    assert device_tokens.revoke_all() == 2
    assert device_tokens.verify_token(s1) is None
    assert device_tokens.verify_token(s2) is None
    assert device_tokens.revoke_all() == 0        # idempotent


def test_revoking_unknown_id_is_false(isolated_store):
    assert device_tokens.revoke_token("nope") is False


def test_expired_token_stops_verifying(isolated_store, monkeypatch):
    secret, _ = device_tokens.mint_token("temp", ttl_days=1)
    assert device_tokens.verify_token(secret) is not None
    # Jump past the expiry without waiting.
    monkeypatch.setattr(device_tokens, "_utc_now_iso", lambda: "2099-01-01 00:00:00")
    assert device_tokens.verify_token(secret) is None


def test_last_used_is_stamped(isolated_store):
    secret, rec = device_tokens.mint_token("Pixel 8")
    assert rec.last_used_at is None
    device_tokens.verify_token(secret)
    reread = [t for t in device_tokens.list_tokens() if t.id == rec.id][0]
    assert reread.last_used_at is not None


def test_corrupt_store_fails_closed(isolated_store):
    """A broken file denies token holders rather than admitting them."""
    isolated_store.write_text("{ not json", encoding="utf-8")
    assert device_tokens.list_tokens() == []
    assert device_tokens.verify_token("svcs_anything") is None


def test_one_corrupt_record_does_not_break_the_others(isolated_store):
    secret, _ = device_tokens.mint_token("good")
    blob = json.loads(isolated_store.read_text(encoding="utf-8"))
    blob["tokens"].insert(0, {"id": "", "sha256": "too-short"})   # malformed
    isolated_store.write_text(json.dumps(blob), encoding="utf-8")
    assert device_tokens.verify_token(secret) is not None


def test_missing_store_is_not_an_error(isolated_store):
    assert device_tokens.list_tokens() == []
    assert device_tokens.any_tokens_configured() is False


def test_token_file_is_in_the_factory_reset_list():
    """A factory reset must revoke every paired device."""
    from utils.paths import STATE_FILE_NAMES
    assert device_tokens.TOKEN_FILE_NAME in STATE_FILE_NAMES


# ── the auth guard accepts Bearer alongside Basic ────────────────────────────

@pytest.fixture()
def guarded_client():
    app = Flask(__name__)

    @app.route("/")
    def index():
        return "ok"

    install_basic_auth(app, "admin", "secret")
    return app.test_client()


def test_bearer_token_authenticates(guarded_client, isolated_store):
    secret, _ = device_tokens.mint_token("Pixel 8")
    assert guarded_client.get("/", headers=_bearer(secret)).status_code == 200


def test_basic_still_authenticates(guarded_client, isolated_store):
    """The browser path must be unchanged by adding tokens."""
    assert guarded_client.get("/", headers=_basic("admin", "secret")).status_code == 200


def test_revoked_token_is_401_at_the_guard(guarded_client, isolated_store):
    secret, rec = device_tokens.mint_token("Pixel 8")
    device_tokens.revoke_token(rec.id)
    assert guarded_client.get("/", headers=_bearer(secret)).status_code == 401


def test_bogus_bearer_is_401(guarded_client, isolated_store):
    assert guarded_client.get("/", headers=_bearer("svcs_nope")).status_code == 401


def test_no_credential_is_still_401(guarded_client, isolated_store):
    resp = guarded_client.get("/")
    assert resp.status_code == 401
    # Both accepted schemes are advertised so a client knows a token will do.
    www = resp.headers.get("WWW-Authenticate", "")
    assert "Basic" in www and "Bearer" in www


# ── the privilege rule ────────────────────────────────────────────────────────

@pytest.fixture()
def token_api():
    """App with the token routes behind the real auth guard."""
    app = Flask(__name__)
    app.register_blueprint(tokens_bp)
    install_basic_auth(app, "admin", "secret")
    return app.test_client()


def test_password_can_mint_and_list(token_api, isolated_store):
    resp = token_api.post("/api/auth/tokens", json={"label": "Pixel 8"},
                          headers=_basic("admin", "secret"))
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["token"].startswith(device_tokens.TOKEN_PREFIX)
    assert body["label"] == "Pixel 8"

    listed = token_api.get("/api/auth/tokens", headers=_basic("admin", "secret"))
    assert listed.status_code == 200
    assert listed.get_json()["count"] == 1
    # The listing must not leak the secret or the hash.
    assert body["token"] not in listed.get_data(as_text=True)
    assert "sha256" not in listed.get_data(as_text=True)


def test_a_device_token_cannot_mint_another(token_api, isolated_store):
    """A stolen phone must not be able to issue itself successors."""
    secret, _ = device_tokens.mint_token("stolen phone")
    resp = token_api.post("/api/auth/tokens", json={"label": "attacker"},
                          headers=_bearer(secret))
    assert resp.status_code == 403
    assert len([t for t in device_tokens.list_tokens() if t.is_usable()]) == 1


def test_a_device_token_cannot_revoke_other_devices(token_api, isolated_store):
    """A stolen phone must not be able to lock the owner out."""
    _, victim = device_tokens.mint_token("owner laptop")
    thief_secret, _ = device_tokens.mint_token("stolen phone")
    resp = token_api.delete(f"/api/auth/tokens/{victim.id}",
                            headers=_bearer(thief_secret))
    assert resp.status_code == 403
    assert [t for t in device_tokens.list_tokens() if t.id == victim.id][0].revoked is False


def test_a_device_token_cannot_revoke_all(token_api, isolated_store):
    secret, _ = device_tokens.mint_token("stolen phone")
    resp = token_api.post("/api/auth/tokens/revoke_all", headers=_bearer(secret))
    assert resp.status_code == 403


def test_a_device_token_cannot_list_devices(token_api, isolated_store):
    """Enumerating the owner's other devices is reconnaissance."""
    secret, _ = device_tokens.mint_token("stolen phone")
    assert token_api.get("/api/auth/tokens", headers=_bearer(secret)).status_code == 403


def test_password_can_revoke(token_api, isolated_store):
    _, rec = device_tokens.mint_token("Pixel 8")
    resp = token_api.delete(f"/api/auth/tokens/{rec.id}",
                            headers=_basic("admin", "secret"))
    assert resp.status_code == 200
    assert resp.get_json()["revoked"] is True


def test_revoking_unknown_id_is_404(token_api, isolated_store):
    resp = token_api.delete("/api/auth/tokens/nope", headers=_basic("admin", "secret"))
    assert resp.status_code == 404


def test_unauthenticated_cannot_reach_the_token_api(token_api, isolated_store):
    assert token_api.get("/api/auth/tokens").status_code == 401
    assert token_api.post("/api/auth/tokens", json={}).status_code == 401
