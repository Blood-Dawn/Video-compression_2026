"""
tests/test_event_webhook.py - the machine-readable event webhook (planner 4.9).

Cases follow section 11 of docs/plans/WEBHOOK-EMITTER-SPEC.md. Every test
talks to a throwaway local HTTP server, never a real receiver, and conftest
points config_path() at a temp directory so a developer's own webhook is
never hit.

Author: Victor De Souza Teixeira, 2026-10-03 (planner 4.9).
"""

import hashlib
import hmac
import json
import queue
import sys
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils import event_log, event_webhook, push_notify  # noqa: E402


# ── a local receiver ─────────────────────────────────────────────────────────


class _Receiver(BaseHTTPRequestHandler):
    received = []
    mode = "ok"            # "ok" | "redirect" | "hang" | "error"
    hang_s = 5.0
    location = "/moved"    # where "redirect" mode points
    redirect_status = 302

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler's spelling
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        if _Receiver.mode == "hang":
            time.sleep(_Receiver.hang_s)
        _Receiver.received.append({
            "path": self.path,
            "body": body,
            "headers": {k.lower(): v for k, v in self.headers.items()},
        })
        if _Receiver.mode == "redirect" and self.path != "/moved":
            self.send_response(_Receiver.redirect_status)
            self.send_header("Location", _Receiver.location)
            self.end_headers()
            return
        code = 500 if _Receiver.mode == "error" else 200
        self.send_response(code)
        self.send_header("Content-Length", "6")
        self.end_headers()
        self.wfile.write(b"secret")   # must never be echoed by send_test

    def log_message(self, *args):
        return


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False


@pytest.fixture(autouse=True)
def _drained_worker():
    """No test may inherit a delivery a previous test left in flight.

    The worker is module-global, so a hanging-receiver test would otherwise
    leave its 2 second timeout queued ahead of the next test's delivery.
    """
    assert event_webhook.flush(5.0)
    yield
    assert event_webhook.flush(5.0)


@pytest.fixture
def receiver():
    """A throwaway HTTP server; yields its base URL."""
    _Receiver.received = []
    _Receiver.mode = "ok"
    _Receiver.hang_s = 5.0
    _Receiver.location = "/moved"
    _Receiver.redirect_status = 302
    srv = _Server(("127.0.0.1", 0), _Receiver)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}"
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def enabled(receiver):
    ok, err, _cfg = event_webhook.save_config({"enabled": True, "url": receiver + "/hook"})
    assert ok, err
    return receiver


def _events(n=1, **extra):
    base = {"kind": "line_crossing", "camera_id": "cam_00", "t": 12.5,
            "track_id": 3, "label": "person", "geometry_id": "gate",
            "direction": "right"}
    base.update(extra)
    return [dict(base, track_id=i) for i in range(n)]


