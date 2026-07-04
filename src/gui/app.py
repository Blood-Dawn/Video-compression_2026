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

# ── path setup ────────────────────────────────────────────────────────────────
# Allow imports from src/ regardless of working directory. The pipeline / DB /
# encryption imports that used to live here moved out with the routes - each
# blueprint and service now imports exactly what it needs (TASK 1.2/1.3).
_SRC = Path(__file__).resolve().parent.parent
_ROOT = _SRC.parent
sys.path.insert(0, str(_SRC))

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates")

# All state files now live in the platform-standard app data directory
# instead of the repo root, so the installer works on Windows / macOS /
# Linux where Program Files / /Applications are read-only.
# Author: Bloodawn (KheivenD), 2026-05-14 (installer prep).
try:
    from utils import paths as _paths
except ModuleNotFoundError:
    from src.utils import paths as _paths

# Persist SECRET_KEY so signed cookies/sessions survive restarts.
# File is created with mode 0600 on first run.
_SK_FILE = _paths.state_file("flask_secret")
try:
    app.config["SECRET_KEY"] = _SK_FILE.read_bytes()
except FileNotFoundError:
    _sk = os.urandom(32)
    _SK_FILE.write_bytes(_sk)
    try:
        _SK_FILE.chmod(0o600)
    except Exception:
        pass
    app.config["SECRET_KEY"] = _sk

# ── Extracted state + logging (M1 refactor, TASK 1.1) ────────────────────────
# Pure-data globals now live in gui.state; logging handlers + atexit in
# gui.logging_setup. They are imported (and thereby re-exported) here so that
# existing in-module references AND the gui.app.* test contract keep working
# without churn. Importing gui.logging_setup also wires the root logger and
# registers the atexit shutdown marker (side effect, as before).
# Import direction is one-way: state <- logging_setup <- app.
# Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - state/logging split).
try:
    from gui import state as _state
    from gui.state import (
        _state_lock, _status,
        _power_lock, _power_state,
        _demo_lock, _demo_state,
        _hls_lock, _hls_state, _hls_frame_ts_dq, _hls_segment_latencies,
        _log_queue, _log_history, _log_lock,
        _VALID_MODES, _VALID_BG, _VALID_DEVICES, _VALID_MODELS,
        _CLOUD_SUBFOLDER, _SAFE_FILENAME_RE, _ALLOWED_EXTENSIONS,
    )
    from gui.logging_setup import log, _LOG_FILE
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui import state as _state
    from src.gui.state import (
        _state_lock, _status,
        _power_lock, _power_state,
        _demo_lock, _demo_state,
        _hls_lock, _hls_state, _hls_frame_ts_dq, _hls_segment_latencies,
        _log_queue, _log_history, _log_lock,
        _VALID_MODES, _VALID_BG, _VALID_DEVICES, _VALID_MODELS,
        _CLOUD_SUBFOLDER, _SAFE_FILENAME_RE, _ALLOWED_EXTENSIONS,
    )
    from src.gui.logging_setup import log, _LOG_FILE

# ── Pipeline thread runner ────────────────────────────────────────────────────
# _patch_frame_source / _patch_encoder / _run_pipeline_thread and the rebindable
# _pipeline_thread / _stop_event / _active_encoder handles now live in
# gui.services.pipeline_runner. The handles are forwarded from this module (see
# _FORWARDED_GLOBALS) so /api/start and /api/stop and the tests share one live
# value. _run_pipeline_thread is re-exported into this module's namespace (NOT
# forwarded) so tests can monkeypatch gui_module._run_pipeline_thread and the
# /api/start route's bare-name call picks up the fake.
try:
    from gui.services import pipeline_runner as _pipeline_runner
    from gui.services.pipeline_runner import _run_pipeline_thread
    # hls_runner module is needed only for the _FORWARDED_GLOBALS map below
    # (the HLS handles); the HLS routes themselves live in gui.routes.hls_bp.
    from gui.services import hls_runner as _hls_runner
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services import pipeline_runner as _pipeline_runner
    from src.gui.services.pipeline_runner import _run_pipeline_thread
    from src.gui.services import hls_runner as _hls_runner

