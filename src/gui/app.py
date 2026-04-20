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

import collections
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote

from flask import Flask, Response, jsonify, render_template, request, send_from_directory, abort

# ── path setup ────────────────────────────────────────────────────────────────
# Allow imports from src/ regardless of working directory
_SRC = Path(__file__).resolve().parent.parent
_ROOT = _SRC.parent
sys.path.insert(0, str(_SRC))

try:
    from pipeline.pipeline import run_pipeline                          # noqa: E402
    from utils.db import (                                              # noqa: E402
        get_connection,
        query_by_type,
        query_daily_storage_summary,
        query_segments_by_target_count,
    )
except ModuleNotFoundError:
    from src.pipeline.pipeline import run_pipeline                      # noqa: E402
    from src.utils.db import (                                          # noqa: E402
        get_connection,
        query_by_type,
        query_daily_storage_summary,
        query_segments_by_target_count,
    )

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
_log_history: collections.deque = collections.deque(maxlen=300)  # (event_id, line)
_log_id = 0
_log_lock = threading.Lock()


class _QueueLogHandler(logging.Handler):
    """Forwards log records to the shared queue for SSE streaming.

    Each record is stamped with a monotonic event ID so SSE clients can
    resume without replaying duplicate lines after a reconnect.
    """

    def emit(self, record: logging.LogRecord) -> None:
        global _log_id
        line = self.format(record)
        with _log_lock:
            _log_id += 1
            item = (_log_id, line)
            _log_history.append(item)
        try:
            _log_queue.put_nowait(item)
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
        try:
            import utils.frame_source as _fs
            import compression.roi_encoder as _re
        except ModuleNotFoundError:
            import src.utils.frame_source as _fs
            import src.compression.roi_encoder as _re

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
            mode=config.get("mode", "mode0"),
            demo=False,          # demo metadata not needed from GUI
            show_preview=False,
            warmup_frames=int(config.get("warmup_frames", 120)),
            enhance=config.get("enhance", False),
            enhance_model=config.get("enhance_model", "bicubic"),
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
            try:
                import utils.frame_source as _fs
                import compression.roi_encoder as _re
            except ModuleNotFoundError:
                import src.utils.frame_source as _fs
                import src.compression.roi_encoder as _re
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
        "enhance_model": data.get("enhance_model", "bicubic"),
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
                       file_size, duration, file_path,
                       COALESCE(object_type, 'unknown') AS object_type
                FROM segments
                ORDER BY timestamp DESC
                LIMIT 50
                """
            ).fetchall()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    output_dir = str(cfg.get("output_dir", str(_ROOT / "outputs")))
    segs = []
    for r in rows:
        abs_path = _segment_absolute_path(r[6], output_dir)
        playable_url = None
        if abs_path.exists() and abs_path.suffix.lower() in {".mp4", ".webm", ".mov", ".avi"}:
            playable_url = f"/api/media?path={quote(str(abs_path))}"

        segs.append({
            "timestamp": r[0],
            "camera_id": r[1],
            "target_detected": bool(r[2]),
            "roi_count": r[3],
            "file_size_kb": round(r[4] / 1024, 1),
            "duration_s": round(r[5], 1),
            "file_path": r[6],
            "object_type": r[7],
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
    """Server-Sent Events stream — delivers live log lines to the browser.

    Supports Last-Event-ID resume: on reconnect the browser sends the last
    event ID it received, and the server replays only newer entries so no
    lines are lost or duplicated across dropped connections.
    """
    last_event_id_hdr = request.headers.get("Last-Event-ID", "").strip()
    try:
        initial_last_sent = int(last_event_id_hdr) if last_event_id_hdr else 0
    except ValueError:
        initial_last_sent = 0

    def generate():
        last_sent = initial_last_sent

        # Replay history entries the client hasn't seen yet.
        with _log_lock:
            backlog = [item for item in _log_history if item[0] > last_sent]
        for event_id, line in backlog:
            last_sent = event_id
            yield f"id: {event_id}\ndata: {json.dumps(line)}\n\n"

        # Stream new lines as they arrive.
        while True:
            try:
                event_id, line = _log_queue.get(timeout=15)
                if event_id <= last_sent:
                    continue   # already sent in backlog replay
                last_sent = event_id
                yield f"id: {event_id}\ndata: {json.dumps(line)}\n\n"
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


@app.route("/api/media")
def api_media():
    """Serve any local video file by absolute path (local tool only).

    Called as /api/media?path=<url-encoded-absolute-path>.
    Rejects non-video extensions and non-existent files.
    """
    path = unquote(request.args.get("path", "").strip())
    if not path:
        abort(400)
    p = Path(path).resolve()
    if not p.exists() or not p.is_file():
        abort(404)
    if p.suffix.lower() not in {".mp4", ".webm", ".mov", ".avi", ".mkv"}:
        abort(403)
    return send_from_directory(str(p.parent), p.name, as_attachment=False)


@app.route("/api/browse")
def api_browse():
    """Open a native OS file-picker dialog and return the selected path.

    Uses subprocess so the tkinter dialog runs in its own process — tkinter
    requires the OS main thread, which Flask request handlers are not on Windows.
    """
    script = (
        "import tkinter as tk; from tkinter import filedialog; "
        "root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True); "
        "path = filedialog.askopenfilename("
        "    title='Select video file',"
        "    filetypes=[('Video files', '*.mp4 *.avi *.mov *.mkv *.h264'), ('All files', '*.*')]"
        "); root.destroy(); print(path or '', end='')"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
        path = result.stdout.strip()
    except Exception as exc:
        log.warning(f"File picker failed: {exc}")
        path = ""
    return jsonify({"path": path})


# ── Archive query routes (Ashleyn's DB queries) ───────────────────────────────

def _get_db_path() -> Path:
    """Return the metadata.db path from the last-used config, or default."""
    with _state_lock:
        cfg = _status.get("config", {})
    return Path(cfg.get("output_dir", str(_ROOT / "outputs"))) / "metadata.db"


def _rows_to_segment_list(rows) -> list:
    """Convert raw DB tuples to JSON-serialisable dicts."""
    segs = []
    for r in rows:
        # schema: id, timestamp, camera_id, target_detected, roi_count,
        #         file_size, duration, file_path, object_type
        abs_path = Path(r[7]).resolve()
        playable_url = None
        if abs_path.exists() and abs_path.suffix.lower() in {".mp4", ".webm", ".mov", ".avi"}:
            playable_url = f"/api/media?path={quote(str(abs_path))}"
        segs.append({
            "id": r[0],
            "timestamp": r[1],
            "camera_id": r[2],
            "target_detected": bool(r[3]),
            "roi_count": r[4],
            "file_size_kb": round(r[5] / 1024, 1),
            "duration_s": round(r[6], 1),
            "file_path": r[7],
            "object_type": r[8] if len(r) > 8 else "unknown",
            "playable_url": playable_url,
        })
    return segs


@app.route("/api/query_segments")
def api_query_segments():
    """Filter segments by object_type (and optionally camera_id, time range).

    Query params:
        object_type  – required (e.g. 'vehicle', 'person', 'unknown')
        camera_id    – optional
        start_time   – optional ISO-style timestamp prefix
        end_time     – optional ISO-style timestamp prefix
    """
    object_type = request.args.get("object_type", "").strip()
    if not object_type:
        return jsonify({"error": "object_type is required"}), 400

    db_path = _get_db_path()
    if not db_path.exists():
        return jsonify({"segments": [], "db_path": str(db_path)})

    try:
        rows = query_by_type(
            object_type=object_type,
            camera_id=request.args.get("camera_id") or None,
            start_time=request.args.get("start_time") or None,
            end_time=request.args.get("end_time") or None,
            db_path=str(db_path),
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"segments": _rows_to_segment_list(rows), "db_path": str(db_path)})


@app.route("/api/daily_summary")
def api_daily_summary():
    """Return daily storage totals grouped by date and camera."""
    db_path = _get_db_path()
    if not db_path.exists():
        return jsonify({"rows": [], "db_path": str(db_path)})

    try:
        rows = query_daily_storage_summary(db_path=str(db_path))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    result = [
        {
            "date": r[0],
            "camera_id": r[1],
            "total_mb": round(r[2] / 1e6, 2),
            "total_hours": r[3],
        }
        for r in rows
    ]
    return jsonify({"rows": result, "db_path": str(db_path)})


@app.route("/api/busiest")
def api_busiest():
    """Return segments with the highest ROI/detection counts (busiest clips)."""
    db_path = _get_db_path()
    if not db_path.exists():
        return jsonify({"segments": [], "db_path": str(db_path)})

    try:
        limit = int(request.args.get("limit", 20))
        rows = query_segments_by_target_count(db_path=str(db_path), limit=limit)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"segments": _rows_to_segment_list(rows), "db_path": str(db_path)})


# ── Demo / comparison routes (Riley's render system) ─────────────────────────

_demo_lock = threading.Lock()
_demo_state: dict = {
    "running": False,
    "status": "idle",        # idle | running | done | error
    "modes": [],
    "progress": "",
    "result": None,          # populated on success
    "error": None,
}


def _run_demo_thread(config: dict) -> None:
    """Background thread: run multi-mode pipeline + render demo videos."""
    try:
        from demo.run_demo import run_all_demos          # noqa: E402
    except ModuleNotFoundError:
        from src.demo.run_demo import run_all_demos      # noqa: E402

    def _update(**kw):
        with _demo_lock:
            _demo_state.update(kw)

    _update(status="running", progress="Starting pipeline runs…", error=None, result=None)

    try:
        run_all_demos(
            input_path=config["input_path"],
            output_root=config["output_root"],
            camera_id=config.get("camera_id", "cam_00"),
            modes=config["modes"],
            views=config.get("views", ["standard"]),
            no_boxes=config.get("no_boxes", False),
        )
    except Exception as exc:
        log.error(f"Demo run failed: {exc}", exc_info=True)
        _update(running=False, status="error", error=str(exc))
        return

    _update(progress="Locating manifest…")

    # Find the manifest written by run_all_demos() — it picks a suffix to avoid
    # overwriting previous runs, so we glob for the newest one.
    output_root = Path(config["output_root"]).resolve()
    manifests = sorted(
        output_root.glob("demos_stitched*/manifest.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not manifests:
        _update(running=False, status="error", error="manifest.json not found after demo run")
        return

    manifest_path = manifests[0]
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as exc:
        _update(running=False, status="error", error=f"Could not read manifest: {exc}")
        return

    # Build playable URL dict: {mode: {view: url}}
    videos: dict = {}
    for mode, view_map in manifest.get("outputs", {}).items():
        videos[mode] = {}
        for view, file_path in view_map.items():
            p = Path(file_path).resolve()
            if p.exists():
                videos[mode][view] = f"/api/media?path={quote(str(p))}"
            else:
                videos[mode][view] = None

    # Split-screen is in the same stitched dir if multiple modes ran
    split_screen_url = None
    stitched_dir = Path(manifest.get("stitched_dir", ""))
    if stitched_dir.exists():
        for candidate in stitched_dir.glob("demo_splitscreen*.mp4"):
            split_screen_url = f"/api/media?path={quote(str(candidate.resolve()))}"
            break

    result = {
        "manifest_path": str(manifest_path),
        "modes": manifest.get("modes", []),
        "videos": videos,
        "split_screen": split_screen_url,
    }
    _update(running=False, status="done", progress="Complete.", result=result)
    log.info(f"Demo run complete. Manifest: {manifest_path}")


@app.route("/api/demo", methods=["POST"])
def api_demo():
    """Start a multi-mode demo run in the background.

    POST body (JSON):
        input_path   – path to source video
        output_root  – root directory for demo outputs
        camera_id    – camera identifier
        modes        – list of mode strings, e.g. ["mode0", "mode1"]
        views        – list of view strings (default ["standard"])
        no_boxes     – bool, suppress ROI box overlays (default false)
    """
    with _demo_lock:
        if _demo_state["running"]:
            return jsonify({"error": "Demo already running"}), 409

    data = request.get_json(force=True) or {}

    input_path = data.get("input_path", "").strip()
    output_root = data.get("output_root", "").strip() or str(_ROOT / "outputs")
    modes = data.get("modes", ["mode0", "mode1"])

    if not input_path:
        return jsonify({"error": "input_path is required"}), 400
    if not modes:
        return jsonify({"error": "at least one mode is required"}), 400

    config = {
        "input_path": input_path,
        "output_root": output_root,
        "camera_id": data.get("camera_id", "cam_00"),
        "modes": modes,
        "views": data.get("views", ["standard"]),
        "no_boxes": bool(data.get("no_boxes", False)),
    }

    with _demo_lock:
        _demo_state.update(running=True, modes=modes, result=None, error=None, status="queued")

    t = threading.Thread(target=_run_demo_thread, args=(config,), daemon=True, name="demo-worker")
    t.start()

    return jsonify({"ok": True, "modes": modes})


@app.route("/api/demo/status")
def api_demo_status():
    """Return the current state of the background demo run."""
    with _demo_lock:
        return jsonify(dict(_demo_state))


# ── HLS live streaming (task 4.1) ────────────────────────────────────────────
#
# Architecture:
#   Input (RTSP / webcam / file) → FFmpeg subprocess → .m3u8 + .ts chunks
#   → Flask serves /api/hls/<camera_id>/ → hls.js plays in browser
#
# The HLS transcoder runs independently of the main pipeline so you can
# preview a live stream without recording compressed segments.

_hls_lock = threading.Lock()
_hls_state: dict = {
    "running": False,
    "camera_id": None,
    "input_source": None,
    "playlist_url": None,
    "hls_dir": None,
    "error": None,
}
_hls_process: subprocess.Popen | None = None


def _hls_dir_for(camera_id: str, output_dir: str) -> Path:
    return Path(output_dir) / "hls" / camera_id


@app.route("/api/hls/start", methods=["POST"])
def api_hls_start():
    """Start an FFmpeg HLS transcoder for a given input source.

    POST body (JSON):
        input_source  – RTSP URL, webcam index (int as string), or file path
        camera_id     – identifier used in the playlist URL (default: cam_00)
        output_dir    – where to write HLS chunks (default: outputs/)

    Returns:
        {"ok": true, "playlist_url": "/api/hls/<camera_id>/playlist.m3u8"}
    """
    global _hls_process

    with _hls_lock:
        if _hls_state["running"]:
            return jsonify({"error": "HLS stream already running"}), 409

    data = request.get_json(force=True) or {}
    input_source = str(data.get("input_source", "0")).strip()
    camera_id = str(data.get("camera_id", "cam_00")).strip()
    output_dir = str(data.get("output_dir", "")).strip() or str(_ROOT / "outputs")

    hls_dir = _hls_dir_for(camera_id, output_dir)
    hls_dir.mkdir(parents=True, exist_ok=True)
    playlist = hls_dir / "playlist.m3u8"

    # FFmpeg HLS command:
    #   -preset ultrafast + -tune zerolatency → minimal encode latency
    #   -hls_time 2       → 2-second segments (target latency ~4–6s end-to-end)
    #   -hls_list_size 5  → keep 5 segments in the playlist (10 seconds of buffer)
    #   -hls_flags delete_segments+append_list → auto-delete old .ts files
    cmd = [
        "ffmpeg", "-y",
        "-i", input_source,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-an",                          # drop audio — not needed for surveillance
        "-f", "hls",
        "-hls_time", "2",
        "-hls_list_size", "5",
        "-hls_flags", "delete_segments+append_list",
        str(playlist),
    ]

    try:
        # stderr → DEVNULL so the pipe buffer never blocks FFmpeg on Windows.
        # (With stderr=PIPE and no reader the 4 KB Windows pipe buffer fills in
        # ~1-2 s of FFmpeg progress output, freezing the process before it can
        # write any .ts segments or the playlist.)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return jsonify({"error": "ffmpeg not found on PATH — install FFmpeg and retry"}), 500

    playlist_url = f"/api/hls/{camera_id}/playlist.m3u8"

    with _hls_lock:
        _hls_process = proc
        _hls_state.update(
            running=True,
            camera_id=camera_id,
            input_source=input_source,
            playlist_url=playlist_url,
            hls_dir=str(hls_dir),
            error=None,
        )

    log.info(f"HLS stream started: {input_source} → {hls_dir}/playlist.m3u8")
    return jsonify({"ok": True, "playlist_url": playlist_url})


@app.route("/api/hls/stop", methods=["POST"])
def api_hls_stop():
    """Stop the running FFmpeg HLS transcoder."""
    global _hls_process

    with _hls_lock:
        if not _hls_state["running"]:
            return jsonify({"error": "HLS stream not running"}), 409
        proc = _hls_process

    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    with _hls_lock:
        _hls_process = None
        _hls_state.update(
            running=False, camera_id=None,
            input_source=None, playlist_url=None,
        )

    log.info("HLS stream stopped.")
    return jsonify({"ok": True})


@app.route("/api/hls/status")
def api_hls_status():
    """Return current HLS stream state.

    Also detects if the FFmpeg process exited unexpectedly and updates state.
    """
    with _hls_lock:
        snap = dict(_hls_state)
        proc = _hls_process

    if snap["running"] and proc and proc.poll() is not None:
        # Process exited on its own — capture stderr for the error message
        try:
            _, stderr_bytes = proc.communicate(timeout=1)
            err_msg = (stderr_bytes or b"").decode(errors="replace").strip()
            err_msg = err_msg[-300:] if len(err_msg) > 300 else err_msg
        except Exception:
            err_msg = "FFmpeg process exited unexpectedly"
        with _hls_lock:
            _hls_state["running"] = False
            _hls_state["error"] = err_msg or "FFmpeg process exited unexpectedly"
        snap["running"] = False
        snap["error"] = _hls_state["error"]

    return jsonify(snap)


@app.route("/api/hls/<camera_id>/playlist.m3u8")
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


@app.route("/api/hls/<camera_id>/<path:ts_file>")
def api_hls_segment(camera_id: str, ts_file: str):
    """Serve individual .ts chunk files for hls.js."""
    with _hls_lock:
        hls_dir = _hls_state.get("hls_dir")
        state_cam = _hls_state.get("camera_id")

    if not hls_dir or state_cam != camera_id:
        abort(404)

    # Only serve .ts files — reject anything else
    if not ts_file.endswith(".ts"):
        abort(403)

    seg = Path(hls_dir) / Path(ts_file).name   # strip any path traversal
    if not seg.exists() or not seg.is_file():
        abort(404)

    return send_from_directory(str(Path(hls_dir)), seg.name)


# ── Entry point ───────────────────────────────────────────────────────────────

def create_app() -> Flask:
    return app


if __name__ == "__main__":
    log.info(f"Project root: {_ROOT}")
    log.info("Dashboard: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
