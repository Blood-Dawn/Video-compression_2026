"""
tests/test_webhook_routes.py - webhook settings routes and panel (planner 4.10).

The planner outcome: "Off by default, write-only secret field, refuses
metadata endpoints." Each of the three gets a test against the real app, plus
the panel itself is checked to be on the page and wired to its script.

conftest points event_webhook.config_path() at a temp directory, so nothing
here touches a developer's real webhook.

Author: Victor De Souza Teixeira, 2026-10-06 (planner 4.10).
"""

import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils import event_webhook  # noqa: E402


@pytest.fixture()
def client():
    from gui.app import app
    return app.test_client()


@pytest.fixture()
def receiver():
    """A local receiver whose response body must never reach the caller."""
    hits = []

    class _H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            hits.append(self.path)
            body = b"INTERNAL-PAGE-CONTENT"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}", hits
    finally:
        srv.shutdown()
        srv.server_close()


# ── off by default ───────────────────────────────────────────────────────────


def test_off_by_default(client):
    cfg = client.get("/api/webhook/config").get_json()["config"]
    assert cfg == {"enabled": False, "url": "", "has_secret": False}


def test_turning_on_without_a_url_is_refused(client):
    resp = client.post("/api/webhook/config", json={"enabled": True})
    assert resp.status_code == 400
    assert "required" in resp.get_json()["error"]


def test_a_non_object_body_is_refused(client):
    resp = client.post("/api/webhook/config", data="[1,2]", content_type="application/json")
    assert resp.status_code == 400


# ── write-only secret ────────────────────────────────────────────────────────


def test_secret_is_never_echoed(client):
    resp = client.post("/api/webhook/config", json={
        "enabled": True, "url": "http://192.168.1.20:8123/hook", "secret": "s3cret-value"})
    assert resp.status_code == 200
    assert "s3cret-value" not in resp.get_data(as_text=True)
    got = client.get("/api/webhook/config")
    assert "s3cret-value" not in got.get_data(as_text=True)
    assert got.get_json()["config"]["has_secret"] is True


def test_omitting_the_secret_keeps_it_and_empty_clears_it(client):
    client.post("/api/webhook/config", json={
        "enabled": True, "url": "http://192.168.1.20:8123/hook", "secret": "keep-me"})
    client.post("/api/webhook/config", json={"enabled": False})
    assert event_webhook.load_config()["secret"] == "keep-me"
    client.post("/api/webhook/config", json={"secret": ""})
    assert event_webhook.load_config()["secret"] == ""


# ── refuses metadata endpoints ───────────────────────────────────────────────


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://100.100.100.200/latest/meta-data/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://[fd00:ec2::254]/latest/",
    "file:///etc/passwd",
    "http://admin:pw@192.168.1.20/hook",
])
def test_saving_a_refused_url_is_a_400_and_nothing_is_stored(client, url):
    resp = client.post("/api/webhook/config", json={"enabled": True, "url": url})
    assert resp.status_code == 400
    assert event_webhook.load_config()["url"] == ""


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://168.63.129.16/machine",
])
def test_the_test_button_refuses_metadata_too(client, url):
    data = client.post("/api/webhook/test", json={"url": url}).get_json()
    assert data["ok"] is False


# ── the test button ──────────────────────────────────────────────────────────


def test_test_button_reaches_an_unsaved_url_and_returns_only_a_status(client, receiver):
    base, hits = receiver
    resp = client.post("/api/webhook/test", json={"url": base + "/try"})
    data = resp.get_json()
    assert resp.status_code == 200
    assert data == {"ok": True, "detail": "HTTP 200"}
    assert hits == ["/try"]
    assert "INTERNAL-PAGE-CONTENT" not in resp.get_data(as_text=True)
    assert event_webhook.load_config()["url"] == "", "a test must not save the URL"


def test_test_button_with_nothing_configured_says_so(client):
    data = client.post("/api/webhook/test", json={}).get_json()
    assert data["ok"] is False and "no webhook URL" in data["detail"]


# ── the panel ────────────────────────────────────────────────────────────────


def test_panel_is_on_the_page_next_to_the_push_panel(client):
    html = client.get("/").get_data(as_text=True)
    for element_id in ("webhook-panel", "webhook-enabled", "webhook-url",
                       "webhook-secret", "webhook-test-btn", "webhook-save-btn",
                       "webhook-status"):
        assert f'id="{element_id}"' in html, element_id
    assert html.index('id="push-panel"') < html.index('id="webhook-panel"')
    assert 'type="password" id="webhook-secret"' in html
    assert "js/webhook.js" in html


def test_panel_script_is_served_and_never_sends_an_empty_secret(client):
    js = client.get("/static/js/webhook.js").get_data(as_text=True)
    assert "webhookCfgSave" in js and "webhookCfgTest" in js and "webhookCfgRefresh" in js
    # The secret key is only added when the field has text in it.
    assert "if (sec) body.secret = sec;" in js


def test_a_refused_save_does_not_reset_what_the_operator_ticked(client):
    """Found by browser check: re-applying the stored config after an error
    unticked "enabled", so the corrected save went through as OFF."""
    js = client.get("/static/js/webhook.js").get_data(as_text=True)
    error_branch = js.split("if (!res.ok || data.error) {", 1)[1].split("}", 1)[0]
    assert "_webhookApply" not in error_branch
