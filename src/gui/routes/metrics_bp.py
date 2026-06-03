"""
src/gui/routes/metrics_bp.py

metrics routes blueprint, carved from gui/app.py (TASK 1.3).
Pure relocation: every URL, method, and response shape is unchanged.
Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - blueprints).
"""

import time
from flask import Blueprint, jsonify

try:
    from gui.state import (_state_lock, _status, _power_lock, _power_state, _VALID_MODES, _VALID_BG, _VALID_DEVICES, _VALID_MODELS)
    from gui.services.cpu_sampler import _PSUTIL_OK
    from utils.db import (get_connection)
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.state import (_state_lock, _status, _power_lock, _power_state, _VALID_MODES, _VALID_BG, _VALID_DEVICES, _VALID_MODELS)
    from src.gui.services.cpu_sampler import _PSUTIL_OK
    from src.utils.db import (get_connection)

metrics_bp = Blueprint("metrics", __name__)

@metrics_bp.route("/api/system_metrics")
def api_system_metrics():
    """Return live CPU/RAM/battery stats plus per-mode CPU averages."""
    with _power_lock:
        snap = dict(_power_state)
        snap["mode_avgs"] = {k: dict(v) for k, v in _power_state["mode_avgs"].items()}

    # If psutil not available, still return stub so frontend degrades gracefully
    if not _PSUTIL_OK:
        return jsonify({"available": False})

    # _bg_hw_sampler_loop keeps _power_state fresh every ~2 s at all times,
    # so no blocking cpu_percent() call is needed here.

    # Estimate battery runtime on current load (Cody's "3-hr baseline" formula):
    # remaining_hrs = battery_mins_left / 60 (real) or synthetic from charge%
    estimated_hrs = None
    if snap["battery_pct"] is not None and not snap["battery_plugged"]:
        if snap["battery_mins_left"] is not None:
            estimated_hrs = round(snap["battery_mins_left"] / 60, 2)
        else:
            # Fallback: linear estimate from a 3-hr baseline
            estimated_hrs = round((snap["battery_pct"] / 100) * 3.0, 2)

    # Storage rate (MB / hr) from current session segments
    storage_mb_hr = None
    with _state_lock:
        cfg = _status.get("config", {})
        start = _status.get("start_time")
        seg_count = _status.get("segment_count", 0)
    if start and seg_count > 0:
        elapsed_hr = (time.time() - start) / 3600
        if elapsed_hr > 0:
            # Estimate from segments table
            try:
                with get_connection() as conn:
                    output_dir = cfg.get("output_dir", "")
                    row = conn.execute(
                        "SELECT SUM(file_size_kb) FROM segments WHERE file_path LIKE ?",
                        (str(output_dir).replace("\\", "/") + "%",),
                    ).fetchone()
                    total_kb = (row[0] or 0) if row else 0
                storage_mb_hr = round((total_kb / 1024) / elapsed_hr, 2)
            except Exception:
                pass

    snap["available"]        = True
    snap["estimated_hrs"]    = estimated_hrs
    snap["storage_mb_hr"]    = storage_mb_hr
    return jsonify(snap)


@metrics_bp.route("/api/gpu_info")
def api_gpu_info():
    """Return GPU detection results for the SR enhancement device selector."""
    try:
        try:
            from enhancement.enhancer import detect_gpu  # type: ignore
        except ImportError:
            from src.enhancement.enhancer import detect_gpu  # type: ignore
        info = detect_gpu()
    except Exception as exc:
        info = {
            "available": False,
            "backend": "cpu",
            "device_name": "CPU only",
            "cuda_available": False,
            "mps_available": False,
            "will_work": False,
            "note": f"GPU detection failed: {exc}",
            "mobile_note": "",
        }
    return jsonify(info)


# ── Plate reader (post-process AI enhancement + ALPR) ────────────────────────
#
# Two routes power the in-GUI license-plate reader:
#
#   GET  /api/enhance/plates/status  - which OCR/SR backends are installed
#   POST /api/enhance/plates         - run the reader on a saved segment
#
# This is intentionally a post-process flow (matches sponsor's "AI upscaling
# for low-quality footage on offload" use case from the March 23 kickoff).
# Running heavy SR + OCR live during recording would blow the FPS budget.
#
# Author: Bloodawn (KheivenD), 2026-05-02
# ─────────────────────────────────────────────────────────────────────────────


@metrics_bp.route("/api/network_info")
def api_network_info():
    """Return the server's LAN IP so teammates can connect."""
    import socket
    lan_ip = "127.0.0.1"
    try:
        # Connect to an external address to find the default route interface
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    port = 5000
    return jsonify({
        "lan_ip": lan_ip,
        "port": port,
        "url": f"http://{lan_ip}:{port}",
        "localhost_url": f"http://localhost:{port}",
    })


# ── Config import / export ────────────────────────────────────────────────────
# _VALID_MODES / _VALID_BG / _VALID_DEVICES / _VALID_MODELS now live in
# gui.state (imported at the top).


