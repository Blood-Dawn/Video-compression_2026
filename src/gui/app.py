"""
src/gui/app.py

Flask web dashboard for the surveillance video compression pipeline.

Serves a browser-based UI at http://localhost:5000 that lets you:
  - Configure and start / stop the pipeline with all settings
  - Watch a live terminal log stream (Server-Sent Events)
  - Monitor real-time stats: frame count, segment count, FPS, storage
  - Browse recent output segments from the SQLite metadata DB

The pipeline runs in a daemon background thread so the Flask server stays
responsive. A threading.Event is used to signal a clean stop.

Usage:
    python run_gui.py                # from project root
    python src/gui/app.py            # from project root

Author: Bloodawn (KheivenD)
"""

import os
import sys
from datetime import datetime
from pathlib import Path

from flask import Flask

# Allow imports from src/ regardless of working directory.
_SRC = Path(__file__).resolve().parent.parent
_ROOT = _SRC.parent
sys.path.insert(0, str(_SRC))

app = Flask(__name__, template_folder="templates")

# State files live in the platform app data directory, not the repo root:
# an installed copy sits under Program Files / /Applications, which are
# read-only.
# Author: Bloodawn (KheivenD), 2026-05-14 (installer prep).
try:
    from utils import paths as _paths
except ModuleNotFoundError:
    from src.utils import paths as _paths

# Persist SECRET_KEY so signed cookies/sessions survive restarts.
_SK_FILE = _paths.state_file("flask_secret")
try:
    app.config["SECRET_KEY"] = _SK_FILE.read_bytes()
except FileNotFoundError:
    _sk = os.urandom(32)
    _SK_FILE.write_bytes(_sk)
    try:
        _SK_FILE.chmod(0o600)   # owner-only; a no-op on Windows
    except OSError:
        pass
    app.config["SECRET_KEY"] = _sk

# State globals live in gui.state and logging in gui.logging_setup. They are
# re-exported here because the gui.app.* test contract reaches into them.
# Importing gui.logging_setup wires the root logger and registers the atexit
# shutdown marker. Import direction is one-way: state <- logging_setup <- app.
# Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - state/logging split).
try:
    from gui import state as _state
    from gui.state import (  # noqa: F401 (re-export, see note above)
        _state_lock, _status,
        _power_lock, _power_state,
        _demo_lock, _demo_state,
        _hls_lock, _hls_state, _hls_frame_ts_dq, _hls_segment_latencies,
        _log_queue, _log_history, _log_lock,
        _VALID_MODES, _VALID_BG, _VALID_DEVICES, _VALID_MODELS,
        _CLOUD_SUBFOLDER, _SAFE_FILENAME_RE, _ALLOWED_EXTENSIONS,
    )
    from gui.logging_setup import log, _LOG_FILE  # noqa: F401 (re-export)
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui import state as _state
    from src.gui.state import (  # noqa: F401 (re-export, see note above)
        _state_lock, _status,
        _power_lock, _power_state,
        _demo_lock, _demo_state,
        _hls_lock, _hls_state, _hls_frame_ts_dq, _hls_segment_latencies,
        _log_queue, _log_history, _log_lock,
        _VALID_MODES, _VALID_BG, _VALID_DEVICES, _VALID_MODELS,
        _CLOUD_SUBFOLDER, _SAFE_FILENAME_RE, _ALLOWED_EXTENSIONS,
    )
    from src.gui.logging_setup import log, _LOG_FILE  # noqa: F401 (re-export)

