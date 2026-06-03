"""
src/gui/routes/presets_bp.py

presets routes blueprint, carved from gui/app.py (TASK 1.3).
Pure relocation: every URL, method, and response shape is unchanged.
Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - blueprints).
"""

import json
from datetime import datetime
from pathlib import Path
from flask import Blueprint, current_app, jsonify, request

try:
    from gui.state import (_state_lock, _status, _VALID_MODES, _VALID_BG, _VALID_DEVICES, _VALID_MODELS, _CLOUD_SUBFOLDER)
    from gui.logging_setup import log
    from gui.services.cloud_detection import _default_output_dir, _detect_onedrive_root, _detect_gdrive_root, _detect_cloud_root
    from pipeline.presets import list_presets, resolve_preset, PRESETS, DEFAULT_PRESET, VALID_CODECS
    from pipeline.content_detect import detect_content
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.state import (_state_lock, _status, _VALID_MODES, _VALID_BG, _VALID_DEVICES, _VALID_MODELS, _CLOUD_SUBFOLDER)
    from src.gui.logging_setup import log
    from src.gui.services.cloud_detection import _default_output_dir, _detect_onedrive_root, _detect_gdrive_root, _detect_cloud_root
    from src.pipeline.presets import list_presets, resolve_preset, PRESETS, DEFAULT_PRESET, VALID_CODECS
    from src.pipeline.content_detect import detect_content

presets_bp = Blueprint("presets", __name__)


@presets_bp.route("/api/presets", methods=["GET"])
def api_presets():
    """Named surveillance presets for the dashboard (M3 TASK 3.1).

    Returns the ordered catalog the UI shows (modes are hidden behind these
    names), the default selection, and the fully-resolved encode config for
    each so the front-end can apply a preset to the form without a round-trip.
    """
    resolved = {key: resolve_preset(key) for key in PRESETS}
    return jsonify({
        "presets": list_presets(),
        "default": DEFAULT_PRESET,
        "configs": resolved,
    })

@presets_bp.route("/api/detect_content", methods=["POST"])
def api_detect_content():
    """Recommend a preset by analyzing a clip's first ~30s (M3 TASK 3.2).

    Body: {"path": "<local video file>"} (a file already on disk - an upload or
    a scanned recording). Returns the recommended preset key, its label, a
    one-line human reason, the resolved encode config, and the raw signals so
    the UI can show *why* and let the operator override.

    Returns:
        {"ok": true, "preset": "continuous_cctv", "label": "...",
         "reason": "...", "config": {...}, "signals": {...}}
        {"error": "..."} with 400 on bad input / unreadable video.
    """
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    raw = str(data.get("path", "")).strip()
    if not raw:
        return jsonify({"error": "Missing 'path' to a local video file"}), 400

    # Resolve and guard: must be an existing regular file, no traversal tricks.
    try:
        p = Path(raw).resolve()
    except (OSError, ValueError):
        return jsonify({"error": "Invalid path"}), 400
    if ".." in p.parts:
        return jsonify({"error": "Path traversal not allowed"}), 400
    if not p.is_file():
        return jsonify({"error": f"No such file: {raw}"}), 400

    try:
        rec = detect_content(str(p))
    except FileNotFoundError:
        return jsonify({"error": f"No such file: {raw}"}), 400
    except ValueError as exc:
        return jsonify({"error": f"Could not analyze video: {exc}"}), 400
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("detect_content failed for %s: %s", raw, exc)
        return jsonify({"error": "Content detection failed"}), 400

    log.info("Auto-detected preset '%s' for %s (%s)", rec.preset, p.name, rec.reason)
    return jsonify({
        "ok": True,
        "preset": rec.preset,
        "label": rec.label,
        "reason": rec.reason,
        "config": resolve_preset(rec.preset),
        "signals": rec.signals.as_dict(),
    })


