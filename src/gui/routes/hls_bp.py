"""
src/gui/routes/hls_bp.py

Live HLS streaming: start/stop the stream, latency stats, and serving
the playlist and .ts segments.
Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - blueprints).

Pipeline: OpenCV VideoCapture -> BackgroundSubtractor -> ROI boxes and corner
overlay drawn on each frame -> rawvideo piped to FFmpeg stdin -> .m3u8 + .ts ->
Flask serves /api/hls/<camera_id>/ -> hls.js. Frames are annotated before
encoding so the live stream shows the same green ROI boxes as the demo output.
The worker and its rebindable handles live in gui.services.hls_runner.
"""

import threading
import subprocess
import time
from pathlib import Path
from flask import Blueprint, jsonify, request, send_from_directory, abort

try:
    from gui.state import (_hls_lock, _hls_state, _hls_frame_ts_dq, _hls_segment_latencies)
    from gui.logging_setup import log
    from gui.services.cloud_detection import _default_output_dir
    from gui.services import hls_runner as _hls_runner
    from gui.services.hls_runner import _hls_dir_for, _hls_annotator_thread
    from gui.services.path_safety import is_safe_input_source, redact_input_source
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.state import (_hls_lock, _hls_state, _hls_frame_ts_dq, _hls_segment_latencies)
    from src.gui.logging_setup import log
    from src.gui.services.cloud_detection import _default_output_dir
    from src.gui.services import hls_runner as _hls_runner
    from src.gui.services.hls_runner import _hls_dir_for, _hls_annotator_thread
    from src.gui.services.path_safety import (is_safe_input_source,
                                              redact_input_source)

hls_bp = Blueprint("hls", __name__)

@hls_bp.route("/api/hls/start", methods=["POST"])
def api_hls_start():
    """Start the annotated HLS stream for a given input source.

    POST body (JSON):
        input_source  - RTSP URL, webcam index (int as string), or file path
        camera_id     - identifier used in the playlist URL (default: cam_00)
        output_dir    - where to write HLS chunks (default: outputs/)
        mode          - display label shown in the corner overlay (default: Mode 0)

    Returns:
        {"ok": true, "playlist_url": "/api/hls/<camera_id>/playlist.m3u8"}
    """
    # _hls_thread / _hls_stop_event live in hls_runner; assign through that
    # module so the forwarder, the annotator, and stop() agree.
    with _hls_lock:
        if _hls_state["running"]:
            return jsonify({"error": "HLS stream already running"}), 409

    data = request.get_json(force=True) or {}
    input_source = str(data.get("input_source", "0")).strip()
    # SEC-013: reject file:// and cloud-metadata/link-local SSRF targets.
    _ok, _why = is_safe_input_source(input_source)
    if not _ok:
        return jsonify({"error": f"input_source not allowed: {_why}"}), 400
    camera_id = str(data.get("camera_id", "cam_00")).strip()
    # HLS chunks land next to saved segments, in the chosen output folder.
    # Author: Bloodawn (KheivenD), 2026-05-02.
    output_dir = str(data.get("output_dir", "")).strip() or _default_output_dir()
    mode_label = str(data.get("mode", "Mode 0")).strip()

    hls_dir = _hls_dir_for(camera_id, output_dir)
    hls_dir.mkdir(parents=True, exist_ok=True)

    # Clear segments from any previous session so hls.js cannot serve old video.
    for _stale in list(hls_dir.glob("*.ts")) + list(hls_dir.glob("*.m3u8")):
        try:
            _stale.unlink()
        except OSError:
            pass
    log.debug("HLS: cleared stale segments from %s", hls_dir)

    # Cache-bust so a reused camera_id never gets a stale playlist.
    _session_ts = int(time.time())
    playlist_url = f"/api/hls/{camera_id}/playlist.m3u8?t={_session_ts}"

    with _hls_lock:
        _hls_state.update(
            running=True,
            camera_id=camera_id,
            input_source=input_source,
            playlist_url=playlist_url,
            hls_dir=str(hls_dir),
            error=None,
        )
        # Reset the rolling latency window so a new run starts clean.
        # Author: Bloodawn (KheivenD)
        _hls_frame_ts_dq.clear()
        _hls_segment_latencies.clear()
        _hls_state["ingest_latency_s"] = None
        _hls_state["latency_avg_s"]    = None
        _hls_state["latency_last_s"]   = None
        _hls_state["latency_samples"]  = 0
        _hls_state["stream_start_time"] = None
        # Clear the last-fetch timestamp, or the idle watchdog inherits it and
        # reaps this stream before a client connects (HLS_STARTUP_GRACE_S only
        # applies while it is None).
        # Author: Bloodawn (KheivenD), 2026-07-19 (M3).
        _hls_state["last_segment_fetch"] = None

    _hls_runner._hls_stop_event = threading.Event()
    _hls_runner._hls_thread = threading.Thread(
        target=_hls_annotator_thread,
        args=(input_source, hls_dir, mode_label, _hls_runner._hls_stop_event),
        daemon=True,
        name="hls-annotator",
    )
    _hls_runner._hls_thread.start()

    log.info("HLS annotator started: %s -> %s/playlist.m3u8", input_source, hls_dir)
    return jsonify({"ok": True, "playlist_url": playlist_url})