# The pipeline thread handles (_pipeline_thread, _stop_event, _active_encoder)
# are owned by gui.services.pipeline_runner and forwarded from this module (see
# _FORWARDED_GLOBALS) so /api/start, /api/stop and the tests share one live
# value. _run_pipeline_thread is re-exported (NOT forwarded) so tests can
# monkeypatch gui_module._run_pipeline_thread and /api/start picks up the fake.
try:
    from gui.services import pipeline_runner as _pipeline_runner
    from gui.services.pipeline_runner import _run_pipeline_thread  # noqa: F401 (re-export)
    # hls_runner module is needed only for the _FORWARDED_GLOBALS map below
    # (the HLS handles); the HLS routes themselves live in gui.routes.hls_bp.
    from gui.services import hls_runner as _hls_runner
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services import pipeline_runner as _pipeline_runner
    from src.gui.services.pipeline_runner import _run_pipeline_thread  # noqa: F401 (re-export)
    from src.gui.services import hls_runner as _hls_runner

try:
    from gui.services.path_safety import (  # noqa: F401 (re-export, see note above)
        _safe_output_dir, _assert_within_output, _safe_filename,
    )
    from gui.services.cloud_detection import (  # noqa: F401 (re-export, see note above)
        _default_output_dir,
        _detect_onedrive_root, _detect_gdrive_root, _detect_cloud_root,
    )
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services.path_safety import (  # noqa: F401 (re-export, see note above)
        _safe_output_dir, _assert_within_output, _safe_filename,
    )
    from src.gui.services.cloud_detection import (  # noqa: F401 (re-export, see note above)
        _default_output_dir,
        _detect_onedrive_root, _detect_gdrive_root, _detect_cloud_root,
    )


# The always-on hardware sampler is started by create_app(), not at import.
try:
    from gui.services.cpu_sampler import (  # noqa: F401 (re-export, see note above)
        _PSUTIL_OK, _start_cpu_sampler, _stop_cpu_sampler, start_hw_sampler,
    )
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services.cpu_sampler import (  # noqa: F401 (re-export, see note above)
        _PSUTIL_OK, _start_cpu_sampler, _stop_cpu_sampler, start_hw_sampler,
    )


try:
    from gui.services.gui_state_persist import (  # noqa: F401 (re-export, see note above)
        _GUI_STATE_FILE, _load_gui_state, _save_gui_state,
    )
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services.gui_state_persist import (  # noqa: F401 (re-export, see note above)
        _GUI_STATE_FILE, _load_gui_state, _save_gui_state,
    )


