"""
src/gui/routes/usage_bp.py

Opt-in usage-stats consent routes (M5 TASK 5.2).

Backs the first-run consent banner and the settings toggle:
  * GET  /api/usage_stats          - current state {consent, known, enabled}
  * POST /api/usage_stats/consent  - store the user's choice {consent: bool}

The actual collection lives in utils.usage_stats, which is default-OFF and
scrubs PII/paths. These routes only persist the yes/no decision.

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 5.2 - usage-stats consent).
"""

from flask import Blueprint, jsonify, request

try:
    from gui.logging_setup import log
    from utils import usage_stats
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.logging_setup import log
    from src.utils import usage_stats

usage_bp = Blueprint("usage", __name__)


@usage_bp.route("/api/usage_stats", methods=["GET"])
def api_usage_stats():
    """Report whether the user has answered the consent prompt and the result.

    ``known`` is false on first run (no decision yet) so the UI knows to show
    the consent banner; ``enabled`` reflects the effective state (consent given
    and not overridden by the env kill-switch).
    """
    consent = usage_stats.read_consent()
    return jsonify({
        "known": consent is not None,
        "consent": bool(consent) if consent is not None else None,
        "enabled": usage_stats.is_enabled(),
    })


@usage_bp.route("/api/usage_stats/consent", methods=["POST"])
def api_usage_stats_consent():
    """Persist the user's opt-in/opt-out decision."""
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict) or "consent" not in data:
        return jsonify({"error": "Body must be a JSON object with a 'consent' boolean"}), 400
    consent = bool(data.get("consent"))
    usage_stats.set_consent(consent)
    log.info("Usage stats consent set to %s", consent)
    return jsonify({"ok": True, "consent": consent, "enabled": usage_stats.is_enabled()})
