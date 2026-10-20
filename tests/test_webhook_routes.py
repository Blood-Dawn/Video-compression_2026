"""
tests/test_webhook_routes.py - webhook settings routes and panel.

Covers: off by default, write-only secret, refused URLs, the test route never
returning the receiver body, password-only writes (a device bearer token is
refused), strict boolean flags, the atomic config write, and the panel script's
error path (run under node when it is installed).

conftest points event_webhook.config_path() at a temp directory, so nothing
here touches a developer's real webhook.

Ported from Victor De Souza Teixeira's planner 4.10 tests and extended.
"""

import base64
import json
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils import event_webhook  # noqa: E402

JS_PATH = SRC / "gui" / "static" / "js" / "webhook.js"


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


# -- off by default ----------------------------------------------------------


def test_off_by_default(client):
    cfg = client.get("/api/webhook/config").get_json()["config"]
    assert cfg["enabled"] is False
    assert cfg["url"] == ""
    assert cfg["has_secret"] is False
    assert "secret" not in cfg


def test_turning_on_without_a_url_is_refused(client):
    resp = client.post("/api/webhook/config", json={"enabled": True})
    assert resp.status_code == 400
    assert "required" in resp.get_json()["error"]


def test_a_non_object_body_is_refused(client):
    resp = client.post("/api/webhook/config", data="[1,2]", content_type="application/json")
    assert resp.status_code == 400


# -- strict booleans ---------------------------------------------------------


@pytest.mark.parametrize("key", ["enabled", "on_jobs", "on_events"])
@pytest.mark.parametrize("value", ["false", "true", 0, 1, None, "", []])
def test_non_boolean_flags_are_a_400(client, key, value):
    body = {"url": "http://192.168.1.20:8123/hook", key: value}
    resp = client.post("/api/webhook/config", json=body)
    assert resp.status_code == 400
    assert key in resp.get_json()["error"]
    assert event_webhook.load_config()["url"] == "", "nothing may be stored"


def test_boolean_flags_are_saved(client):
    resp = client.post("/api/webhook/config", json={
        "enabled": True, "url": "http://192.168.1.20:8123/hook",
        "on_jobs": False, "on_events": True})
    assert resp.status_code == 200
    cfg = event_webhook.load_config()
    assert cfg["enabled"] is True and cfg["on_jobs"] is False and cfg["on_events"] is True


# -- write-only secret -------------------------------------------------------


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


# -- refuses metadata endpoints ----------------------------------------------


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


# -- the test route ----------------------------------------------------------


def test_test_route_reaches_an_unsaved_url_and_returns_only_a_status(client, receiver):
    base, hits = receiver
    resp = client.post("/api/webhook/test", json={"url": base + "/try"})
    data = resp.get_json()
    assert resp.status_code == 200
    assert data == {"ok": True, "detail": "HTTP 200"}
    assert hits == ["/try"]
    assert "INTERNAL-PAGE-CONTENT" not in resp.get_data(as_text=True)
    assert event_webhook.load_config()["url"] == "", "a test must not save the URL"


def test_test_route_with_nothing_configured_says_so(client):
    data = client.post("/api/webhook/test", json={}).get_json()
    assert data["ok"] is False and "no webhook URL" in data["detail"]


# -- password-only writes ----------------------------------------------------


@pytest.fixture()
def guarded(tmp_path, monkeypatch):
    """The real webhook blueprint behind the real auth guard."""
    from flask import Flask

    from gui import device_tokens
    from gui.auth import install_basic_auth
    from gui.routes.webhook_bp import webhook_bp

    monkeypatch.setattr(device_tokens, "token_path", lambda: tmp_path / "device_tokens.json")
    app = Flask(__name__)
    app.register_blueprint(webhook_bp)
    install_basic_auth(app, "admin", "secret")
    secret = device_tokens.mint_token("phone")[0]
    return app.test_client(), secret


def _mint_secret(minted):
    return minted if isinstance(minted, str) else minted[0]


def _basic():
    blob = base64.b64encode(b"admin:secret").decode("ascii")
    return {"Authorization": f"Basic {blob}"}


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_device_token_cannot_change_the_webhook(guarded):
    cl, token = guarded
    resp = cl.post("/api/webhook/config", headers=_bearer(token), json={
        "enabled": True, "url": "http://192.168.1.20:8123/hook"})
    assert resp.status_code == 403
    assert event_webhook.load_config()["url"] == ""


def test_device_token_cannot_trigger_the_test_route(guarded, receiver):
    cl, token = guarded
    base, hits = receiver
    resp = cl.post("/api/webhook/test", headers=_bearer(token), json={"url": base + "/x"})
    assert resp.status_code == 403
    assert hits == [], "no server side request may have been made"


def test_basic_auth_can_change_and_test_the_webhook(guarded, receiver):
    cl, _token = guarded
    base, hits = receiver
    saved = cl.post("/api/webhook/config", headers=_basic(), json={
        "enabled": True, "url": base + "/hook"})
    assert saved.status_code == 200
    tested = cl.post("/api/webhook/test", headers=_basic(), json={"url": base + "/x"})
    assert tested.status_code == 200 and tested.get_json()["ok"] is True
    assert "/x" in hits


def test_no_credentials_is_401_and_token_can_still_read_without_secret(guarded):
    cl, token = guarded
    assert cl.post("/api/webhook/config", json={}).status_code == 401
    got = cl.get("/api/webhook/config", headers=_bearer(token))
    assert got.status_code == 200 and "secret" not in got.get_json()["config"]


# -- atomic write ------------------------------------------------------------


