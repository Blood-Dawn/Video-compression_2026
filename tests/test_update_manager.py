"""
tests/test_update_manager.py

Fall 3.18 - the desktop auto-update pipeline (gui.services.update_manager):
download the latest installer, verify it against the release's own
SHA256SUMS.txt, and (Windows only) hand off to a detached helper that
installs it and restarts the app.

Covers:
- check_for_update() finding a newer release and staying silent on network
  failure (the full matrix of "which release is newest" - mobile tag
  exclusion, apk-only exclusion, draft exclusion, picking the newest of
  several - stays in test_setup.py's TestUpdateCheck, which now exercises
  this same shared logic through the /api/setup/update_check route).
- _fetch_checksum()'s parsing of a SHA256SUMS.txt-style body.
- The download -> verify -> ready pipeline, including refusing to install on
  a checksum mismatch or a missing/unreachable checksums file.
- install_and_restart()'s phase gating (refuses unless "ready" with a file
  actually on disk) and that it spawns a detached helper rather than running
  the installer itself.
- quit_app_for_update() actually scheduling process exit.
"""

import hashlib
import json
import threading
import time
from pathlib import Path

import pytest

import gui.services.update_manager as um


class _FakeHTTPResponse:
    """Minimal stand-in for urllib.request.urlopen(...)'s return value."""

    def __init__(self, body: bytes, headers=None):
        self._body = body
        self.headers = headers or {}

    def read(self, n=-1):
        if n is None or n < 0:
            data, self._body = self._body, b""
            return data
        data, self._body = self._body[:n], self._body[n:]
        return data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _reset_state():
    um.reset()
    yield
    um.reset()


def _releases_payload(*releases):
    return json.dumps(list(releases)).encode("utf-8")


def _release(tag, exe_name="SVCS-Setup-999.0.0.exe", checksum=True, exe_asset=True):
    assets = []
    if exe_asset:
        assets.append({
            "name": exe_name,
            "browser_download_url": f"https://example.invalid/dl/{exe_name}",
        })
    if checksum:
        assets.append({
            "name": "SHA256SUMS.txt",
            "browser_download_url": "https://example.invalid/dl/SHA256SUMS.txt",
        })
    return {
        "tag_name": tag, "html_url": "https://example.invalid/releases/x",
        "draft": False, "assets": assets,
    }


class TestCheckForUpdate:
    def test_finds_newer_release(self, monkeypatch):
        payload = _releases_payload(_release("v999.0.0"))
        monkeypatch.setattr(
            um.urllib.request, "urlopen",
            lambda req, timeout=5: _FakeHTTPResponse(payload),
        )
        result = um.check_for_update(current_version="1.0.0")
        assert result["checked"] is True
        assert result["update_available"] is True
        assert result["latest_version"] == "v999.0.0"
        assert result["download_url"].endswith(".exe")
        assert result["checksum_url"].endswith("SHA256SUMS.txt")

    def test_older_release_reports_no_update(self, monkeypatch):
        payload = _releases_payload(_release("v0.0.1"))
        monkeypatch.setattr(
            um.urllib.request, "urlopen",
            lambda req, timeout=5: _FakeHTTPResponse(payload),
        )
        result = um.check_for_update(current_version="5.0.0")
        assert result["update_available"] is False

    def test_network_failure_is_silent(self, monkeypatch):
        import urllib.error

        def _boom(req, timeout=5):
            raise urllib.error.URLError("no network")

        monkeypatch.setattr(um.urllib.request, "urlopen", _boom)
        result = um.check_for_update()
        assert result["checked"] is False
        assert result["update_available"] is False


class TestFetchChecksum:
    def test_parses_matching_line(self, monkeypatch):
        digest = "a" * 64
        body = f"{digest}  SVCS-Setup-1.0.0.exe\n".encode()
        monkeypatch.setattr(
            um.urllib.request, "urlopen",
            lambda req, timeout=8: _FakeHTTPResponse(body),
        )
        assert um._fetch_checksum(
            "https://x/SHA256SUMS.txt", "SVCS-Setup-1.0.0.exe"
        ) == digest

    def test_ignores_unrelated_lines_and_binary_marker(self, monkeypatch):
        digest = "b" * 64
        body = (
            "# comment\n"
            f"{'c' * 64}  other-file.exe\n"
            f"{digest} *SVCS-Setup-1.0.0.exe\n"
        ).encode()
        monkeypatch.setattr(
            um.urllib.request, "urlopen",
            lambda req, timeout=8: _FakeHTTPResponse(body),
        )
        assert um._fetch_checksum(
            "https://x/SHA256SUMS.txt", "SVCS-Setup-1.0.0.exe"
        ) == digest

    def test_missing_file_returns_none(self, monkeypatch):
        body = f"{'d' * 64}  SomeOtherInstaller.exe\n".encode()
        monkeypatch.setattr(
            um.urllib.request, "urlopen",
            lambda req, timeout=8: _FakeHTTPResponse(body),
        )
        assert um._fetch_checksum(
            "https://x/SHA256SUMS.txt", "SVCS-Setup-1.0.0.exe"
        ) is None

    def test_network_failure_returns_none(self, monkeypatch):
        import urllib.error

        def _boom(req, timeout=8):
            raise urllib.error.URLError("no network")

        monkeypatch.setattr(um.urllib.request, "urlopen", _boom)
        assert um._fetch_checksum("https://x/SHA256SUMS.txt", "x.exe") is None