def _wait_for(n, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline and len(_Receiver.received) < n:
        time.sleep(0.01)
    return _Receiver.received


# ── 1. off by default ────────────────────────────────────────────────────────


def test_off_by_default_opens_no_socket(receiver):
    assert event_webhook.load_config()["enabled"] is False
    assert event_webhook.emit_events(_events()) is False
    assert event_webhook.flush(1.0)
    assert _Receiver.received == []


def test_enabling_without_a_url_is_refused():
    ok, err, _ = event_webhook.save_config({"enabled": True})
    assert not ok and "required" in err


def test_saving_a_refused_url_does_not_persist_it():
    ok, err, _ = event_webhook.save_config(
        {"enabled": True, "url": "http://169.254.169.254/latest"})
    assert not ok and "link-local" in err
    assert event_webhook.load_config()["url"] == ""


# ── 2. delivery ──────────────────────────────────────────────────────────────


def test_one_event_arrives_as_json(enabled):
    assert event_webhook.emit_events(_events(), camera_id="cam_00")
    assert event_webhook.flush(3.0)
    got = _wait_for(1)
    assert len(got) == 1 and got[0]["path"] == "/hook"
    payload = json.loads(got[0]["body"])
    assert payload["source"] == "svcs"
    assert payload["schema"] == 1
    assert payload["camera_id"] == "cam_00"
    assert payload["dropped"] == 0
    assert payload["events"][0]["kind"] == "line_crossing"
    headers = got[0]["headers"]
    assert headers["content-type"] == "application/json"
    assert headers["user-agent"] == "SVCS-Webhook"
    assert headers["x-svcs-delivery"] and headers["x-svcs-timestamp"].isdigit()


def test_append_events_reaches_the_webhook(enabled, tmp_path):
    """The real hook point, not just the module."""
    assert event_log.append_events(tmp_path, _events(), camera_id="cam_07") == 1
    assert event_webhook.flush(3.0)
    payload = json.loads(_wait_for(1)[0]["body"])
    assert payload["camera_id"] == "cam_07"


# ── 3. allowlist ─────────────────────────────────────────────────────────────


def test_extra_keys_never_leave_the_machine(enabled):
    ev = _events(plate_text="ABC1234", path="C:/footage/x.mp4",
                 stream_url="rtsp://admin:pw@10.0.0.9/1")
    event_webhook.emit_events(ev)
    assert event_webhook.flush(3.0)
    raw = _wait_for(1)[0]["body"].decode()
    sent = json.loads(raw)["events"][0]
    assert set(sent) <= set(event_webhook.EVENT_FIELDS)
    for leaked in ("ABC1234", "footage", "admin:pw"):
        assert leaked not in raw


# ── 4. batch cap ─────────────────────────────────────────────────────────────


def test_a_burst_is_capped_and_counted(enabled):
    event_webhook.emit_events(_events(25))
    assert event_webhook.flush(3.0)
    got = _wait_for(1)
    assert len(got) == 1, "a burst must be ONE request, not 25"
    payload = json.loads(got[0]["body"])
    assert len(payload["events"]) == 20
    assert payload["dropped"] == 5


# ── 5-7. signing and the write-only secret ───────────────────────────────────


def test_signature_verifies_and_a_tampered_body_fails(receiver):
    secret = "s3cret-for-tests"
    ok, err, _ = event_webhook.save_config(
        {"enabled": True, "url": receiver + "/hook", "secret": secret})
    assert ok, err
    event_webhook.emit_events(_events())
    assert event_webhook.flush(3.0)
    got = _wait_for(1)[0]
    ts, body = got["headers"]["x-svcs-timestamp"], got["body"]
    sig = got["headers"]["x-svcs-signature"]
    expected = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + body,
                                    hashlib.sha256).hexdigest()
    assert hmac.compare_digest(sig, expected)
    tampered = body.replace(b"person", b"nobody")
    forged = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + tampered,
                                  hashlib.sha256).hexdigest()
    assert not hmac.compare_digest(sig, forged)


def test_no_secret_means_no_signature_header(enabled):
    event_webhook.emit_events(_events())
    assert event_webhook.flush(3.0)
    assert "x-svcs-signature" not in _wait_for(1)[0]["headers"]


def test_secret_is_never_echoed_and_survives_an_omitted_key(receiver):
    event_webhook.save_config({"enabled": True, "url": receiver + "/h", "secret": "abc"})
    pub = event_webhook.public_config()
    assert pub["has_secret"] is True and "secret" not in pub
    # Re-saving other fields without the key keeps the secret.
    ok, _err, pub = event_webhook.save_config({"enabled": False})
    assert ok and pub["has_secret"] is True
    assert event_webhook.load_config()["secret"] == "abc"
    # An explicit empty string clears it.
    _ok, _err, pub = event_webhook.save_config({"secret": ""})
    assert pub["has_secret"] is False


def test_config_file_is_json_with_only_known_keys(enabled):
    data = json.loads(event_webhook.config_path().read_text(encoding="utf-8"))
    assert set(data) == {"enabled", "url", "secret", "saved_at"}


# ── 8-11. failure modes ──────────────────────────────────────────────────────


def test_a_redirect_is_refused_not_followed(enabled):
    _Receiver.mode = "redirect"
    ok, detail = event_webhook.send_test()
    assert not ok and "redirect refused" in detail
    assert [r["path"] for r in _Receiver.received] == ["/hook"]


def test_hanging_receiver_caller_side_returns_immediately(enabled):
    _Receiver.mode = "hang"
    start = time.monotonic()
    assert event_webhook.emit_events(_events())
    assert time.monotonic() - start < 0.5, "emit_events must never wait on the socket"


def test_hanging_receiver_worker_side_gives_up_after_the_timeout(enabled):
    """flush() only drains if the worker's 2s socket timeout actually fires."""
    _Receiver.mode = "hang"
    _Receiver.hang_s = 6.0
    event_webhook.emit_events(_events())
    start = time.monotonic()
    assert event_webhook.flush(timeout=4.0), "worker stayed stuck past its timeout"
    assert time.monotonic() - start < 4.0


def test_an_unreachable_receiver_is_reported_not_raised():
    ok, detail = event_webhook.send_test(url="http://127.0.0.1:9/hook")
    assert not ok and "could not reach" in detail


def test_a_server_error_is_a_status_line_and_the_body_is_never_echoed(enabled):
    _Receiver.mode = "error"
    ok, detail = event_webhook.send_test()
    assert not ok and detail == "HTTP 500"
    _Receiver.mode = "ok"
    ok, detail = event_webhook.send_test()
    assert ok and detail == "HTTP 200" and "secret" not in detail


