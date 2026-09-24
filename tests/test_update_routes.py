"""
tests/test_update_routes.py

Route-level tests for the Fall 3.18 auto-update pipeline
(/api/update/status, /api/update/download, /api/update/install), which sits
behind gui.routes.update_bp and delegates all real work to
gui.services.update_manager (unit-tested in test_update_manager.py). These
tests only check the wiring: status shape, that download/install call
through to update_manager, that install refuses (400) when update_manager
says it can't, and that no client-supplied download URL can reach it.
"""

import inspect

import pytest

import gui.services.update_manager as um


@pytest.fixture()
def client():
    from gui.app import app
    return app.test_client()


@pytest.fixture(autouse=True)
def _reset_update_state():
    um.reset()
    yield
    um.reset()


class TestUpdateStatusRoute:
    def test_reports_idle_by_default(self, client):
        body = client.get("/api/update/status").get_json()
        assert body["phase"] == "idle"

    def test_reflects_manager_state(self, client):
        um._set(phase="ready", latest_version="v9.9.9", installer_path="C:/x.exe")
        body = client.get("/api/update/status").get_json()
        assert body["phase"] == "ready"
        assert body["latest_version"] == "v9.9.9"


class TestUpdateDownloadRoute:
    def test_calls_start_download(self, client, monkeypatch):
        seen = {}

        def _fake_start_download():
            seen["called"] = True
            return {"phase": "downloading"}

        monkeypatch.setattr(um, "start_download", _fake_start_download)
        r = client.post("/api/update/download")
        assert r.status_code == 200
        assert r.get_json()["phase"] == "downloading"
        assert seen.get("called") is True

    def test_ignores_a_client_supplied_download_url(self, client, monkeypatch):
        """A malicious/buggy client sending a download_url in the body must
        have no effect - start_download() takes no arguments at all, so
        there is nothing for a request body to override."""
        assert len(inspect.signature(um.start_download).parameters) == 0
        seen = {}

        def _fake_start_download():
            seen["called"] = True
            return {"phase": "downloading"}

        monkeypatch.setattr(um, "start_download", _fake_start_download)
        r = client.post(
            "/api/update/download",
            json={"download_url": "https://evil.example/malware.exe"},
        )
        assert r.status_code == 200
        assert seen.get("called") is True


class TestUpdateInstallRoute:
    def test_refuses_with_400_when_not_ready(self, client):
        r = client.post("/api/update/install")
        assert r.status_code == 400
        assert r.get_json()["ok"] is False

    def test_calls_install_and_quits_when_ready(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(
            um, "install_and_restart", lambda: {"ok": True, "restarting": True}
        )
        monkeypatch.setattr(um, "quit_app_for_update", lambda: calls.append("quit"))
        r = client.post("/api/update/install")
        assert r.status_code == 200
        assert r.get_json() == {"ok": True, "restarting": True}
        assert calls == ["quit"]

    def test_does_not_quit_when_install_refused(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(
            um, "install_and_restart",
            lambda: {"ok": False, "error": "No verified update is ready to install."},
        )
        monkeypatch.setattr(um, "quit_app_for_update", lambda: calls.append("quit"))
        r = client.post("/api/update/install")
        assert r.status_code == 400
        assert calls == []
