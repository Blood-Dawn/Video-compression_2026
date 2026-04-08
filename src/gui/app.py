"""
src/gui/app.py

Flask web dashboard for the surveillance video compression pipeline.

Serves a browser-based UI at http://localhost:5000 that lets you:
  - Configure and start / stop the pipeline with all settings
  - Watch a live terminal log stream (Server-Sent Events)
  - Monitor real-time stats: frame count, segment count, FPS, storage
  - Browse recent output segments from the SQLite metadata DB

The pipeline runs in a daemon background thread so the Flask server stays
responsive. A threading.Event is used to signal a clean stop.

Usage:
    python run_gui.py                # from project root
    python src/gui/app.py            # from project root

Author: Bloodawn (KheivenD)
"""

import json
import logging
import os
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_from_directory, abort

# ── path setup ────────────────────────────────────────────────────────────────
# Allow imports from src/ regardless of working directory
_SRC = Path(__file__).resolve().parent.parent
_ROOT = _SRC.parent
sys.path.insert(0, str(_SRC))

from pipeline.pipeline import run_pipeline  # noqa: E402
from utils.db import get_connection          # noqa: E402

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates")
app.config["SECRET_KEY"] = os.urandom(24)

# ── Shared pipeline state (protected by _state_lock) ─────────────────────────
_state_lock = threading.Lock()
_pipeline_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None

_status: dict = {
    "running": False,
    "start_time": None,
    "config": {},
    "frame_count": 0,
    "segment_count": 0,
    "error": None,
}

# ── Log capture ───────────────────────────────────────────────────────────────
_log_queue: queue.Queue = queue.Queue(maxsize=1000)
_log_history: list[str] = []   # kept in memory for late-connecting clients
_LOG_HISTORY_MAX = 300


class _QueueLogHandler(logging.Handler):
    """Forwards log records to the shared queue for SSE streaming."""

    def emit(self, record: logging.LogRecord) -> None:
        line = self.format(record)
        # also append to history (with a cap)
        _log_history.append(line)
        if len(_log_history) > _LOG_HISTORY_MAX:
            _log_history.pop(0)
        try:
            _log_queue.put_nowait(line)
        except queue.Full:
            pass  # drop oldest — client will re-fetch on reconnect


# Attach the handler once to the root logger so it captures pipeline logs too
_queue_handler = _QueueLogHandler()
_queue_handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s"))
logging.getLogger().addHandler(_queue_handler)
logging.getLogger().setLevel(logging.INFO)

log = logging.getLogger(__name__)

# ── Frame-count interceptor ───────────────────────────────────────────────────
# We wrap the FrameSource.read() method at runtime to count decoded frames
# without touching the core pipeline code.

def _patch_frame_source(src_obj):
    """Monkey-patch src.read() to increment _status['frame_count']."""
    original_read = src_obj.read

    def _counted_read():
        ret, frame = original_read()
        if ret:
            with _state_lock:
                _status["frame_count"] += 1
        return ret, frame

    src_obj.read = _counted_read
    return src_obj


# ── Segment-count interceptor ─────────────────────────────────────────────────
# We patch ROIEncoder.encode_segment() to count encoded segments without
# modifying roi_encoder.py.

def _patch_encoder(enc_obj):
    original_encode = enc_obj.encode_segment

    def _counted_encode(*args, **kwargs):
        result = original_encode(*args, **kwargs)
        with _state_lock:
            _status["segment_count"] += 1
        return result

    enc_obj.encode_segment = _counted_encode
    return enc_obj


# ── Pipeline thread runner ────────────────────────────────────────────────────

