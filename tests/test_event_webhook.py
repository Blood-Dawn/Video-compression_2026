"""
tests/test_event_webhook.py - generic outbound webhook (Week 3 TASK 3.9/3.10).

Same testing shape as test_push_notify.py, adapted to what actually differs
here: a plain signed JSON POST instead of ntfy's header-carried title/tags,
so the things worth proving are the shared URL guard (reused, not
reimplemented - covered by test_push_notify.py, spot-checked here), the
off-by-default contract, the write-only secret, the HMAC-SHA256 signature
in X-SVCS-Signature, and delivery against a real local HTTP listener rather
than a mocked opener.

Author: Bloodawn (KheivenD), Week 3 (3.10).
"""

import hashlib
import hmac
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils import event_webhook  # noqa: E402


# ── a local webhook receiver stand-in ───────────────────────────────────────


class _Recorder(BaseHTTPRequestHandler):
    received = []
    redirect_once = False

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler's spelling
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", "replace")
        _Recorder.received.append({
            "path": self.path,
            "body": body,
            "headers": {k.lower(): v for k, v in self.headers.items()},
        })
        if _Recorder.redirect_once and self.path != "/moved":
            self.send_response(302)
            self.send_header("Location", "/moved")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):  # keep pytest output clean
        return


@pytest.fixture
def listener():
    """A throwaway HTTP server; yields its base URL."""
    _Recorder.received = []
    _Recorder.redirect_once = False
    srv = HTTPServer(("127.0.0.1", 0), _Recorder)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}"
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def enabled(listener):
    """Webhook turned on and pointed at the local listener."""
    ok, err, _cfg = event_webhook.save_config({
        "enabled": True, "url": listener + "/svcs-webhook",
    })
    assert ok, err
    return listener


# ── the URL guard (reused from push_notify, spot-checked not re-derived) ────


def test_guard_is_the_same_function_push_notify_uses():
    from utils.push_notify import is_safe_push_url
    assert event_webhook.is_safe_push_url is is_safe_push_url


def test_guard_refuses_metadata_and_allows_self_hosted():
    ok, why = event_webhook.is_safe_push_url("http://169.254.169.254/latest")
    assert not ok and "link-local" in why
    ok, why = event_webhook.is_safe_push_url("http://192.168.1.50:8080/hook")
    assert ok, why


# ── the off-by-default contract ─────────────────────────────────────────────


def test_off_by_default():
    cfg = event_webhook.load_config()
    assert cfg["enabled"] is False
    assert cfg["url"] == ""
    assert event_webhook.publish("test", {}) is False


def test_disabled_config_never_posts(listener):
    ok, err, _ = event_webhook.save_config(
        {"enabled": False, "url": listener + "/svcs"})
    assert ok, err
    assert event_webhook.publish_events([
        {"kind": "line_crossing", "label": "person", "geometry_id": "gate"}]) == 0
    event_webhook.flush(0.3)
    assert _Recorder.received == []


def test_enabling_without_a_url_is_refused():
    ok, err, _ = event_webhook.save_config({"enabled": True, "url": ""})
    assert not ok and "webhook URL is required" in err


def test_saving_a_refused_url_does_not_persist_it():
    ok, err, _ = event_webhook.save_config(
        {"enabled": True, "url": "http://169.254.169.254/x"})
    assert not ok and "link-local" in err
    assert event_webhook.load_config()["url"] == ""


# ── the secret ───────────────────────────────────────────────────────────────


def test_secret_is_never_echoed_and_survives_an_omitted_key(listener):
    ok, err, pub = event_webhook.save_config({
        "enabled": True, "url": listener + "/svcs", "secret": "sh_secret"})
    assert ok, err
    assert "secret" not in pub and pub["has_secret"] is True
    # A client editing the OTHER fields must not have to hold the secret.
    ok, err, pub = event_webhook.save_config({"on_events": False})
    assert ok, err
    assert pub["has_secret"] is True
    assert event_webhook.load_config()["secret"] == "sh_secret"
    # An explicit empty string is how you clear it.
    ok, err, pub = event_webhook.save_config({"secret": ""})
    assert ok, err
    assert pub["has_secret"] is False


def test_secret_signs_the_body_with_hmac_sha256(enabled):
    event_webhook.save_config({"secret": "sh_abc"})
    ok, detail = event_webhook.send_test()
    assert ok, detail
    got = _Recorder.received[-1]
    sig = got["headers"]["x-svcs-signature"]
    assert sig.startswith("sha256=")
    expected = hmac.new(b"sh_abc", got["body"].encode("utf-8"),
                        hashlib.sha256).hexdigest()
    assert sig == "sha256=" + expected


def test_no_secret_means_no_signature_header(enabled):
    ok, detail = event_webhook.send_test()
    assert ok, detail
    assert "x-svcs-signature" not in _Recorder.received[-1]["headers"]


# ── delivery ─────────────────────────────────────────────────────────────────


def test_behavior_event_reaches_the_url(enabled):
    n = event_webhook.publish_events([{
        "kind": "line_crossing", "label": "person", "geometry_id": "gate",
        "direction": "right",
    }], camera_id="cam_00")
    assert n == 1
    assert event_webhook.flush(3.0)
    got = _Recorder.received[-1]
    assert got["path"] == "/svcs-webhook"
    assert got["headers"]["content-type"] == "application/json"
    body = json.loads(got["body"])
    assert body["event"] == "event"
    assert body["data"]["kind"] == "line_crossing"
    assert body["data"]["camera_id"] == "cam_00"
    assert body["data"]["direction"] == "right"