def test_a_full_queue_drops_without_blocking(enabled, monkeypatch):
    full = queue.Queue(maxsize=1)
    full.put_nowait(("x", b"x"))
    # Scoped so the real queue is back before the drain fixture checks it.
    with monkeypatch.context() as m:
        m.setattr(event_webhook, "_queue", full)
        m.setattr(event_webhook, "_ensure_worker", lambda: None)
        start = time.monotonic()
        assert event_webhook.emit_events(_events()) is False
        assert time.monotonic() - start < 0.5
        assert event_webhook._inflight == 0


def test_test_send_accepts_an_unsaved_url(receiver):
    ok, detail = event_webhook.send_test(url=receiver + "/try")
    assert ok, detail
    assert event_webhook.load_config()["url"] == ""


# ── 12-14. the URL guard ─────────────────────────────────────────────────────


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:9000/hook",
    "http://localhost:9000/hook",
    "http://192.168.1.20:9000/",
    "http://192.168.1.20:9000",          # no path is fine for a webhook
    "http://10.0.0.5/hook",
    "http://172.16.4.4:8123/api/webhook/svcs",
    "https://[::1]:8443/hook",
])
def test_guard_allows_the_self_hosted_targets(url):
    ok, why = event_webhook.is_safe_webhook_url(url)
    assert ok, f"{url} should be allowed, got: {why}"


@pytest.mark.parametrize("url,fragment", [
    ("http://169.254.169.254/latest", "link-local"),
    ("http://100.100.100.100/hook", "metadata"),
    ("http://[fd00:ec2::254]/hook", "metadata"),
    ("http://[::ffff:169.254.169.254]/hook", "link-local"),
    ("http://metadata.google.internal/hook", "metadata"),
    ("http://metadata/hook", "metadata"),
    ("file:///etc/passwd", "scheme"),
    ("ftp://192.168.1.5/hook", "scheme"),
    ("gopher://192.168.1.5/hook", "scheme"),
    ("http://user:pw@192.168.1.5/hook", "secret field"),
    ("", "empty webhook URL"),
    ("   ", "empty webhook URL"),
])
def test_guard_refuses_the_dangerous_shapes(url, fragment):
    ok, why = event_webhook.is_safe_webhook_url(url)
    assert not ok, f"{url} should have been refused"
    assert fragment in why, f"reason {why!r} should mention {fragment!r}"


def test_guard_messages_never_mention_push_fields():
    """The review fix: a webhook operator is never told about a token field."""
    _ok, why = event_webhook.is_safe_webhook_url("http://u:p@10.0.0.1/h")
    assert "token" not in why and "topic" not in why


def test_guard_refuses_a_hostname_that_resolves_to_metadata(monkeypatch):
    def fake_getaddrinfo(host, *_a, **_k):
        return [(2, 1, 6, "", ("169.254.169.254", 0))]
    monkeypatch.setattr(push_notify.socket, "getaddrinfo", fake_getaddrinfo)
    ok, why = event_webhook.is_safe_webhook_url("http://friendly.example/hook")
    assert not ok and "link-local" in why


