"""
src/gui/routes/autocompress_bp.py

Auto-compress routes (R3.1b).

The HTTP surface for the AUTO-COMPRESS tab. It drives the opt-in auto-compress
daemon (``gui.services.autocompress_runner``), which watches a folder and
compresses any video that lands in it into ``<output_dir>/compressed/``. The
daemon NEVER starts on app launch - it starts only when the user POSTs to
``/start`` from the UI.

Endpoints:
  * POST /api/autocompress/start    {folder, mode|preset, profile?, delete_original?}
  * POST /api/autocompress/stop
  * GET  /api/autocompress/status   running?, watched folder, queue, recent N
  * POST /api/autocompress/scan_now one batch pass over the folder right now

Author: Bloodawn (KheivenD), 2026-06-06 (R3.1b - auto-compress blueprint).
"""

from pathlib import Path

from flask import Blueprint, jsonify, request

try:
    from gui.logging_setup import log
    from gui.services.cloud_detection import _default_output_dir
    from gui.services import autocompress_runner as ac
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.logging_setup import log
    from src.gui.services.cloud_detection import _default_output_dir
    from src.gui.services import autocompress_runner as ac

autocompress_bp = Blueprint("autocompress", __name__)


def _output_dir() -> str:
    """The base output dir; compressed clips go under ``<this>/compressed/``."""
    return str(_default_output_dir())


@autocompress_bp.route("/api/autocompress/start", methods=["POST"])
def api_autocompress_start():
    """Start the auto-compress daemon on a watched folder.

    Body: {folder (required), mode (default "mode0"), preset?, profile?,
    delete_original?}. Refuses if the folder is missing or already running.
    """
    body = request.get_json(silent=True) or {}
    folder = (body.get("folder") or "").strip()
    if not folder:
        return jsonify({"ok": False, "error": "folder is required"}), 400
    if not Path(folder).is_dir():
        return jsonify({"ok": False, "error": f"not a folder: {folder}"}), 400
    if ac.is_running():
        return jsonify({"ok": False, "error": "auto-compress is already running",
                        "status": ac.get_status()}), 409

    config = {
        "folder": folder,
        "output_dir": _output_dir(),
        "mode": (body.get("mode") or ac.DEFAULT_MODE).strip(),
        "preset": (body.get("preset") or None),
        "profile": (body.get("profile") or None),
        "delete_original": bool(body.get("delete_original", False)),
        "poll_interval": int(body.get("poll_interval", 10) or 10),
    }
    started = ac.start_autocompress(config)
    if not started:
        return jsonify({"ok": False, "error": "could not start",
                        "status": ac.get_status()}), 409
    log.info("Auto-compress start requested for %s", folder)
    return jsonify({"ok": True, "status": ac.get_status()})


@autocompress_bp.route("/api/autocompress/stop", methods=["POST"])
def api_autocompress_stop():
    """Signal the auto-compress daemon to stop."""
    stopped = ac.stop_autocompress()
    return jsonify({"ok": True, "stopped": stopped, "status": ac.get_status()})


@autocompress_bp.route("/api/autocompress/status", methods=["GET"])
def api_autocompress_status():
    """Return the current auto-compress status (running, folder, queue, recent)."""
    return jsonify(ac.get_status())


@autocompress_bp.route("/api/autocompress/scan_now", methods=["POST"])
def api_autocompress_scan_now():
    """Run one batch pass: compress every uncompressed clip in the folder now.

    Body: {folder (required), mode, preset?, profile?, delete_original?}. This is
    synchronous (returns when the pass finishes) and is independent of whether
    the watch daemon is running.
    """
    body = request.get_json(silent=True) or {}
    folder = (body.get("folder") or "").strip()
    if not folder:
        return jsonify({"ok": False, "error": "folder is required"}), 400
    if not Path(folder).is_dir():
        return jsonify({"ok": False, "error": f"not a folder: {folder}"}), 400

    try:
        done = ac.scan_once(
            folder=folder,
            output_dir=_output_dir(),
            mode=(body.get("mode") or ac.DEFAULT_MODE).strip(),
            preset=(body.get("preset") or None),
            profile=(body.get("profile") or None),
            delete_original=bool(body.get("delete_original", False)),
        )
    except Exception as exc:  # noqa: BLE001
        log.error("Auto-compress scan_now failed: %s", exc, exc_info=True)
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": True, "compressed": len(done), "items": done,
                    "status": ac.get_status()})
