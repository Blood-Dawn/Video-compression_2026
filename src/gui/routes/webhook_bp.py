"""
src/gui/routes/webhook_bp.py - event webhook settings (planner 4.10).

Two routes over utils.event_webhook, shaped exactly like push_bp:

  * GET  /api/webhook/config  - the current settings, secret replaced by a boolean
  * POST /api/webhook/config  - validate and save them
  * POST /api/webhook/test    - deliver one synthetic event NOW and report the
                                status line, optionally against a URL that has
                                not been saved yet

The signing secret is write-only. A client that wants to change the other
fields omits the ``secret`` key and the stored secret survives; sending
``"secret": ""`` clears it.

The test route makes the server send a request to a caller-supplied URL. That
is acceptable only because the URL goes through the shared SSRF guard, the
route sits behind the dashboard auth and the CSRF guard, and the answer is a
status line only: the receiver's response body is never echoed, so this
cannot be used to read pages on the operator's network.

Author: Victor De Souza Teixeira, 2026-10-06 (planner 4.10).
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
    """Deliver one test event synchronously and report the outcome."""
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    url = data.get("url")
    secret = data.get("secret")
    ok, detail = event_webhook.send_test(
        url=str(url) if url is not None else None,
        secret=str(secret) if secret is not None else None,
    )
    # A failed test is a normal answer to "does this URL work", not a server
    # error, so it stays a 200 with ok=False and the reason, like /api/push/test.
    return jsonify({"ok": ok, "detail": detail})