def _run_pipeline_thread(config: dict, stop_event: threading.Event) -> None:
    """Target function for the pipeline background thread."""
    with _state_lock:
        _status["running"] = True
        _status["frame_count"] = 0
        _status["segment_count"] = 0
        _status["error"] = None
        _status["start_time"] = time.time()
        _status["config"] = config

    log.info("━" * 60)
    log.info("GUI PIPELINE START")
    log.info(f"  Input:   {config.get('input_source', '0')}")
    log.info(f"  Mode:    {config.get('mode', 'mode0')}")
    log.info(f"  Output:  {config.get('output_dir', 'outputs/')}")
    log.info("━" * 60)

    _orig_fs_init = None
    _orig_re_init = None
    try:
        # Patch FrameSource and ROIEncoder lazily — import here so we can wrap.
        import utils.frame_source as _fs
        import compression.roi_encoder as _re

        _orig_fs_init = _fs.FrameSource.__init__
        _orig_re_init = _re.ROIEncoder.__init__

        def _patched_fs_init(self_inner, *a, **kw):
            _orig_fs_init(self_inner, *a, **kw)
            _patch_frame_source(self_inner)

        def _patched_re_init(self_inner, *a, **kw):
            _orig_re_init(self_inner, *a, **kw)
            _patch_encoder(self_inner)

        _fs.FrameSource.__init__ = _patched_fs_init
        _re.ROIEncoder.__init__ = _patched_re_init

        run_pipeline(
            input_source=config.get("input_source", 0),
            camera_id=config.get("camera_id", "cam_00"),
            output_dir=config.get("output_dir", str(_ROOT / "outputs")),
            segment_seconds=int(config.get("segment_seconds", 60)),
            bg_method=config.get("bg_method", "MOG2"),
            show_preview=False,
            warmup_frames=int(config.get("warmup_frames", 120)),
            mode=config.get("mode", "mode0"),
            enhance=config.get("enhance", False),
            enhance_model=config.get("enhance_model", "espcn"),
            enhance_scale=int(config.get("enhance_scale", 4)),
            encrypt=config.get("encrypt", False),
            encrypt_password=config.get("encrypt_password") or None,
            encrypt_key_file=config.get("encrypt_key_file") or None,
            stop_event=stop_event,
        )

    except Exception as exc:
        log.error(f"Pipeline error: {exc}", exc_info=True)
        with _state_lock:
            _status["error"] = str(exc)
    finally:
        # Always restore monkey patches, even if run_pipeline raised.
        try:
            import utils.frame_source as _fs
            import compression.roi_encoder as _re
            if _orig_fs_init is not None:
                _fs.FrameSource.__init__ = _orig_fs_init
            if _orig_re_init is not None:
                _re.ROIEncoder.__init__ = _orig_re_init
        except Exception:
            pass

        with _state_lock:
            _status["running"] = False
        log.info("Pipeline stopped.")


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    with _state_lock:
        snap = dict(_status)

    elapsed = None
    fps = None
    if snap["start_time"] and snap["running"]:
        elapsed = round(time.time() - snap["start_time"], 1)
        fc = snap["frame_count"]
        fps = round(fc / elapsed, 1) if elapsed > 0 else 0.0

    return jsonify({
        **snap,
        "elapsed_seconds": elapsed,
        "fps": fps,
    })


@app.route("/api/start", methods=["POST"])
def api_start():
    global _pipeline_thread, _stop_event

    with _state_lock:
        if _status["running"]:
            return jsonify({"error": "Pipeline already running"}), 409

    data = request.get_json(force=True) or {}

    # Resolve input: if digit treat as camera index, else file path
    raw_input = str(data.get("input_source", "0")).strip()
    try:
        resolved_input = int(raw_input)
    except ValueError:
        resolved_input = raw_input

    # Default output dir: <project_root>/outputs/
    output_dir = data.get("output_dir", "").strip() or str(_ROOT / "outputs")

    config = {
        "input_source": resolved_input,
        "camera_id": data.get("camera_id", "cam_00"),
        "output_dir": output_dir,
        "segment_seconds": data.get("segment_seconds", 60),
        "bg_method": data.get("bg_method", "MOG2"),
        "warmup_frames": data.get("warmup_frames", 120),
        "mode": data.get("mode", "mode0"),
        "enhance": bool(data.get("enhance", False)),
        "enhance_model": data.get("enhance_model", "espcn"),
        "enhance_scale": data.get("enhance_scale", 4),
        "encrypt": bool(data.get("encrypt", False)),
        "encrypt_password": data.get("encrypt_password", ""),
        "encrypt_key_file": data.get("encrypt_key_file", ""),
    }

    _stop_event = threading.Event()
    _pipeline_thread = threading.Thread(
        target=_run_pipeline_thread,
        args=(config, _stop_event),
        daemon=True,
        name="pipeline-worker",
    )
    _pipeline_thread.start()

    return jsonify({"ok": True, "config": config})


def _segment_absolute_path(file_path: str, output_dir: str) -> Path:
    """Resolve a segment path from DB into an absolute path."""
    p = Path(file_path)
    if not p.is_absolute():
        p = Path(output_dir) / p
    return p.resolve()


@app.route("/api/stop", methods=["POST"])
def api_stop():
    global _stop_event
    with _state_lock:
        if not _status["running"]:
            return jsonify({"error": "Pipeline not running"}), 409

    if _stop_event:
        _stop_event.set()
        log.info("Stop signal sent to pipeline.")

    return jsonify({"ok": True})


