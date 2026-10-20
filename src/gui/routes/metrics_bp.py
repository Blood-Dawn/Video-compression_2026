"""
src/gui/routes/metrics_bp.py

Host metrics for the dashboard strip: CPU/RAM/battery, GPU and network.
Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - blueprints).
"""

import socket

from flask import Blueprint, jsonify

try:
    from gui.state import _power_lock, _power_state
    from gui.services.cpu_sampler import _PSUTIL_OK
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.state import (_power_lock, _power_state)
    from src.gui.services.cpu_sampler import _PSUTIL_OK

metrics_bp = Blueprint("metrics", __name__)


@metrics_bp.route("/api/system_metrics")
def api_system_metrics():
    """Return live CPU/RAM/battery stats plus per-mode CPU averages."""
    with _power_lock:
        snap = dict(_power_state)
        snap["mode_avgs"] = {k: dict(v) for k, v in _power_state["mode_avgs"].items()}

    if not _PSUTIL_OK:
        return jsonify({"available": False})

    # The background sampler keeps _power_state fresh every ~2 s, so no
    # blocking cpu_percent() call is needed here.

    # Battery runtime: the OS estimate when there is one, else a linear
    # estimate from charge against a 3-hour baseline.
    estimated_hrs = None
    if snap["battery_pct"] is not None and not snap["battery_plugged"]:
        if snap["battery_mins_left"] is not None:
            estimated_hrs = round(snap["battery_mins_left"] / 60, 2)
        else:
            estimated_hrs = round((snap["battery_pct"] / 100) * 3.0, 2)

    snap["available"] = True
    snap["estimated_hrs"] = estimated_hrs
    # TODO: storage rate (MB/hr) needs a decision on which segment rows count
    # as "this session". The key stays in the payload for metrics.js.
    snap["storage_mb_hr"] = None
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
    except Exception as exc:  # noqa: BLE001 - torch/CUDA probing can raise anything
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


@metrics_bp.route("/api/network_info")
def api_network_info():
    """Return the server's LAN IP so teammates can connect."""
    lan_ip = "127.0.0.1"
    try:
        # A UDP connect sends nothing; it only picks the default-route
        # interface, whose address is the LAN IP.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            lan_ip = s.getsockname()[0]
    except OSError:
        pass
    port = 5000
    return jsonify({
        "lan_ip": lan_ip,
        "port": port,
        "url": f"http://{lan_ip}:{port}",
        "localhost_url": f"http://localhost:{port}",
    })
