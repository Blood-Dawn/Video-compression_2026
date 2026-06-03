"""
tests/test_onvif_discovery.py

Tests for ONVIF / WS-Discovery camera discovery (M-CAM TASK 1).

Network-free: the parser is exercised against captured ProbeMatch SOAP bodies
(a Reolink and a Hikvision camera, with different namespace prefixes and a
percent-encoded name), RTSP-URL building is checked for credential encoding and
path handling, and discover() is driven through a fake socket so the multicast
loop is covered deterministically — plus a graceful-degradation case where the
network errors out and discover() must return [] rather than raise. The two
camera-setup routes are smoke-tested through the Flask test client.

Author: Bloodawn (KheivenD), 2026-06-03 (M-CAM TASK 1 — ONVIF discovery).
"""

import socket
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils import onvif_discovery as od  # noqa: E402
from utils.onvif_discovery import (  # noqa: E402
    OnvifDevice,
    build_rtsp_url,
    discover,
    parse_probe_matches,
    rtsp_url_candidates,
)


# A real-shape Reolink ProbeMatch (SOAP-ENV / wsdd prefixes).
REOLINK_XML = """<?xml version="1.0" encoding="utf-8"?>
<SOAP-ENV:Envelope
 xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"
 xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:wsdd="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
 <SOAP-ENV:Header>
  <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches</wsa:Action>
 </SOAP-ENV:Header>
 <SOAP-ENV:Body>
  <wsdd:ProbeMatches>
   <wsdd:ProbeMatch>
    <wsa:EndpointReference><wsa:Address>urn:uuid:2419d68a-aaaa</wsa:Address></wsa:EndpointReference>
    <wsdd:Types>dn:NetworkVideoTransmitter tds:Device</wsdd:Types>
    <wsdd:Scopes>onvif://www.onvif.org/name/Reolink onvif://www.onvif.org/hardware/RLC-810A onvif://www.onvif.org/location/garage</wsdd:Scopes>
    <wsdd:XAddrs>http://192.168.1.50/onvif/device_service</wsdd:XAddrs>
    <wsdd:MetadataVersion>1</wsdd:MetadataVersion>
   </wsdd:ProbeMatch>
  </wsdd:ProbeMatches>
 </SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""

# A Hikvision ProbeMatch with different prefixes and a %20 in the name.
HIK_XML = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
 xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
 <s:Body>
  <d:ProbeMatches>
   <d:ProbeMatch>
    <a:EndpointReference><a:Address>urn:uuid:hik-001</a:Address></a:EndpointReference>
    <d:Scopes>onvif://www.onvif.org/name/HIKVISION%20DS-2CD2042 onvif://www.onvif.org/hardware/DS-2CD2042</d:Scopes>
    <d:XAddrs>http://192.168.1.64:80/onvif/device_service</d:XAddrs>
   </d:ProbeMatch>
  </d:ProbeMatches>
 </s:Body>
</s:Envelope>"""


# ── parsing ──────────────────────────────────────────────────────────────────

def test_parse_reolink_probe_match():
    devices = parse_probe_matches(REOLINK_XML)
    assert len(devices) == 1
    d = devices[0]
    assert d.address == "192.168.1.50"
    assert d.xaddr == "http://192.168.1.50/onvif/device_service"
    assert d.name == "Reolink"
    assert d.hardware == "RLC-810A"
    assert d.location == "garage"
    assert d.endpoint == "urn:uuid:2419d68a-aaaa"
    assert d.vendor_key() == "reolink"


def test_parse_handles_alt_prefixes_and_percent_encoding():
    devices = parse_probe_matches(HIK_XML.encode("utf-8"))  # also accepts bytes
    assert len(devices) == 1
    d = devices[0]
    assert d.address == "192.168.1.64"
    assert d.name == "HIKVISION DS-2CD2042"  # %20 decoded
    assert d.vendor_key() == "hikvision"


def test_parse_skips_match_without_xaddrs():
    no_xaddr = REOLINK_XML.replace(
        "<wsdd:XAddrs>http://192.168.1.50/onvif/device_service</wsdd:XAddrs>", ""
    )
    assert parse_probe_matches(no_xaddr) == []


def test_parse_garbage_returns_empty():
    assert parse_probe_matches("not xml at all") == []
    assert parse_probe_matches(b"\x00\x01\x02") == []
    assert parse_probe_matches("<a><b/></a>") == []  # valid xml, no ProbeMatch


# ── RTSP URL building ────────────────────────────────────────────────────────

def test_build_rtsp_url_no_credentials():
    assert build_rtsp_url("192.168.1.50", "/stream1") == "rtsp://192.168.1.50:554/stream1"


def test_build_rtsp_url_with_credentials():
    url = build_rtsp_url("10.0.0.5", "/h264", port=8554, username="admin", password="pw")
    assert url == "rtsp://admin:pw@10.0.0.5:8554/h264"


