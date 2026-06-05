"""
tests/test_setup.py

Tests the first-run Setup + destination chooser (FIX 1).

Covers: list_destinations offers options without auto-selecting (local first,
custom last, cloud only when detected), the three /api/setup/* routes, the
choose-persists-and-completes flow, and that the encrypted dir defaults to an
Encrypted subfolder of the chosen output. The no-implicit-cloud rule for
_default_output_dir is covered in test_default_output_dir.py.

Author: Bloodawn (KheivenD), 2026-06-03 (FIX 1).
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.services import cloud_detection as cd  # noqa: E402
from gui.services import gui_state_persist as gsp  # noqa: E402
from gui import state as gui_state  # noqa: E402


@pytest.fixture()
def restore_status():
    """Snapshot and restore the shared _status so tests don't leak choices."""
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


@pytest.fixture()
def isolated_state_file(tmp_path, monkeypatch):
    """Point the persistence file at a tmp location."""
    monkeypatch.setattr(gsp, "_GUI_STATE_FILE", tmp_path / "gui_state.json")


@pytest.fixture()
def client():
    from gui.app import app
    return app.test_client()


# ── list_destinations ────────────────────────────────────────────────────────

def test_destinations_local_first_custom_last():
    dests = cd.list_destinations()
    assert dests[0]["kind"] == cd.DEST_LOCAL
    assert dests[-1]["kind"] == cd.DEST_CUSTOM
    # every entry has the expected shape
    for d in dests:
        assert set(d) >= {"kind", "label", "path", "available"}


def test_destinations_custom_has_empty_path():
    custom = [d for d in cd.list_destinations() if d["kind"] == cd.DEST_CUSTOM][0]
    assert custom["path"] == ""  # free-form, nothing pre-filled


def test_destinations_cloud_only_when_detected(monkeypatch):
    # No cloud detected -> no onedrive/gdrive/icloud entries.
    monkeypatch.setattr(cd, "_detect_onedrive_root", lambda prefer_business=True: (None, None))
    monkeypatch.setattr(cd, "_detect_gdrive_root", lambda: None)
    monkeypatch.setattr(cd, "_detect_icloud_root", lambda: None)
    monkeypatch.setattr(cd, "_windows_drive_roots", lambda: [])
    kinds = {d["kind"] for d in cd.list_destinations()}
    assert kinds == {cd.DEST_LOCAL, cd.DEST_CUSTOM}


def test_destinations_includes_detected_onedrive(monkeypatch, tmp_path):
    fake = tmp_path / "OneDrive - Org"
    fake.mkdir()
    monkeypatch.setattr(cd, "_detect_onedrive_root",
                        lambda prefer_business=True: (fake, "OneDrive - Org"))
    monkeypatch.setattr(cd, "_detect_gdrive_root", lambda: None)
    monkeypatch.setattr(cd, "_detect_icloud_root", lambda: None)
    monkeypatch.setattr(cd, "_windows_drive_roots", lambda: [])
    od = [d for d in cd.list_destinations() if d["kind"] == cd.DEST_ONEDRIVE]
    assert len(od) == 1
    assert od[0]["path"].endswith("SVCS")


# ── routes ───────────────────────────────────────────────────────────────────

def test_route_state_shape(client):
    body = client.get("/api/setup/state").get_json()
    assert set(body) == {"setup_complete", "output_dir", "encrypted_dir",
                         "library_folder", "default_output_dir"}


def test_route_destinations_shape(client):
    body = client.get("/api/setup/destinations").get_json()
    assert "destinations" in body and isinstance(body["destinations"], list)
    assert "neutral_default" in body


def test_route_choose_requires_output_dir(client):
    assert client.post("/api/setup/choose", json={}).status_code == 400


def test_route_choose_persists_and_completes(client, tmp_path, restore_status, isolated_state_file):
    out = tmp_path / "chosen_out"
    resp = client.post("/api/setup/choose", json={"output_dir": str(out)})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] and body["setup_complete"]
    assert body["output_dir"] == str(out.resolve())
    # encrypted defaults to <output>/Encrypted
    assert body["encrypted_dir"] == str((out.resolve() / "Encrypted"))
    # folders were created
    assert out.exists() and (out / "Encrypted").exists()
    # state now reports complete + the chosen dirs
    st = client.get("/api/setup/state").get_json()
    assert st["setup_complete"] is True
    assert st["output_dir"] == str(out.resolve())


def test_route_choose_custom_encrypted_dir(client, tmp_path, restore_status, isolated_state_file):
    out = tmp_path / "out2"
    enc = tmp_path / "secure" / "enc"
    resp = client.post("/api/setup/choose",
                       json={"output_dir": str(out), "encrypted_dir": str(enc)})
    assert resp.status_code == 200
    assert resp.get_json()["encrypted_dir"] == str(enc.resolve())
    assert enc.exists()


def test_save_setup_choice_and_is_complete(tmp_path, restore_status, isolated_state_file):
    assert gsp.is_setup_complete() in (True, False)  # callable
    gsp.save_setup_choice(str(tmp_path / "o"), str(tmp_path / "e"))
    assert gsp.is_setup_complete() is True
    with gui_state._state_lock:
        assert gui_state._status["config"]["output_dir"] == str(tmp_path / "o")
        assert gui_state._status["config"]["encrypted_dir"] == str(tmp_path / "e")