class TestDownloadAndVerify:
    def test_successful_download_reaches_ready(self, monkeypatch, tmp_path):
        exe_bytes = b"fake installer bytes " * 100
        digest = hashlib.sha256(exe_bytes).hexdigest()
        name = "SVCS-Setup-999.0.0.exe"
        checksum_body = f"{digest}  {name}\n".encode()

        monkeypatch.setattr(um, "_staging_dir", lambda: tmp_path)

        def _fake_urlopen(req, timeout=30):
            url = getattr(req, "full_url", req)
            if str(url).endswith(".exe"):
                return _FakeHTTPResponse(
                    exe_bytes, headers={"Content-Length": str(len(exe_bytes))}
                )
            return _FakeHTTPResponse(checksum_body)

        monkeypatch.setattr(um.urllib.request, "urlopen", _fake_urlopen)

        info = {
            "latest_version": "v999.0.0",
            "download_url": f"https://example.invalid/dl/{name}",
            "checksum_url": "https://example.invalid/dl/SHA256SUMS.txt",
        }
        um._download_and_verify(info)
        status = um.get_status()
        assert status["phase"] == "ready"
        assert status["installer_path"] == str(tmp_path / name)
        assert Path(status["installer_path"]).read_bytes() == exe_bytes

    def test_checksum_mismatch_refuses_and_discards(self, monkeypatch, tmp_path):
        exe_bytes = b"fake installer bytes " * 100
        name = "SVCS-Setup-999.0.0.exe"
        wrong_checksum_body = f"{'0' * 64}  {name}\n".encode()

        monkeypatch.setattr(um, "_staging_dir", lambda: tmp_path)

        def _fake_urlopen(req, timeout=30):
            url = getattr(req, "full_url", req)
            if str(url).endswith(".exe"):
                return _FakeHTTPResponse(
                    exe_bytes, headers={"Content-Length": str(len(exe_bytes))}
                )
            return _FakeHTTPResponse(wrong_checksum_body)

        monkeypatch.setattr(um.urllib.request, "urlopen", _fake_urlopen)

        info = {
            "latest_version": "v999.0.0",
            "download_url": f"https://example.invalid/dl/{name}",
            "checksum_url": "https://example.invalid/dl/SHA256SUMS.txt",
        }
        um._download_and_verify(info)
        status = um.get_status()
        assert status["phase"] == "error"
        assert "checksum" in status["error"].lower() or "mismatch" in status["error"].lower()
        assert not (tmp_path / name).exists()

    def test_missing_checksum_url_refuses_to_install(self, monkeypatch, tmp_path):
        exe_bytes = b"fake installer bytes"
        name = "SVCS-Setup-999.0.0.exe"
        monkeypatch.setattr(um, "_staging_dir", lambda: tmp_path)
        monkeypatch.setattr(
            um.urllib.request, "urlopen",
            lambda req, timeout=30: _FakeHTTPResponse(
                exe_bytes, headers={"Content-Length": str(len(exe_bytes))}
            ),
        )
        info = {
            "latest_version": "v999.0.0",
            "download_url": f"https://example.invalid/dl/{name}",
            "checksum_url": None,
        }
        um._download_and_verify(info)
        status = um.get_status()
        assert status["phase"] == "error"
        assert not (tmp_path / name).exists()

    def test_download_failure_sets_error(self, monkeypatch, tmp_path):
        import urllib.error

        monkeypatch.setattr(um, "_staging_dir", lambda: tmp_path)

        def _boom(req, timeout=30):
            raise urllib.error.URLError("no network")

        monkeypatch.setattr(um.urllib.request, "urlopen", _boom)
        info = {
            "latest_version": "v999.0.0",
            "download_url": "https://example.invalid/dl/x.exe",
            "checksum_url": None,
        }
        um._download_and_verify(info)
        assert um.get_status()["phase"] == "error"


