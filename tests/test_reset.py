"""
tests/test_reset.py

Tests fresh-install hygiene + factory reset (FIX 2).

Covers paths.reset_state (deletes the per-install state files), the CPU sampler
historical-flag + reset_mode_avgs, and the POST /api/setup/reset route that
returns the app to first-run. All file operations are redirected to a tmp dir or
monkeypatched so the developer's real %LOCALAPPDATA%\\SVCS is never touched.

Author: Bloodawn (KheivenD), 2026-06-03 (FIX 2).
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils import paths as paths_mod  # noqa: E402
from gui.services import cpu_sampler as cs  # noqa: E402
from gui import state as gui_state  # noqa: E402


# ── paths.reset_state ────────────────────────────────────────────────────────

def test_reset_state_deletes_known_files(tmp_path, monkeypatch):
    monkeypatch.setattr(paths_mod, "data_dir", lambda: tmp_path)
    for name in paths_mod.STATE_FILE_NAMES:
        (tmp_path / name).write_text("x")
    removed = paths_mod.reset_state()
    assert set(removed) == set(paths_mod.STATE_FILE_NAMES)
    for name in paths_mod.STATE_FILE_NAMES:
        assert not (tmp_path / name).exists()


def test_reset_state_ignores_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(paths_mod, "data_dir", lambda: tmp_path)
    assert paths_mod.reset_state() == []  # nothing to delete


def test_state_file_inventory_nonempty():
    assert "mode_cpu_avgs.json" in paths_mod.STATE_FILE_NAMES
    assert "gui_state.json" in paths_mod.STATE_FILE_NAMES


# ── cpu_sampler historical + reset ───────────────────────────────────────────

def test_reset_mode_avgs_clears(monkeypatch, tmp_path):
    # Point the mode-avg file at tmp so we never delete the real one.
    monkeypatch.setattr(cs, "_MODE_AVG_FILE", tmp_path / "mode_cpu_avgs.json")
    with cs._power_lock:
        cs._power_state["mode_avgs"]["mode0"] = {"cpu_sum": 10, "n": 5, "avg": 2.0}
    cs.reset_mode_avgs()
    with cs._power_lock:
        assert cs._power_state["mode_avgs"] == {}


# ── /api/setup/reset route ───────────────────────────────────────────────────

@pytest.fixture()
def client():
    from gui.app import app
    return app.test_client()


@pytest.fixture()
def restore_status():
    with gui_state._state_lock:
        prev_cfg = dict(gui_state._status.get("config", {}))
        prev_setup = gui_state._status.get("setup_complete")
    yield
    with gui_state._state_lock:
        gui_state._status["config"] = prev_cfg
        if prev_setup is None:
            gui_state._status.pop("setup_complete", None)
        else:
            gui_state._status["setup_complete"] = prev_setup


def test_reset_route_returns_to_first_run(client, monkeypatch, restore_status):
    import gui.routes.setup_bp as sbp
    # Stub the destructive helpers so no real files are removed.
    monkeypatch.setattr(sbp, "reset_state", lambda: ["mode_cpu_avgs.json"])
    monkeypatch.setattr(sbp, "reset_mode_avgs", lambda: None)
    # Pretend setup was complete with a chosen dir.
    with gui_state._state_lock:
        gui_state._status["setup_complete"] = True
        gui_state._status.setdefault("config", {})["output_dir"] = "C:/somewhere"

    resp = client.post("/api/setup/reset")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] and body["setup_complete"] is False
    assert "mode_cpu_avgs.json" in body["removed"]
    # state now reports first-run again
    st = client.get("/api/setup/state").get_json()
    assert st["setup_complete"] is False
    assert st["output_dir"] == ""


# ── PT-01: a device token cannot factory-reset (pentest 2026-10-03) ──────────
# reset_state() deletes device_tokens.json, so a token that could reset would
# be a stolen phone unpairing every other phone. The route must demand the
# PASSWORD, the same rule the token-management routes already enforce.

@pytest.fixture()
def guarded_reset(tmp_path, monkeypatch, restore_status):
    """setup_bp behind the real auth guard, with the destructive helper stubbed."""
    import base64
    from flask import Flask
    from gui import device_tokens
    from gui.auth import install_basic_auth
    import gui.routes.setup_bp as sbp

    monkeypatch.setattr(device_tokens, "token_path", lambda: tmp_path / "device_tokens.json")
    calls = []
    monkeypatch.setattr(sbp, "reset_state", lambda: calls.append("reset") or ["device_tokens.json"])
    monkeypatch.setattr(sbp, "reset_mode_avgs", lambda: None)
    with gui_state._state_lock:
        gui_state._status["setup_complete"] = True

    app = Flask(__name__)
    app.register_blueprint(sbp.setup_bp)
    install_basic_auth(app, "admin", "secret")
    basic = {"Authorization": "Basic " + base64.b64encode(b"admin:secret").decode("ascii")}
    secret, _ = device_tokens.mint_token("stolen phone")
    return app.test_client(), basic, {"Authorization": f"Bearer {secret}"}, calls


def test_a_device_token_cannot_factory_reset(guarded_reset):
    client, _basic, bearer, calls = guarded_reset
    resp = client.post("/api/setup/reset", headers=bearer)
    assert resp.status_code == 403
    assert "password" in resp.get_json()["error"]
    assert calls == [], "reset_state ran for a device token"
    assert gui_state._status["setup_complete"] is True


def test_the_password_can_still_factory_reset(guarded_reset):
    client, basic, _bearer, calls = guarded_reset
    resp = client.post("/api/setup/reset", headers=basic)
    assert resp.status_code == 200
    assert calls == ["reset"]
    assert gui_state._status["setup_complete"] is False