def test_camera_id_does_not_override_one_already_on_the_event(enabled):
    event_webhook.publish_events(
        [{"kind": "loitering", "camera_id": "cam_explicit"}], camera_id="cam_default")
    assert event_webhook.flush(3.0)
    body = json.loads(_Recorder.received[-1]["body"])
    assert body["data"]["camera_id"] == "cam_explicit"


def test_a_burst_is_capped_at_max_per_batch(enabled):
    events = [{"kind": "line_crossing", "label": "car", "geometry_id": f"g{i}"}
              for i in range(9)]
    sent = event_webhook.publish_events(events, camera_id="cam_00")
    assert sent == event_webhook._MAX_PER_BATCH
    assert event_webhook.flush(4.0)
    assert len(_Recorder.received) == event_webhook._MAX_PER_BATCH


def test_job_completion_is_delivered(enabled):
    assert event_webhook.publish_job({
        "kind": "pipeline", "label": "highway.mp4", "status": "completed",
        "elapsed_s": 42.3, "bytes_in": 220_000_000, "bytes_out": 31_000_000,
    })
    assert event_webhook.flush(3.0)
    got = _Recorder.received[-1]
    body = json.loads(got["body"])
    assert body["event"] == "job"
    assert body["data"]["status"] == "completed"
    assert body["data"]["label"] == "highway.mp4"


def test_job_failure_is_delivered(enabled):
    event_webhook.publish_job({"kind": "pipeline", "label": "cam_00",
                               "status": "error", "error": "codec missing"})
    assert event_webhook.flush(3.0)
    body = json.loads(_Recorder.received[-1]["body"])
    assert body["data"]["status"] == "error"
    assert body["data"]["error"] == "codec missing"


def test_per_kind_switches_are_honoured(enabled):
    event_webhook.save_config({"on_events": False, "on_jobs": True})
    assert event_webhook.publish_events([{"kind": "line_crossing"}]) == 0
    event_webhook.save_config({"on_events": True, "on_jobs": False})
    assert event_webhook.publish_job({"status": "completed"}) is False
    event_webhook.flush(0.3)
    assert _Recorder.received == []


def test_a_redirect_is_refused_not_followed(enabled):
    _Recorder.redirect_once = True
    ok, detail = event_webhook.send_test()
    assert not ok
    assert "redirect refused" in detail
    assert [r["path"] for r in _Recorder.received] == ["/svcs-webhook"]


def test_an_unreachable_url_is_reported_not_raised():
    ok, err, _ = event_webhook.save_config({
        "enabled": True, "url": "http://127.0.0.1:9/svcs"})
    assert ok, err
    ok, detail = event_webhook.send_test(url="http://127.0.0.1:9/svcs")
    assert not ok and "could not reach" in detail


def test_test_send_accepts_an_unsaved_url_and_secret(listener):
    """Prove a URL works BEFORE committing it, the same order push_notify uses."""
    assert event_webhook.load_config()["url"] == ""
    ok, detail = event_webhook.send_test(url=listener + "/scratch", secret="tmp")
    assert ok, detail
    got = _Recorder.received[-1]
    assert got["path"] == "/scratch"
    assert got["headers"]["x-svcs-signature"].startswith("sha256=")
    assert event_webhook.load_config()["url"] == ""


def test_config_file_is_json_and_holds_no_surprises(listener):
    event_webhook.save_config({"enabled": True, "url": listener + "/svcs"})
    data = json.loads(event_webhook.config_path().read_text(encoding="utf-8"))
    assert set(data) == {"enabled", "url", "secret", "on_jobs", "on_events",
                         "saved_at"}


# ── blueprint wiring (Flask test client, no live server) ───────────────────


def test_blueprint_config_roundtrip_and_test_route(listener):
    """The Flask side of this feature, exercised end to end like /api/zones/frame."""
    import flask
    from gui.routes.webhook_bp import webhook_bp

    app = flask.Flask(__name__)
    app.register_blueprint(webhook_bp)
    client = app.test_client()

    # GET before anything is configured: off, no secret.
    resp = client.get("/api/webhook/config")
    assert resp.status_code == 200
    cfg = resp.get_json()["config"]
    assert cfg["enabled"] is False and cfg["has_secret"] is False

    # POST an invalid body shape is a 400, not a 500.
    resp = client.post("/api/webhook/config", data="not json",
                       content_type="application/json")
    assert resp.status_code == 400

    # Turning it on without a URL is refused with the real validation error.
    resp = client.post("/api/webhook/config", json={"enabled": True})
    assert resp.status_code == 400
    assert "webhook URL is required" in resp.get_json()["error"]

    # A real save works and never echoes the secret back.
    resp = client.post("/api/webhook/config", json={
        "enabled": True, "url": listener + "/svcs", "secret": "sh_xyz",
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert "secret" not in body["config"] and body["config"]["has_secret"] is True

    # The test route delivers synchronously and reports the outcome.
    resp = client.post("/api/webhook/test", json={})
    assert resp.status_code == 200
    result = resp.get_json()
    assert result["ok"] is True
    got = _Recorder.received[-1]
    assert got["headers"]["x-svcs-signature"].startswith("sha256=")


def test_blueprint_test_route_reports_failure_without_500(listener):
    import flask
    from gui.routes.webhook_bp import webhook_bp

    app = flask.Flask(__name__)
    app.register_blueprint(webhook_bp)
    client = app.test_client()

    resp = client.post("/api/webhook/test", json={"url": "http://127.0.0.1:9/x"})
    assert resp.status_code == 200
    result = resp.get_json()
    assert result["ok"] is False
    assert "could not reach" in result["detail"]
