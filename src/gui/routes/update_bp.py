"""
src/gui/routes/update_bp.py

Auto-update pipeline (download + verify + install), building on the notify-only
/api/setup/update_check.

  * GET  /api/update/status   - poll download/verify/install progress
  * POST /api/update/download - re-checks GitHub itself and starts a
                                 background download + checksum verify of
                                 whatever it finds (ignores any request body)
  * POST /api/update/install  - launches the verified installer and begins
                                 shutting this process down so it can run

Each route only acts on the release update_manager itself found on the pinned
GitHub releases endpoint; none accepts or forwards a caller-supplied URL.

Registered in both editions (unlike rtsp_bp/hls_bp): auto-update applies to
every desktop install.

Author: Bloodawn (KheivenD), 2026-09-24 (Fall 3.18 - auto-update pipeline).
"""

from flask import Blueprint, jsonify

try:
    from gui.services import update_manager
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services import update_manager

update_bp = Blueprint("update", __name__)


@update_bp.route("/api/update/status", methods=["GET"])
def api_update_status():
    """Current download/verify/install phase, for the dashboard to poll."""
    return jsonify(update_manager.get_status())


@update_bp.route("/api/update/download", methods=["POST"])
def api_update_download():
    """Start (or report the status of) a background installer download.

    The request body is ignored on purpose: the URL always comes from
    update_manager's own GitHub check, never from the client.
    """
    return jsonify(update_manager.start_download())


@update_bp.route("/api/update/install", methods=["POST"])
def api_update_install():
    """Launch the verified installer and start shutting this process down.

    Refuses (400) unless a download has already finished and passed
    checksum verification (update_manager enforces this, not this route).
    """
    result = update_manager.install_and_restart()
    if not result.get("ok"):
        return jsonify(result), 400
    # Lets the HTTP response reach the browser before this process exits.
    update_manager.quit_app_for_update()
    return jsonify(result)