# Blueprints are registered at import time so `from gui.app import app` (used
# by run_gui.py and the test suite) has every route without create_app().
def register_blueprints(flask_app: Flask, edition: str | None = None) -> None:
    """Register the route blueprints on the given Flask app.

    The "field" (offline, local-compression-only) edition drops the RTSP
    (MediaMTX) and HLS blueprints so it has no server surface. The default
    (``edition`` None resolves to "server") registers every blueprint.
    """
    try:
        from gui.edition import EDITION_FIELD, EDITION_SERVER, is_field
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.gui.edition import EDITION_FIELD, EDITION_SERVER, is_field
    field = is_field(edition)
    # Record the edition actually registered so /api/capabilities matches the
    # real surface; re-deriving it from the environment diverges when a caller
    # passes an explicit edition.
    flask_app.config["SVCS_RESOLVED_EDITION"] = (
        EDITION_FIELD if field else EDITION_SERVER)
    try:
        from gui.routes.ui_bp import ui_bp
        from gui.routes.sse_bp import sse_bp
        from gui.routes.metrics_bp import metrics_bp
        from gui.routes.presets_bp import presets_bp
        from gui.routes.encryption_bp import encryption_bp
        from gui.routes.plates_bp import plates_bp
        from gui.routes.queries_bp import queries_bp
        from gui.routes.rtsp_bp import rtsp_bp
        from gui.routes.demo_bp import demo_bp
        from gui.routes.hls_bp import hls_bp
        from gui.routes.files_bp import files_bp
        from gui.routes.pipeline_bp import pipeline_bp
        from gui.routes.cameras_bp import cameras_bp
        from gui.routes.usage_bp import usage_bp
        from gui.routes.setup_bp import setup_bp
        from gui.routes.library_bp import library_bp
        from gui.routes.autocompress_bp import autocompress_bp
        from gui.routes.tokens_bp import tokens_bp
        from gui.routes.capabilities_bp import capabilities_bp
        from gui.routes.savings_bp import savings_bp
        from gui.routes.events_bp import events_bp
        from gui.routes.ingest_bp import ingest_bp
        from gui.routes.push_bp import push_bp
        from gui.routes.webhook_bp import webhook_bp
        from gui.routes.update_bp import update_bp
        from gui.routes.timelapse_bp import timelapse_bp
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.gui.routes.ui_bp import ui_bp
        from src.gui.routes.sse_bp import sse_bp
        from src.gui.routes.metrics_bp import metrics_bp
        from src.gui.routes.presets_bp import presets_bp
        from src.gui.routes.encryption_bp import encryption_bp
        from src.gui.routes.plates_bp import plates_bp
        from src.gui.routes.queries_bp import queries_bp
        from src.gui.routes.rtsp_bp import rtsp_bp
        from src.gui.routes.demo_bp import demo_bp
        from src.gui.routes.hls_bp import hls_bp
        from src.gui.routes.files_bp import files_bp
        from src.gui.routes.pipeline_bp import pipeline_bp
        from src.gui.routes.cameras_bp import cameras_bp
        from src.gui.routes.usage_bp import usage_bp
        from src.gui.routes.setup_bp import setup_bp
        from src.gui.routes.library_bp import library_bp
        from src.gui.routes.autocompress_bp import autocompress_bp
        from src.gui.routes.tokens_bp import tokens_bp
        from src.gui.routes.capabilities_bp import capabilities_bp
        from src.gui.routes.savings_bp import savings_bp
        from src.gui.routes.events_bp import events_bp
        from src.gui.routes.ingest_bp import ingest_bp
        from src.gui.routes.push_bp import push_bp
        from src.gui.routes.webhook_bp import webhook_bp
        from src.gui.routes.update_bp import update_bp
        from src.gui.routes.timelapse_bp import timelapse_bp
    all_bps = [ui_bp, sse_bp, metrics_bp, presets_bp, encryption_bp, plates_bp,
               queries_bp, rtsp_bp, demo_bp, hls_bp, files_bp, pipeline_bp,
               cameras_bp, usage_bp, setup_bp, library_bp, autocompress_bp,
               tokens_bp, capabilities_bp, savings_bp, events_bp, ingest_bp,
               push_bp, webhook_bp, update_bp, timelapse_bp]
    if field:
        server_only = {rtsp_bp, hls_bp}
        all_bps = [bp for bp in all_bps if bp not in server_only]
    for bp in all_bps:
        flask_app.register_blueprint(bp)


register_blueprints(app)

# CSRF guard (SEC-001): same-origin check on state-changing requests, installed
# on the module app so the test client and every entry point are protected.
# Non-browser clients (no Origin/Referer) are allowed.
try:
    from gui.csrf import install_csrf_protection
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.csrf import install_csrf_protection
install_csrf_protection(app)

# Browser hardening headers (PT-02): anti-framing closes the clickjacking path
# the Origin-based CSRF guard cannot see.
try:
    from gui.security_headers import install_security_headers
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.security_headers import install_security_headers
install_security_headers(app)


# Rebound-global forwarding. Most state names are mutable containers
# re-exported as the SAME object, so in-place mutation round-trips. A few are
# rebound inside their owning module (e.g. `state._log_id += 1`); a plain
# re-import would bind a stale copy, and the gui.app.* test contract reads and
# writes them. So this module's class forwards those names to their owner.
# Add to the map whenever a rebound global moves to another module.
# Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - rebound forwarding).
import types as _types

