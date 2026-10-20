"""
src/gui/routes/timelapse_bp.py

POST /api/timelapse - generate a sped-up summary clip from an already-recorded
segment, so a long, mostly-quiet recording can be reviewed quickly. A
convenience post-process over utils.timelapse; it never touches the live
pipeline.

Author: Bloodawn (KheivenD), 2026-10-01.
"""
from flask import Blueprint, jsonify, request

try:
    from gui.logging_setup import log
    from gui.services.path_safety import confine_to_allowed, allowed_media_roots
    from utils.timelapse import make_timelapse, clamp_speed, DEFAULT_SPEED
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.logging_setup import log
    from src.gui.services.path_safety import confine_to_allowed, allowed_media_roots
    from src.utils.timelapse import make_timelapse, clamp_speed, DEFAULT_SPEED

timelapse_bp = Blueprint("timelapse", __name__)


@timelapse_bp.route("/api/timelapse", methods=["POST"])
def api_timelapse():
    """Generate a sped-up timelapse of an existing segment.

    POST body (JSON):
        path  - absolute path to the source segment. Must resolve inside an
                allowed media root (the confinement every file-reading route
                uses) so ffmpeg cannot be run over an arbitrary host path.
        speed - playback speed multiplier, default 8x, clamped to [2, 60].

    Output is written beside the source as "<stem>_timelapse_<speed>x<ext>" and
    is not registered in the compressed index or job history.
    """
    data = request.get_json(force=True) or {}
    raw_path = str(data.get("path", "")).strip()
    if not raw_path:
        return jsonify({"error": "path is required"}), 400

    try:
        src = confine_to_allowed(raw_path, allowed_media_roots())
    except ValueError:
        log.warning("api_timelapse: rejected path outside allowed roots: %s", raw_path)
        return jsonify({"error": "path must be inside an allowed media folder"}), 403

    if not src.is_file():
        return jsonify({"error": f"File not found: {src.name}"}), 400

    speed = clamp_speed(data.get("speed", DEFAULT_SPEED))
    out_path = src.with_name(f"{src.stem}_timelapse_{int(speed)}x{src.suffix}")

    ok, result = make_timelapse(src, out_path, speed=speed)
    if not ok:
        return jsonify({"error": result}), 500

    log.info("Timelapse generated: %s -> %s (%.0fx)", src.name, out_path.name, speed)
    return jsonify({
        "ok": True,
        "path": str(out_path),
        "filename": out_path.name,
        "speed": speed,
    })
