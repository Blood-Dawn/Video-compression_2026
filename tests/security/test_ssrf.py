"""
tests/security/test_ssrf.py  (SEC-013)

The pipeline / HLS input_source is opened with cv2.VideoCapture, which honours
http(s) and file:// URLs. Assert the input guard blocks file:// and the
cloud-metadata / link-local SSRF targets at /api/start and /api/hls/start, while
allowing webcam indices, local paths, and real stream URLs (incl. LAN cameras).
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.services.path_safety import is_safe_input_source  # noqa: E402


@pytest.fixture()
def client():
    from gui.app import app
    # Ensure the start routes are idle so they reach the input-source check rather
    # than short-circuiting with a 409 "already running" left by another test.
    try:
        from gui.state import _state_lock, _status, _hls_lock, _hls_state
    except ModuleNotFoundError:  # pragma: no cover
        from src.gui.state import _state_lock, _status, _hls_lock, _hls_state
    with _state_lock:
        _status["running"] = False
    with _hls_lock:
        _hls_state["running"] = False
    return app.test_client()


BLOCKED = [
    "file:///etc/passwd",
    "file://C:/Windows/win.ini",
    "http://169.254.169.254/latest/meta-data/",
    "https://metadata.google.internal/computeMetadata/v1/",
    "gopher://127.0.0.1:6379/_INFO",
    "dict://localhost:11211/",
]
ALLOWED = [
    "0",                                   # webcam index
    "rtsp://192.168.1.50:554/stream",      # LAN camera (private host must work)
    "http://example.com/live.m3u8",        # public http stream
    "data/sample.mp4",                     # local relative path
    r"C:\Users\op\Videos\clip.mp4",        # windows drive path
]


@pytest.mark.parametrize("src", BLOCKED)
def test_guard_blocks_ssrf_targets(src):
    ok, _why = is_safe_input_source(src)
    assert ok is False, f"{src} should be blocked"


@pytest.mark.parametrize("src", ALLOWED)
def test_guard_allows_legitimate_sources(src):
    ok, why = is_safe_input_source(src)
    assert ok is True, f"{src} should be allowed ({why})"


@pytest.mark.parametrize("src", ["file:///etc/passwd",
                                 "http://169.254.169.254/latest/meta-data/"])
def test_start_route_rejects_ssrf(client, src):
    resp = client.post("/api/start", json={"input_source": src})
    assert resp.status_code == 400
    assert b"input_source not allowed" in resp.data


@pytest.mark.parametrize("src", ["file:///etc/passwd",
                                 "http://169.254.169.254/latest/meta-data/"])
def test_hls_start_route_rejects_ssrf(client, src):
    resp = client.post("/api/hls/start", json={"input_source": src})
    assert resp.status_code == 400
    assert b"input_source not allowed" in resp.data
