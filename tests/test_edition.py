"""
tests/test_edition.py

R4 Phase 4: the server/field build split.

  * gui.edition resolution (env > bundled marker > default "server");
  * register_blueprints drops the server-making blueprints (RTSP + HLS) in the
    field edition and keeps everything local (compression, retention, library);
  * the default module app is unchanged (server, all 73 routes);
  * the index template gates the TOOLS tab + injects the edition;
  * run_gui forces localhost + the usage-stats kill-switch in the field build.

Author: Bloodawn (KheivenD), 2026-07-04 (R4 Phase 4 - server/field split).
"""

import sys
from pathlib import Path

import pytest
from flask import Flask

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui import edition                     # noqa: E402
import gui.app as app_mod                   # noqa: E402


# ── edition resolution ────────────────────────────────────────────────────────

def test_default_is_server(monkeypatch):
    monkeypatch.delenv("SVCS_EDITION", raising=False)
    monkeypatch.delenv("SVCS_BUNDLE_ROOT", raising=False)
    assert edition.get_edition() == "server"
    assert edition.is_server() and not edition.is_field()
    assert edition.server_features_enabled() is True


def test_env_selects_field(monkeypatch):
    monkeypatch.setenv("SVCS_EDITION", "field")
    assert edition.get_edition() == "field"
    assert edition.is_field() and not edition.is_server()
    assert edition.server_features_enabled() is False


def test_env_garbage_falls_back_to_server(monkeypatch):
    monkeypatch.setenv("SVCS_EDITION", "banana")
    assert edition.get_edition() == "server"


def test_bundled_marker_selects_field(monkeypatch, tmp_path):
    monkeypatch.delenv("SVCS_EDITION", raising=False)
    (tmp_path / "edition.txt").write_text("field", encoding="utf-8")
    monkeypatch.setenv("SVCS_BUNDLE_ROOT", str(tmp_path))
    assert edition.get_edition() == "field"


def test_env_overrides_marker(monkeypatch, tmp_path):
    (tmp_path / "edition.txt").write_text("field", encoding="utf-8")
    monkeypatch.setenv("SVCS_BUNDLE_ROOT", str(tmp_path))
    monkeypatch.setenv("SVCS_EDITION", "server")
    assert edition.get_edition() == "server"


# ── blueprint registration ────────────────────────────────────────────────────

def _routes(flask_app):
    return {r.rule for r in flask_app.url_map.iter_rules() if r.endpoint != "static"}


_TEMPLATES = SRC / "gui" / "templates"
_STATIC = SRC / "gui" / "static"


def _make_app(edition_name):
    """A Flask app wired to the real templates/static, with the edition's
    blueprints registered - so the index template actually renders."""
    fa = Flask(__name__, template_folder=str(_TEMPLATES), static_folder=str(_STATIC))
    app_mod.register_blueprints(fa, edition=edition_name)
    return fa


def test_field_app_drops_server_blueprints():
    field = Flask(__name__)
    app_mod.register_blueprints(field, edition="field")
    rules = _routes(field)
    # Server-making surfaces gone.
    assert not any(r.startswith("/api/rtsp") for r in rules)
    assert not any(r.startswith("/api/hls") for r in rules)
    # Local compression, retention, library, encrypt, upload all kept.
    assert "/api/start" in rules
    assert "/api/retention" in rules
    assert "/api/library/videos" in rules
    assert "/api/encrypt" in rules
    assert "/api/upload" in rules
    assert "/api/autocompress/start" in rules   # watches LOCAL folders - kept


def test_server_app_keeps_everything():
    server = Flask(__name__)
    app_mod.register_blueprints(server, edition="server")
    rules = _routes(server)
    assert any(r.startswith("/api/rtsp") for r in rules)
    assert any(r.startswith("/api/hls") for r in rules)


def test_field_has_fewer_routes_than_server():
    server, field = Flask(__name__), Flask(__name__)
    app_mod.register_blueprints(server, edition="server")
    app_mod.register_blueprints(field, edition="field")
    assert len(_routes(field)) < len(_routes(server))


def test_module_app_is_server_by_default():
    # The import-time app (used by the whole test suite) is the full server
    # build: the 73-route guard elsewhere depends on this.
    rules = _routes(app_mod.app)
    assert any(r.startswith("/api/rtsp") for r in rules)
    assert any(r.startswith("/api/hls") for r in rules)


# ── template gating ───────────────────────────────────────────────────────────

def test_index_template_gates_tools_tab(monkeypatch):
    monkeypatch.setenv("SVCS_EDITION", "field")
    html = _make_app("field").test_client().get("/").get_data(as_text=True)
    assert 'window.SVCS_SERVER_FEATURES = false' in html
    assert "OFFLINE BUILD" in html
    # The TOOLS tab button is hidden; the ENCRYPT button remains.
    assert "switchTab('tools')" not in html
    assert "switchTab('encrypt')" in html


def test_index_template_server_shows_tools(monkeypatch):
    monkeypatch.delenv("SVCS_EDITION", raising=False)
    html = _make_app("server").test_client().get("/").get_data(as_text=True)
    assert 'window.SVCS_SERVER_FEATURES = true' in html
    assert "switchTab('tools')" in html
    assert "OFFLINE BUILD" not in html


# ── run_gui field enforcement ─────────────────────────────────────────────────

def test_field_forces_localhost_and_optout(monkeypatch):
    """The field build must override a LAN --host to 127.0.0.1 and set the
    usage-stats kill-switch, before ever calling app.run()."""
    monkeypatch.setenv("SVCS_EDITION", "field")
    monkeypatch.delenv("SVCS_DISABLE_USAGE_STATS", raising=False)
    monkeypatch.setattr(sys, "argv",
                        ["run_gui.py", "--host", "0.0.0.0", "--no-browser", "--no-sync"])

    import run_gui
    captured = {}

    class _FakeApp:
        def run(self, host=None, port=None, **kw):
            captured["host"] = host
    monkeypatch.setattr(run_gui, "_ensure_extras_installed", lambda *a, **k: None)

    def _fake_create_app():
        return _FakeApp()
    # gui.app.create_app is imported inside main(); patch it there.
    import gui.app
    monkeypatch.setattr(gui.app, "create_app", _fake_create_app)

    run_gui.main()
    assert captured["host"] == "127.0.0.1"
    import os
    assert os.environ.get("SVCS_DISABLE_USAGE_STATS") == "1"
