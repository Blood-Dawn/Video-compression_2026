"""
tests/test_button_sweep_fixes.py

Regression tests for the buttons that looked fine in the dev venv but did
nothing in the installed app (found by hand on 2026-11-25):

  * Browse on Encrypt / Unlock: /api/browse ran ``sys.executable -c`` which is
    SVCS.exe in the installed app, so no dialog ever opened.
  * Home "Compress this video" after an upload only switched to the tab it was
    already on.
  * Double-clicking a .enc file: the registry pointed at SVCS-Unlock.exe but the
    build never produced it.
  * Pair a device: no server address was shown, and the device name had to be
    typed in before the phone was known.

Author: Bloodawn (KheivenD), 2026-11-25 (button sweep).
"""
import base64
import subprocess
import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui import device_tokens, native_dialog         # noqa: E402
from gui.auth import install_basic_auth              # noqa: E402
from gui.routes.files_bp import files_bp             # noqa: E402
from gui.routes.tokens_bp import tokens_bp           # noqa: E402

JS = SRC / "gui" / "static" / "js"


# ── native file dialog ───────────────────────────────────────────────────


class _R:
    def __init__(self, out):
        self.stdout = out


def test_pick_file_uses_powershell_on_windows_never_sys_executable(monkeypatch):
    seen = {}

    def fake_run(cmd, *a, **k):
        seen["cmd"] = cmd
        return _R("C:\\clips\\a.mp4.enc".encode("utf-8"))

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "platform", "win32")
    assert native_dialog.pick_file("enc") == "C:\\clips\\a.mp4.enc"
    assert seen["cmd"][0] == "powershell"
    assert "-c" not in seen["cmd"] and sys.executable not in seen["cmd"]
    script = seen["cmd"][-1]
    assert "OpenFileDialog" in script and "*.enc" in script
    assert "ShowDialog($owner)" in script      # owned by a top-most form


def test_pick_file_cancel_returns_empty(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R(b""))
    monkeypatch.setattr(sys, "platform", "win32")
    assert native_dialog.pick_file("video") == ""


def test_frozen_non_windows_does_not_relaunch_itself(monkeypatch):
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a) or _R(""))
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert native_dialog.pick_file("video") == ""
    assert called == []


def test_api_browse_passes_kind(monkeypatch):
    got = {}
    monkeypatch.setattr(native_dialog, "pick_file", lambda kind="video", timeout=300: got.setdefault("k", kind) and "X")
    app = Flask(__name__)
    app.register_blueprint(files_bp)
    body = app.test_client().get("/api/browse?kind=key").get_json()
    assert got["k"] == "key" and body["path"] == "X"


def test_encrypt_page_browse_buttons_ask_for_the_right_kind():
    js = (JS / "encryption.js").read_text(encoding="utf-8")
    assert "_browseInto('enc-src-path', 'video'" in js
    assert "_browseInto('dec-src-path', 'enc'" in js
    assert "catch(e) { /* ignore */ }" not in js   # failures are shown, not swallowed


# ── Home: Compress this video after upload ───────────────────────────────


def test_compress_this_video_after_upload_starts_the_run():
    js = (JS / "pipeline.js").read_text(encoding="utf-8")
    assert 'onclick="startPipeline()">Compress this video' in js
    assert "switchTab(\\'home\\')\">Compress this video" not in js


# ── .enc double-click ────────────────────────────────────────────────────


def test_build_produces_svcs_unlock_and_installer_ships_it():
    build = (ROOT / "installer" / "build.ps1").read_text(encoding="utf-8")
    iss = (ROOT / "installer" / "svcs.iss").read_text(encoding="utf-8")
    assert "svcs_unlock.spec" in build and "SVCS-Unlock.exe" in build
    assert 'Source: "..\\dist\\SVCS\\SVCS-Unlock.exe"' in iss
    assert "{app}\\SVCS-Unlock.exe" in iss


# ── pairing: server address and automatic device name ────────────────────


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(device_tokens, "token_path", lambda: tmp_path / "device_tokens.json")
    app = Flask(__name__)
    app.register_blueprint(tokens_bp)

    @app.route("/api/ping")
    def ping():
        return "ok"

    install_basic_auth(app, "admin", "secret")
    return app.test_client()


BASIC = {"Authorization": "Basic " + base64.b64encode(b"admin:secret").decode()}


def test_mint_without_a_name_returns_server_url_and_waits_for_the_phone(api):
    r = api.post("/api/auth/tokens", json={"label": ""}, headers=BASIC)
    body = r.get_json()
    assert r.status_code == 201
    assert body["server_url"].startswith("http://") and body["server_url"].count(":") == 2
    assert body["label"] == device_tokens.WAITING_LABEL