@hls_bp.route("/api/hls/stop", methods=["POST"])
def api_hls_stop():
    """Stop the running HLS annotator and FFmpeg encoder."""
    # Handles live in hls_runner; go through that module so the forwarder
    # stays consistent.
    with _hls_lock:
        if not _hls_state["running"]:
            return jsonify({"error": "HLS stream not running"}), 409

    if _hls_runner._hls_stop_event:
        _hls_runner._hls_stop_event.set()

    # Terminate FFmpeg directly rather than waiting for the input to end.
    with _hls_lock:
        proc = _hls_runner._hls_process
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    with _hls_lock:
        _hls_runner._hls_process = None
        _hls_state.update(
            running=False, camera_id=None,
            input_source=None, playlist_url=None,
            stream_start_time=None, ingest_latency_s=None,
        )

    log.info("HLS stream stopped.")
    return jsonify({"ok": True})


@hls_bp.route("/api/hls/status")
def api_hls_status():
    """Return current HLS stream state, with the camera password removed.

    An RTSP input_source commonly embeds the camera's credentials, and a device
    token is a weaker credential than the dashboard password. Redact on the way
    out, not at write time: the runner needs the working URL.
    """
    with _hls_lock:
        snap = dict(_hls_state)

    snap["input_source"] = redact_input_source(snap.get("input_source"))
    return jsonify(snap)


@hls_bp.route("/api/hls/latency")
def api_hls_latency():
    """Return ingest and end-to-end latency for the current HLS session.

    Two latency metrics are exposed:

    1. ``ingest_latency_s``: one-shot startup latency from FFmpeg launch to
       the first .ts segment, set once per run.

    2. ``latency_avg_s`` / ``latency_last_s`` / ``latency_samples``: rolling
       steady-state latency for sizing hardware against the real ingest to
       playable chunk delay. ``latency_avg_s`` is the median frame age across
       the last ``latency_window`` segments.

    Response fields:
        stream_start_time  - epoch timestamp when FFmpeg launched (float or null)
        ingest_latency_s   - seconds from FFmpeg launch to first .ts file (float or null)
        latency_avg_s      - rolling-avg end-to-end latency, seconds (float or null)
        latency_last_s     - latency of the most recent segment, seconds (float or null)
        latency_samples    - integer count of segments in the rolling window
        latency_window     - integer max size of the rolling window
        measuring          - true while no latency sample is available yet

    Author: Bloodawn (KheivenD)
    """
    with _hls_lock:
        start          = _hls_state.get("stream_start_time")
        ingest         = _hls_state.get("ingest_latency_s")
        latency_avg    = _hls_state.get("latency_avg_s")
        latency_last   = _hls_state.get("latency_last_s")
        latency_n      = _hls_state.get("latency_samples", 0)
        latency_window = _hls_state.get("latency_window", 20)
        running        = _hls_state.get("running", False)

    # True until any latency sample exists; the front-end keeps polling on it.
    measuring = running and (ingest is None) and (latency_avg is None)

    return jsonify({
        "stream_start_time": start,
        "ingest_latency_s":  ingest,
        "latency_avg_s":     latency_avg,
        "latency_last_s":    latency_last,
        "latency_samples":   latency_n,
        "latency_window":    latency_window,
        "measuring":         measuring,
    })


@hls_bp.route("/api/hls/<camera_id>/playlist.m3u8")
def api_hls_playlist(camera_id: str):
    """Serve the HLS playlist file for hls.js."""
    with _hls_lock:
        hls_dir = _hls_state.get("hls_dir")
        state_cam = _hls_state.get("camera_id")

    if not hls_dir or state_cam != camera_id:
        abort(404)

    playlist = Path(hls_dir) / "playlist.m3u8"
    if not playlist.exists():
        abort(404)

    resp = send_from_directory(str(Path(hls_dir)), "playlist.m3u8")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Content-Type"] = "application/vnd.apple.mpegurl"
    return resp


@hls_bp.route("/api/hls/<camera_id>/<path:ts_file>")
def api_hls_segment(camera_id: str, ts_file: str):
    """Serve individual .ts chunk files for hls.js."""
    with _hls_lock:
        hls_dir = _hls_state.get("hls_dir")
        state_cam = _hls_state.get("camera_id")

    if not hls_dir or state_cam != camera_id:
        abort(404)

    # Only serve .ts files. Reject anything else.
    if not ts_file.endswith(".ts"):
        abort(403)

    seg = Path(hls_dir) / Path(ts_file).name   # strip any path traversal
    if not seg.is_file():
        abort(404)

    # Liveness signal for hls_runner._hls_idle_watchdog, stamped on a real
    # segment hit only so 404 probes cannot keep a dead stream alive.
    with _hls_lock:
        _hls_state["last_segment_fetch"] = time.monotonic()

    # Force the MPEG-TS type: ".ts" is absent from CPython's table, so the host
    # decides (Windows: video/vnd.dlna.mpeg-tts, slim containers:
    # application/octet-stream, desktop Linux: text/vnd.trolltech.linguist) and
    # ExoPlayer fails on a wrong Content-Type.
    return send_from_directory(str(Path(hls_dir)), seg.name,
                               mimetype="video/mp2t")