class TestStartDownload:
    def test_no_update_available_sets_error(self, monkeypatch):
        monkeypatch.setattr(um, "check_for_update", lambda: {
            "update_available": False, "download_url": None, "latest_version": None,
        })
        status = um.start_download()
        assert status["phase"] == "error"

    def test_starts_background_thread_and_completes(self, monkeypatch, tmp_path):
        exe_bytes = b"x" * 1000
        digest = hashlib.sha256(exe_bytes).hexdigest()
        name = "SVCS-Setup-999.0.0.exe"
        checksum_body = f"{digest}  {name}\n".encode()

        monkeypatch.setattr(um, "_staging_dir", lambda: tmp_path)
        monkeypatch.setattr(um, "check_for_update", lambda: {
            "update_available": True,
            "latest_version": "v999.0.0",
            "download_url": f"https://example.invalid/dl/{name}",
            "checksum_url": "https://example.invalid/dl/SHA256SUMS.txt",
        })

        def _fake_urlopen(req, timeout=30):
            url = getattr(req, "full_url", req)
            if str(url).endswith(".exe"):
                return _FakeHTTPResponse(
                    exe_bytes, headers={"Content-Length": str(len(exe_bytes))}
                )
            return _FakeHTTPResponse(checksum_body)

        monkeypatch.setattr(um.urllib.request, "urlopen", _fake_urlopen)

        status = um.start_download()
        assert status["phase"] == "downloading"

        deadline = time.time() + 5
        while time.time() < deadline and um.get_status()["phase"] not in ("ready", "error"):
            time.sleep(0.05)
        final = um.get_status()
        assert final["phase"] == "ready", final

    def test_already_in_progress_is_a_noop(self, monkeypatch):
        um._set(phase="downloading")
        calls = []
        monkeypatch.setattr(um, "check_for_update", lambda: calls.append(1))
        status = um.start_download()
        assert status["phase"] == "downloading"
        assert calls == []  # never even re-checked GitHub


class TestInstallAndRestart:
    def test_refuses_when_not_ready(self):
        result = um.install_and_restart()
        assert result["ok"] is False

    def test_refuses_when_installer_file_missing(self, tmp_path):
        um._set(phase="ready", installer_path=str(tmp_path / "nope.exe"))
        result = um.install_and_restart()
        assert result["ok"] is False
        assert um.get_status()["phase"] == "error"

    def test_refuses_on_non_windows(self, monkeypatch, tmp_path):
        installer = tmp_path / "SVCS-Setup.exe"
        installer.write_bytes(b"x")
        um._set(phase="ready", installer_path=str(installer))
        monkeypatch.setattr(um.sys, "platform", "linux")
        result = um.install_and_restart()
        assert result["ok"] is False
        assert "windows" in result["error"].lower()

    def test_spawns_detached_helper_on_windows(self, monkeypatch, tmp_path):
        installer = tmp_path / "SVCS-Setup.exe"
        installer.write_bytes(b"x")
        um._set(phase="ready", installer_path=str(installer))
        monkeypatch.setattr(um.sys, "platform", "win32")
        monkeypatch.setattr(um, "_staging_dir", lambda: tmp_path)
        # DETACHED_PROCESS / CREATE_NEW_PROCESS_GROUP only exist on the
        # subprocess module when running on Windows; force them present so
        # this test's logic (not the OS) is what's under test.
        monkeypatch.setattr(um.subprocess, "DETACHED_PROCESS", 0x00000008, raising=False)
        monkeypatch.setattr(um.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)

        calls = {}

        def _fake_popen(cmd, creationflags=None, close_fds=None):
            calls["cmd"] = cmd
            calls["creationflags"] = creationflags
            return object()

        monkeypatch.setattr(um.subprocess, "Popen", _fake_popen)
        result = um.install_and_restart(app_exe_path=r"C:\Program Files\SVCS\SVCS.exe")
        assert result == {"ok": True, "restarting": True}
        assert um.get_status()["phase"] == "installing"
        assert "cmd" in calls
        assert "powershell" in calls["cmd"][0].lower()
        script = calls["cmd"][-1]
        assert str(installer) in script
        assert "/VERYSILENT" in script
        assert r"C:\Program Files\SVCS\SVCS.exe" in script

    def test_popen_failure_sets_error(self, monkeypatch, tmp_path):
        installer = tmp_path / "SVCS-Setup.exe"
        installer.write_bytes(b"x")
        um._set(phase="ready", installer_path=str(installer))
        monkeypatch.setattr(um.sys, "platform", "win32")
        monkeypatch.setattr(um, "_staging_dir", lambda: tmp_path)
        monkeypatch.setattr(um.subprocess, "DETACHED_PROCESS", 0x8, raising=False)
        monkeypatch.setattr(um.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)

        def _boom(*a, **k):
            raise OSError("no powershell")

        monkeypatch.setattr(um.subprocess, "Popen", _boom)
        result = um.install_and_restart()
        assert result["ok"] is False
        assert um.get_status()["phase"] == "error"


class TestQuitAppForUpdate:
    def test_schedules_exit_on_background_thread(self, monkeypatch):
        called = threading.Event()
        monkeypatch.setattr(um.os, "_exit", lambda code: called.set())
        um.quit_app_for_update(delay_seconds=0.01)
        assert called.wait(timeout=2), "os._exit was not called"