def test_guard_refuses_a_host_that_does_not_resolve(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("nope")
    monkeypatch.setattr(push_notify.socket, "getaddrinfo", boom)
    ok, why = event_webhook.is_safe_webhook_url("http://nowhere.invalid/hook")
    assert not ok and why == "webhook host does not resolve"


def test_url_is_revalidated_at_send_time(enabled, monkeypatch):
    """A DNS answer that changed since saving is caught on the way out."""
    monkeypatch.setattr(event_webhook, "is_safe_webhook_url",
                        lambda _u: (False, "blocked link-local address"))
    ok, detail = event_webhook.send_test()
    assert not ok and "link-local" in detail
    assert _Receiver.received == []


# ── 16. the two notifiers are independent ────────────────────────────────────


def test_a_webhook_failure_does_not_stop_the_push(enabled, monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(push_notify, "publish_events",
                        lambda ev, camera_id="": seen.append(len(ev)) or 1)

    def boom(*_a, **_k):
        raise RuntimeError("webhook exploded")
    monkeypatch.setattr(event_webhook, "emit_events", boom)
    assert event_log.append_events(tmp_path, _events()) == 1
    assert seen == [1]


def test_a_push_failure_does_not_stop_the_webhook(enabled, monkeypatch, tmp_path):
    def boom(*_a, **_k):
        raise RuntimeError("push exploded")
    monkeypatch.setattr(push_notify, "publish_events", boom)
    assert event_log.append_events(tmp_path, _events()) == 1
    assert event_webhook.flush(3.0)
    assert len(_wait_for(1)) == 1


def test_a_broken_webhook_import_cannot_escape_append_events(monkeypatch, tmp_path):
    """The review fix: an ImportError while loading the module is swallowed."""
    broken = types.ModuleType("utils.event_webhook")   # has no emit_events
    monkeypatch.setitem(sys.modules, "utils.event_webhook", broken)
    assert event_log.append_events(tmp_path, _events()) == 1
    assert (tmp_path / event_log.EVENTS_FILENAME).exists()


# ── 5.10: URL rejection, the bypass shapes (planner 5.10) ────────────────────
# The cases above are the plain spellings. These are the spellings real SSRF
# payload lists use to slip a metadata address past a naive string check.


@pytest.mark.parametrize("url,fragment", [
    # 169.254.169.254 written every other way an IPv4 address can be written
    ("http://2852039166/hook", "link-local"),              # one decimal integer
    ("http://0xa9fea9fe/hook", "link-local"),              # one hex integer
    ("http://0xa9.0xfe.0xa9.0xfe/hook", "link-local"),     # dotted hex
    ("http://0251.0376.0251.0376/hook", "link-local"),     # dotted octal
    ("http://169.254.43518/hook", "link-local"),           # short form
    ("http://169.254.169.254./hook", "link-local"),        # trailing dot
    ("HTTP://169.254.169.254/hook", "link-local"),         # scheme case
    ("http://169.254.169.254:80/hook", "link-local"),      # explicit port
    # the same address through IPv6
    ("http://[::ffff:a9fe:a9fe]/hook", "link-local"),
    ("http://[0:0:0:0:0:ffff:169.254.169.254]/hook", "link-local"),
    ("http://[fe80::1%25eth0]/hook", "link-local"),        # with a zone id
    # every major cloud's metadata endpoint, not only AWS's
    ("http://100.100.100.200/hook", "metadata"),           # Alibaba Cloud
    ("http://192.0.0.192/hook", "metadata"),               # Oracle Cloud (classic)
    ("http://168.63.129.16/hook", "metadata"),             # Azure WireServer
    ("http://[fd00:ec2::254]/hook", "metadata"),           # AWS IMDS over IPv6
    ("http://METADATA.GOOGLE.INTERNAL/hook", "metadata"),  # name case
    ("http://metadata.google.internal./hook", "metadata"), # FQDN trailing dot
    # parser-confusion: which part is the host?
    ("http://192.168.1.5@169.254.169.254/hook", "credentials"),
    ("http://169.254.169.254\\@192.168.1.5/hook", "credentials"),
    ("http://169.254.169.254#@192.168.1.5/hook", "link-local"),
    # nothing-addresses
    ("http://0.0.0.0/hook", "unspecified"),
    ("http://[::]/hook", "unspecified"),
    ("http:///hook", "no host"),
    ("javascript:alert(1)", "scheme"),
])
def test_guard_refuses_ssrf_bypass_spellings(url, fragment):
    ok, why = event_webhook.is_safe_webhook_url(url)
    assert not ok, f"{url} should have been refused"
    assert fragment in why, f"reason {why!r} should mention {fragment!r}"


def test_a_redirect_to_metadata_is_not_followed(enabled):
    """An allowed receiver must not be able to bounce us onto 169.254.169.254."""
    _Receiver.mode = "redirect"
    _Receiver.location = "http://169.254.169.254/latest/meta-data/"
    ok, detail = event_webhook.send_test()
    assert not ok and "redirect refused" in detail
    assert len(_Receiver.received) == 1


def test_a_redirect_to_another_host_never_reaches_it(enabled):
    """Proved from the other end: the second server is never contacted."""
    second = []

    class _Second(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            second.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            return

    srv = _Server(("127.0.0.1", 0), _Second)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        _Receiver.mode = "redirect"
        _Receiver.location = f"http://127.0.0.1:{srv.server_port}/elsewhere"
        for status in (301, 302, 303, 307, 308):
            _Receiver.received = []
            _Receiver.redirect_status = status
            ok, detail = event_webhook.send_test()
            assert not ok and detail == f"HTTP {status} redirect refused"
        assert second == [], "a redirect was followed to the second host"
    finally:
        srv.shutdown()
        srv.server_close()


def test_embedded_credentials_are_refused_on_save_and_never_stored():
    ok, err, _ = event_webhook.save_config(
        {"enabled": True, "url": "http://admin:hunter2@192.168.1.20/hook"})
    assert not ok and "secret field" in err
    assert "hunter2" not in json.dumps(event_webhook.load_config())
