"""
tests/test_push_notify.py - closed-app push publisher (R6 TRACK C1).

Covers the three things that can actually hurt someone here:

  * the URL guard, which has to ALLOW the loopback and RFC1918 targets a
    self-hosted ntfy really lives on while refusing the cloud-metadata
    surface, including via DNS answers and IPv4-mapped IPv6 forms;
  * the off-by-default contract, so a stock install never opens a socket;
  * header hygiene, because ntfy carries the title and tags as HTTP HEADERS
    and the strings feeding them come from camera ids and class labels.

The delivery tests run against a real HTTP listener on 127.0.0.1 rather
than a mocked opener, so redirects, timeouts, and header encoding are
exercised the way urllib will actually behave in production.

Author: Bloodawn (KheivenD), 2026-08-17 (R6 TRACK C1).
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils import push_notify  # noqa: E402


# ── a local ntfy stand-in ────────────────────────────────────────────────────


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
    """Push turned on and pointed at the local listener."""
    ok, err, _cfg = push_notify.save_config({
        "enabled": True, "topic_url": listener + "/svcs-alerts",
    })
    assert ok, err
    return listener


# ── the URL guard ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8080/svcs",
    "http://localhost:8080/svcs",
    "http://192.168.1.50:8080/alerts",
    "http://10.0.0.5/topic",
    "http://172.16.4.4:2586/topic",
    "https://[::1]:8080/topic",
])
def test_guard_allows_the_self_hosted_targets(url):
    """Loopback and RFC1918 are the LEGITIMATE targets for this feature."""
    ok, why = push_notify.is_safe_push_url(url)
    assert ok, f"{url} should be allowed, got: {why}"


@pytest.mark.parametrize("url,fragment", [
    ("http://169.254.169.254/latest", "link-local"),
    ("http://100.100.100.100/topic", "metadata"),
    ("http://[fd00:ec2::254]/topic", "metadata"),
    ("http://[::ffff:169.254.169.254]/topic", "link-local"),
    ("http://metadata.google.internal/topic", "metadata"),
    ("http://metadata/topic", "metadata"),
    ("file:///etc/passwd", "scheme"),
    ("ftp://192.168.1.5/topic", "scheme"),
    ("gopher://192.168.1.5/topic", "scheme"),
    ("http://user:secret@192.168.1.5/topic", "credentials"),
    ("http://192.168.1.5", "no topic"),
    ("http://192.168.1.5/", "no topic"),
    ("", "empty"),
    ("   ", "empty"),
])
def test_guard_refuses_the_dangerous_shapes(url, fragment):
    ok, why = push_notify.is_safe_push_url(url)
    assert not ok, f"{url} should have been refused"
    assert fragment in why, f"reason {why!r} should mention {fragment!r}"


def test_guard_refuses_a_hostname_that_resolves_to_metadata(monkeypatch):
    """A friendly name pointing at 169.254.169.254 is still refused.

    This is the DNS-rebinding shape: the string looks harmless, the answer
    does not, so the check has to happen after resolution.
    """
    def fake_getaddrinfo(host, *a, **kw):
        return [(2, 1, 6, "", ("169.254.169.254", 0))]
    monkeypatch.setattr(push_notify.socket, "getaddrinfo", fake_getaddrinfo)
    ok, why = push_notify.is_safe_push_url("http://ntfy.example.test/topic")
    assert not ok
    assert "link-local" in why


def test_guard_refuses_a_host_that_does_not_resolve(monkeypatch):
    def boom(host, *a, **kw):
        raise OSError("no such host")
    monkeypatch.setattr(push_notify.socket, "getaddrinfo", boom)
    ok, why = push_notify.is_safe_push_url("http://nope.invalid/topic")
    assert not ok and "resolve" in why


# ── the off-by-default contract ──────────────────────────────────────────────


def test_off_by_default():
    cfg = push_notify.load_config()
    assert cfg["enabled"] is False
    assert cfg["topic_url"] == ""
    assert push_notify.publish("t", "m") is False


def test_disabled_config_never_posts(listener):
    """A saved but switched-off config stays silent."""
    ok, err, _ = push_notify.save_config(
        {"enabled": False, "topic_url": listener + "/svcs"})
    assert ok, err
    assert push_notify.publish_events([
        {"kind": "line_crossing", "label": "person", "geometry_id": "gate"}]) == 0
    push_notify.flush(0.3)
    assert _Recorder.received == []


def test_enabling_without_a_url_is_refused():
    ok, err, _ = push_notify.save_config({"enabled": True, "topic_url": ""})
    assert not ok and "topic URL is required" in err


def test_saving_a_refused_url_does_not_persist_it():
    ok, err, _ = push_notify.save_config(
        {"enabled": True, "topic_url": "http://169.254.169.254/x"})
    assert not ok and "link-local" in err
    assert push_notify.load_config()["topic_url"] == ""


# ── the token ────────────────────────────────────────────────────────────────


def test_token_is_never_echoed_and_survives_an_omitted_key(listener):
    ok, err, pub = push_notify.save_config({
        "enabled": True, "topic_url": listener + "/svcs", "token": "tk_secret"})
    assert ok, err
    assert "token" not in pub and pub["has_token"] is True
    # A client editing the OTHER fields must not have to hold the secret.
    ok, err, pub = push_notify.save_config({"on_events": False})
    assert ok, err
    assert pub["has_token"] is True
    assert push_notify.load_config()["token"] == "tk_secret"
    # An explicit empty string is how you clear it.
    ok, err, pub = push_notify.save_config({"token": ""})
    assert ok, err
    assert pub["has_token"] is False


def test_token_becomes_a_bearer_header(enabled):
    push_notify.save_config({"token": "tk_abc"})
    ok, detail = push_notify.send_test()
    assert ok, detail
    assert _Recorder.received[-1]["headers"]["authorization"] == "Bearer tk_abc"


# ── delivery ─────────────────────────────────────────────────────────────────


def test_behavior_event_reaches_the_topic(enabled):
    n = push_notify.publish_events([{
        "kind": "line_crossing", "label": "person", "geometry_id": "gate",
        "direction": "right",
    }], camera_id="cam_00")
    assert n == 1
    assert push_notify.flush(3.0)
    got = _Recorder.received[-1]
    assert got["path"] == "/svcs-alerts"
    assert got["headers"]["title"] == "SVCS: line crossed"
    assert "person" in got["body"] and "gate" in got["body"]
    assert "cam_00" in got["body"] and "right" in got["body"]
    assert got["headers"]["priority"] == "high"


def test_loitering_reads_like_a_sentence(enabled):
    push_notify.publish_events([{
        "kind": "loitering", "label": "person", "geometry_id": "driveway",
        "dwell_s": 34.2,
    }], camera_id="cam_01")
    assert push_notify.flush(3.0)
    body = _Recorder.received[-1]["body"]
    assert "loitering" in body and "driveway" in body and "34s" in body


def test_a_burst_is_capped_and_summarised(enabled):
    events = [{"kind": "line_crossing", "label": "car", "geometry_id": f"g{i}"}
              for i in range(9)]
    sent = push_notify.publish_events(events, camera_id="cam_00")
    assert sent == push_notify._MAX_PER_BATCH
    assert push_notify.flush(4.0)
    # One message per capped event, plus a single "there were more" note.
    assert len(_Recorder.received) == push_notify._MAX_PER_BATCH + 1
    assert "4 further event" in _Recorder.received[-1]["body"]


def test_job_completion_reports_the_real_saving(enabled):
    assert push_notify.publish_job({
        "kind": "pipeline", "label": "highway.mp4", "status": "completed",
        "elapsed_s": 42.3, "bytes_in": 220_000_000, "bytes_out": 31_000_000,
    })
    assert push_notify.flush(3.0)
    got = _Recorder.received[-1]
    assert got["headers"]["title"] == "SVCS: compression finished"
    assert "86 percent saved" in got["body"] and "42.3s" in got["body"]


def test_job_failure_says_so(enabled):
    push_notify.publish_job({"kind": "pipeline", "label": "cam_00",
                             "status": "error", "error": "codec missing"})
    assert push_notify.flush(3.0)
    got = _Recorder.received[-1]
    assert got["headers"]["title"] == "SVCS: compression failed"
    assert "codec missing" in got["body"]


def test_per_kind_switches_are_honoured(enabled):
    push_notify.save_config({"on_events": False, "on_jobs": True})
    assert push_notify.publish_events([{"kind": "line_crossing"}]) == 0
    push_notify.save_config({"on_events": True, "on_jobs": False})
    assert push_notify.publish_job({"status": "completed"}) is False
    push_notify.flush(0.3)
    assert _Recorder.received == []


# ── hardening ────────────────────────────────────────────────────────────────


def test_header_sanitiser_strips_injection_and_folds_non_ascii():
    assert "\r" not in push_notify._header_safe("a\r\nX-Evil: 1")
    assert "\n" not in push_notify._header_safe("a\r\nX-Evil: 1")
    assert push_notify._header_safe("a\r\nX-Evil: 1") == "aX-Evil: 1"
    assert push_notify._header_safe("café") == "caf?"
    assert len(push_notify._header_safe("x" * 500)) == 200


def test_a_crafted_title_cannot_inject_a_header(enabled):
    push_notify.publish("SVCS\r\nX-Evil: yes", "body")
    assert push_notify.flush(3.0)
    assert "x-evil" not in _Recorder.received[-1]["headers"]


def test_a_redirect_is_refused_not_followed(enabled):
    _Recorder.redirect_once = True
    ok, detail = push_notify.send_test()
    assert not ok
    assert "redirect refused" in detail
    assert [r["path"] for r in _Recorder.received] == ["/svcs-alerts"]


def test_an_unreachable_topic_is_reported_not_raised():
    ok, err, _ = push_notify.save_config({
        "enabled": True, "topic_url": "http://127.0.0.1:9/svcs"})
    assert ok, err
    ok, detail = push_notify.send_test(topic_url="http://127.0.0.1:9/svcs")
    assert not ok and "could not reach" in detail


def test_test_send_accepts_an_unsaved_url(listener):
    """Prove a URL works BEFORE committing it, which is the real order."""
    assert push_notify.load_config()["topic_url"] == ""
    ok, detail = push_notify.send_test(topic_url=listener + "/scratch")
    assert ok, detail
    assert _Recorder.received[-1]["path"] == "/scratch"
    assert push_notify.load_config()["topic_url"] == ""


def test_config_file_is_json_and_holds_no_surprises(listener):
    push_notify.save_config({"enabled": True, "topic_url": listener + "/svcs",
                             "priority": "urgent"})
    data = json.loads(push_notify.config_path().read_text(encoding="utf-8"))
    assert set(data) == {"enabled", "topic_url", "token", "on_jobs",
                         "on_events", "priority", "saved_at"}
    assert data["priority"] == "urgent"


def test_a_bad_priority_is_refused():
    ok, err, _ = push_notify.save_config({"priority": "screaming"})
    assert not ok and "priority must be" in err