# ── Security helpers ──────────────────────────────────────────────────────────
# _safe_output_dir / _assert_within_output / _safe_filename now live in
# gui.services.path_safety (imported below). `import re as _re` stays - the
# route handlers still use it for camera_id / stream_name validation.
import re as _re

try:
    from gui.services.path_safety import (
        _safe_output_dir, _assert_within_output, _safe_filename,
    )
    from gui.services.cloud_detection import (
        _default_output_dir,
        _detect_onedrive_root, _detect_gdrive_root, _detect_cloud_root,
    )
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services.path_safety import (
        _safe_output_dir, _assert_within_output, _safe_filename,
    )
    from src.gui.services.cloud_detection import (
        _default_output_dir,
        _detect_onedrive_root, _detect_gdrive_root, _detect_cloud_root,
    )


# ── Power / hardware metrics ───────────────────────────────────────────────────
# The CPU/RAM/battery samplers (per-pipeline + always-on) now live in
# gui.services.cpu_sampler. The always-on sampler is no longer started at import
# time - create_app() calls start_hw_sampler() instead. _PSUTIL_OK is re-imported
# here because the /api/system_metrics route still consults it.
try:
    from gui.services.cpu_sampler import (
        _PSUTIL_OK, _start_cpu_sampler, _stop_cpu_sampler, start_hw_sampler,
    )
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services.cpu_sampler import (
        _PSUTIL_OK, _start_cpu_sampler, _stop_cpu_sampler, start_hw_sampler,
    )


# ── GUI state persistence ─────────────────────────────────────────────
# _GUI_STATE_FILE / _load_gui_state / _save_gui_state now live in
# gui.services.gui_state_persist (imported below). _load_gui_state() is still
# invoked once at module import (further down) to seed the last-known roots.
try:
    from gui.services.gui_state_persist import (
        _GUI_STATE_FILE, _load_gui_state, _save_gui_state,
    )
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services.gui_state_persist import (
        _GUI_STATE_FILE, _load_gui_state, _save_gui_state,
    )







# ── Log capture + handlers ────────────────────────────────────────────────────
# Moved to gui.logging_setup (TASK 1.1): the SSE queue handler, file/console
# handlers, root-logger wiring, _write_shutdown_log, and the atexit
# registration now live there. `log`, `_LOG_FILE`, and the live-log ring
# buffers (_log_queue / _log_history / _log_lock) are imported at the top of
# this module. The file handler and the shutdown marker stay co-located in
# logging_setup so the atexit ordering keeps landing the marker in svcs.log.

# _patch_frame_source / _patch_encoder / _run_pipeline_thread now live in
# gui.services.pipeline_runner (imported above).


# ── Blueprint registration ────────────────────────────────────────────────────
# The 48 routes now live in 12 blueprints under gui.routes. They are registered
# at import time so `from gui.app import app` (used by run_gui.py and the test
# suite) has every route without calling create_app().
def register_blueprints(flask_app: Flask, edition: str | None = None) -> None:
    """Register the route blueprints on the given Flask app.

    R4 Phase 4: the "field" (offline, local-compression-only) edition drops the
    server-making blueprints - the RTSP server (MediaMTX) and HLS live streaming
    - so a field build has no server surface at all. The default (``edition``
    None -> resolves to "server") registers all 17, so source runs and the
    existing route/blueprint guards are unchanged.
    """
    try:
        from gui.edition import is_field as _is_field
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.gui.edition import is_field as _is_field
    field = _is_field(edition)
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
    all_bps = [ui_bp, sse_bp, metrics_bp, presets_bp, encryption_bp, plates_bp,
               queries_bp, rtsp_bp, demo_bp, hls_bp, files_bp, pipeline_bp,
               cameras_bp, usage_bp, setup_bp, library_bp, autocompress_bp]
    if field:
        # Field build: no server-making surfaces (RTSP server + HLS streaming).
        server_only = {rtsp_bp, hls_bp}
        all_bps = [bp for bp in all_bps if bp not in server_only]
    for bp in all_bps:
        flask_app.register_blueprint(bp)


register_blueprints(app)

# ── CSRF guard (SEC-001) ──────────────────────────────────────────────────────
# Same-origin check on all state-changing requests. Installed on the module app
# (not just create_app) so the test client and every entry point are protected.
# Safe to always enable: non-browser clients (no Origin/Referer) are allowed.
try:
    from gui.csrf import install_csrf_protection
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.csrf import install_csrf_protection
install_csrf_protection(app)


