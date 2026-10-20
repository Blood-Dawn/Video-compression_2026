"""
src/gui/routes/push_bp.py - closed-app push settings (R6 TRACK C1).

Routes over utils.push_notify:

  * GET  /api/push/config  - the current settings, token replaced by a boolean
  * POST /api/push/config  - validate and save them
  * POST /api/push/test    - post a test message now and report the outcome,
                             optionally against a URL not yet saved

The token is never echoed back. Omitting the key keeps the stored token;
``"token": ""`` clears it, so the settings form never holds the secret it edits.

Author: Bloodawn (KheivenD), 2026-08-17 (R6 TRACK C1).
"""

from flask import Blueprint, jsonify, request

try:
    from utils import push_notify
    from gui import device_tokens
    from gui.auth import current_device_id
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils import push_notify
    from src.gui import device_tokens
    from src.gui.auth import current_device_id

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
    # A failed test is an expected answer, so it stays a 200 with ok=False.
    return jsonify({"ok": ok, "detail": detail})


# A device registers its OWN native push endpoint (UnifiedPush): a URL that,
# when POSTed to, wakes that phone.
#
# One device can never register, read, or clear another device's endpoint, by
# construction: these routes take no device id from the request. The device is
# whichever token authenticated it, via current_device_id(). A Basic (password)
# request has no device identity and is refused.
#
# The URL goes through the same SSRF guard as push and the webhook, because
# the server is the one that sends to it.

_NOT_A_DEVICE = ("Only a paired device can manage its own push endpoint. "
                 "Sign in with that device's token, not the dashboard password.")


def is_safe_push_endpoint(url) -> "tuple[bool, str]":
    """The shared outbound-URL guard, worded for a push endpoint."""
    return push_notify.check_outbound_url(
        url, require_path=False, label="push endpoint",
        credential_field="endpoint your push distributor issued")


@push_bp.route("/api/push/endpoint", methods=["GET", "PUT", "DELETE"])
def api_push_endpoint():
    """Read, set, or clear THIS device's push endpoint."""
    device_id = current_device_id()
    if not device_id:
        return jsonify({"error": _NOT_A_DEVICE}), 403

    if request.method == "GET":
        endpoint = device_tokens.get_push_endpoint(device_id)
        return jsonify({"endpoint": endpoint or "", "registered": bool(endpoint)})

    if request.method == "DELETE":
        if not device_tokens.set_push_endpoint(device_id, None):
            return jsonify({"error": "This device token is no longer valid."}), 403
        return jsonify({"ok": True, "registered": False})

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400
    endpoint = str(data.get("endpoint") or "").strip()
    ok, why = is_safe_push_endpoint(endpoint)
    if not ok:
        return jsonify({"error": why}), 400
    if not device_tokens.set_push_endpoint(device_id, endpoint):
        return jsonify({"error": "This device token is no longer valid."}), 403
    return jsonify({"ok": True, "registered": True})
