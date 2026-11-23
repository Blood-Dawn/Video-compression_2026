"""
tests/test_security_cam.py

Security cam: a paired phone uploads short clips, the desktop compresses them.
These tests cover the desktop side: saved settings, the password-only rule for
changes, starting and stopping the watch on the upload folder, and the recent
clip list with real source and output sizes.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.app import app                                    # noqa: E402
from gui.routes import security_cam_bp as sc               # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated settings file, upload folder and auto compress stub."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    calls = {"start": [], "stop": 0}
    state = {"running": False, "folder": ""}

    monkeypatch.setattr(sc, "state_file", lambda name: tmp_path / name)
    monkeypatch.setattr(sc, "_upload_dir", lambda: uploads)
    monkeypatch.setattr(sc, "_output_root", lambda: tmp_path / "out")
    monkeypatch.setattr(sc, "_phones", lambda: [])
    monkeypatch.setattr(sc.ac, "get_status", lambda: dict(state))

    def fake_start(config):
        calls["start"].append(config)
        state.update(running=True, folder=config["folder"])
        return True

    def fake_stop():
        calls["stop"] += 1
        state.update(running=False)
        return True

    monkeypatch.setattr(sc.ac, "start_autocompress", fake_start)
    monkeypatch.setattr(sc.ac, "stop_autocompress", fake_stop)
    app.config["TESTING"] = True
    return SimpleNamespace(uploads=uploads, calls=calls, state=state,
                           client=app.test_client(), tmp=tmp_path)


def test_defaults(env):
    body = env.client.get("/api/security-cam").get_json()
    assert body["segment_seconds"] == 300
    assert body["mode"] == "mode0"
    assert body["receiving"] is False
    assert body["segment_choices"] == [60, 300, 600, 900, 1800]
    assert body["watch_folder"] == str(env.uploads)


def test_settings_are_saved_and_read_back(env):
    res = env.client.post("/api/security-cam", json={"segment_seconds": 600, "mode": "mode1"})
    assert res.status_code == 200
    body = env.client.get("/api/security-cam").get_json()
    assert (body["segment_seconds"], body["mode"]) == (600, "mode1")


@pytest.mark.parametrize("bad", [{"segment_seconds": 45}, {"segment_seconds": "300"},
                                 {"mode": "mode9"}, {"mode": ""}])
def test_invalid_settings_are_rejected_and_not_saved(env, bad):
    res = env.client.post("/api/security-cam", json=bad)
    assert res.status_code == 400
    assert env.client.get("/api/security-cam").get_json()["segment_seconds"] == 300


def test_a_corrupt_settings_file_falls_back_to_defaults(env):
    (env.tmp / sc.SETTINGS_FILE).write_text("{not json", encoding="utf-8")
    assert sc.load_settings() == sc.DEFAULTS


def test_enable_starts_auto_compress_on_the_upload_folder(env):
    env.client.post("/api/security-cam", json={"mode": "mode2"})
    res = env.client.post("/api/security-cam", json={"enabled": True})
    assert res.status_code == 200 and res.get_json()["receiving"] is True
    cfg = env.calls["start"][0]
    assert cfg["folder"] == str(env.uploads)
    assert cfg["mode"] == "mode2"
    assert cfg["delete_original"] is False


def test_enabling_twice_does_not_start_a_second_watch(env):
    env.client.post("/api/security-cam", json={"enabled": True})
    env.client.post("/api/security-cam", json={"enabled": True})
    assert len(env.calls["start"]) == 1


def test_disable_stops_the_watch(env):
    env.client.post("/api/security-cam", json={"enabled": True})
    res = env.client.post("/api/security-cam", json={"enabled": False})
    assert env.calls["stop"] == 1 and res.get_json()["receiving"] is False


def test_disable_leaves_a_watch_on_another_folder_alone(env):
    env.state.update(running=True, folder=str(env.tmp / "elsewhere"))
    env.client.post("/api/security-cam", json={"enabled": False})
    assert env.calls["stop"] == 0


def test_enable_reports_when_auto_compress_is_busy(env, monkeypatch):
    monkeypatch.setattr(sc.ac, "start_autocompress", lambda cfg: False)
    res = env.client.post("/api/security-cam", json={"enabled": True})
    assert res.status_code == 409
    assert "another folder" in res.get_json()["error"]


def test_a_device_token_cannot_change_security_cam(env, monkeypatch):
    monkeypatch.setattr(sc, "current_auth_scheme", lambda: sc.SCHEME_BEARER)
    res = env.client.post("/api/security-cam", json={"enabled": True})
    assert res.status_code == 403
    assert env.calls["start"] == []


def test_a_device_token_can_read_the_settings(env, monkeypatch):
    monkeypatch.setattr(sc, "current_auth_scheme", lambda: sc.SCHEME_BEARER)
    assert env.client.get("/api/security-cam").status_code == 200


def _index_entry(folder, name, source_size, output_path, when, output_bytes=None):
    src = folder / name
    entry = {"source": str(src), "signature": f"{src}|{source_size}|1700000000",
             "output": str(output_path), "when": when}
    if output_bytes:
        entry["output_bytes"] = output_bytes
    return entry


def test_recent_clips_use_real_sizes_newest_first(env, monkeypatch):
    out_a = env.tmp / "a_out.mp4"; out_a.write_bytes(b"x" * 400)
    out_b = env.tmp / "b_out.mp4"; out_b.write_bytes(b"x" * 250)
    entries = {
        "a": _index_entry(env.uploads, "a.mp4", 1000, out_a, when=100.0),
        "b": _index_entry(env.uploads, "b.mp4", 1000, out_b, when=200.0),
    }
    monkeypatch.setattr(sc._cidx, "_load", lambda *a, **k: {"entries": entries})
    clips = env.client.get("/api/security-cam").get_json()["recent"]
    assert [c["name"] for c in clips] == ["b.mp4", "a.mp4"]
    assert clips[0]["saved_pct"] == 75 and clips[1]["saved_pct"] == 60
    assert clips[0]["headline"] == "Saved 75%"


def test_recent_clips_ignore_files_from_other_folders(env, monkeypatch):
    out = env.tmp / "o.mp4"; out.write_bytes(b"x" * 10)
    other = env.tmp / "someone_else"
    other.mkdir()
    entries = {"x": _index_entry(other, "x.mp4", 1000, out, when=1.0)}
    monkeypatch.setattr(sc._cidx, "_load", lambda *a, **k: {"entries": entries})
    assert env.client.get("/api/security-cam").get_json()["recent"] == []


def test_recent_clips_skip_a_missing_output(env, monkeypatch):
    entries = {"g": _index_entry(env.uploads, "g.mp4", 1000, env.tmp / "gone.mp4", when=1.0)}
    monkeypatch.setattr(sc._cidx, "_load", lambda *a, **k: {"entries": entries})
    assert env.client.get("/api/security-cam").get_json()["recent"] == []


def test_recent_clips_are_capped(env, monkeypatch):
    outs = {}
    for i in range(15):
        p = env.tmp / f"o{i}.mp4"; p.write_bytes(b"x" * 100)
        outs[str(i)] = _index_entry(env.uploads, f"c{i}.mp4", 1000, p, when=float(i))
    monkeypatch.setattr(sc._cidx, "_load", lambda *a, **k: {"entries": outs})
    clips = env.client.get("/api/security-cam").get_json()["recent"]
    assert len(clips) == sc.RECENT_LIMIT and clips[0]["name"] == "c14.mp4"


def test_unusable_phone_tokens_are_not_listed(monkeypatch):
    live = SimpleNamespace(is_usable=lambda: True,
                           to_public=lambda: {"id": "a1", "label": "Pixel 8",
                                              "last_used_at": "2026-11-23 10:00:00"})
    dead = SimpleNamespace(is_usable=lambda: False, to_public=lambda: {"id": "b2"})
    monkeypatch.setattr(sc.device_tokens, "list_tokens", lambda: [live, dead])
    assert sc._phones() == [{"id": "a1", "label": "Pixel 8", "last_seen": "2026-11-23 10:00:00"}]