@presets_bp.route("/api/config/import", methods=["POST"])
def api_config_import():
    """Accept a previously exported SVCS config JSON and store it as last_config.

    The front-end reads the returned ``config`` object and applies each value
    to the appropriate form field.  Fields not present in the JSON are left at
    their current defaults.  Credentials (encrypt_password, encrypt_key_file)
    are never stored by this route even if the client accidentally sends them.

    Returns:
        {"ok": true, "config": { ... normalised fields ... }}
        {"error": "..."} with 400 on bad input
    """
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    version = data.get("svcs_config_version")
    if version is None:
        return jsonify({"error": "Not a valid SVCS config file (missing svcs_config_version)"}), 400

    def _str(key, default=""):
        return str(data.get(key, default)).strip() or default

    def _int(key, default, lo=None, hi=None):
        try:
            v = int(data[key])
        except (KeyError, TypeError, ValueError):
            return default
        if lo is not None:
            v = max(lo, v)
        if hi is not None:
            v = min(hi, v)
        return v

    def _float(key, default, lo=None, hi=None):
        try:
            v = float(data[key])
        except (KeyError, TypeError, ValueError):
            return default
        if lo is not None:
            v = max(lo, v)
        if hi is not None:
            v = min(hi, v)
        return v

    def _bool(key, default=False):
        val = data.get(key, default)
        if isinstance(val, bool):
            return val
        return str(val).lower() in ("true", "1", "yes")

    def _choice(key, valid_set, default):
        v = str(data.get(key, default))
        return v if v in valid_set else default

    cfg = {
        "input_source":     _str("input_source", "0"),
        "camera_id":        _str("camera_id", "cam_00"),
        "output_dir":       _str("output_dir", "outputs/"),
        "mode":             _choice("mode", _VALID_MODES, "mode0"),
        "segment_seconds":  _int("segment_seconds", 60, lo=10, hi=3600),
        "bg_method":        _choice("bg_method", _VALID_BG, "MOG2"),
        "warmup_frames":    _int("warmup_frames", 120, lo=0, hi=9999),
        "enhance":          _bool("enhance"),
        "enhance_model":    _choice("enhance_model", _VALID_MODELS, "bicubic"),
        "enhance_scale":    _int("enhance_scale", 4, lo=2, hi=4),
        "enhance_every_n":  _int("enhance_every_n", 5, lo=1, hi=25),
        "enhance_max_roi_px": _int("enhance_max_roi_px", 200, lo=32),
        "enhance_device":   _choice("enhance_device", _VALID_DEVICES, "auto"),
        "upscale_output":   _bool("upscale_output"),
        "object_filter":    _bool("object_filter"),
        "filter_confidence":_float("filter_confidence", 0.30, lo=0.05, hi=0.95),
        "encrypt":          _bool("encrypt"),
        # Preset + per-mode codec/CRF (M3 TASK 3.1). preset is the named preset
        # key (or None for a hand-tuned config); crf None means "use the mode
        # default". background_crf drives the dual-CRF background stream.
        "preset":           (str(data.get("preset")) if str(data.get("preset", "")) in PRESETS else None),
        "codec":            _choice("codec", VALID_CODECS, "auto"),
        "crf":              _int("crf", None, lo=0, hi=63),
        "background_crf":   _int("background_crf", 45, lo=0, hi=63),
        # NOTE: credentials (encrypt_password, encrypt_key_file) are never stored
    }

    with _state_lock:
        _status["last_config"] = cfg

    log.info("Config imported: mode=%s segment=%ss enhance=%s", cfg["mode"], cfg["segment_seconds"], cfg["enhance"])
    return jsonify({"ok": True, "config": cfg})


@presets_bp.route("/api/config/export", methods=["GET"])
def api_config_export():
    """Return the last-used pipeline config as a downloadable JSON file.

    If the pipeline has not been run yet in this session, returns the
    default config values so the operator still gets a valid starting point.
    """
    with _state_lock:
        cfg = _status.get("last_config") or {}

    export = {
        "svcs_config_version": "1.0",
        "saved_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_source": str(cfg.get("input_source", "0")),
        "camera_id": cfg.get("camera_id", "cam_00"),
        "output_dir": cfg.get("output_dir", "outputs/"),
        "mode": cfg.get("mode", "mode0"),
        "segment_seconds": cfg.get("segment_seconds", 60),
        "bg_method": cfg.get("bg_method", "MOG2"),
        "warmup_frames": cfg.get("warmup_frames", 120),
        "enhance": cfg.get("enhance", False),
        "enhance_model": cfg.get("enhance_model", "bicubic"),
        "enhance_scale": cfg.get("enhance_scale", 4),
        "enhance_every_n": cfg.get("enhance_every_n", 5),
        "enhance_max_roi_px": cfg.get("enhance_max_roi_px", 200),
        "enhance_device": cfg.get("enhance_device", "auto"),
        "upscale_output": cfg.get("upscale_output", False),
        "object_filter": cfg.get("object_filter", False),
        "filter_confidence": cfg.get("filter_confidence", 0.30),
        "encrypt": cfg.get("encrypt", False),
        # Preset + per-mode codec/CRF (M3 TASK 3.1).
        "preset": cfg.get("preset"),
        "codec": cfg.get("codec", "auto"),
        "crf": cfg.get("crf"),
        "background_crf": cfg.get("background_crf", 45),
    }

    filename = f"svcs_config_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    response = current_app.response_class(
        response=json.dumps(export, indent=2),
        status=200,
        mimetype="application/json",
    )
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ── Cloud storage helpers ─────────────────────────────────────────────────────
# _detect_onedrive_root / _detect_gdrive_root / _detect_cloud_root and
# _default_output_dir now live in gui.services.cloud_detection (imported at the
# top). _CLOUD_SUBFOLDER lives in gui.state.


@presets_bp.route("/api/gdrive/detect", methods=["GET"])
def api_gdrive_detect():
    """Detect the best available local cloud sync folder (OneDrive preferred, then Google Drive).

    Returns JSON:
      { "found": true, "provider": "OneDrive - Florida Atlantic University",
        "drive_root": "C:\\Users\\k\\OneDrive - FAU",
        "output_path": "C:\\Users\\k\\OneDrive - FAU\\SVCS",
        "web_url": "https://portal.office.com/onedrive" }
      { "found": false, "hint": "..." }
    """
    root, label, web_url = _detect_cloud_root()
    if root is None:
        return jsonify({
            "found": False,
            "provider": None,
            "drive_root": None,
            "output_path": None,
            "web_url": None,
            "hint": (
                "No cloud sync folder found. "
                "Make sure OneDrive is installed and signed in - "
                "on Windows it comes pre-installed, just open it from the Start menu."
            ),
        })

    output_path = root / _CLOUD_SUBFOLDER
    return jsonify({
        "found": True,
        "provider": label,
        "drive_root": str(root),
        "output_path": str(output_path),
        "web_url": web_url,
    })


