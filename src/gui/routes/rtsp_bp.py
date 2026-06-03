"""
src/gui/routes/rtsp_bp.py

rtsp routes blueprint, carved from gui/app.py (TASK 1.3).
Pure relocation: every URL, method, and response shape is unchanged.
Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - blueprints).
"""

from pathlib import Path
import re as _re
from flask import Blueprint, jsonify, request

try:
    from gui.state import (_state_lock, _status)
    from gui.logging_setup import log
    from gui.services.rtsp import _rtsp_mgr
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.state import (_state_lock, _status)
    from src.gui.logging_setup import log
    from src.gui.services.rtsp import _rtsp_mgr

# Repo root (…/src/gui/routes/<bp>_bp.py -> parents[3]).
_ROOT = Path(__file__).resolve().parents[3]

rtsp_bp = Blueprint("rtsp", __name__)

@rtsp_bp.route("/api/rtsp/status")
def api_rtsp_status():
    """Return the current state of the local RTSP server manager."""
    return jsonify(_rtsp_mgr.get_state())


@rtsp_bp.route("/api/rtsp/download", methods=["POST"])
def api_rtsp_download():
    """Start downloading the MediaMTX binary in the background.

    Idempotent. Safe to call again if the binary is already present
    (returns ok without re-downloading).
    """
    if _rtsp_mgr.binary_present():
        return jsonify({"ok": True, "message": "binary already present"})

    try:
        _rtsp_mgr.start_download()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409

    log.info("MediaMTX download started.")
    return jsonify({"ok": True, "message": "download started"})


@rtsp_bp.route("/api/rtsp/start", methods=["POST"])
def api_rtsp_start():
    """Start the local MediaMTX RTSP server."""
    try:
        _rtsp_mgr.start()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409

    state = _rtsp_mgr.get_state()
    log.info("Local RTSP server started. Listening on rtsp://localhost:8554/")
    return jsonify({"ok": True, "rtsp_url": state["rtsp_url"]})


@rtsp_bp.route("/api/rtsp/stop", methods=["POST"])
def api_rtsp_stop():
    """Stop the local RTSP server (and any active push)."""
    _rtsp_mgr.stop()
    log.info("Local RTSP server stopped.")
    return jsonify({"ok": True})


@rtsp_bp.route("/api/rtsp/push", methods=["POST"])
def api_rtsp_push():
    """Start FFmpeg looping a local video file into the RTSP server.

    POST body (JSON):
        video_path   - absolute path to the video file
        stream_name  - RTSP path to publish to (default: "live")
    """
    data = request.get_json(force=True) or {}
    video_path  = str(data.get("video_path", "")).strip()
    stream_name = str(data.get("stream_name", "live")).strip() or "live"

    if not video_path:
        return jsonify({"error": "video_path is required"}), 400

    # Sanitize stream_name to alphanumeric + dash/underscore only.
    # Used directly in an RTSP URL - any shell metacharacter is a command injection risk.
    if not _re.match(r"^[a-zA-Z0-9_\-]{1,64}$", stream_name):
        return jsonify({"error": "stream_name must be 1-64 alphanumeric/dash/underscore chars"}), 400

    # Validate video_path is inside the output directory
    with _state_lock:
        cfg = _status.get("config", {})
    output_dir = Path(cfg.get("output_dir", str(_ROOT / "outputs"))).resolve()
    vp = Path(video_path).resolve()
    data_dir = (_ROOT / "data").resolve()
    allowed = [output_dir, data_dir, (_ROOT / "outputs").resolve()]
    if not any(vp == r or r in vp.parents for r in allowed):
        log.warning("api_rtsp_push: rejected video_path outside allowed roots: %s", vp)
        return jsonify({"error": "video_path must be inside the output or data directory"}), 403

    if not vp.exists():
        return jsonify({"error": f"File not found: {vp.name}"}), 400
    if not _rtsp_mgr.is_running():
        return jsonify({"error": "RTSP server is not running. Start it first"}), 409

    try:
        _rtsp_mgr.push(str(vp), stream_name)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    rtsp_url = f"rtsp://localhost:8554/{stream_name}"
    log.info("RTSP push started: %s → %s", vp.name, rtsp_url)
    return jsonify({"ok": True, "rtsp_url": rtsp_url})


@rtsp_bp.route("/api/rtsp/stop_push", methods=["POST"])
def api_rtsp_stop_push():
    """Stop the active FFmpeg push."""
    _rtsp_mgr.stop_push()
    log.info("RTSP push stopped.")
    return jsonify({"ok": True})


# ── GPU info ─────────────────────────────────────────────────────────────────