# ── Rebound-global forwarding (REFACTOR-PLAN §5) ─────────────────────────────
# Most state names are mutable containers re-exported from gui.state as the
# SAME object, so `gui.app.<name>` and `gui.state.<name>` are identical and
# in-place mutation round-trips for free. A few names are *rebound* (reassigned,
# not mutated in place) inside the owning submodule - e.g. the SSE log handler
# does `state._log_id += 1`. A plain re-import would bind a stale copy here, and
# the gui.app.* test contract reaches into these names for both reads AND
# writes. We swap this module's class so those specific names are forwarded to
# their owning module in both directions. The map below covers every rebound
# name now owned by an extracted submodule (gui.state / hls_runner /
# pipeline_runner); add to it whenever a future move relocates a rebound global.
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


# ── Entry point ───────────────────────────────────────────────────────────────

def _resolve_serve_auth(flask_app: Flask, host: str, env=None):
    """Apply the dashboard auth policy for a direct run of this module (SEC-010).

    `python src/gui/app.py` / `python -m gui.app` used to call
    ``run(host="0.0.0.0")`` with NO authentication (only run_gui.py installed it),
    exposing the dashboard unauthenticated on the LAN. This mirrors run_gui's
    policy: decide auth from the bind + env credentials, install Basic-Auth when
    credentials are present, and let ``AuthConfigError`` propagate when a
    non-localhost bind has no credentials so the caller refuses to start.
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
    # Start the always-on hardware sampler here rather than at import time so
    # that merely importing gui.app stays side-effect-free (TASK 1.2). All real
    # entry points (run_gui.py, the PyInstaller launcher, and __main__ below)
    # go through create_app(), so the dashboard's CPU/RAM strip is live.
    start_hw_sampler()

    # FIX 1: do NOT pre-create any cloud (OneDrive/Drive/iCloud) folder on
    # startup. A cloud destination is only ever created when the user explicitly
    # chooses one in the Setup page (/api/setup/choose creates the folders).
    return app


def _field_safe_host(host: str) -> str:
    """Force loopback in the field (offline) build; pass ``host`` through in the
    server build.

    The field build's guarantee - "local-only, never binds the network" - has to
    hold on EVERY entry point (run_gui AND `python -m gui.app`), independent of
    SVCS_DASHBOARD_HOST or whether credentials are set. R4 Phase 4 review fix.
    """
    try:
        from gui.edition import is_field as _is_field
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.gui.edition import is_field as _is_field
    if _is_field() and host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("Field (offline) build: overriding host %s -> 127.0.0.1 "
                    "(local-only build never binds the network).", host)
        return "127.0.0.1"
    return host


if __name__ == "__main__":
    import os as _os
    import sys as _sys

    log.info("=" * 60)
    log.info("SVCS SERVER STARTUP: %s", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
    log.info("Project root:  %s", _ROOT)
    log.info("Log file:      %s", _LOG_FILE)
    log.info("=" * 60)

    _host = _os.environ.get("SVCS_DASHBOARD_HOST", "0.0.0.0")
    _port = int(_os.environ.get("SVCS_DASHBOARD_PORT", "5000"))

    # R4 Phase 4 (review fix): the field (offline) build must NEVER bind the
    # network, on ANY entry point (this is a second, documented entry besides
    # run_gui). Force loopback here too, before the bind.
    _host = _field_safe_host(_host)

    _app = create_app()

    # SEC-010: refuse to expose the dashboard unauthenticated on the network.
    # A non-localhost bind without SVCS_DASHBOARD_USER/PASSWORD raises here, the
    # same policy run_gui.py enforces, instead of silently binding 0.0.0.0 open.
    try:
        from gui.auth import AuthConfigError
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.gui.auth import AuthConfigError
    try:
        _decision = _resolve_serve_auth(_app, _host)
    except AuthConfigError as exc:
        print(f"\n  [fatal] {exc}")
        _sys.exit(2)
    if _decision.auth_enabled:
        log.info("Dashboard auth: ENABLED (user %r)", _decision.username)
    log.info("Dashboard:     http://%s:%d", _host, _port)
    _app.run(host=_host, port=_port, debug=False, threaded=True)
