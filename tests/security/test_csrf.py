"""
tests/security/test_csrf.py  (SEC-001)

Assert the same-origin CSRF guard blocks a cross-origin state-changing POST (the
malicious-page-drives-the-dashboard attack) while allowing same-origin and
non-browser (no Origin/Referer) requests, and never interfering with safe GETs.
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.csrf import is_cross_origin  # noqa: E402

# A representative set of state-changing POSTs across blueprints.
STATE_CHANGING_POSTS = [
    "/api/start",
    "/api/stop",
    "/api/autocompress/start",
    "/api/autocompress/stop",
    "/api/decrypt",
    "/api/encrypt",
    "/api/setup/reset",
    "/api/segments/clear",
    "/api/hls/start",
]


@pytest.fixture()
def client():
    from gui.app import app
    return app.test_client()


@pytest.fixture(autouse=True)
def _contain_the_side_effects(tmp_path, monkeypatch):
    """Point the real destructive routes at tmp before POSTing to them.

    The list above is deliberately made of REAL state-changing routes, and the
    same-origin cases below assert the guard lets them through, which means the
    handlers actually run. Two of them bite the developer's own install:

      * ``/api/setup/reset`` is a factory reset. It deletes flask_secret,
        gui_state.json, job_history.json and device_tokens.json out of
        ``paths.data_dir()``. Deleting device_tokens.json unpairs every phone
        that has ever paired with this install, permanently, and the suite was
        doing it twice per run. A phone that had been working all evening would
        start answering "the server rejected that token" with nothing in the
        session to explain why.
      * ``/api/segments/clear`` flags every row in the configured output
        folder's metadata.db as hidden, so a real run's recordings vanish from
        the dashboard.

    Redirecting data_dir and the configured output_dir keeps the assertion
    exactly as strong (the request still reaches the handler, the handler still
    runs) while the damage lands in tmp. The in-memory setup flag is restored
    too, because the reset route flips it on the shared app object.

    Author: Bloodawn (KheivenD), 2026-08-17 (found during R6 Track C).
    """
    from utils import paths as paths_mod
    from gui import state as gui_state

    d = tmp_path / "state"
    d.mkdir()
    monkeypatch.setattr(paths_mod, "data_dir", lambda: d)

    with gui_state._state_lock:
        prev_cfg = dict(gui_state._status.get("config", {}))
        prev_setup = gui_state._status.get("setup_complete")
        gui_state._status.setdefault("config", {})["output_dir"] = str(tmp_path / "out")
    try:
        yield
    finally:
        with gui_state._state_lock:
            gui_state._status["config"] = prev_cfg
            if prev_setup is None:
                gui_state._status.pop("setup_complete", None)
            else:
                gui_state._status["setup_complete"] = prev_setup


# ── pure helper ───────────────────────────────────────────────────────────────

def test_is_cross_origin_logic():
    assert is_cross_origin("http://evil.com", None, "127.0.0.1:5000") is True
    assert is_cross_origin("http://127.0.0.1:5000", None, "127.0.0.1:5000") is False
    # Referer fallback when Origin is absent.
    assert is_cross_origin(None, "http://evil.com/x", "127.0.0.1:5000") is True
    assert is_cross_origin(None, "http://127.0.0.1:5000/", "127.0.0.1:5000") is False
    # Neither header -> treated as same-origin (non-browser client).
    assert is_cross_origin(None, None, "127.0.0.1:5000") is False


# ── route behaviour ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("route", STATE_CHANGING_POSTS)
def test_cross_origin_post_is_blocked(client, route):
    resp = client.post(route, headers={"Origin": "http://evil.example"},
                       json={})
    assert resp.status_code == 403, f"{route} allowed a cross-origin POST"
    assert b"CSRF" in resp.data


@pytest.mark.parametrize("route", STATE_CHANGING_POSTS)
def test_same_origin_post_is_not_csrf_blocked(client, route):
    # Same-origin POST: the guard must let it through to the handler (which may
    # then 400/409/etc on its own merits, but never 403-CSRF).
    resp = client.post(route, headers={"Origin": "http://localhost"}, json={})
    # Flask test client uses host "localhost" by default.
    assert resp.status_code != 403 or b"CSRF" not in resp.data


@pytest.mark.parametrize("route", STATE_CHANGING_POSTS)
def test_no_origin_post_is_allowed(client, route):
    # Non-browser client (no Origin/Referer) is allowed (no breakage for tools).
    resp = client.post(route, json={})
    assert resp.status_code != 403 or b"CSRF" not in resp.data


def test_cross_origin_get_is_allowed(client):
    # Safe methods are never CSRF-blocked.
    resp = client.get("/api/status", headers={"Origin": "http://evil.example"})
    assert resp.status_code == 200
