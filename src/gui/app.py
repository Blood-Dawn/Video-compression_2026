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

import atexit
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

import cv2
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
    from compression.roi_encoder import draw_corner_overlay             # noqa: E402
except ModuleNotFoundError:
    from src.pipeline.pipeline import run_pipeline                      # noqa: E402
    from src.utils.db import (                                          # noqa: E402
        get_connection,
        query_by_type,
        query_daily_storage_summary,
        query_segments_by_target_count,
    )
    from src.compression.roi_encoder import draw_corner_overlay         # noqa: E402

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates")
app.config["SECRET_KEY"] = os.urandom(24)

# ── Shared pipeline state (protected by _state_lock) ─────────────────────────
_state_lock = threading.Lock()
_pipeline_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None
_active_encoder = None   # set by _patched_re_init so stop can abort a hung FFmpeg pipe

_status: dict = {
    "running": False,
    "start_time": None,
    "config": {},
    "frame_count": 0,
    "segment_count": 0,
    "total_frames": 0,   # 0 = live/unknown, >0 = video file with known length
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


# ── Log formatter and handlers ────────────────────────────────────────────────
_LOG_FMT = logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s — %(message)s")

# Queue handler — forwards records to the SSE stream for the browser
_queue_handler = _QueueLogHandler()
_queue_handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s"))

# File handler — writes all records to outputs/svcs.log for offline debugging
_LOG_FILE = _ROOT / "outputs" / "svcs.log"
_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
_file_handler = logging.FileHandler(str(_LOG_FILE), encoding="utf-8")
_file_handler.setFormatter(_LOG_FMT)

# Console handler — mirrors to terminal
_console_handler = logging.StreamHandler(sys.stderr)
_console_handler.setFormatter(_LOG_FMT)

_root_logger = logging.getLogger()
_root_logger.addHandler(_queue_handler)
_root_logger.addHandler(_file_handler)
_root_logger.setLevel(logging.DEBUG)   # capture DEBUG level — filter per-handler below

# Only forward INFO+ to browser SSE and terminal (DEBUG goes to file only)
_queue_handler.setLevel(logging.INFO)
_console_handler.setLevel(logging.INFO)
_file_handler.setLevel(logging.DEBUG)

log = logging.getLogger(__name__)


def _write_shutdown_log():
    """Write a clean shutdown marker to the log file on process exit."""
    log.info("=" * 60)
    log.info("SVCS SERVER SHUTDOWN — %s", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
    log.info("=" * 60)
    # Flush file handler so nothing is lost if Python exits abruptly
    _file_handler.flush()


atexit.register(_write_shutdown_log)

# ── Frame-count interceptor ───────────────────────────────────────────────────
# We wrap the FrameSource.read() method at runtime to count decoded frames
# without touching the core pipeline code.

def _patch_frame_source(src_obj):
    """Monkey-patch src.read() to increment _status['frame_count'].
    Also reads total_frames from the source so the progress bar knows the denominator.
    """
    # Push total frame count into status so the progress bar has a denominator.
    # total_frames == 0 for live cameras/RTSP — progress bar shows spinner instead.
    total = getattr(src_obj, "total_frames", 0) or 0
    with _state_lock:
        _status["total_frames"] = int(total)

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
        _status["total_frames"] = 0
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
            global _active_encoder
            _orig_re_init(self_inner, *a, **kw)
            _patch_encoder(self_inner)
            _active_encoder = self_inner   # expose to stop handler

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
            enhance_every_n=int(config.get("enhance_every_n", 5)),
            enhance_max_roi_px=int(config.get("enhance_max_roi_px", 200)),
            enhance_device=config.get("enhance_device", "auto"),
            encrypt=config.get("encrypt", False),
            encrypt_password=config.get("encrypt_password") or None,
            encrypt_key_file=config.get("encrypt_key_file") or None,
            object_filter=config.get("object_filter", False),
            filter_confidence=float(config.get("filter_confidence", 0.30)),
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
        global _active_encoder
        _active_encoder = None
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
    progress_pct = None
    eta_seconds = None
    if snap["start_time"] and snap["running"]:
        elapsed = round(time.time() - snap["start_time"], 1)
        fc = snap["frame_count"]
        fps = round(fc / elapsed, 1) if elapsed > 0 else 0.0
        total = snap.get("total_frames", 0)
        if total and total > 0:
            progress_pct = round(min(fc / total * 100, 100), 1)
            remaining_frames = max(0, total - fc)
            eta_seconds = round(remaining_frames / fps, 0) if fps and fps > 0 else None

    return jsonify({
        **snap,
        "elapsed_seconds": elapsed,
        "fps": fps,
        "progress_pct": progress_pct,
        "eta_seconds": int(eta_seconds) if eta_seconds is not None else None,
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
        "enhance_every_n": int(data.get("enhance_every_n", 5)),
        "enhance_max_roi_px": int(data.get("enhance_max_roi_px", 200)),
        "enhance_device": data.get("enhance_device", "auto"),
        "encrypt": bool(data.get("encrypt", False)),
        "encrypt_password": data.get("encrypt_password", ""),
        "encrypt_key_file": data.get("encrypt_key_file", ""),
        "object_filter": bool(data.get("object_filter", False)),
        "filter_confidence": float(data.get("filter_confidence", 0.30)),
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
    global _stop_event, _active_encoder
    with _state_lock:
        if not _status["running"]:
            return jsonify({"error": "Pipeline not running"}), 409

    if _stop_event:
        _stop_event.set()
        log.info("Stop signal sent to pipeline.")

    # If the pipeline thread is blocked inside finish_segment() waiting for
    # FFmpeg to flush, abort the pipe immediately so the thread can exit.
    enc = _active_encoder
    if enc is not None:
        try:
            enc.abort_segment()
            log.info("Active FFmpeg pipe aborted.")
        except Exception:
            pass

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
                       COALESCE(object_type, 'unknown') AS object_type,
                       avg_sharpness, sharpness_label
                FROM segments
                WHERE COALESCE(hidden, 0) = 0
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
            "avg_sharpness": r[8],
            "sharpness_label": r[9],
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
    """Serve any local video file by absolute path with HTTP range support.

    Called as /api/media?path=<url-encoded-absolute-path>.
    Rejects non-video extensions and non-existent files.

    Range request support is required for browser <video> elements to seek
    and play without buffering the entire file. Flask's send_from_directory
    does not handle Range headers — this implementation does.
    """
    path = unquote(request.args.get("path", "").strip())
    if not path:
        abort(400)
    p = Path(path).resolve()
    if not p.exists() or not p.is_file():
        abort(404)
    suffix = p.suffix.lower()
    if suffix not in {".mp4", ".webm", ".mov", ".avi", ".mkv"}:
        abort(403)

    mime_map = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
    }
    mime = mime_map.get(suffix, "video/mp4")
    file_size = p.stat().st_size

    range_header = request.headers.get("Range", None)
    if range_header:
        # Parse "bytes=start-end"
        try:
            byte_range = range_header.strip().replace("bytes=", "")
            parts = byte_range.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
        except (ValueError, IndexError):
            abort(416)

        end = min(end, file_size - 1)
        if start > end or start < 0:
            abort(416)

        length = end - start + 1

        def _generate_range():
            with open(p, "rb") as f:
                f.seek(start)
                remaining = length
                chunk = 65536
                while remaining > 0:
                    data = f.read(min(chunk, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        resp = Response(
            _generate_range(),
            status=206,
            mimetype=mime,
            direct_passthrough=True,
        )
        resp.headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        resp.headers["Content-Length"] = str(length)
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    # Full file response (no Range header)
    def _generate_full():
        with open(p, "rb") as f:
            while True:
                data = f.read(65536)
                if not data:
                    break
                yield data

    resp = Response(_generate_full(), status=200, mimetype=mime, direct_passthrough=True)
    resp.headers["Content-Length"] = str(file_size)
    resp.headers["Accept-Ranges"] = "bytes"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/api/browse")
def api_browse():
    """Open a native OS file-picker dialog on the HOST machine.

    Only useful when the browser is on the same machine as the server.
    Remote users should use /api/upload instead.
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


_UPLOAD_DIR = _ROOT / "data" / "uploads"
_ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".h264", ".m4v"}


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Accept a video file upload from a remote browser.

    Saves the file into data/uploads/ on the server and returns the
    server-side path so the pipeline can use it as input_source.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file in request"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    suffix = Path(f.filename).suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        return jsonify({"error": f"File type {suffix} not allowed"}), 400

    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    # Sanitize filename — strip any path components the client might inject
    safe_name = Path(f.filename).name
    dest = _UPLOAD_DIR / safe_name
    # Avoid clobbering existing files by appending a counter
    counter = 1
    while dest.exists():
        dest = _UPLOAD_DIR / f"{Path(safe_name).stem}_{counter}{suffix}"
        counter += 1

    f.save(str(dest))
    log.info("Uploaded video saved: %s (%d bytes)", dest.name, dest.stat().st_size)
    return jsonify({"path": str(dest), "filename": dest.name})


@app.route("/api/segments/clear", methods=["POST"])
def api_segments_clear():
    """Hide all segments from the dashboard view by marking them hidden in the DB.

    Files on disk are NOT deleted. The DB rows are kept but flagged so the
    dashboard no longer shows them. Re-running the pipeline adds new rows
    which appear as normal.
    """
    with _state_lock:
        cfg = _status.get("config", {})

    output_dir = Path(cfg.get("output_dir", str(_ROOT / "outputs")))
    db_path = output_dir / "metadata.db"

    if db_path.exists():
        try:
            with get_connection(str(db_path)) as conn:
                # Add hidden column if upgrading from older DB
                cols = [c[1] for c in conn.execute("PRAGMA table_info(segments)").fetchall()]
                if "hidden" not in cols:
                    conn.execute("ALTER TABLE segments ADD COLUMN hidden INTEGER DEFAULT 0")
                conn.execute("UPDATE segments SET hidden = 1")
                conn.commit()
        except Exception as exc:
            log.warning("Could not hide segments: %s", exc)
            return jsonify({"error": str(exc)}), 500

    log.info("Segment table cleared from dashboard view (files preserved on disk)")
    return jsonify({"ok": True})


# ── Archive query routes (Ashleyn's DB queries) ───────────────────────────────

def _get_db_path() -> Path:
    """Return the metadata.db path from the last-used config, or default."""
    with _state_lock:
        cfg = _status.get("config", {})
    return Path(cfg.get("output_dir", str(_ROOT / "outputs"))) / "metadata.db"


def _get_archive_db_path() -> Path:
    """Return metadata.db from an explicit archive folder, defaulting to outputs/."""
    archive_dir = request.args.get("archive_dir", "").strip()
    if archive_dir:
        return Path(archive_dir).expanduser().resolve() / "metadata.db"
    return (_ROOT / "outputs" / "metadata.db").resolve()


def _rows_to_segment_list(rows, base_dir: Path | None = None) -> list:
    """Convert raw DB tuples to JSON-serialisable dicts."""
    segs = []
    for r in rows:
        # schema: id, timestamp, camera_id, target_detected, roi_count,
        #         file_size, duration, file_path, object_type
        abs_path = Path(r[7])
        if not abs_path.is_absolute() and base_dir is not None:
            abs_path = base_dir / abs_path
        abs_path = abs_path.resolve()
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

    db_path = _get_archive_db_path()
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

    return jsonify({"segments": _rows_to_segment_list(rows, db_path.parent), "db_path": str(db_path)})


@app.route("/api/daily_summary")
def api_daily_summary():
    """Return daily storage totals grouped by date and camera."""
    db_path = _get_archive_db_path()
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
    db_path = _get_archive_db_path()
    if not db_path.exists():
        return jsonify({"segments": [], "db_path": str(db_path)})

    try:
        limit = int(request.args.get("limit", 20))
        rows = query_segments_by_target_count(db_path=str(db_path), limit=limit)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"segments": _rows_to_segment_list(rows, db_path.parent), "db_path": str(db_path)})


# ── Demo / comparison routes (Riley's render system) ─────────────────────────

_demo_lock = threading.Lock()
_demo_state: dict = {
    "running": False,
    "status": "idle",        # idle | running | done | error
    "modes": [],
    "progress": "",
    "demo_phase": "",        # start | pipeline | render | stitch | done
    "demo_mode": "",         # current mode being processed
    "demo_step": "",         # e.g. "(1/2)"
    "result": None,          # populated on success
    "error": None,
}


def _build_demo_result_from_manifest(manifest_path: Path) -> dict:
    """Build the GUI demo result payload from a stitched demo manifest."""
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    videos: dict = {}
    for mode, view_map in manifest.get("outputs", {}).items():
        videos[mode] = {}
        for view, file_path in view_map.items():
            p = Path(file_path).resolve()
            if p.exists():
                videos[mode][view] = f"/api/media?path={quote(str(p))}"
            else:
                videos[mode][view] = None

    split_screen_url = None
    stitched_dir = Path(manifest.get("stitched_dir", ""))
    if stitched_dir.exists():
        for candidate in stitched_dir.glob("demo_splitscreen*.mp4"):
            split_screen_url = f"/api/media?path={quote(str(candidate.resolve()))}"
            break

    return {
        "manifest_path": str(manifest_path),
        "modes": manifest.get("modes", []),
        "videos": videos,
        "split_screen": split_screen_url,
        "metrics": manifest.get("metrics", {}),
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

    def _progress_cb(message: str, detail: dict):
        """Receive step updates from run_all_demos and push to demo state."""
        phase = detail.get("phase", "")
        mode = detail.get("mode", "")
        mode_index = detail.get("mode_index")
        mode_total = detail.get("mode_total")

        # Build a concise progress string for the UI
        if mode_total and mode_index is not None:
            step_label = f"({mode_index + 1}/{mode_total})"
        else:
            step_label = ""

        _update(
            progress=message,
            demo_phase=phase,
            demo_mode=mode,
            demo_step=step_label,
        )
        log.debug("Demo progress [%s]: %s", phase, message)

    _update(
        status="running",
        progress="Starting demo…",
        demo_phase="start",
        demo_mode="",
        demo_step="",
        error=None,
        result=None,
    )

    try:
        run_all_demos(
            input_path=config["input_path"],
            output_root=config["output_root"],
            camera_id=config.get("camera_id", "cam_00"),
            modes=config["modes"],
            views=config.get("views", ["standard"]),
            no_boxes=config.get("no_boxes", False),
            no_tint=config.get("no_tint", False),
            progress_callback=_progress_cb,
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

    try:
        manifest_path = manifests[0]
        result = _build_demo_result_from_manifest(manifest_path)
    except Exception as exc:
        _update(running=False, status="error", error=f"Could not read manifest: {exc}")
        return
    _update(running=False, status="done", progress="Complete.", result=result)
    log.info(f"Demo run complete. Manifest: {manifest_path}")


@app.route("/api/demo", methods=["POST"])
def api_demo():
    """Start a multi-mode demo run in the background.

    POST body (JSON):
        input_path   – path to source video
        output_root  – root directory for demo outputs
        camera_id    – camera identifier
        modes        – list of mode strings, e.g. ["mode0", "mode1", "mode2", "mode3"]
        views        – list of view strings (default ["standard"])
        no_boxes     – bool, suppress ROI box overlays (default false)
        no_tint      – bool, suppress ROI tint overlays (default false)
    """
    with _demo_lock:
        if _demo_state["running"]:
            return jsonify({"error": "Demo already running"}), 409

    data = request.get_json(force=True) or {}

    input_path = data.get("input_path", "").strip()
    output_root = data.get("output_root", "").strip() or str(_ROOT / "outputs")
    modes = data.get("modes", ["mode0", "mode1", "mode2", "mode3"])

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
        "no_tint": bool(data.get("no_tint", False)),
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


@app.route("/api/demo/latest")
def api_demo_latest():
    """Load the newest demos_stitched*/manifest.json from a demo output root."""
    output_root = request.args.get("output_root", "").strip() or str(_ROOT / "outputs")
    root = Path(output_root).expanduser().resolve()
    manifests = sorted(
        root.glob("demos_stitched*/manifest.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not manifests:
        return jsonify({"error": f"No stitched demo manifest found in {root}"}), 404
    try:
        result = _build_demo_result_from_manifest(manifests[0])
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "result": result})


# ── HLS live streaming (task 4.1) ────────────────────────────────────────────
#
# Architecture:
#   Input → OpenCV VideoCapture → BackgroundSubtractor → ROI boxes + corner
#   overlay drawn on each frame → rawvideo piped to FFmpeg stdin → .m3u8 + .ts
#   → Flask serves /api/hls/<camera_id>/ → hls.js plays in browser
#
# Frames are annotated in Python before encoding so the live stream shows
# the same green ROI bounding boxes as the demo comparison output.

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
_hls_thread: threading.Thread | None = None
_hls_stop_event: threading.Event | None = None


def _hls_dir_for(camera_id: str, output_dir: str) -> Path:
    return Path(output_dir) / "hls" / camera_id


def _draw_corner_overlay(frame, mode_label: str, elapsed_s: int) -> None:
    """Thin wrapper — delegates to the shared roi_encoder.draw_corner_overlay.

    Kept as a module-level name so the HLS annotator thread can call it
    without changes.
    """
    draw_corner_overlay(frame, mode_label, elapsed_s)


def _hls_annotator_thread(
    input_source: str,
    hls_dir: Path,
    mode_label: str,
    stop_event: threading.Event,
) -> None:
    """Background thread: annotate frames with ROI boxes then pipe to FFmpeg.

    Pipeline:
        cv2.VideoCapture  →  BackgroundSubtractor  →  green ROI rectangles
        + corner overlay  →  proc.stdin (rawvideo bgr24)  →  FFmpeg HLS muxer
    """
    import numpy as np  # noqa: F401 — needed for tobytes on numpy array

    try:
        from background_subtraction.background_subtraction import BackgroundSubtractor
    except ModuleNotFoundError:
        from src.background_subtraction.background_subtraction import BackgroundSubtractor

    # ── open input ────────────────────────────────────────────────────────────
    try:
        cap_src = int(input_source)
    except ValueError:
        cap_src = input_source

    is_rtsp = isinstance(cap_src, str) and cap_src.lower().startswith("rtsp://")
    CONNECT_TIMEOUT = 10  # seconds — Python-level timeout for VideoCapture.open()

    # cv2.VideoCapture.open() blocks until the OS-level RTSP timeout fires
    # (~30s on Windows with pip opencv-python).  CAP_PROP_OPEN_TIMEOUT_MSEC is
    # silently ignored on that build, so we enforce our own timeout by running
    # the open() call in a daemon thread and giving up after CONNECT_TIMEOUT
    # seconds.  The leaked thread will eventually exit on its own.
    _cap_holder: list = [None]
    _cap_opened: list = [False]
    _open_done = threading.Event()

    def _do_open():
        c = cv2.VideoCapture()
        # Try to set the property anyway — no-op on most builds but harmless
        c.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, CONNECT_TIMEOUT * 1000)
        c.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
        ok = c.open(cap_src)
        _cap_holder[0] = c
        _cap_opened[0] = ok
        _open_done.set()

    if is_rtsp:
        log.info(f"HLS: connecting to RTSP stream ({CONNECT_TIMEOUT}s timeout)…")
        _open_thread = threading.Thread(target=_do_open, daemon=True)
        _open_thread.start()
        if not _open_done.wait(timeout=CONNECT_TIMEOUT):
            # Timeout fired before cv2 returned — the thread is still blocked
            # in the OS network stack and we cannot kill it; it will
            # self-terminate when the 30s OS timeout fires in the background.
            err = (f"RTSP connection timed out after {CONNECT_TIMEOUT}s "
                   f"— server unreachable or stream not found: {input_source}")
            with _hls_lock:
                _hls_state["error"] = err
                _hls_state["running"] = False
            log.error(f"HLS: {err}")
            return
    else:
        _do_open()

    cap = _cap_holder[0]
    if cap is None or not _cap_opened[0] or not cap.isOpened():
        err = f"Could not open input: {input_source}"
        with _hls_lock:
            _hls_state["error"] = err
            _hls_state["running"] = False
        log.error(f"HLS: {err}")
        return

    log.info(f"HLS: connected to {input_source}")

    # ── resolve frame dimensions ──────────────────────────────────────────────
    # VideoCapture.get() returns 0x0 for RTSP streams until the first frame
    # arrives (the codec info isn't decoded yet). Read one frame to get real
    # dimensions, then seek back for files or just continue for live sources.
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    first_frame = None
    if w == 0 or h == 0:
        log.info("HLS: frame dimensions unknown from stream header — reading first frame…")
        for _ in range(30):        # try up to 30 frames (handles buffered RTSP)
            if stop_event.is_set():
                cap.release()
                with _hls_lock:
                    _hls_state["running"] = False
                return
            ret, first_frame = cap.read()
            if ret and first_frame is not None:
                h, w = first_frame.shape[:2]
                break
        else:
            cap.release()
            with _hls_lock:
                _hls_state["error"] = f"Could not determine frame size from: {input_source}"
                _hls_state["running"] = False
            log.error("HLS: failed to read first frame for dimension detection")
            return

    if fps <= 0 or fps > 120:
        fps = 25.0

    log.info(f"HLS: stream dimensions {w}x{h} @ {fps:.1f} fps")

    # ── start FFmpeg receiving rawvideo from stdin ────────────────────────────
    playlist = hls_dir / "playlist.m3u8"
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", f"{w}x{h}",
        "-r", str(fps),
        "-i", "pipe:0",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-an",
        "-f", "hls",
        "-hls_time", "2",
        "-hls_list_size", "5",
        "-hls_flags", "delete_segments",
        str(playlist),
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        cap.release()
        with _hls_lock:
            _hls_state["error"] = "ffmpeg not found on PATH"
            _hls_state["running"] = False
        return

    global _hls_process
    with _hls_lock:
        _hls_process = proc

    # ── frame loop ────────────────────────────────────────────────────────────
    subtractor = BackgroundSubtractor(var_threshold=50)
    start_time = time.time()
    WARMUP_FRAMES = 30
    frame_num = 0

    try:
        while not stop_event.is_set():
            # Use the pre-read first_frame (from RTSP dimension probe) on
            # the first iteration so we don't skip a frame.
            if first_frame is not None:
                frame = first_frame
                first_frame = None
                ret = True
            else:
                ret, frame = cap.read()
            if not ret or frame is None:
                break  # EOF or read error

            # Run background subtraction on every frame to build the model
            mask = subtractor.apply(frame)

            if frame_num >= WARMUP_FRAMES:
                regions = subtractor.get_foreground_regions(mask)

                # Draw green bounding boxes around each detected ROI
                for region in regions:
                    x1 = max(0, region.x)
                    y1 = max(0, region.y)
                    x2 = min(w, region.x + region.w)
                    y2 = min(h, region.y + region.h)
                    if x2 > x1 and y2 > y1:
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

                # Small corner overlay: mode + elapsed time
                elapsed = int(time.time() - start_time)
                _draw_corner_overlay(frame, mode_label, elapsed)

            frame_num += 1

            try:
                proc.stdin.write(frame.tobytes())
            except (BrokenPipeError, OSError):
                break

    except Exception as exc:
        log.error(f"HLS annotator error: {exc}", exc_info=True)
        with _hls_lock:
            _hls_state["error"] = str(exc)
    finally:
        cap.release()
        try:
            proc.stdin.close()
        except Exception:
            pass
        # Wait for FFmpeg to finish muxing its last segment
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
        with _hls_lock:
            _hls_state["running"] = False
        log.info("HLS annotator thread finished.")


@app.route("/api/hls/start", methods=["POST"])
def api_hls_start():
    """Start the annotated HLS stream for a given input source.

    POST body (JSON):
        input_source  – RTSP URL, webcam index (int as string), or file path
        camera_id     – identifier used in the playlist URL (default: cam_00)
        output_dir    – where to write HLS chunks (default: outputs/)
        mode          – display label shown in the corner overlay (default: Mode 0)

    Returns:
        {"ok": true, "playlist_url": "/api/hls/<camera_id>/playlist.m3u8"}
    """
    global _hls_thread, _hls_stop_event

    with _hls_lock:
        if _hls_state["running"]:
            return jsonify({"error": "HLS stream already running"}), 409

    data = request.get_json(force=True) or {}
    input_source = str(data.get("input_source", "0")).strip()
    camera_id = str(data.get("camera_id", "cam_00")).strip()
    output_dir = str(data.get("output_dir", "")).strip() or str(_ROOT / "outputs")
    mode_label = str(data.get("mode", "Mode 0")).strip()

    hls_dir = _hls_dir_for(camera_id, output_dir)
    hls_dir.mkdir(parents=True, exist_ok=True)

    # Clear stale segments from any previous session so FFmpeg starts fresh
    # and hls.js cannot accidentally serve old video from a different source.
    for _stale in list(hls_dir.glob("*.ts")) + list(hls_dir.glob("*.m3u8")):
        try:
            _stale.unlink()
        except OSError:
            pass
    log.debug("HLS: cleared stale segments from %s", hls_dir)

    # Cache-bust the playlist URL so the browser never serves a stale playlist
    # from a previous session when the camera_id is reused.
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

    _hls_stop_event = threading.Event()
    _hls_thread = threading.Thread(
        target=_hls_annotator_thread,
        args=(input_source, hls_dir, mode_label, _hls_stop_event),
        daemon=True,
        name="hls-annotator",
    )
    _hls_thread.start()

    log.info(f"HLS annotator started: {input_source} → {hls_dir}/playlist.m3u8")
    return jsonify({"ok": True, "playlist_url": playlist_url})


@app.route("/api/hls/stop", methods=["POST"])
def api_hls_stop():
    """Stop the running HLS annotator and FFmpeg encoder."""
    global _hls_process, _hls_thread, _hls_stop_event

    with _hls_lock:
        if not _hls_state["running"]:
            return jsonify({"error": "HLS stream not running"}), 409

    # Signal the annotator thread to stop reading frames
    if _hls_stop_event:
        _hls_stop_event.set()

    # Also terminate FFmpeg directly so we don't wait for the file to end
    with _hls_lock:
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
    """Return current HLS stream state."""
    with _hls_lock:
        snap = dict(_hls_state)

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


# ── Local RTSP server (optional MediaMTX integration) ────────────────────────
#
# Allows developers and demo operators to spin up a local RTSP server
# without any external dependency.  MediaMTX is downloaded on first use
# and cached in <project_root>/tools/mediamtx/.  It is MIT-licensed.
#
# Routes:
#   GET  /api/rtsp/status         – current state of the manager
#   POST /api/rtsp/download       – start background download of MediaMTX binary
#   POST /api/rtsp/start          – start the MediaMTX server process
#   POST /api/rtsp/stop           – stop server (and any active push)
#   POST /api/rtsp/push           – start FFmpeg looping a file into the server
#   POST /api/rtsp/stop_push      – stop the FFmpeg push

try:
    from utils.rtsp_server import RtspServerManager
except ModuleNotFoundError:
    from src.utils.rtsp_server import RtspServerManager

_rtsp_mgr = RtspServerManager(tools_dir=_ROOT / "tools")


@app.route("/api/rtsp/status")
def api_rtsp_status():
    """Return the current state of the local RTSP server manager."""
    return jsonify(_rtsp_mgr.get_state())


@app.route("/api/rtsp/download", methods=["POST"])
def api_rtsp_download():
    """Start downloading the MediaMTX binary in the background.

    Idempotent — safe to call again if the binary is already present
    (returns ok without re-downloading).
    """
    if _rtsp_mgr.binary_present():
        return jsonify({"ok": True, "message": "binary already present"})

    try:
        _rtsp_mgr.start_download()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409

    log.info("MediaMTX download started.")
    return jsonify({"ok": True, "message": "download started"})


@app.route("/api/rtsp/start", methods=["POST"])
def api_rtsp_start():
    """Start the local MediaMTX RTSP server."""
    try:
        _rtsp_mgr.start()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409

    state = _rtsp_mgr.get_state()
    log.info("Local RTSP server started — listening on rtsp://localhost:8554/")
    return jsonify({"ok": True, "rtsp_url": state["rtsp_url"]})


@app.route("/api/rtsp/stop", methods=["POST"])
def api_rtsp_stop():
    """Stop the local RTSP server (and any active push)."""
    _rtsp_mgr.stop()
    log.info("Local RTSP server stopped.")
    return jsonify({"ok": True})


@app.route("/api/rtsp/push", methods=["POST"])
def api_rtsp_push():
    """Start FFmpeg looping a local video file into the RTSP server.

    POST body (JSON):
        video_path   – absolute path to the video file
        stream_name  – RTSP path to publish to (default: "live")
    """
    data = request.get_json(force=True) or {}
    video_path = str(data.get("video_path", "")).strip()
    stream_name = str(data.get("stream_name", "live")).strip() or "live"

    if not video_path:
        return jsonify({"error": "video_path is required"}), 400
    if not Path(video_path).exists():
        return jsonify({"error": f"File not found: {video_path}"}), 400
    if not _rtsp_mgr.is_running():
        return jsonify({"error": "RTSP server is not running — start it first"}), 409

    try:
        _rtsp_mgr.push(video_path, stream_name)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    rtsp_url = f"rtsp://localhost:8554/{stream_name}"
    log.info(f"RTSP push started: {video_path} → {rtsp_url}")
    return jsonify({"ok": True, "rtsp_url": rtsp_url})


@app.route("/api/rtsp/stop_push", methods=["POST"])
def api_rtsp_stop_push():
    """Stop the active FFmpeg push."""
    _rtsp_mgr.stop_push()
    log.info("RTSP push stopped.")
    return jsonify({"ok": True})


# ── GPU info ─────────────────────────────────────────────────────────────────

@app.route("/api/gpu_info")
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


# ── Network / LAN info ────────────────────────────────────────────────────────

@app.route("/api/network_info")
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


# ── Entry point ───────────────────────────────────────────────────────────────

def create_app() -> Flask:
    return app


if __name__ == "__main__":
    log.info("=" * 60)
    log.info("SVCS SERVER STARTUP — %s", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
    log.info("Project root:  %s", _ROOT)
    log.info("Dashboard:     http://localhost:5000")
    log.info("Log file:      %s", _LOG_FILE)
    log.info("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