def test_save_writes_atomically_with_the_same_format(tmp_path, monkeypatch):
    path = tmp_path / "webhook_config.json"
    monkeypatch.setattr(event_webhook, "config_path", lambda: path)
    replaced = []
    real_replace = event_webhook.os.replace

    def spy(src, dst):
        replaced.append((Path(src), Path(dst)))
        assert Path(src).exists(), "temp file must be fully written before the swap"
        return real_replace(src, dst)

    monkeypatch.setattr(event_webhook.os, "replace", spy)
    ok, err, _cfg = event_webhook.save_config({
        "enabled": True, "url": "http://192.168.1.20:8123/hook", "secret": "abc"})
    assert ok, err
    assert replaced and replaced[0][1] == path and replaced[0][0] != path
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert set(on_disk) == {"enabled", "url", "secret", "on_jobs", "on_events", "saved_at"}
    assert on_disk["secret"] == "abc"
    assert [p.name for p in tmp_path.iterdir()] == ["webhook_config.json"], "no temp leftovers"


def test_failed_write_leaves_the_old_config_intact(tmp_path, monkeypatch):
    path = tmp_path / "webhook_config.json"
    monkeypatch.setattr(event_webhook, "config_path", lambda: path)
    assert event_webhook.save_config({"url": "http://192.168.1.20:8123/a"})[0]

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(event_webhook.os, "replace", boom)
    ok, err, _cfg = event_webhook.save_config({"url": "http://192.168.1.20:8123/b"})
    assert ok is False and "could not save" in err
    assert json.loads(path.read_text(encoding="utf-8"))["url"].endswith("/a")
    assert [p.name for p in tmp_path.iterdir()] == ["webhook_config.json"]


def test_concurrent_saves_never_corrupt_the_file(tmp_path, monkeypatch):
    path = tmp_path / "webhook_config.json"
    monkeypatch.setattr(event_webhook, "config_path", lambda: path)
    errors = []

    def work(i):
        ok, err, _ = event_webhook.save_config({"url": f"http://192.168.1.20:8123/{i}"})
        if not ok:
            errors.append(err)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert json.loads(path.read_text(encoding="utf-8"))["url"].startswith("http://192.168.1.20")


# -- the panel ---------------------------------------------------------------


def test_panel_is_on_the_page_next_to_the_push_panel(client):
    html = client.get("/").get_data(as_text=True)
    for element_id in ("webhook-panel", "webhook-enabled", "webhook-url",
                       "webhook-secret", "webhook-clear-secret", "webhook-on-jobs",
                       "webhook-on-events", "webhook-test-btn", "webhook-save-btn",
                       "webhook-status"):
        assert f'id="{element_id}"' in html, element_id
    assert html.index('id="push-panel"') < html.index('id="webhook-panel"')
    assert "js/webhook.js" in html


def test_panel_script_is_served(client):
    js = client.get("/static/js/webhook.js").get_data(as_text=True)
    assert "webhookCfgSave" in js and "webhookCfgTest" in js and "webhookCfgRefresh" in js


_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const src = fs.readFileSync(process.argv[2], "utf8");
const mode = process.argv[3];
const els = {};
function el(id, props) { els[id] = Object.assign({value: "", checked: false}, props); }
el("webhook-enabled", {checked: true});
el("webhook-url", {value: "not a url"});
el("webhook-secret", {});
el("webhook-clear-secret", {checked: mode === "clear"});
el("webhook-on-jobs", {checked: true});
el("webhook-on-events", {checked: true});
el("webhook-save-btn", {});
el("webhook-status", {style: {}});
const sent = [];
const ctx = {
  console, window: {},
  document: {getElementById: (id) => els[id] || null},
  fetch: async (url, opts) => {
    sent.push(JSON.parse(opts.body));
    if (mode === "refuse") {
      return {ok: false, json: async () => ({error: "bad url",
        config: {enabled: false, url: "", on_jobs: true, on_events: true, has_secret: false}})};
    }
    return {ok: true, json: async () => ({ok: true,
      config: {enabled: true, url: "http://x", on_jobs: true, on_events: true, has_secret: false}})};
  },
};
vm.createContext(ctx);
vm.runInContext(src, ctx);
ctx.window.webhookCfgSave().then(() => {
  console.log(JSON.stringify({enabled: els["webhook-enabled"].checked,
    url: els["webhook-url"].value, status: els["webhook-status"].textContent,
    sent: sent[0], clear: els["webhook-clear-secret"].checked}));
});
"""

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _run_panel(tmp_path, mode):
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS, encoding="utf-8")
    out = subprocess.run(["node", str(harness), str(JS_PATH), mode],
                         capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


@needs_node
def test_a_refused_save_does_not_reset_what_the_operator_ticked(tmp_path):
    """Re-applying the stored config after an error used to untick "enabled",
    so the corrected save then went through as OFF."""
    state = _run_panel(tmp_path, "refuse")
    assert state["enabled"] is True, "enabled must stay ticked after a refused save"
    assert state["url"] == "not a url", "the typed URL must stay for correction"
    assert state["status"] == "bad url"


@needs_node
def test_clear_secret_box_sends_an_empty_secret_and_resets(tmp_path):
    state = _run_panel(tmp_path, "clear")
    assert state["sent"]["secret"] == ""
    assert state["clear"] is False


@needs_node
def test_without_the_clear_box_no_secret_key_is_sent(tmp_path):
    state = _run_panel(tmp_path, "ok")
    assert "secret" not in state["sent"]


def test_refused_save_branch_does_not_call_apply():
    """Source level backstop for when node is unavailable."""
    js = JS_PATH.read_text(encoding="utf-8")
    branch = js.split("if (!res.ok || data.error) {", 1)[1].split("return;", 1)[0]
    code = "\n".join(ln for ln in branch.splitlines() if not ln.strip().startswith("//"))
    assert "_webhookApply" not in code
