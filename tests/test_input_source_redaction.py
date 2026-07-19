"""
tests/test_input_source_redaction.py

Camera passwords must not reach an API client.

RTSP URLs commonly embed credentials, and /api/cameras/rtsp_url builds exactly
that shape (its own comment says "never log the full URL - it may carry a
password"). Two routes still echoed the stored input_source straight back:
/api/hls/status returned the whole HLS state dict, and /api/status returned
config.input_source. Both are readable with a DEVICE TOKEN, which M0.10
deliberately made the weaker credential - a stolen one cannot mint successors
or revoke other devices, but it could read the camera's password, and that
usually unlocks the camera's own web admin.

Found while measuring HLS warmup for M3: the LIVE tab is what makes a phone
poll these routes continuously, and the HOME tab already polls /api/status
every 2.5s.

Author: Bloodawn (KheivenD), 2026-07-19 (M3 pre-work).
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui import state                                          # noqa: E402
from gui.app import app                                        # noqa: E402
from gui.services.path_safety import redact_input_source       # noqa: E402

SECRET = "SuperSecret123"


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    return app.test_client()


class TestRedactInputSource:
    """The helper itself."""

    def test_strips_rtsp_password_but_keeps_the_camera_identifiable(self):
        out = redact_input_source(
            f"rtsp://admin:{SECRET}@192.168.1.50:554/stream1")
        assert SECRET not in out
        # An operator still has to be able to tell which camera this is.
        assert "192.168.1.50" in out
        assert "554" in out
        assert "/stream1" in out
        assert "admin" in out

    def test_webcam_index_passes_through(self):
        assert redact_input_source("0") == "0"

    def test_local_path_passes_through(self):
        p = r"C:\Users\op\Videos\clip.mp4"
        assert redact_input_source(p) == p

    def test_url_without_credentials_is_unchanged(self):
        u = "rtsp://192.168.1.50:554/stream1"
        assert redact_input_source(u) == u

    def test_none_becomes_empty_string(self):
        # The state dict holds None before any stream has run; the route must
        # not emit the string "None" to a client.
        assert redact_input_source(None) == ""

    def test_password_containing_at_sign_is_fully_removed(self):
        # "@" inside the password is the case a naive split on the last "@"
        # gets wrong: it would leave part of the password behind.
        out = redact_input_source("rtsp://admin:p%40ss%40word@10.0.0.5:554/s")
        assert "p%40ss%40word" not in out
        assert "10.0.0.5" in out

    def test_username_only_url_is_left_alone(self):
        # No password component, so there is nothing to strip.
        u = "rtsp://admin@10.0.0.5:554/s"
        assert redact_input_source(u) == u

    @pytest.mark.parametrize("scheme", ["rtsp", "rtsps", "http", "https", "rtmp"])
    def test_every_credential_carrying_scheme_is_covered(self, scheme):
        out = redact_input_source(f"{scheme}://u:{SECRET}@host:1234/path")
        assert SECRET not in out


class TestRoutesDoNotLeak:
    """The two routes that were actually leaking."""

    def test_hls_status_redacts_input_source(self, client):
        with state._hls_lock:
            state._hls_state["input_source"] = (
                f"rtsp://admin:{SECRET}@192.168.1.50:554/stream1")
            state._hls_state["running"] = True
        try:
            resp = client.get("/api/hls/status")
            assert resp.status_code == 200
            body = resp.get_data(as_text=True)
            assert SECRET not in body, \
                "camera password served by /api/hls/status"
            assert "192.168.1.50" in body
        finally:
            with state._hls_lock:
                state._hls_state["input_source"] = None
                state._hls_state["running"] = False

    def test_status_redacts_config_input_source(self, client):
        with state._state_lock:
            state._status["config"] = {
                "input_source": f"rtsp://op:{SECRET}@192.168.1.77:554/h264",
                "camera_id": "cam_00",
            }
        try:
            resp = client.get("/api/status")
            assert resp.status_code == 200
            assert SECRET not in resp.get_data(as_text=True), \
                "camera password served by /api/status"
        finally:
            with state._state_lock:
                state._status["config"] = {}

    def test_redacting_the_response_does_not_corrupt_running_state(self, client):
        """The pipeline still needs the real URL to keep streaming.

        dict(_status) is a SHALLOW copy, so redacting config in place would
        scrub the URL out from under the running pipeline and the stream would
        die on the next reconnect. This is the test that catches that mistake.
        """
        real = f"rtsp://op:{SECRET}@192.168.1.77:554/h264"
        with state._state_lock:
            state._status["config"] = {"input_source": real}
        try:
            client.get("/api/status")
            with state._state_lock:
                assert state._status["config"]["input_source"] == real, \
                    "serialising the response mutated the live pipeline config"
        finally:
            with state._state_lock:
                state._status["config"] = {}
