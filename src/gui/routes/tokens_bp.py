"""
src/gui/routes/tokens_bp.py

Device-token management for the mobile client (M0.10).

  * GET    /api/auth/tokens              - list paired devices (no secrets)
  * POST   /api/auth/tokens              - mint one, returns the secret ONCE
  * DELETE /api/auth/tokens/<token_id>   - revoke one device
  * POST   /api/auth/tokens/revoke_all   - revoke every device

Every route here requires the PASSWORD (HTTP Basic), never a Bearer token. A
stolen phone token must not be able to mint successors or revoke the operator's
other devices, which would let an attacker both persist and lock the owner out.
gui.auth records the scheme that authenticated the request on flask.g and
``current_auth_scheme()`` reads it back.

The minted secret is returned exactly once, in the POST response, and only its
SHA-256 is ever persisted. There is deliberately no route that can re-reveal it.

Author: Bloodawn (KheivenD), 2026-07-18 (M0.10 - device tokens).
"""

from flask import Blueprint, Response, jsonify, request

try:
    from gui import device_tokens
    from gui.auth import SCHEME_BEARER, current_auth_scheme
    from gui.logging_setup import log
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui import device_tokens
    from src.gui.auth import SCHEME_BEARER, current_auth_scheme
    from src.gui.logging_setup import log

tokens_bp = Blueprint("tokens", __name__)

# Cap on stored tokens. Not a security boundary, just a guard against a runaway
# client minting without bound and growing the state file forever.
_MAX_TOKENS = 50


def _require_password_auth():
    """Return a 403 Response if this request authenticated with a token.

    None means the caller is allowed to proceed.
    """
    if current_auth_scheme() == SCHEME_BEARER:
        return Response(
            '{"error": "Token management requires the dashboard password, '
            'not a device token."}',
            403, {"Content-Type": "application/json"})
    return None


@tokens_bp.route("/api/auth/tokens", methods=["GET"])
def api_list_tokens():
    """List paired devices. Returns metadata only, never hashes or secrets."""
    denied = _require_password_auth()
    if denied is not None:
        return denied
    items = [t.to_public() for t in device_tokens.list_tokens()]
    return jsonify({"tokens": items, "count": len(items)})


@tokens_bp.route("/api/auth/tokens", methods=["POST"])
def api_mint_token():
    """Mint a device token. The secret is in the response and never again."""
    denied = _require_password_auth()
    if denied is not None:
        return denied

    data = request.get_json(silent=True) or {}
    label = str(data.get("label") or "").strip() or "device"

    live = [t for t in device_tokens.list_tokens() if t.is_usable()]
    if len(live) >= _MAX_TOKENS:
        return jsonify({
            "error": f"Token limit reached ({_MAX_TOKENS} live). "
                     "Revoke an unused device first.",
        }), 409

    ttl_raw = data.get("ttl_days")
    ttl = None
    if ttl_raw not in (None, "", False):
        try:
            ttl = max(0, int(ttl_raw))
        except (TypeError, ValueError):
            ttl = None

    # An unreadable store must not be papered over: minting on top of a
    # failed read would have deleted every other paired device. Report it and
    # let the operator fix the file.
    try:
        secret, rec = device_tokens.mint_token(label, ttl_days=ttl)
    except device_tokens.StoreUnreadable as exc:
        log.error(f"Refusing to mint a token: {exc}")
        return jsonify({
            "error": "The device-token store could not be read, so pairing a "
                     "new device would have unpaired the existing ones. "
                     "Nothing was changed. Check the server log.",
        }), 503
    # Log the pairing event but NOT the secret, per the house rule.
    log.info(f"Device token minted: label={rec.label!r} id={rec.id} "
             f"expires={rec.expires_at or 'never'}")
    return jsonify({
        "token": secret,          # shown once; the client must store it now
        "id": rec.id,
        "label": rec.label,
        "created_at": rec.created_at,
        "expires_at": rec.expires_at,
        "warning": "Copy this token now. It cannot be shown again.",
    }), 201


@tokens_bp.route("/api/auth/tokens/<token_id>", methods=["DELETE"])
def api_revoke_token(token_id):
    """Revoke one device by id."""
    denied = _require_password_auth()
    if denied is not None:
        return denied
    try:
        ok = device_tokens.revoke_token(str(token_id))
    except device_tokens.StoreUnreadable as exc:
        log.error(f"Refusing to revoke a token: {exc}")
        return jsonify({
            "error": "The device-token store could not be read. Nothing was "
                     "changed. Check the server log.",
        }), 503
    if not ok:
        return jsonify({"error": "No live token with that id."}), 404
    log.info(f"Device token revoked: id={token_id}")
    return jsonify({"revoked": True, "id": token_id})


@tokens_bp.route("/api/auth/tokens/revoke_all", methods=["POST"])
def api_revoke_all_tokens():
    """Revoke every device. The panic button for a lost phone."""
    denied = _require_password_auth()
    if denied is not None:
        return denied
    try:
        n = device_tokens.revoke_all()
    except device_tokens.StoreUnreadable as exc:
        log.error(f"Refusing to revoke all tokens: {exc}")
        return jsonify({
            "error": "The device-token store could not be read. Nothing was "
                     "changed. Check the server log.",
        }), 503
    log.info(f"All device tokens revoked ({n}).")
    return jsonify({"revoked": True, "count": n})
