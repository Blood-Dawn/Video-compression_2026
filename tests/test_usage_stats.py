"""
tests/test_usage_stats.py

Tests opt-in anonymous usage statistics (M5 TASK 5.2).

The acceptance: nothing is collected or sent when usage stats are off (the
default), and any payload that IS sent carries no PII or path fields. Also
covers consent persistence, the env kill-switch, the field whitelist + PII
scrub, categorical coercion, and the consent routes.

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 5.2 - usage stats).
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils import usage_stats as us  # noqa: E402


@pytest.fixture()
def consent_file(tmp_path):
    return tmp_path / "usage_consent.json"


@pytest.fixture(autouse=True)
def _reset_sink(monkeypatch):
    # Capture emitted payloads instead of writing to disk / network.
    sent = []
    monkeypatch.setattr(us, "_SINK", lambda payload: sent.append(payload))
    monkeypatch.delenv(us.ENV_OPT_OUT, raising=False)
    return sent


# ── consent + enablement ─────────────────────────────────────────────────────

def test_default_is_off(consent_file):
    assert us.read_consent(consent_file) is None      # unknown on first run
    assert us.is_enabled(consent_file) is False


def test_consent_round_trip(consent_file):
    us.set_consent(True, consent_file)
    assert us.read_consent(consent_file) is True
    assert us.is_enabled(consent_file) is True
    us.set_consent(False, consent_file)
    assert us.read_consent(consent_file) is False
    assert us.is_enabled(consent_file) is False


def test_env_kill_switch_forces_off(consent_file, monkeypatch):
    us.set_consent(True, consent_file)
    monkeypatch.setenv(us.ENV_OPT_OUT, "1")
    assert us.is_enabled(consent_file) is False


# ── nothing is sent when off (THE acceptance) ────────────────────────────────

def test_record_event_is_noop_when_off(consent_file, _reset_sink):
    result = us.record_event("encode", path=consent_file,
                             preset="continuous_cctv", mode="mode2",
                             codec="auto", success=True)
    assert result is None          # nothing built
    assert _reset_sink == []       # sink never called


def test_record_event_emits_when_on(consent_file, _reset_sink):
    us.set_consent(True, consent_file)
    result = us.record_event("encode", path=consent_file,
                             preset="continuous_cctv", mode="mode2",
                             codec="libsvtav1", success=True,
                             error_category="none", ingestion_path="rtsp")
    assert result is not None
    assert _reset_sink == [result]
    assert result["preset"] == "continuous_cctv"
    assert result["ingestion_path"] == "rtsp"
    assert result["success"] is True


# ── payloads carry no PII / paths (THE other half of acceptance) ─────────────

def test_sanitize_drops_path_and_pii_shaped_values():
    # Even if a path/email/IP is shoved into an allowed free field, it's dropped.
    payload = us.sanitize_event("encode", {
        "preset": "doorbell",
        "mode": "mode3",
        "codec": "libsvtav1",
        "success": True,
        # error_category fed something path-like -> coerced to vocab, not leaked
        "error_category": "/home/user/secret/clip.mp4",
        "ingestion_path": "watchfolder",
    })
    blob = repr(payload)
    assert "/home/user" not in blob and "clip.mp4" not in blob
    assert payload["error_category"] in us._VOCAB["error_category"]


def test_sanitize_strips_unknown_fields():
    payload = us.sanitize_event("encode", {
        "preset": "generic", "mode": "mode1", "codec": "auto",
        "filename": "C:/Users/bob/evidence.mp4",   # not whitelisted
        "camera_id": "front_door",                 # not whitelisted
        "ip": "192.168.1.50",                      # not whitelisted
    })
    assert set(payload) <= {"schema", "event_type", "preset", "mode", "codec",
                            "success", "error_category", "ingestion_path"}
    blob = repr(payload).lower()
    for leak in ("evidence", "users/bob", "front_door", "192.168"):
        assert leak not in blob


def test_unknown_preset_becomes_other():
    payload = us.sanitize_event("encode", {"preset": "../etc/passwd"})
    assert payload["preset"] == "other"


def test_invalid_categorical_coerced_to_vocab():
    payload = us.sanitize_event("encode", {"mode": "mode99", "codec": "h265",
                                           "ingestion_path": "ftp"})
    # mode/codec have no "unknown" member -> "other"; ingestion_path has one.
    assert payload["mode"] == "other"
    assert payload["codec"] == "other"
    assert payload["ingestion_path"] == "unknown"
    # No H.265 ever - and it didn't pass through.
    assert "265" not in repr(payload)


def test_no_persistent_identifier_in_payload():
    payload = us.sanitize_event("encode", {"preset": "archive"})
    # No machine id / uuid / user fields.
    for k in payload:
        assert k in {"schema", "event_type", "preset", "mode", "codec",
                     "success", "error_category", "ingestion_path"}


# ── consent routes ───────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    from gui.app import app
    return app.test_client()


def test_route_get_status_shape(client):
    body = client.get("/api/usage_stats").get_json()
    assert set(body) == {"known", "consent", "enabled"}


def test_route_consent_requires_field(client):
    assert client.post("/api/usage_stats/consent", json={}).status_code == 400


def test_route_consent_sets_value(client, tmp_path, monkeypatch):
    # Redirect the consent file to tmp so the test doesn't touch real app data.
    monkeypatch.setattr(us, "_consent_path", lambda path=None: tmp_path / "c.json")
    resp = client.post("/api/usage_stats/consent", json={"consent": True})
    assert resp.status_code == 200 and resp.get_json()["consent"] is True
    assert us.read_consent() is True
