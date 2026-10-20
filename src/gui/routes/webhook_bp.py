"""
src/gui/routes/webhook_bp.py - outbound webhook settings.

Same three-route shape as push_bp.py, over utils.event_webhook instead of
utils.push_notify:

  * GET  /api/webhook/config  - the current settings, secret replaced by a boolean
  * POST /api/webhook/config  - validate and save them
  * POST /api/webhook/test    - post a test delivery NOW and report what
                                happened, optionally against a URL that has
                                not been saved yet

The secret is never echoed back, same write-only contract as push_bp.py's
token: omitting the key on save keeps the stored secret, sending "" clears it.

Author: Bloodawn (KheivenD), Week 3 (3.9).
"""

from flask import Blueprint, Response, jsonify, request

try:
    from gui.auth import SCHEME_BEARER, current_auth_scheme
    from utils import event_webhook
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.auth import SCHEME_BEARER, current_auth_scheme
    from src.utils import event_webhook

webhook_bp = Blueprint("webhook", __name__)


def _require_password_auth():
    """Return a 403 Response if this request authenticated with a device token.

    Changing where deliveries go, or making the server send a request, must
    not be possible with a stolen phone token. None means proceed.
    """
    if current_auth_scheme() == SCHEME_BEARER:
        return Response(
            '{"error": "Webhook changes require the dashboard password, '
            'not a device token."}',
            403, {"Content-Type": "application/json"})
    return None


@webhook_bp.route("/api/webhook/config", methods=["GET", "POST"])
def api_webhook_config():
    """Read or replace the webhook settings."""
    if request.method == "GET":
        return jsonify({"config": event_webhook.public_config()})

    denied = _require_password_auth()
    if denied is not None:
        return denied
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400
    ok, error, cfg = event_webhook.save_config(data)
    if not ok:
        return jsonify({"error": error, "config": cfg}), 400
    return jsonify({"ok": True, "config": cfg})


@webhook_bp.route("/api/webhook/test", methods=["POST"])
def api_webhook_test():
    """Send one test delivery synchronously and report the outcome."""
    denied = _require_password_auth()
    if denied is not None:
        return denied
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    url = data.get("url")
    secret = data.get("secret")
    ok, detail = event_webhook.send_test(
        url=str(url) if url is not None else None,
        secret=str(secret) if secret is not None else None,
    )
    # A failed test is an expected answer, so it stays a 200 with ok=False.
    return jsonify({"ok": ok, "detail": detail})
