"""
src/gui/routes/setup_bp.py

First-run Setup + destination chooser (FIX 1).

The dashboard used to silently default outputs to a detected OneDrive root. The
owner wants to CHOOSE the destination explicitly and never have a cloud folder
picked implicitly. These routes back a first-run Setup page:

  * GET  /api/setup/state         - whether Setup is done + the current choices
  * GET  /api/setup/destinations  - the OFFERED destinations (none auto-picked)
  * POST /api/setup/choose        - persist the user's output + encrypted choice

The actual default-resolution change lives in gui.services.cloud_detection
(_default_output_dir no longer falls through to a cloud root).

Author: Bloodawn (KheivenD), 2026-06-03 (FIX 1 - setup + destinations).
"""

from pathlib import Path

from flask import Blueprint, jsonify, request

try:
    from gui.logging_setup import log
    from gui.services.cloud_detection import list_destinations, _default_output_dir
    from gui.services.gui_state_persist import save_setup_choice, is_setup_complete
    from gui.services.path_safety import _safe_output_dir
    from gui.state import _state_lock, _status
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.logging_setup import log
    from src.gui.services.cloud_detection import list_destinations, _default_output_dir
    from src.gui.services.gui_state_persist import save_setup_choice, is_setup_complete
    from src.gui.services.path_safety import _safe_output_dir
    from src.gui.state import _state_lock, _status

setup_bp = Blueprint("setup", __name__)


def _default_encrypted_dir(output_dir: str) -> str:
    """Default encrypted-output location: an ``Encrypted`` subfolder of output."""
    try:
        return str(Path(output_dir) / "Encrypted")
    except Exception:  # noqa: BLE001
        return ""


@setup_bp.route("/api/setup/state", methods=["GET"])
def api_setup_state():
    """Report whether first-run Setup is done and the current destinations."""
    with _state_lock:
        cfg = _status.get("config", {})
        out_dir = (cfg.get("output_dir") or "").strip()
        enc_dir = (cfg.get("encrypted_dir") or "").strip()
    return jsonify({
        "setup_complete": is_setup_complete(),
        "output_dir": out_dir,
        "encrypted_dir": enc_dir,
        # Neutral local fallback the UI shows when nothing is chosen yet.
        "default_output_dir": _default_output_dir(),
    })


@setup_bp.route("/api/setup/destinations", methods=["GET"])
def api_setup_destinations():
    """List the OFFERED output destinations. Nothing is auto-selected."""
    dests = list_destinations()
    return jsonify({
        "destinations": dests,
        # The neutral local fallback used if the user skips Setup.
        "neutral_default": _default_output_dir(),
    })


@setup_bp.route("/api/setup/choose", methods=["POST"])
def api_setup_choose():
    """Persist the user's explicit destination choice and finish Setup.

    Body (JSON):
        output_dir    - required, absolute path the user picked
        encrypted_dir - optional; defaults to <output_dir>/Encrypted

    The path is validated (no traversal) and created if missing. Returns the
    resolved choices.
    """
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    raw_out = str(data.get("output_dir", "")).strip()
    if not raw_out:
        return jsonify({"error": "output_dir is required"}), 400

    try:
        out_path = _safe_output_dir(raw_out)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    raw_enc = str(data.get("encrypted_dir", "")).strip()
    if raw_enc:
        try:
            enc_path = _safe_output_dir(raw_enc)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    else:
        enc_path = Path(_default_encrypted_dir(str(out_path)))

    # Create the folders now so Start does not fail later on a typo.
    try:
        out_path.mkdir(parents=True, exist_ok=True)
        enc_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return jsonify({"error": f"Could not create folder: {exc}"}), 400

    save_setup_choice(str(out_path), str(enc_path))
    log.info("Setup destination chosen: output=%s encrypted=%s", out_path, enc_path)
    return jsonify({
        "ok": True,
        "setup_complete": True,
        "output_dir": str(out_path),
        "encrypted_dir": str(enc_path),
    })