# name -> owning module object. Forwarded names must NOT be bound in this
# module's __dict__, or normal attribute lookup would shadow __getattr__.
_FORWARDED_GLOBALS: dict = {
    "_log_id": _state,                       # gui.state; rebound by the SSE log handler
    "_hls_process": _hls_runner,             # gui.services.hls_runner; rebound by start/stop + annotator
    "_hls_thread": _hls_runner,
    "_hls_stop_event": _hls_runner,
    "_pipeline_thread": _pipeline_runner,    # gui.services.pipeline_runner; rebound by /api/start + tests
    "_stop_event": _pipeline_runner,
    "_active_encoder": _pipeline_runner,
}


class _ForwardingModule(_types.ModuleType):
    """gui.app module class: forwards rebound globals to their owning module."""

    def __getattr__(self, name):          # called only when normal lookup misses
        owner = _FORWARDED_GLOBALS.get(name)
        if owner is not None:
            return getattr(owner, name)
        raise AttributeError(f"module {self.__name__!r} has no attribute {name!r}")

    def __setattr__(self, name, value):
        owner = _FORWARDED_GLOBALS.get(name)
        if owner is not None:
            setattr(owner, name, value)
        else:
            super().__setattr__(name, value)


sys.modules[__name__].__class__ = _ForwardingModule


def _resolve_serve_auth(flask_app: Flask, host: str, env=None):
    """Apply the dashboard auth policy for a direct run of this module (SEC-010).

    Without this, `python -m gui.app` would serve on 0.0.0.0 unauthenticated.
    Mirrors run_gui: install Basic-Auth when credentials are present and let
    ``AuthConfigError`` propagate for a non-localhost bind without them.
    """
    try:
        from gui.auth import decide_auth, install_basic_auth
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.gui.auth import decide_auth, install_basic_auth
    decision = decide_auth(host, env=env)
    if decision.auth_enabled:
        install_basic_auth(flask_app, decision.username, decision.password)
    return decision


def create_app() -> Flask:
    # The hardware sampler starts here, not at import, so importing gui.app
    # stays side-effect-free. Every real entry point goes through create_app().
    #
    # No cloud (OneDrive/Drive/iCloud) folder is created on startup: only
    # /api/setup/choose creates one, when the user picks it.
    start_hw_sampler()
    return app


def _field_safe_host(host: str) -> str:
    """Force loopback in the field (offline) build; pass ``host`` through otherwise.

    The field build never binds the network, on every entry point (run_gui and
    `python -m gui.app`), whatever SVCS_DASHBOARD_HOST or credentials say.
    """
    try:
        from gui.edition import is_field
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.gui.edition import is_field
    if is_field() and host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("Field (offline) build: overriding host %s -> 127.0.0.1 "
                    "(local-only build never binds the network).", host)
        return "127.0.0.1"
    return host


if __name__ == "__main__":
    log.info("=" * 60)
    log.info("SVCS SERVER STARTUP: %s", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
    log.info("Project root:  %s", _ROOT)
    log.info("Log file:      %s", _LOG_FILE)
    log.info("=" * 60)

    _host = os.environ.get("SVCS_DASHBOARD_HOST", "0.0.0.0")
    _port = int(os.environ.get("SVCS_DASHBOARD_PORT", "5000"))

    # The field (offline) build must never bind the network, on any entry point.
    _host = _field_safe_host(_host)

    _app = create_app()

    # SEC-010: a non-localhost bind without SVCS_DASHBOARD_USER/PASSWORD
    # raises here, the same policy run_gui.py enforces.
    try:
        from gui.auth import AuthConfigError
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.gui.auth import AuthConfigError
    try:
        _decision = _resolve_serve_auth(_app, _host)
    except AuthConfigError as exc:
        print(f"\n  [fatal] {exc}")
        sys.exit(2)
    if _decision.auth_enabled:
        log.info("Dashboard auth: ENABLED (user %r)", _decision.username)
    log.info("Dashboard:     http://%s:%d", _host, _port)
    _app.run(host=_host, port=_port, debug=False, threaded=True)
