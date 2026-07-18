"""
tests/test_mobile_client_contract.py

The server-side contract the Android client depends on (M1.1).

The Android module in mobile/android cannot be compiled or run in this
environment (no JDK, no Android SDK, no Gradle), so its own tests cannot gate
anything here. What CAN be pinned, and what actually matters, is the HTTP
contract it codes against: if these assertions hold, a correct client works, and
if someone changes the server in a way that breaks the phone, this fails on the
Python side where CI does run.

Every request below is shaped exactly as the Kotlin client issues it:
Authorization: Bearer on a plain OkHttp call, no Origin and no Referer headers
(a native client sends neither), and separate connections for API, media, and
HLS, since ExoPlayer fetches on its own connection.

Author: Bloodawn (KheivenD), 2026-07-18 (M1.1 - mobile client contract).
"""

import base64
import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui import device_tokens                                    # noqa: E402
from gui.app import register_blueprints                          # noqa: E402
from gui.auth import install_basic_auth                          # noqa: E402


@pytest.fixture(autouse=True)
def isolated_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(device_tokens, "token_path",
                        lambda: tmp_path / "device_tokens.json")


@pytest.fixture()
def paired():
    """A server with auth enabled and one paired device, like a real setup."""
    app = Flask(__name__)
    register_blueprints(app, edition="server")
    install_basic_auth(app, "operator", "dashboard-pw")
    secret, _ = device_tokens.mint_token("Pixel 8")
    app.config["TESTING"] = True
    return app.test_client(), secret


def _bearer(tok):
    """Exactly what the Kotlin client sends: nothing else."""
    return {"Authorization": f"Bearer {tok}"}


# ── pairing ───────────────────────────────────────────────────────────────────

def test_capabilities_is_reachable_with_only_a_token(paired):
    """The pairing screen's Test button: token in, server identity out."""
    client, token = paired
    r = client.get("/api/capabilities", headers=_bearer(token))
    assert r.status_code == 200
    d = r.get_json()
    assert d["app"] == "SVCS"
    assert d["edition"] in ("server", "field")
    assert isinstance(d["features"], dict)


def test_capabilities_401s_with_a_bad_token(paired):
    """A wrong token must read as "wrong credential", not as a broken server."""
    client, _ = paired
    r = client.get("/api/capabilities", headers=_bearer("svcs_wrong"))
    assert r.status_code == 401


def test_native_client_sends_no_origin_and_is_not_csrf_blocked(paired):
    """A native client sends neither Origin nor Referer.

    The CSRF guard treats that as same-origin and allows it, which is the
    reason a native client works against this server with no change. A WebView
    would send Origin and be 403'd on every POST, which is what ruled that
    approach out.
    """
    client, token = paired
    r = client.post("/api/auth/tokens", json={"label": "x"},
                    headers=_bearer(token))
    # 403 here is the TOKEN-privilege refusal, not the CSRF one. Distinguish.
    assert r.status_code != 400
    body = r.get_data(as_text=True).lower()
    assert "cross-origin" not in body, (
        "a native client without Origin was blocked by the CSRF guard")


# ── the streaming credential path ─────────────────────────────────────────────

def test_media_route_accepts_the_same_bearer_token(paired, tmp_path, monkeypatch):
    """ExoPlayer fetches on its OWN connection, so the credential must travel
    in a header rather than a session cookie. This is the single property that
    makes the LIVE and playback tabs possible."""
    client, token = paired
    r = client.get("/media/does-not-exist.mp4", headers=_bearer(token))
    # 404 or 403 both prove auth passed; 401 would mean the token was rejected.
    assert r.status_code != 401, "the media route rejected a valid device token"


def test_hls_segment_route_accepts_the_same_bearer_token(paired):
    client, token = paired
    r = client.get("/api/hls/cam_00/playlist0.ts", headers=_bearer(token))
    assert r.status_code != 401, "the HLS segment route rejected a valid token"


def test_library_thumb_accepts_the_same_bearer_token(paired):
    """Coil loads thumbnails on its own connection too."""
    client, token = paired
    r = client.get("/api/library/thumb?path=nope.mp4", headers=_bearer(token))
    assert r.status_code != 401


def test_every_surface_the_client_uses_rejects_no_credential(paired):
    """Nothing the phone touches may be reachable unauthenticated."""
    client, _ = paired
    for url in ("/api/capabilities", "/api/status", "/api/library/videos",
                "/api/system_metrics", "/media/x.mp4",
                "/api/hls/cam_00/playlist.m3u8", "/api/auth/tokens"):
        assert client.get(url).status_code == 401, f"{url} is open"


# ── token lifecycle from the phone's point of view ────────────────────────────

def test_revoking_the_phone_token_locks_the_phone_out_immediately(paired):
    """The reason tokens exist: a lost phone is cut off without rotating the
    password for every other client."""
    client, token = paired
    assert client.get("/api/capabilities", headers=_bearer(token)).status_code == 200

    rec = [t for t in device_tokens.list_tokens() if t.is_usable()][0]
    device_tokens.revoke_token(rec.id)

    assert client.get("/api/capabilities", headers=_bearer(token)).status_code == 401
    # ...and the dashboard password still works, untouched.
    blob = base64.b64encode(b"operator:dashboard-pw").decode("ascii")
    assert client.get("/api/capabilities",
                      headers={"Authorization": f"Basic {blob}"}).status_code == 200


def test_the_phone_cannot_escalate_to_token_management(paired):
    """If a phone is stolen, its token must not be able to mint successors or
    revoke the owner's other devices."""
    client, token = paired
    assert client.get("/api/auth/tokens", headers=_bearer(token)).status_code == 403
    assert client.post("/api/auth/tokens", json={"label": "evil"},
                       headers=_bearer(token)).status_code == 403
    assert client.post("/api/auth/tokens/revoke_all",
                       headers=_bearer(token)).status_code == 403


# ── shape stability ───────────────────────────────────────────────────────────

def test_capabilities_keys_the_client_parses_are_present(paired):
    """The Kotlin data class parses exactly these. A rename breaks the app on a
    user's phone, where it cannot be hot-fixed, so it fails here first."""
    client, token = paired
    d = client.get("/api/capabilities", headers=_bearer(token)).get_json()
    for key in ("capabilities_version", "app", "version", "edition",
                "edition_label", "server_features", "features", "auth"):
        assert key in d, f"the client parses {key!r} and it is missing"
    for feat in ("hls", "library", "upload", "metrics", "device_tokens"):
        assert feat in d["features"], f"the client reads features.{feat!r}"
    assert "schemes" in d["auth"]


def test_capabilities_version_is_an_int_the_client_can_compare(paired):
    client, token = paired
    v = client.get("/api/capabilities", headers=_bearer(token)).get_json()
    assert isinstance(v["capabilities_version"], int)
