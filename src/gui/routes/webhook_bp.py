"""
src/gui/routes/webhook_bp.py - outbound webhook settings (Week 3 TASK 3.9).

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

from flask import Blueprint, jsonify, request

try:
    from utils import event_webhook
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils import event_webhook

webhook_bp = Blueprint("webhook", __name__)


@webhook_bp.route("/api/webhook/config", methods=["GET", "POST"])
def api_webhook_config():
    """Read or replace the webhook settings."""
    if request.method == "GET":
        return jsonify({"config": event_webhook.public_config()})

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
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    url = data.get("url")
    secret = data.get("secret")
    ok, detail = event_webhook.send_test(
        url=str(url) if url is not None else None,
        secret=str(secret) if secret is not None else None,
    )
    # A failed test is a normal, expected answer to "does this URL work",
    # not a server error, so it stays a 200 with ok=False and the reason.
    return jsonify({"ok": ok, "detail": detail})
