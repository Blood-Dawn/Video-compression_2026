"""
src/gui/routes/update_bp.py

Fall 3.18: the actual auto-update pipeline (download + verify + install),
building on Fall 3.17's notify-only /api/setup/update_check.

  * GET  /api/update/status   - poll download/verify/install progress
  * POST /api/update/download - re-checks GitHub itself and starts a
                                 background download + checksum verify of
                                 whatever it finds (ignores any request body)
  * POST /api/update/install  - launches the verified installer and begins
                                 shutting this process down so it can run

Every one of these only ever acts on the release update_manager itself found
on the pinned GitHub releases endpoint - nothing here accepts or forwards a
caller-supplied URL. See update_manager's module docstring for the full
reasoning (same 2026-09-24 dishonesty-audit pass as the encryption-honesty
and dead-segment-counter fixes: a feature that can silently do something
other than what it visibly says is a liability).

Registered in both editions (unlike rtsp_bp/hls_bp): auto-update is not a
server-making surface, it applies to every desktop install.

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
    """Start (or report the status of) a background download of the latest
    desktop installer. Ignores the request body on purpose - see module
    docstring: the download URL always comes from update_manager's own
    GitHub check, never from the client."""
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
    # Give the HTTP response a moment to actually reach the browser before
    # this process exits out from under it.
    update_manager.quit_app_for_update()
    return jsonify(result)
