"""
src/utils/onvif_discovery.py

ONVIF / WS-Discovery camera discovery + RTSP URL building (M-CAM TASK 1).

Finds ONVIF cameras on the local network with WS-Discovery (a SOAP "Probe"
multicast to 239.255.255.250:3702) and turns a discovered device into an RTSP
source the rest of SVCS already understands (FrameSource handles rtsp:// URLs).

Design goals:
  * No new dependencies - plain UDP socket + xml.etree, so it works in the slim
    ONNX bundle without pulling an ONVIF SDK.
  * Parsing is pure and isolated (parse_probe_matches) so it's unit-testable
    against a captured ProbeMatch without touching the network.
  * Graceful degradation: discover() never raises on a blocked/empty network  - 
    it returns [] and the UI falls back to manual RTSP-URL entry.
  * Credentials never get logged. build_rtsp_url URL-encodes them and callers
    are expected to keep the returned URL out of logs.

ONVIF gives us the device-management XAddr (e.g. http://192.168.1.50/onvif/
device_service); the actual stream URI normally comes from GetStreamUri, which
needs authentication and varies per device. For a dependency-free first pass we
build the well-known RTSP paths for the major surveillance brands
(Reolink/Amcrest/Dahua/Hikvision) from the device's advertised scopes, plus
generic fallbacks - the operator can pick or paste the exact path.

Author: Bloodawn (KheivenD), 2026-06-03 (M-CAM TASK 1 - ONVIF discovery).
"""

from __future__ import annotations

import socket
import uuid
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree as ET

# WS-Discovery multicast endpoint (same for IPv4 ONVIF everywhere).
WSD_MCAST_ADDR = "239.255.255.250"
WSD_MCAST_PORT = 3702

# Well-known RTSP path templates per brand, keyed by a substring that shows up
# in the ONVIF "name"/"hardware" scope. Data-driven on purpose: adding a brand
# is one line, no code branch. {chan}/{stream} are filled with sane defaults.
VENDOR_RTSP_PATHS: Dict[str, List[str]] = {
    "reolink": ["/h264Preview_01_main", "/h264Preview_01_sub"],
    "amcrest": ["/cam/realmonitor?channel=1&subtype=0"],
    "dahua":   ["/cam/realmonitor?channel=1&subtype=0"],
    "hikvision": ["/Streaming/Channels/101", "/Streaming/Channels/102"],
    "hilook":  ["/Streaming/Channels/101"],
    "axis":    ["/axis-media/media.amp"],
    "tp-link": ["/stream1", "/stream2"],
    "tapo":    ["/stream1", "/stream2"],
    "wyze":    ["/live"],
}
# Tried when the brand is unknown - common ONVIF/RTSP defaults.
GENERIC_RTSP_PATHS: List[str] = ["/stream1", "/onvif1", "/live", "/11", "/0"]

DEFAULT_RTSP_PORT = 554


@dataclass
class OnvifDevice:
    """A camera found via WS-Discovery."""
    address: str                      # IP/host parsed from the XAddr
    xaddr: str                        # ONVIF device-service URL
    name: str = ""                    # from onvif://.../name/<...>
    hardware: str = ""                # from onvif://.../hardware/<...>
    location: str = ""                # from onvif://.../location/<...>
    endpoint: str = ""                # EndpointReference Address (stable id)
    scopes: List[str] = field(default_factory=list)

    def vendor_key(self) -> Optional[str]:
        """Best-effort brand key for VENDOR_RTSP_PATHS, from name/hardware."""
        hay = f"{self.name} {self.hardware}".lower()
        for key in VENDOR_RTSP_PATHS:
            if key in hay:
                return key
        return None

    def as_dict(self) -> dict:
        return asdict(self)


def _local_tag(tag: str) -> str:
    """Strip the XML namespace from a tag: '{ns}ProbeMatch' -> 'ProbeMatch'."""
    return tag.rsplit("}", 1)[-1]


def _findall_local(root: ET.Element, name: str) -> List[ET.Element]:
    """Find every descendant whose local (namespace-stripped) tag == name."""
    return [el for el in root.iter() if _local_tag(el.tag) == name]


def _parse_scopes(scopes_text: str) -> Tuple[str, str, str, List[str]]:
    """Pull name/hardware/location out of a space-separated ONVIF scopes string."""
    name = hardware = location = ""
    scopes = [s for s in scopes_text.split() if s]
    for s in scopes:
        low = s.lower()
        # scope looks like onvif://www.onvif.org/name/Reolink
        if "/name/" in low:
            name = s.rsplit("/name/", 1)[-1]
        elif "/hardware/" in low:
            hardware = s.rsplit("/hardware/", 1)[-1]
        elif "/location/" in low:
            location = s.rsplit("/location/", 1)[-1]
    # ONVIF percent-encodes spaces in scope values.
    unq = lambda v: v.replace("%20", " ").replace("%2F", "/")
    return unq(name), unq(hardware), unq(location), scopes


