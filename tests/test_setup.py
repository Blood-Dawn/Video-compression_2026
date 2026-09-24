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


# ── /api/setup/update_check (Fall 3.17) ──────────────────────────────────────

class _FakeHTTPResponse:
    """Minimal stand-in for what urllib.request.urlopen(...) returns, enough
    for `with urllib.request.urlopen(req, timeout=5) as resp: resp.read()`."""

    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _releases_payload(*releases):
    import json as _json
    return _json.dumps(list(releases)).encode("utf-8")


def _release(tag, html_url="https://example.invalid/releases/x",
             draft=False, exe_asset=True):
    assets = []
    if exe_asset:
        assets.append({
            "name": f"SVCS-Setup-{tag.lstrip('v')}.exe",
            "browser_download_url": f"https://example.invalid/dl/{tag}.exe",
        })
    return {"tag_name": tag, "html_url": html_url, "draft": draft, "assets": assets}


class TestUpdateCheck:
    def test_newer_release_reports_update_available(self, client, monkeypatch):
        import gui.routes.setup_bp as setup_bp

        payload = _releases_payload(_release("v999.0.0"))
        monkeypatch.setattr(
            setup_bp.urllib.request, "urlopen",
            lambda req, timeout=5: _FakeHTTPResponse(payload),
        )
        r = client.get("/api/setup/update_check")
        body = r.get_json()
        assert r.status_code == 200
        assert body["checked"] is True
        assert body["update_available"] is True
        assert body["latest_version"] == "v999.0.0"
        assert body["download_url"] == "https://example.invalid/dl/v999.0.0.exe"
        assert body["current_version"] == setup_bp.APP_VERSION

    def test_older_release_reports_no_update(self, client, monkeypatch):
        import gui.routes.setup_bp as setup_bp

        payload = _releases_payload(_release("v0.0.1"))
        monkeypatch.setattr(
            setup_bp.urllib.request, "urlopen",
            lambda req, timeout=5: _FakeHTTPResponse(payload),
        )
        body = client.get("/api/setup/update_check").get_json()
        assert body["update_available"] is False
        assert body["latest_version"] == "v0.0.1"

    def test_mobile_tag_is_excluded(self, client, monkeypatch):
        """A newer MOBILE release must never look like a newer desktop build."""
        import gui.routes.setup_bp as setup_bp

        payload = _releases_payload(_release("mobile-v999.0.0"))
        monkeypatch.setattr(
            setup_bp.urllib.request, "urlopen",
            lambda req, timeout=5: _FakeHTTPResponse(payload),
        )
        body = client.get("/api/setup/update_check").get_json()
        assert body["update_available"] is False
        assert body["latest_version"] is None

    def test_apk_only_release_is_excluded(self, client, monkeypatch):
        """The real mobile release is tagged `v1-beta` with APKs only (no
        `mobile-` prefix). A higher-numbered APK-only tag must not read as a
        desktop update just because its version compares newer."""
        import gui.routes.setup_bp as setup_bp

        apk_only = _release("v999-beta", exe_asset=False)
        apk_only["assets"] = [{"name": "svcs-mobile-v999-beta.apk",
                               "browser_download_url": "https://example.invalid/a.apk"}]
        payload = _releases_payload(apk_only, _release("v0.0.1"))
        monkeypatch.setattr(
            setup_bp.urllib.request, "urlopen",
            lambda req, timeout=5: _FakeHTTPResponse(payload),
        )
        body = client.get("/api/setup/update_check").get_json()
        assert body["update_available"] is False
        assert body["latest_version"] == "v0.0.1"

    def test_draft_release_is_excluded(self, client, monkeypatch):
        import gui.routes.setup_bp as setup_bp

        payload = _releases_payload(_release("v999.0.0", draft=True))
        monkeypatch.setattr(
            setup_bp.urllib.request, "urlopen",
            lambda req, timeout=5: _FakeHTTPResponse(payload),
        )
        body = client.get("/api/setup/update_check").get_json()
        assert body["update_available"] is False

    def test_picks_the_newest_of_several_releases(self, client, monkeypatch):
        import gui.routes.setup_bp as setup_bp

        payload = _releases_payload(
            _release("v2.0.0-beta"), _release("v999.0.0"), _release("v0.5.0"),
        )
        monkeypatch.setattr(
            setup_bp.urllib.request, "urlopen",
            lambda req, timeout=5: _FakeHTTPResponse(payload),
        )
        body = client.get("/api/setup/update_check").get_json()
        assert body["latest_version"] == "v999.0.0"

    def test_network_failure_is_silent_not_an_error(self, client, monkeypatch):
        import urllib.error

        import gui.routes.setup_bp as setup_bp

        def _boom(req, timeout=5):
            raise urllib.error.URLError("no network")

        monkeypatch.setattr(setup_bp.urllib.request, "urlopen", _boom)
        r = client.get("/api/setup/update_check")
        body = r.get_json()
        assert r.status_code == 200
        assert body["checked"] is False
        assert body["update_available"] is False

    def test_malformed_json_is_silent_not_an_error(self, client, monkeypatch):
        import gui.routes.setup_bp as setup_bp

        monkeypatch.setattr(
            setup_bp.urllib.request, "urlopen",
            lambda req, timeout=5: _FakeHTTPResponse(b"not json"),
        )
        r = client.get("/api/setup/update_check")
        assert r.status_code == 200
        assert r.get_json()["checked"] is False

    def test_no_exe_asset_leaves_download_url_none(self, client, monkeypatch):
        import gui.routes.setup_bp as setup_bp

        payload = _releases_payload(_release("v999.0.0", exe_asset=False))
        monkeypatch.setattr(
            setup_bp.urllib.request, "urlopen",
            lambda req, timeout=5: _FakeHTTPResponse(payload),
        )
        body = client.get("/api/setup/update_check").get_json()
        assert body["update_available"] is True
        assert body["download_url"] is None
        assert body["release_url"] == "https://example.invalid/releases/x"
