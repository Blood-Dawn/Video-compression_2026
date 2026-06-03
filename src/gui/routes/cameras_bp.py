"""
src/gui/routes/cameras_bp.py

Camera-setup routes: ONVIF discovery + RTSP URL building (M-CAM TASK 1).

Two endpoints back the dashboard's "Add camera" flow:
  * GET  /api/cameras/discover  — WS-Discovery scan of the LAN; returns the
    ONVIF cameras found (address/name/hardware + candidate RTSP paths). Never
    errors on an empty/blocked network — returns an empty list so the UI falls
    back to manual RTSP entry.
  * POST /api/cameras/rtsp_url  — build a properly URL-encoded rtsp:// URL from
    host/path/port/username/password (server-side so credentials with special
    characters are encoded correctly). The built URL is NOT logged.

Author: Bloodawn (KheivenD), 2026-06-03 (M-CAM TASK 1 — camera setup).
"""

from flask import Blueprint, jsonify, request

try:
    from gui.logging_setup import log
    from utils.onvif_discovery import discover, build_rtsp_url, rtsp_url_candidates, DEFAULT_RTSP_PORT
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.logging_setup import log
    from src.utils.onvif_discovery import discover, build_rtsp_url, rtsp_url_candidates, DEFAULT_RTSP_PORT

cameras_bp = Blueprint("cameras", __name__)


@cameras_bp.route("/api/cameras/discover", methods=["GET"])
def api_cameras_discover():
    """Discover ONVIF cameras on the LAN via WS-Discovery.

    Optional query param ``timeout`` (seconds, 1–10, default 3). Returns the
    devices found plus suggested (credential-free) RTSP URL candidates so the
    operator can pick a stream; an empty list means discovery found nothing
    (manual entry is the fallback, not an error).
    """
    try:
        timeout = float(request.args.get("timeout", 3.0))
    except (TypeError, ValueError):
        timeout = 3.0
    timeout = max(1.0, min(10.0, timeout))

    devices = discover(timeout=timeout)
    out = []
    for d in devices:
        item = d.as_dict()
        item["vendor"] = d.vendor_key()
        item["rtsp_candidates"] = rtsp_url_candidates(d)  # no credentials
        out.append(item)

    log.info("ONVIF discovery found %d camera(s).", len(out))
    return jsonify({"ok": True, "count": len(out), "cameras": out})


@cameras_bp.route("/api/cameras/rtsp_url", methods=["POST"])
def api_cameras_rtsp_url():
    """Build a URL-encoded rtsp:// URL from parts.

    Body (JSON): {"host": "192.168.1.50", "path": "/stream1",
                  "port": 554, "username": "...", "password": "..."}
    Only ``host`` is required. The returned URL may embed credentials, so it is
    deliberately not written to the log.
    """
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    host = str(data.get("host", "")).strip()
    if not host:
        return jsonify({"error": "host is required"}), 400
    path = str(data.get("path", "/stream1")).strip() or "/stream1"
    try:
        port = int(data.get("port", DEFAULT_RTSP_PORT))
    except (TypeError, ValueError):
        return jsonify({"error": "port must be an integer"}), 400
    if not (1 <= port <= 65535):
        return jsonify({"error": "port must be in 1..65535"}), 400
    username = data.get("username") or None
    password = data.get("password") or None

    try:
        url = build_rtsp_url(host, path, port, username, password)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Log only the host — never the full URL (it may carry a password).
    log.info("Built RTSP URL for camera host %s (path %s)", host, path)
    return jsonify({"ok": True, "rtsp_url": url})