def parse_probe_matches(xml_data, source_ip: Optional[str] = None) -> List[OnvifDevice]:
    """Parse a WS-Discovery ProbeMatch(es) SOAP body into OnvifDevice objects.

    Pure and network-free - this is the unit-tested core. Tolerates the
    namespace and tag-ordering variations real cameras emit by matching on
    local tag names. Returns [] on unparseable input.
    """
    if isinstance(xml_data, bytes):
        try:
            xml_data = xml_data.decode("utf-8", "replace")
        except Exception:  # pragma: no cover - decode is very forgiving
            return []
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError:
        return []

    devices: List[OnvifDevice] = []
    for match in _findall_local(root, "ProbeMatch"):
        xaddrs_els = _findall_local(match, "XAddrs")
        xaddrs_text = " ".join((el.text or "") for el in xaddrs_els).strip()
        xaddrs = [x for x in xaddrs_text.split() if x]
        if not xaddrs:
            continue  # nothing addressable; skip

        scopes_els = _findall_local(match, "Scopes")
        scopes_text = " ".join((el.text or "") for el in scopes_els)
        name, hardware, location, scopes = _parse_scopes(scopes_text)

        endpoint = ""
        for addr in _findall_local(match, "Address"):
            if (addr.text or "").strip():
                endpoint = addr.text.strip()
                break

        # One device per first XAddr; host parsed from it (fallback to source_ip).
        xaddr = xaddrs[0]
        host = urlsplit(xaddr).hostname or (source_ip or "")
        devices.append(OnvifDevice(
            address=host, xaddr=xaddr, name=name, hardware=hardware,
            location=location, endpoint=endpoint, scopes=scopes,
        ))
    return devices


def build_rtsp_url(
    host: str,
    path: str = "/stream1",
    port: int = DEFAULT_RTSP_PORT,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> str:
    """Build an rtsp:// URL, URL-encoding any credentials.

    Credentials are percent-encoded so an '@' or ':' in a password can't break
    the URL (or silently point at the wrong host). The caller must keep the
    returned string out of logs - it may embed a password.
    """
    if not host:
        raise ValueError("host is required")
    if not path.startswith("/"):
        path = "/" + path
    auth = ""
    if username:
        auth = quote(username, safe="")
        if password:
            auth += ":" + quote(password, safe="")
        auth += "@"
    return f"rtsp://{auth}{host}:{int(port)}{path}"


def rtsp_url_candidates(
    device: OnvifDevice,
    username: Optional[str] = None,
    password: Optional[str] = None,
    port: int = DEFAULT_RTSP_PORT,
) -> List[str]:
    """Candidate RTSP URLs for a device: brand-specific paths first, then generics.

    The exact path varies per model/firmware; we offer the known-good ones for
    the detected brand and fall back to common defaults so the operator can try
    them or paste the real one.
    """
    if not device.address:
        return []
    key = device.vendor_key()
    paths = list(VENDOR_RTSP_PATHS.get(key, [])) if key else []
    for gp in GENERIC_RTSP_PATHS:
        if gp not in paths:
            paths.append(gp)
    return [build_rtsp_url(device.address, p, port, username, password) for p in paths]


def _build_probe_message() -> bytes:
    """A minimal WS-Discovery Probe for ONVIF NetworkVideoTransmitter devices."""
    msg_id = "uuid:" + str(uuid.uuid4())
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
        'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
        'xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
        "<e:Header>"
        f"<w:MessageID>{msg_id}</w:MessageID>"
        "<w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>"
        "<w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>"
        "</e:Header>"
        "<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>"
        "</e:Envelope>"
    ).encode("utf-8")


def discover(timeout: float = 3.0) -> List[OnvifDevice]:
    """Probe the LAN for ONVIF cameras; return discovered devices (deduped).

    Never raises: a blocked multicast (Windows Firewall), no network, or no
    cameras all yield []. The caller then falls back to manual RTSP entry.
    Discovered XAddrs/scopes are safe to log; credentials are never involved
    here (auth happens later when building the stream URL).
    """
    sock = None
    found: Dict[str, OnvifDevice] = {}
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(timeout)
        sock.sendto(_build_probe_message(), (WSD_MCAST_ADDR, WSD_MCAST_PORT))
        while True:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                break
            for dev in parse_probe_matches(data, source_ip=addr[0]):
                key = dev.endpoint or dev.xaddr
                found.setdefault(key, dev)
    except OSError:
        return list(found.values())  # whatever we got before the failure
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:  # pragma: no cover
                pass
    return list(found.values())