def test_phone_name_becomes_the_label_until_renamed(api):
    body = api.post("/api/auth/tokens", json={}, headers=BASIC).get_json()
    bearer = {"Authorization": "Bearer " + body["token"], "X-SVCS-Device-Name": "Samsung SM-S918U"}
    assert api.get("/api/ping", headers=bearer).status_code == 200
    tok = api.get("/api/auth/tokens", headers=BASIC).get_json()["tokens"][0]
    assert tok["label"] == "Samsung SM-S918U" and tok["device_name"] == "Samsung SM-S918U"

    r = api.patch("/api/auth/tokens/" + tok["id"], json={"label": "Lobby camera"}, headers=BASIC)
    assert r.get_json()["label"] == "Lobby camera"
    api.get("/api/ping", headers=bearer)          # a later request keeps the custom name
    tok = api.get("/api/auth/tokens", headers=BASIC).get_json()["tokens"][0]
    assert tok["label"] == "Lobby camera"

    r = api.patch("/api/auth/tokens/" + tok["id"], json={"label": ""}, headers=BASIC)
    assert r.get_json()["label"] == "Samsung SM-S918U"


def test_a_device_token_cannot_rename_devices(api):
    body = api.post("/api/auth/tokens", json={}, headers=BASIC).get_json()
    r = api.patch("/api/auth/tokens/" + body["id"], json={"label": "x"},
                  headers={"Authorization": "Bearer " + body["token"]})
    assert r.status_code == 403


def test_mac_fills_the_label_before_the_phone_reports_a_name(tmp_path, monkeypatch):
    monkeypatch.setattr(device_tokens, "token_path", lambda: tmp_path / "t.json")
    _, rec = device_tokens.mint_token("")
    assert device_tokens.note_device(rec.id, None, "AA:BB:CC:DD:EE:FF")
    t = device_tokens.list_tokens()[0]
    assert t.label == "aa:bb:cc:dd:ee:ff" and not t.custom_label
    assert device_tokens.note_device(rec.id, "Pixel 8", None)
    assert device_tokens.list_tokens()[0].label == "Pixel 8"
    assert not device_tokens.note_device(rec.id, "Pixel 8", None)   # no rewrite when unchanged


def test_mac_lookup_parses_windows_arp(monkeypatch):
    from gui import auth
    auth._MAC_CACHE.clear()
    out = ("\nInterface: 192.168.1.10 --- 0x7\n  Internet Address      Physical Address      Type\n"
           "  192.168.1.42          a4-c3-f0-11-22-33     dynamic\n")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: type("R", (), {"stdout": out})())
    assert auth._mac_for_ip("192.168.1.42") == "a4:c3:f0:11:22:33"
    assert auth._mac_for_ip("127.0.0.1") is None


def test_old_records_keep_their_typed_names(tmp_path):
    rec = {"id": "abc", "sha256": "0" * 64, "label": "Kheiven's Pixel", "created_at": ""}
    assert device_tokens.DeviceToken.from_record(rec).custom_label is True
    rec["label"] = "device"
    assert device_tokens.DeviceToken.from_record(rec).custom_label is False


# ── found by the 2026-11-25 browser click sweep ──────────────────────────


def test_setup_reopened_from_change_can_be_cancelled():
    js = (JS / "setup.js").read_text(encoding="utf-8")
    html = (SRC / "gui" / "templates" / "index.html").read_text(encoding="utf-8")
    dialogs = (JS / "dialogs.js").read_text(encoding="utf-8")
    assert 'id="setup-cancel-btn" onclick="closeSetup()" hidden' in html
    assert "_showSetupOverlay(true, reopened !== false)" in js
    assert "await openSetup(false)" in js                 # first run: no Cancel
    assert 'el.dataset.reopened !== "1"' in dialogs       # Escape works only then


def test_consent_banner_pads_the_page_so_it_covers_nothing():
    js = (JS / "usage.js").read_text(encoding="utf-8")
    assert "document.body.style.paddingBottom = (b.offsetHeight + 32)" in js


def test_hls_stop_cancels_pending_playlist_retries():
    js = (JS / "hls.js").read_text(encoding="utf-8")
    assert js.count("window._hlsAttachGen = (window._hlsAttachGen || 0) + 1") >= 3


# ── 2026-11-25 compression-path fixes ────────────────────────────────────


def test_release_build_refuses_to_ship_without_detector_and_ai_models():
    build = (ROOT / "installer" / "build.ps1").read_text(encoding="utf-8")
    assert '"yolov8n.onnx"' in build and "FSRCNN_x4.pb" in build
    assert "Missing model assets" in build and "Bundle is missing" in build
