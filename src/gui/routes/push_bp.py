"""
src/gui/routes/push_bp.py - closed-app push settings (R6 TRACK C1).

Two routes over utils.push_notify:

  * GET  /api/push/config  - the current settings, token replaced by a boolean
  * POST /api/push/config  - validate and save them
  * POST /api/push/test    - post a test message NOW and report what happened,
                             optionally against a URL that has not been saved
                             yet, so an operator can prove a topic works before
                             committing to it

The token is never echoed back. A client that wants to change the other
fields simply omits the key and the stored token survives; sending
``"token": ""`` clears it. That is the only way the dashboard can offer a
settings form without ever holding the secret it is editing.

Author: Bloodawn (KheivenD), 2026-08-17 (R6 TRACK C1).
"""

from flask import Blueprint, jsonify, request

try:
    from utils import push_notify
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils import push_notify

push_bp = Blueprint("push", __name__)


@push_bp.route("/api/push/config", methods=["GET", "POST"])
def api_push_config():
    """Read or replace the push settings."""
    if request.method == "GET":
        return jsonify({"config": push_notify.public_config()})

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400
    ok, error, cfg = push_notify.save_config(data)
    if not ok:
        return jsonify({"error": error, "config": cfg}), 400
    return jsonify({"ok": True, "config": cfg})


@push_bp.route("/api/push/test", methods=["POST"])
def api_push_test():
    """Send one test push synchronously and report the outcome."""
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    topic_url = data.get("topic_url")
    token = data.get("token")
    ok, detail = push_notify.send_test(
        topic_url=str(topic_url) if topic_url is not None else None,
        token=str(token) if token is not None else None,
    )
    # A failed test is a normal, expected answer to "does this URL work",
    # not a server error, so it stays a 200 with ok=False and the reason.
    return jsonify({"ok": ok, "detail": detail})
