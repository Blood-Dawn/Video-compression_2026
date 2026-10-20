"""
src/gui/routes/setup_bp.py

First-run Setup + destination chooser (FIX 1).

The owner CHOOSES the output destination explicitly; a cloud folder is never
picked implicitly. These routes back a first-run Setup page:

  * GET  /api/setup/state         - whether Setup is done + the current choices
  * GET  /api/setup/destinations  - the OFFERED destinations (none auto-picked)
  * POST /api/setup/choose        - persist the user's output + encrypted choice

_default_output_dir (gui.services.cloud_detection) never falls through to a
cloud root.

Author: Bloodawn (KheivenD), 2026-06-03 (FIX 1 - setup + destinations).
"""

import shutil
# Tests patch setup_bp.urllib.request.urlopen, the same module object
# update_manager calls.
import urllib.request  # noqa: F401
from pathlib import Path

from flask import Blueprint, jsonify, request

try:
    from gui.logging_setup import log
    from gui.services.cloud_detection import list_destinations, _default_output_dir
    from gui.services.gui_state_persist import save_setup_choice, is_setup_complete
    from gui.services.cpu_sampler import reset_mode_avgs
    from gui.services.path_safety import _safe_output_dir
    from gui.services import update_manager
    from gui.state import _state_lock, _status
    from utils.paths import reset_state
    from gui.routes.tokens_bp import _require_password_auth
    # Re-exported for tests/test_setup.py.
    from utils.version import APP_VERSION  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.logging_setup import log
    from src.gui.services.cloud_detection import list_destinations, _default_output_dir
    from src.gui.services.gui_state_persist import save_setup_choice, is_setup_complete
    from src.gui.services.cpu_sampler import reset_mode_avgs
    from src.gui.services.path_safety import _safe_output_dir
    from src.gui.services import update_manager
    from src.gui.state import _state_lock, _status
    from src.utils.paths import reset_state
    from src.gui.routes.tokens_bp import _require_password_auth
    from src.utils.version import APP_VERSION  # noqa: F401

setup_bp = Blueprint("setup", __name__)


@setup_bp.route("/api/setup/state", methods=["GET"])
def api_setup_state():
    """Report whether first-run Setup is done and the current destinations."""
    with _state_lock:
        cfg = _status.get("config", {})
        out_dir = (cfg.get("output_dir") or "").strip()
        enc_dir = (cfg.get("encrypted_dir") or "").strip()
        lib_dir = (cfg.get("library_folder") or "").strip()
    return jsonify({
        "setup_complete": is_setup_complete(),
        "output_dir": out_dir,
        "encrypted_dir": enc_dir,
        # Last folder the Library browsed, so it reopens there.
        "library_folder": lib_dir,
        "default_output_dir": _default_output_dir(),
    })


@setup_bp.route("/api/setup/destinations", methods=["GET"])
def api_setup_destinations():
    """List the OFFERED output destinations. Nothing is auto-selected."""
    dests = list_destinations()
    return jsonify({
        "destinations": dests,
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
        enc_path = out_path / "Encrypted"

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


def _dep_entry(present: bool, path) -> dict:
    return {"present": bool(present), "path": (str(path) if path else "")}


@setup_bp.route("/api/setup/dependencies", methods=["GET"])
def api_setup_dependencies():
    """Report whether FFmpeg/FFprobe, the MediaMTX binary and the ONNX model exist.

    Each probe is best effort: a resolver that fails for any reason means "not
    installed" on this screen, never a 500.
    """
    deps = {}

    try:
        from utils.ffmpeg import ffmpeg_path, ffprobe_path
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.utils.ffmpeg import ffmpeg_path, ffprobe_path
    for key, resolver in (("ffmpeg", ffmpeg_path), ("ffprobe", ffprobe_path)):
        try:
            p = resolver()
            present = Path(p).is_file() or shutil.which(p) is not None
        except Exception:  # noqa: BLE001
            p, present = "", False
        deps[key] = _dep_entry(present, p if present else "")

    try:
        from gui.services.rtsp import _rtsp_mgr
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.gui.services.rtsp import _rtsp_mgr
    try:
        mtx = _rtsp_mgr.resolved_binary()
    except Exception:  # noqa: BLE001
        mtx = None
    deps["mediamtx"] = _dep_entry(mtx is not None, mtx)

    try:
        from detection.onnx_backend import _default_model_path
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.detection.onnx_backend import _default_model_path
    try:
        model = _default_model_path()
        present = Path(model).is_file()
    except Exception:  # noqa: BLE001
        model, present = "", False
    deps["onnx_model"] = _dep_entry(present, model if present else "")

    return jsonify({"dependencies": deps})


@setup_bp.route("/api/setup/reset", methods=["POST"])
def api_setup_reset():
    """Factory reset: clear per-install state and return to first-run.

    Deletes the persisted state files (CPU averages, saved prefs, usage consent,
    Flask secret), clears the in-memory CPU-per-mode panel, and forgets the
    destination choice. The user's compressed output folders are not deleted.

    Requires the dashboard PASSWORD, never a device token (PT-01).
    reset_state() deletes device_tokens.json, so a token that could reset would
    let a stolen phone unpair every other phone.
    """
    denied = _require_password_auth()
    if denied is not None:
        return denied
    removed = reset_state()
    reset_mode_avgs()
    with _state_lock:
        cfg = _status.setdefault("config", {})
        cfg["output_dir"] = ""
        cfg["encrypted_dir"] = ""
        _status["setup_complete"] = False
    log.info("Factory reset: removed %s; returning to first-run.", removed or "nothing")
    return jsonify({"ok": True, "removed": removed, "setup_complete": False})


@setup_bp.route("/api/setup/update_check", methods=["GET"])
def api_setup_update_check():
    """Check GitHub releases for a newer desktop build (check and notify only).

    Downloading and installing live behind /api/update/*, which shares
    update_manager's "newest desktop release" logic. Offline, rate limited or
    an unexpected response all fall through to update_available=False, never a
    5xx.
    """
    return jsonify(update_manager.check_for_update())
