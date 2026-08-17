"""
src/gui/routes/events_bp.py - zones config + behavior events API
(R5 TASKS 5.6 + 5.7).

* GET  /api/zones?camera_id=X   - the stored zones/lines/loiter config
* POST /api/zones               - {"camera_id": X, ...config} validate + save
* GET  /api/events/recent       - newest-first behavior events from the
                                  configured output folder's events.jsonl

The pipeline reads the same config (utils.zones_config) at run start, so a
saved change applies to the NEXT run; the response says so rather than
letting a user think a running encode re-reads it live.

Author: Bloodawn (KheivenD), 2026-08-17 (R5 TASKS 5.6/5.7).
"""

import re as _re

from flask import Blueprint, jsonify, request

try:
    from gui.services.cloud_detection import _default_output_dir
    from utils import event_log, zones_config
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services.cloud_detection import _default_output_dir
    from src.utils import event_log, zones_config

events_bp = Blueprint("events", __name__)

_CAM_RE = _re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


@events_bp.route("/api/zones", methods=["GET", "POST"])
def api_zones():
    """Read or replace one camera's zones/lines/loiter config."""
    if request.method == "GET":
        camera_id = (request.args.get("camera_id", "") or "").strip()
        if not _CAM_RE.match(camera_id):
            return jsonify({"error": "camera_id must be 1-64 alphanumeric/dash/underscore chars"}), 400
        return jsonify({"camera_id": camera_id,
                        "config": zones_config.load_camera_config(camera_id),
                        "applies": "next run"})

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400
    camera_id = str(data.get("camera_id", "")).strip()
    if not _CAM_RE.match(camera_id):
        return jsonify({"error": "camera_id must be 1-64 alphanumeric/dash/underscore chars"}), 400
    stored = zones_config.save_camera_config(camera_id, data)
    return jsonify({"ok": True, "camera_id": camera_id, "config": stored,
                    "applies": "next run"})


@events_bp.route("/api/events/recent", methods=["GET"])
def api_events_recent():
    """Newest-first behavior events from the configured output folder."""
    try:
        limit = int(request.args.get("limit", 100))
    except (TypeError, ValueError):
        limit = 100
    out_dir = _default_output_dir()
    return jsonify({
        "events": event_log.read_recent(out_dir, limit=limit),
        "output_dir": str(out_dir),
    })
