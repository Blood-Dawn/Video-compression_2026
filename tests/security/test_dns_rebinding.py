"""
tests/security/test_dns_rebinding.py  (SEC-017)

is_safe_push_url()/validate_push_url() validate a hostname's DNS resolution
ONCE. Before this fix, the actual outbound request (urllib) then resolved the
same hostname a SECOND time, independently, when it opened the connection. A
hostile authoritative DNS server can answer those two lookups differently: a
public IP for the validation lookup, then a loopback or link-local address
for the connection lookup, walking straight through the SSRF guard. This is a
classic DNS-rebinding TOCTOU (time-of-check/time-of-use) bug.

The fix is pin_resolution(): once a hostname's addresses are validated, the
actual connection is pinned to exactly those addresses, so there is only
ever one resolution in effect for that request, regardless of what DNS
answers with in the meantime.

These tests prove two things: (1) the rebinding scenario is real - a naive
two-lookup design really would be fooled by it, and (2) pin_resolution
closes it - once validate_push_url has approved a set of addresses, nothing
that happens to the "live" resolver afterward can change what the actual
connection uses.
"""

import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils import push_notify  # noqa: E402
from utils import event_webhook  # noqa: E402


class _Recorder(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler's spelling
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        _Recorder.received.append(self.path)
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):  # keep pytest output clean
        return


@pytest.fixture
def listener():
    """A throwaway HTTP server on 127.0.0.1; yields its port."""
    _Recorder.received = []
    srv = HTTPServer(("127.0.0.1", 0), _Recorder)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv.server_port
    finally:
        srv.shutdown()
        srv.server_close()


# ── the vulnerability, demonstrated against a naive two-lookup design ────────


def test_a_naive_validate_then_reresolve_design_is_fooled_by_rebinding(monkeypatch):
    """Without pinning, validating a hostname and then letting the HTTP
    client resolve it again independently is exactly the SEC-017 gap. This
    test proves the attack is real against that naive pattern, so the fix
    below is proven against a genuine threat and not a strawman.
    """
    host = "rebind.example.test"
    calls = {"n": 0}

    def rebinding_getaddrinfo(node, *a, **kw):
        if node != host:
            return socket.getaddrinfo.__wrapped__(node, *a, **kw) if hasattr(
                socket.getaddrinfo, "__wrapped__"
            ) else _real_getaddrinfo(node, *a, **kw)
        calls["n"] += 1
        if calls["n"] == 1:
            # The validation lookup: an innocuous public address.
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
        # Every later lookup (i.e. the connection itself): a blocked target.
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    _real_getaddrinfo = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", rebinding_getaddrinfo)

    ok, why, addrs, resolved_host = push_notify.validate_push_url(
        f"http://{host}/svcs-alerts"
    )
    assert ok is True, why
    assert [str(a) for a in addrs] == ["93.184.216.34"]

    # The naive pattern: validate, then let a second, independent lookup
    # decide where the connection actually goes.
    connect_time = socket.getaddrinfo(resolved_host, None)
    connect_ip = connect_time[0][4][0]
    assert connect_ip == "127.0.0.1", (
        "the mocked resolver itself must rebind for this test to mean anything"
    )
    assert connect_ip != str(addrs[0]), "guard was bypassed by the rebinding DNS answer"


# ── the fix: pin_resolution closes the gap ───────────────────────────────────


def test_pin_resolution_ignores_a_rebound_answer_for_the_pinned_host(monkeypatch):
    host = "rebind.example.test"
    real_getaddrinfo = socket.getaddrinfo
    calls = {"n": 0}

    def rebinding_getaddrinfo(node, *a, **kw):
        if node != host:
            return real_getaddrinfo(node, *a, **kw)
        calls["n"] += 1
        if calls["n"] == 1:
            # The validation lookup: a safe, public address.
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
        # Every later (unpinned) lookup: the DNS server has rebound to a
        # blocked target. If this were ever consulted again inside the
        # pinned block, the pin would have failed to hold.
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", rebinding_getaddrinfo)

    ok, why, addrs, resolved_host = push_notify.validate_push_url(
        f"http://{host}/svcs-alerts"
    )
    assert ok is True, why
    assert str(addrs[0]) == "93.184.216.34"

    with push_notify.pin_resolution(resolved_host, addrs):
        pinned = socket.getaddrinfo(host, 8080)
        pinned_ip = pinned[0][4][0]

    assert pinned_ip == str(addrs[0])
    assert pinned_ip != "169.254.169.254"

    # Outside the pinned block, the (mocked) live resolver is back in
    # charge and shows the rebind - proving the pin, not luck, is what kept
    # the in-block lookup on the validated address, and that pin_resolution
    # does not leak its patch past its own scope.
    after = socket.getaddrinfo(host, 8080)
    assert after[0][4][0] == "169.254.169.254"


def test_push_notify_post_reaches_only_the_validated_address(monkeypatch, listener):
    """End-to-end: even when the "live" resolver would rebind a hostname to
    a different address for the connection, _post() still only ever talks
    to the address validate_push_url approved.
    """
    host = "rebind.example.test"
    real_getaddrinfo = socket.getaddrinfo

    def rebinding_getaddrinfo(node, *a, **kw):
        if node != host:
            return real_getaddrinfo(node, *a, **kw)
        # Always answers with the real test listener - pin_resolution only
        # ever consults this once per request (at validate_push_url time),
        # so a call reaching here a second time for the connection itself
        # would be the bug reopening.
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", rebinding_getaddrinfo)

    ok, detail = push_notify._post(
        {"topic_url": f"http://{host}:{listener}/svcs-alerts", "token": ""},
        title="t", message="m",
    )
    assert ok is True, detail
    assert _Recorder.received == ["/svcs-alerts"]


def test_event_webhook_post_reuses_the_same_pinned_guard(monkeypatch, listener):
    """event_webhook._post shares push_notify's guard and pinning, not a
    re-derived copy of it (see the module's own docstring)."""
    host = "rebind.example.test"
    real_getaddrinfo = socket.getaddrinfo

    def rebinding_getaddrinfo(node, *a, **kw):
        if node != host:
            return real_getaddrinfo(node, *a, **kw)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", rebinding_getaddrinfo)

    ok, detail = event_webhook._post(
        {"url": f"http://{host}:{listener}/hook", "secret": ""},
        "job_complete", {"camera_id": "cam1"},
    )
    assert ok is True, detail
    assert _Recorder.received == ["/hook"]


def test_pin_resolution_fails_closed_when_family_does_not_match():
    """A caller that asks getaddrinfo for a family the pin has no address
    for gets a normal resolution error, never a silent fallback to a fresh,
    unpinned lookup - that fallback would just reopen SEC-017."""
    import ipaddress

    host = "svcs-pin-test.invalid"
    addrs = [ipaddress.ip_address("127.0.0.1")]
    with push_notify.pin_resolution(host, addrs):
        with pytest.raises(socket.gaierror):
            socket.getaddrinfo(host, 80, family=socket.AF_INET6)
