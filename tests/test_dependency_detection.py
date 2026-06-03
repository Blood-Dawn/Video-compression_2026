"""
tests/test_dependency_detection.py

Tests robust MediaMTX/dependency detection (FIX 5).

The RTSP manager used to look for mediamtx only under the dev repo tools/ dir,
so a frozen install showed "NOT INSTALLED". resolved_binary now checks the
writable tools dir, extra search dirs (legacy/bundle), the frozen bundle next to
the exe, and PATH. Also covers paths.tools_dir() and the dependency-status route.

Author: Bloodawn (KheivenD), 2026-06-03 (FIX 5).
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import utils.rtsp_server as rs  # noqa: E402
from utils.rtsp_server import RtspServerManager  # noqa: E402
from utils import paths as paths_mod  # noqa: E402


def _exe(mgr):
    return mgr._exe_name


# ── resolution across locations ──────────────────────────────────────────────

def test_found_in_writable_tools_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(rs.shutil, "which", lambda n: None)
    mgr = RtspServerManager(tools_dir=tmp_path)
    exe = tmp_path / "mediamtx" / _exe(mgr)
    exe.parent.mkdir(parents=True)
    exe.write_text("x")
    assert mgr.resolved_binary() == exe
    assert mgr.binary_present()


def test_found_in_extra_search_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(rs.shutil, "which", lambda n: None)
    legacy = tmp_path / "legacy"
    mgr = RtspServerManager(tools_dir=tmp_path / "writable", extra_search_dirs=[legacy])
    exe = legacy / "mediamtx" / _exe(mgr)
    exe.parent.mkdir(parents=True)
    exe.write_text("x")
    assert mgr.resolved_binary() == exe


def test_found_on_path(tmp_path, monkeypatch):
    mgr = RtspServerManager(tools_dir=tmp_path / "none")
    fake = tmp_path / _exe(mgr)
    fake.write_text("x")
    monkeypatch.setattr(rs.shutil, "which",
                        lambda n: str(fake) if n == "mediamtx" else None)
    assert mgr.resolved_binary() == fake


def test_found_in_frozen_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(rs.shutil, "which", lambda n: None)
    bundle = tmp_path / "bundle"
    mgr = RtspServerManager(tools_dir=tmp_path / "none")
    exe = bundle / "tools" / "mediamtx" / _exe(mgr)
    exe.parent.mkdir(parents=True)
    exe.write_text("x")
    monkeypatch.setattr(rs.sys, "frozen", True, raising=False)
    monkeypatch.setattr(rs.sys, "executable", str(bundle / "SVCS.exe"))
    assert mgr.resolved_binary() == exe


def test_absent_everywhere(tmp_path, monkeypatch):
    monkeypatch.setattr(rs.shutil, "which", lambda n: None)
    monkeypatch.setattr(rs.sys, "frozen", False, raising=False)
    mgr = RtspServerManager(tools_dir=tmp_path / "none")
    assert mgr.resolved_binary() is None
    assert not mgr.binary_present()


def test_download_target_is_writable_tools_dir(tmp_path):
    mgr = RtspServerManager(tools_dir=tmp_path)
    # The download destination stays in the writable tools dir regardless.
    assert mgr.binary_path == tmp_path / "mediamtx" / _exe(mgr)


# ── paths.tools_dir ──────────────────────────────────────────────────────────

def test_tools_dir_under_data(tmp_path, monkeypatch):
    monkeypatch.setattr(paths_mod, "data_dir", lambda: tmp_path)
    td = paths_mod.tools_dir()
    assert td == tmp_path / "tools"
    assert td.is_dir()


# ── dependency-status route ──────────────────────────────────────────────────

@pytest.fixture()
def client():
    from gui.app import app
    return app.test_client()


def test_dependencies_route_shape(client):
    body = client.get("/api/setup/dependencies").get_json()
    deps = body["dependencies"]
    assert set(deps) == {"ffmpeg", "ffprobe", "mediamtx", "onnx_model"}
    for v in deps.values():
        assert set(v) == {"present", "path"}
        assert isinstance(v["present"], bool)