def test_build_rtsp_url_encodes_special_chars_in_credentials():
    # An '@' / ':' in the password must be encoded or it would break the URL.
    url = build_rtsp_url("host", "/s", username="user@x", password="p@ss:w/d")
    assert "user%40x" in url
    assert "p%40ss%3Aw%2Fd" in url
    # Exactly one '@' separates auth from host.
    assert url.count("@") == 1


def test_build_rtsp_url_normalizes_path_and_requires_host():
    assert build_rtsp_url("h", "stream1").endswith(":554/stream1")  # adds leading /
    with pytest.raises(ValueError):
        build_rtsp_url("", "/s")


def test_rtsp_candidates_vendor_first_then_generic():
    dev = OnvifDevice(address="192.168.1.50", xaddr="x", name="Reolink", hardware="RLC-810A")
    cands = rtsp_url_candidates(dev)
    assert cands[0] == "rtsp://192.168.1.50:554/h264Preview_01_main"
    assert any("/stream1" in c for c in cands)  # generic fallback still offered


def test_rtsp_candidates_unknown_vendor_uses_generics():
    dev = OnvifDevice(address="192.168.1.99", xaddr="x", name="NoNameCam")
    cands = rtsp_url_candidates(dev)
    assert cands and all(c.startswith("rtsp://192.168.1.99:554/") for c in cands)


def test_rtsp_candidates_without_address_is_empty():
    assert rtsp_url_candidates(OnvifDevice(address="", xaddr="x")) == []


# ── discover() through a fake socket ─────────────────────────────────────────

class _FakeSocket:
    """Yields one ProbeMatch then times out, mimicking a single camera reply."""
    def __init__(self, *a, **k):
        self._queue = [(REOLINK_XML.encode("utf-8"), ("192.168.1.50", 3702))]

    def setsockopt(self, *a):
        pass

    def settimeout(self, t):
        pass

    def sendto(self, data, addr):
        return len(data)

    def recvfrom(self, n):
        if self._queue:
            return self._queue.pop(0)
        raise socket.timeout()

    def close(self):
        pass


def test_discover_parses_fake_socket_reply(monkeypatch):
    monkeypatch.setattr(od.socket, "socket", lambda *a, **k: _FakeSocket())
    devices = discover(timeout=0.1)
    assert len(devices) == 1
    assert devices[0].name == "Reolink"


def test_discover_degrades_gracefully_on_network_error(monkeypatch):
    class _BrokenSocket(_FakeSocket):
        def sendto(self, data, addr):
            raise OSError("network unreachable")
    monkeypatch.setattr(od.socket, "socket", lambda *a, **k: _BrokenSocket())
    assert discover(timeout=0.1) == []  # returns [], never raises


def test_discover_dedupes_repeated_replies(monkeypatch):
    class _DupSocket(_FakeSocket):
        def __init__(self, *a, **k):
            payload = (REOLINK_XML.encode("utf-8"), ("192.168.1.50", 3702))
            self._queue = [payload, payload]  # same camera answers twice
    monkeypatch.setattr(od.socket, "socket", lambda *a, **k: _DupSocket())
    assert len(discover(timeout=0.1)) == 1


# ── camera-setup routes ──────────────────────────────────────────────────────

@pytest.fixture()
def client():
    from gui.app import app
    return app.test_client()


def test_route_discover_returns_cameras(client, monkeypatch):
    import gui.routes.cameras_bp as cbp
    dev = OnvifDevice(address="192.168.1.50", xaddr="x", name="Reolink", hardware="RLC-810A")
    monkeypatch.setattr(cbp, "discover", lambda timeout=3.0: [dev])
    resp = client.get("/api/cameras/discover")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] and body["count"] == 1
    cam = body["cameras"][0]
    assert cam["address"] == "192.168.1.50"
    assert cam["vendor"] == "reolink"
    assert cam["rtsp_candidates"][0].endswith("/h264Preview_01_main")


def test_route_discover_empty_is_ok(client, monkeypatch):
    import gui.routes.cameras_bp as cbp
    monkeypatch.setattr(cbp, "discover", lambda timeout=3.0: [])
    resp = client.get("/api/cameras/discover")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "count": 0, "cameras": []}


def test_route_rtsp_url_builds_and_validates(client):
    ok = client.post("/api/cameras/rtsp_url",
                     json={"host": "192.168.1.50", "path": "/stream1",
                           "username": "admin", "password": "p@ss"})
    assert ok.status_code == 200
    assert ok.get_json()["rtsp_url"] == "rtsp://admin:p%40ss@192.168.1.50:554/stream1"

    assert client.post("/api/cameras/rtsp_url", json={}).status_code == 400
    assert client.post("/api/cameras/rtsp_url",
                       json={"host": "h", "port": 99999}).status_code == 400