@app.route("/api/segments")
def api_segments():
    """Return the 50 most recent segments from the metadata DB."""
    # Try to find metadata.db in the last-used output_dir, or fallback
    with _state_lock:
        cfg = _status.get("config", {})
    db_path = Path(cfg.get("output_dir", str(_ROOT / "outputs"))) / "metadata.db"

    if not db_path.exists():
        return jsonify({"segments": [], "db_path": str(db_path)})

    try:
        with get_connection(str(db_path)) as conn:
            rows = conn.execute(
                """
                SELECT timestamp, camera_id, target_detected, roi_count,
                       file_size, duration, file_path
                FROM segments
                ORDER BY timestamp DESC
                LIMIT 50
                """
            ).fetchall()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    output_dir = str(cfg.get("output_dir", str(_ROOT / "outputs")))
    root_resolved = _ROOT.resolve()
    segs = []
    for r in rows:
        abs_path = _segment_absolute_path(r[6], output_dir)
        playable_url = None
        if abs_path.exists() and abs_path.suffix.lower() in {".mp4", ".webm", ".mov", ".avi"}:
            try:
                rel = abs_path.relative_to(root_resolved).as_posix()
                playable_url = f"/media/{rel}"
            except ValueError:
                # File is outside the project root; do not expose directly.
                playable_url = None

        segs.append({
            "timestamp": r[0],
            "camera_id": r[1],
            "target_detected": bool(r[2]),
            "roi_count": r[3],
            "file_size_kb": round(r[4] / 1024, 1),
            "duration_s": round(r[5], 1),
            "file_path": r[6],
            "playable_url": playable_url,
        })

    return jsonify({"segments": segs, "db_path": str(db_path)})


@app.route("/api/storage")
def api_storage():
    """Return aggregate storage stats from the metadata DB."""
    with _state_lock:
        cfg = _status.get("config", {})
    db_path = Path(cfg.get("output_dir", str(_ROOT / "outputs"))) / "metadata.db"

    if not db_path.exists():
        return jsonify({"available": False})

    try:
        with get_connection(str(db_path)) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(file_size),0),
                       COALESCE(SUM(target_detected),0),
                       COALESCE(SUM(roi_count),0),
                       COALESCE(SUM(duration),0)
                FROM segments
                """
            ).fetchone()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "available": True,
        "total_segments": row[0],
        "total_bytes": row[1],
        "total_mb": round(row[1] / 1e6, 2),
        "segments_with_targets": row[2],
        "total_roi_detections": row[3],
        "total_duration_hours": round(row[4] / 3600, 3),
        "db_path": str(db_path),
    })


@app.route("/api/logs")
def api_logs():
    """Server-Sent Events stream — delivers live log lines to the browser."""

    def generate():
        # First, replay recent history so the browser isn't blank on connect
        for line in list(_log_history[-100:]):
            yield f"data: {json.dumps(line)}\n\n"

        # Then stream new lines as they arrive
        while True:
            try:
                line = _log_queue.get(timeout=15)
                yield f"data: {json.dumps(line)}\n\n"
            except queue.Empty:
                # keepalive ping so the browser doesn't close the SSE connection
                yield ": keepalive\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable Nginx buffering if behind proxy
        },
    )


@app.route("/api/scan_videos")
def api_scan_videos():
    """Return .mp4/.avi/.mov files found in the project data/ folder."""
    data_dir = _ROOT / "data"
    videos = []
    if data_dir.exists():
        for ext in ("*.mp4", "*.avi", "*.mov", "*.mkv"):
            for f in sorted(data_dir.glob(ext)):
                videos.append(str(f))
    return jsonify({"videos": videos, "data_dir": str(data_dir)})


@app.route("/media/<path:rel_path>")
def media_file(rel_path: str):
    """
    Serve media files under the project root for in-dashboard playback.
    Path traversal is blocked by verifying resolved path remains under _ROOT.
    """
    root = _ROOT.resolve()
    abs_path = (root / rel_path).resolve()
    if root not in abs_path.parents and abs_path != root:
        abort(404)
    if not abs_path.exists() or not abs_path.is_file():
        abort(404)
    return send_from_directory(str(root), rel_path, as_attachment=False)


# ── Entry point ───────────────────────────────────────────────────────────────

def create_app() -> Flask:
    return app


if __name__ == "__main__":
    log.info(f"Project root: {_ROOT}")
    log.info("Dashboard: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
