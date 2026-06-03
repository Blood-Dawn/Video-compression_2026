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
    from utils.encryption import (                                      # noqa: E402
        decrypt_file as _decrypt_file,
        encrypt_file as _encrypt_file,
        generate_key as _generate_key,
    )
    _CRYPTO_AVAILABLE = True
except ModuleNotFoundError:
    from src.pipeline.pipeline import run_pipeline                      # noqa: E402
    from src.utils.db import (                                          # noqa: E402
        get_connection,
        query_by_type,
        query_daily_storage_summary,
        query_segments_by_target_count,
    )
    from src.compression.roi_encoder import draw_corner_overlay         # noqa: E402
    try:
        from src.utils.encryption import (                              # noqa: E402
            decrypt_file as _decrypt_file,
            encrypt_file as _encrypt_file,
            generate_key as _generate_key,
        )
        _CRYPTO_AVAILABLE = True
    except ImportError:
        _CRYPTO_AVAILABLE = False
except ImportError:
    # cryptography package not installed — encryption endpoints disabled
    _CRYPTO_AVAILABLE = False
    _decrypt_file = None
    _encrypt_file = None
    _generate_key = None

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates")

# All state files now live in the platform-standard app data directory
# instead of the repo root, so the installer works on Windows / macOS /
# Linux where Program Files / /Applications are read-only.
# Author: Bloodawn (KheivenD), 2026-05-14 (installer prep).
try:
    from utils import paths as _paths
except ModuleNotFoundError:
    from src.utils import paths as _paths

# Persist SECRET_KEY so signed cookies/sessions survive restarts.
# File is created with mode 0600 on first run.
_SK_FILE = _paths.state_file("flask_secret")
try:
    app.config["SECRET_KEY"] = _SK_FILE.read_bytes()
except FileNotFoundError:
    _sk = os.urandom(32)
    _SK_FILE.write_bytes(_sk)
    try:
        _SK_FILE.chmod(0o600)
    except Exception:
        pass
    app.config["SECRET_KEY"] = _sk

# ── Extracted state + logging (M1 refactor, TASK 1.1) ────────────────────────
# Pure-data globals now live in gui.state; logging handlers + atexit in
# gui.logging_setup. They are imported (and thereby re-exported) here so that
# existing in-module references AND the gui.app.* test contract keep working
# without churn. Importing gui.logging_setup also wires the root logger and
# registers the atexit shutdown marker (side effect, as before).
# Import direction is one-way: state <- logging_setup <- app.
# Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — state/logging split).
try:
    from gui import state as _state
    from gui.state import (
        _state_lock, _status,
        _power_lock, _power_state,
        _demo_lock, _demo_state,
        _hls_lock, _hls_state, _hls_frame_ts_dq, _hls_segment_latencies,
        _log_queue, _log_history, _log_lock,
        _VALID_MODES, _VALID_BG, _VALID_DEVICES, _VALID_MODELS,
        _CLOUD_SUBFOLDER, _SAFE_FILENAME_RE, _ALLOWED_EXTENSIONS,
    )
    from gui.logging_setup import log, _LOG_FILE
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui import state as _state
    from src.gui.state import (
        _state_lock, _status,
        _power_lock, _power_state,
        _demo_lock, _demo_state,
        _hls_lock, _hls_state, _hls_frame_ts_dq, _hls_segment_latencies,
        _log_queue, _log_history, _log_lock,
        _VALID_MODES, _VALID_BG, _VALID_DEVICES, _VALID_MODELS,
        _CLOUD_SUBFOLDER, _SAFE_FILENAME_RE, _ALLOWED_EXTENSIONS,
    )
    from src.gui.logging_setup import log, _LOG_FILE

# ── Pipeline thread runner ────────────────────────────────────────────────────
# _patch_frame_source / _patch_encoder / _run_pipeline_thread and the rebindable
# _pipeline_thread / _stop_event / _active_encoder handles now live in
# gui.services.pipeline_runner. The handles are forwarded from this module (see
# _FORWARDED_GLOBALS) so /api/start and /api/stop and the tests share one live
# value. _run_pipeline_thread is re-exported into this module's namespace (NOT
# forwarded) so tests can monkeypatch gui_module._run_pipeline_thread and the
# /api/start route's bare-name call picks up the fake.
try:
    from gui.services import pipeline_runner as _pipeline_runner
    from gui.services.pipeline_runner import _run_pipeline_thread
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services import pipeline_runner as _pipeline_runner
    from src.gui.services.pipeline_runner import _run_pipeline_thread

# ── Security helpers ──────────────────────────────────────────────────────────
# _safe_output_dir / _assert_within_output / _safe_filename now live in
# gui.services.path_safety (imported below). `import re as _re` stays — the
# route handlers still use it for camera_id / stream_name validation.
import re as _re

try:
    from gui.services.path_safety import (
        _safe_output_dir, _assert_within_output, _safe_filename,
    )
    from gui.services.cloud_detection import (
        _default_output_dir,
        _detect_onedrive_root, _detect_gdrive_root, _detect_cloud_root,
    )
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services.path_safety import (
        _safe_output_dir, _assert_within_output, _safe_filename,
    )
    from src.gui.services.cloud_detection import (
        _default_output_dir,
        _detect_onedrive_root, _detect_gdrive_root, _detect_cloud_root,
    )


# ── Power / hardware metrics ───────────────────────────────────────────────────
# The CPU/RAM/battery samplers (per-pipeline + always-on) now live in
# gui.services.cpu_sampler. The always-on sampler is no longer started at import
# time — create_app() calls start_hw_sampler() instead. _PSUTIL_OK is re-imported
# here because the /api/system_metrics route still consults it.
try:
    from gui.services.cpu_sampler import (
        _PSUTIL_OK, _start_cpu_sampler, _stop_cpu_sampler, start_hw_sampler,
    )
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services.cpu_sampler import (
        _PSUTIL_OK, _start_cpu_sampler, _stop_cpu_sampler, start_hw_sampler,
    )


# ── GUI state persistence ─────────────────────────────────────────────
# _GUI_STATE_FILE / _load_gui_state / _save_gui_state now live in
# gui.services.gui_state_persist (imported below). _load_gui_state() is still
# invoked once at module import (further down) to seed the last-known roots.
try:
    from gui.services.gui_state_persist import (
        _GUI_STATE_FILE, _load_gui_state, _save_gui_state,
    )
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services.gui_state_persist import (
        _GUI_STATE_FILE, _load_gui_state, _save_gui_state,
    )







# ── Log capture + handlers ────────────────────────────────────────────────────
# Moved to gui.logging_setup (TASK 1.1): the SSE queue handler, file/console
# handlers, root-logger wiring, _write_shutdown_log, and the atexit
# registration now live there. `log`, `_LOG_FILE`, and the live-log ring
# buffers (_log_queue / _log_history / _log_lock) are imported at the top of
# this module. The file handler and the shutdown marker stay co-located in
# logging_setup so the atexit ordering keeps landing the marker in svcs.log.

# _patch_frame_source / _patch_encoder / _run_pipeline_thread now live in
# gui.services.pipeline_runner (imported above).


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/system_metrics")
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
    # _pipeline_thread / _stop_event are owned by gui.services.pipeline_runner;
    # assign through the module so the forwarder and /api/stop see the value.
    with _state_lock:
        if _status["running"]:
            return jsonify({"error": "Pipeline already running"}), 409

    data = request.get_json(force=True) or {}

    # ── Validate camera_id (alphanumeric / dash / underscore, max 64 chars) ──
    camera_id = str(data.get("camera_id", "cam_00")).strip()
    if not _re.match(r"^[a-zA-Z0-9_\-]{1,64}$", camera_id):
        return jsonify({"error": "camera_id must be 1–64 alphanumeric/dash/underscore chars"}), 400

    # Resolve input: if digit treat as camera index, else file path
    raw_input = str(data.get("input_source", "0")).strip()
    try:
        resolved_input = int(raw_input)
    except ValueError:
        resolved_input = raw_input

    # Default output dir: prefer OneDrive/SVCS so segments land in the cloud
    # folder operators expect. Falls back to <project_root>/outputs/ only when
    # no cloud sync is detected. Was hard-coded to local — fixed 2026-05-02
    # in the audit. Author: Bloodawn (KheivenD).
    raw_out = data.get("output_dir", "").strip() or _default_output_dir()
    try:
        output_dir = str(_safe_output_dir(raw_out))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # ── Validate encrypt_key_file if provided ──────────────────────────────
    encrypt_key_file = (data.get("encrypt_key_file") or "").strip() or None
    if encrypt_key_file:
        kf = Path(encrypt_key_file).resolve()
        if not kf.exists():
            return jsonify({"error": f"encrypt_key_file not found: {kf}"}), 400
        if not kf.is_file():
            return jsonify({"error": "encrypt_key_file must be a regular file"}), 400
        encrypt_key_file = str(kf)

    config = {
        "input_source": resolved_input,
        "camera_id": camera_id,
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
        "upscale_output": bool(data.get("upscale_output", False)),
        "encrypt": bool(data.get("encrypt", False)),
        "encrypt_password": data.get("encrypt_password", ""),
        "encrypt_key_file": encrypt_key_file,
        "object_filter": bool(data.get("object_filter", False)),
        "filter_confidence": float(data.get("filter_confidence", 0.30)),
        # Codec selector (ROADMAP 4.2). Three valid values:
        #   "libsvtav1" — DEFAULT as of 2026-05-03. Netflix-grade SVT-AV1.
        #   "libaom-av1"— reference AV1, slower than SVT.
        #   "libx264"   — H.264 fallback. Always available.
        # ROIEncoder auto-falls-back to libx264 if libsvtav1 isn't in the
        # running ffmpeg build, so a fresh clone on a stock ffmpeg keeps
        # working. Author: Bloodawn (KheivenD), 2026-05-03.
        "codec": str(data.get("codec", "libsvtav1") or "libsvtav1").strip(),
        # Foreground CRF. None means "use the mode default" (18 for
        # Mode 0/1/2, 38 for Mode 3). User can override from the Save To
        # section in the sidebar. Lower = better quality, larger file.
        # Author: Bloodawn (KheivenD), 2026-05-02 (Mode 3 redo).
        "crf": (int(data.get("crf")) if str(data.get("crf", "")).strip() else None),
    }

    _pipeline_runner._stop_event = threading.Event()
    _pipeline_runner._pipeline_thread = threading.Thread(
        target=_run_pipeline_thread,
        args=(config, _pipeline_runner._stop_event),
        daemon=True,
        name="pipeline-worker",
    )
    _pipeline_runner._pipeline_thread.start()

    with _state_lock:
        _status["last_config"] = config

    return jsonify({"ok": True, "config": config})


def _segment_absolute_path(file_path: str, output_dir: str) -> Path:
    """Resolve a segment path from DB into an absolute path."""
    p = Path(file_path)
    if not p.is_absolute():
        p = Path(output_dir) / p
    return p.resolve()


@app.route("/api/stop", methods=["POST"])
def api_stop():
    # _stop_event / _active_encoder are owned by gui.services.pipeline_runner;
    # read them through the module so the forwarder stays consistent.
    with _state_lock:
        if not _status["running"]:
            return jsonify({"error": "Pipeline not running"}), 409

    if _pipeline_runner._stop_event:
        _pipeline_runner._stop_event.set()
        log.info("Stop signal sent to pipeline.")

    # If the pipeline thread is blocked inside finish_segment() waiting for
    # FFmpeg to flush, abort the pipe immediately so the thread can exit.
    enc = _pipeline_runner._active_encoder
    if enc is not None:
        try:
            enc.abort_segment()
            log.info("Active FFmpeg pipe aborted.")
        except Exception:
            pass

    return jsonify({"ok": True})


@app.route("/api/segments")
def api_segments():
    """Return the 50 most recent segments from the metadata DB.

    Query params (all optional):
      object_type   – vehicle | person | person+vehicle | animal | unknown
      color         – red | orange | yellow | green | blue | white | black | gray | ...
      scene_type    – highway | intersection | parking | street | unknown
      time_of_day   – day | night | dusk_dawn
      camera_id     – filter by camera
    """
    with _state_lock:
        cfg = _status.get("config", {})
    with _demo_lock:
        demo_last_root = _demo_state.get("last_output_root", "")

    # ── Discover metadata.db files under EVERY plausible root ────────────────
    # The main pipeline writes to <pipeline-output_dir>/metadata.db.
    # Demo runs write to <demo-output_root>/demo_<mode><suffix>/metadata.db
    # AND ./demo_comp<suffix>/metadata.db (added 2026-05-04 so split-screen
    # videos are searchable).
    # The pipeline cfg's output_dir and the demo's last output_root can
    # legitimately differ (one might point to ./outputs/, the other to
    # OneDrive/SVCS/) — the user's report was that demo recordings
    # weren't appearing in the metrics tab because we were only walking
    # the pipeline cfg root. Now we walk both, plus a hard fallback to
    # ./outputs/ for fresh clones, then de-dup by resolved path.
    # Author: Bloodawn (KheivenD), 2026-05-04 (demo-output discovery).
    candidate_roots: list[Path] = []
    for raw in (
        cfg.get("output_dir", ""),
        demo_last_root,
        str(_ROOT / "outputs"),
    ):
        if raw:
            try:
                p = Path(raw).resolve()
                if p not in candidate_roots:
                    candidate_roots.append(p)
            except Exception:
                continue

    all_dbs_set: set[Path] = set()
    for root in candidate_roots:
        if root.exists():
            for db in root.rglob("metadata.db"):
                all_dbs_set.add(db.resolve())
    all_dbs: list[Path] = sorted(all_dbs_set)

    output_root = candidate_roots[0] if candidate_roots else (_ROOT / "outputs")

    if not all_dbs:
        return jsonify({"segments": [], "db_path": str(output_root / "metadata.db"),
                        "note": "No metadata.db found — run the pipeline or a demo first.",
                        "roots_searched": [str(r) for r in candidate_roots]})

    # ── Build filter clause (same params applied to every db) ────────────────
    filters: list[str] = ["COALESCE(hidden, 0) = 0"]
    params:  list      = []

    f_type      = request.args.get("object_type", "").strip()
    f_color     = request.args.get("color", "").strip()
    f_scene     = request.args.get("scene_type", "").strip()
    f_tod       = request.args.get("time_of_day", "").strip()
    f_cam       = request.args.get("camera_id", "").strip()
    f_start     = request.args.get("start_time", "").strip()
    f_end       = request.args.get("end_time", "").strip()
    f_min_rois  = request.args.get("min_roi_count", "").strip()
    f_enc_only  = request.args.get("encrypted_only", "").strip() == "1"

    if f_type:
        filters.append("COALESCE(object_type,'unknown') = ?"); params.append(f_type)
    if f_color:
        filters.append("dominant_color = ?"); params.append(f_color)
    if f_scene:
        filters.append("COALESCE(scene_type,'unknown') = ?"); params.append(f_scene)
    if f_tod:
        filters.append("time_of_day = ?"); params.append(f_tod)
    if f_cam:
        filters.append("camera_id = ?"); params.append(f_cam)
    if f_start:
        filters.append("timestamp >= ?"); params.append(f_start)
    if f_end:
        filters.append("timestamp <= ?"); params.append(f_end)
    if f_min_rois:
        try:
            filters.append("roi_count >= ?"); params.append(int(f_min_rois))
        except ValueError:
            pass
    if f_enc_only:
        filters.append("file_path LIKE ?")
        params.append("%.enc")

    has_filters = any([f_type, f_color, f_scene, f_tod, f_cam, f_start, f_end, f_min_rois, f_enc_only])
    row_limit   = 500 if has_filters else 200

    where = " AND ".join(filters)
    query = f"""
        SELECT timestamp, camera_id, target_detected, roi_count,
               file_size, duration, file_path,
               COALESCE(object_type, 'unknown')  AS object_type,
               avg_sharpness, sharpness_label,
               COALESCE(object_classes, '[]')    AS object_classes,
               dominant_color,
               COALESCE(scene_type, 'unknown')   AS scene_type,
               time_of_day,
               COALESCE(vehicle_count, 0)        AS vehicle_count,
               COALESCE(person_count, 0)         AS person_count
        FROM segments
        WHERE {where}
        ORDER BY timestamp DESC
        LIMIT {row_limit}
    """

    # ── Query every db, merge results, re-sort ───────────────────────────────
    all_rows: list[tuple] = []
    for db_path in all_dbs:
        try:
            with get_connection(str(db_path)) as conn:
                db_dir = str(db_path.parent)
                rows = conn.execute(query, params).fetchall()
                # Tag each row with its db directory so file paths resolve correctly
                all_rows.extend((r, db_dir) for r in rows)
        except Exception:
            continue  # skip corrupt or schema-mismatched dbs

    # Global sort by timestamp desc, then cap total
    all_rows.sort(key=lambda x: x[0][0], reverse=True)
    all_rows = all_rows[:row_limit]

    # Cache cpu_stats.json reads — many segments share the same db_dir.
    # Author: Bloodawn (KheivenD), 2026-05-03 (per-clip CPU stats).
    _cpu_cache: dict[str, dict | None] = {}

    def _cpu_for_dir(d: str) -> dict | None:
        if d in _cpu_cache:
            return _cpu_cache[d]
        try:
            stats_file = Path(d) / "cpu_stats.json"
            if stats_file.exists():
                _cpu_cache[d] = json.loads(stats_file.read_text())
            else:
                _cpu_cache[d] = None
        except Exception:
            _cpu_cache[d] = None
        return _cpu_cache[d]

    segs = []
    for r, db_dir in all_rows:
        abs_path = _segment_absolute_path(r[6], db_dir)
        playable_url = None
        if abs_path.exists() and abs_path.suffix.lower() in {".mp4", ".webm", ".mov", ".avi"}:
            playable_url = f"/api/media?path={quote(str(abs_path))}"

        try:
            obj_classes = json.loads(r[10]) if r[10] else []
        except Exception:
            obj_classes = []

        cpu_stats = _cpu_for_dir(db_dir)

        segs.append({
            "timestamp":       r[0],
            "camera_id":       r[1],
            "target_detected": bool(r[2]),
            "roi_count":       r[3],
            "file_size_kb":    round(r[4] / 1024, 1),
            "duration_s":      round(r[5], 1),
            "file_path":       r[6],
            "object_type":     r[7],
            "playable_url":    playable_url,
            "avg_sharpness":   r[8],
            "sharpness_label": r[9],
            "object_classes":  obj_classes,
            "dominant_color":  r[11],
            "scene_type":      r[12],
            "time_of_day":     r[13],
            "vehicle_count":   r[14],
            "person_count":    r[15],
            # Per-clip CPU stats (None if no sampler ran for this output dir).
            "cpu_avg":         cpu_stats.get("avg") if cpu_stats else None,
            "cpu_max":         cpu_stats.get("max") if cpu_stats else None,
            "cpu_min":         cpu_stats.get("min") if cpu_stats else None,
            "cpu_samples":     cpu_stats.get("samples") if cpu_stats else None,
            "cpu_duration_s":  cpu_stats.get("duration_s") if cpu_stats else None,
        })

    return jsonify({"segments": segs, "db_count": len(all_dbs)})


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
    """Server-Sent Events stream: delivers live log lines to the browser.

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


@app.route("/api/media_debug")
def api_media_debug():
    """Diagnostic: check whether a given path would be served by /api/media."""
    path = unquote(request.args.get("path", "").strip())
    if not path:
        return jsonify({"error": "no path param"})
    p = Path(path).resolve()
    return jsonify({
        "raw_path": path,
        "resolved": str(p),
        "is_absolute": p.is_absolute(),
        "exists": p.exists(),
        "is_file": p.is_file() if p.exists() else False,
        "suffix": p.suffix.lower(),
        "allowed_suffix": p.suffix.lower() in {".mp4", ".webm", ".mov", ".avi", ".mkv"},
        "would_serve": p.is_absolute() and p.exists() and p.is_file()
                       and p.suffix.lower() in {".mp4", ".webm", ".mov", ".avi", ".mkv"},
    })


@app.route("/api/media")
def api_media():
    """Serve any local video file by absolute path with HTTP range support.

    Called as /api/media?path=<url-encoded-absolute-path>.
    Rejects non-video extensions and non-existent files.

    Range request support is required for browser <video> elements to seek
    and play without buffering the entire file. Flask's send_from_directory
    does not handle Range headers. This implementation does.
    """
    path = unquote(request.args.get("path", "").strip())
    if not path:
        abort(400)
    p = Path(path).resolve()

    # Security: reject non-absolute paths (path traversal guard).
    # We allow any absolute path to a video file that exists on disk — this
    # dashboard runs on localhost only, so the only risk would be a crafted
    # URL from the same machine, which is already trusted.
    if not p.is_absolute():
        log.warning("api_media: rejected non-absolute path: %s", p)
        abort(403)

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


_UPLOAD_DIR_LOCAL = _ROOT / "data" / "uploads"
# _ALLOWED_EXTENSIONS now lives in gui.state (imported at the top).


def _upload_dir() -> Path:
    """Return the best available upload directory.

    Prefers <cloud sync root>/SVCS/uploads/ (OneDrive or Google Drive) so
    uploaded source videos land alongside pipeline output segments in the cloud.
    Falls back to local data/uploads/ if no cloud sync is found.
    """
    root, _label, _url = _detect_cloud_root()
    if root is not None:
        d = root / _CLOUD_SUBFOLDER / "uploads"
    else:
        d = _UPLOAD_DIR_LOCAL
    d.mkdir(parents=True, exist_ok=True)
    return d


@app.route("/api/open_folder", methods=["POST"])
def api_open_folder():
    """Open a folder in the native OS file explorer on the host machine.

    Security: resolves the path and requires it to be a directory (not a file
    or a system path trick). Runs on localhost only.
    """
    import platform as _platform
    data = request.get_json(silent=True) or {}
    raw = data.get("path", "").strip()
    if not raw:
        return jsonify({"error": "No path provided"}), 400

    folder = Path(raw).resolve()

    if not folder.exists():
        return jsonify({"error": f"Path not found: {folder}"}), 404
    if not folder.is_dir():
        # If caller passed a file path, open its parent directory
        folder = folder.parent
    if not folder.is_dir():
        return jsonify({"error": "Not a directory"}), 400

    try:
        sys_name = _platform.system()
        if sys_name == "Windows":
            subprocess.Popen(["explorer", str(folder)])
        elif sys_name == "Darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception as exc:
        log.warning("api_open_folder: failed to open %s — %s", folder, exc)
        return jsonify({"error": str(exc)}), 500

    return jsonify({"ok": True, "path": str(folder)})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Accept a video file upload from a remote browser.

    Saves the file into the Google Drive SVCS/uploads/ folder when Drive is
    detected, otherwise falls back to local data/uploads/.  Returns the
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

    upload_dir = _upload_dir()
    # Sanitize filename: strip any path components the client might inject
    safe_name = Path(f.filename).name
    dest = upload_dir / safe_name
    # Avoid clobbering existing files by appending a counter
    counter = 1
    while dest.exists():
        dest = upload_dir / f"{Path(safe_name).stem}_{counter}{suffix}"
        counter += 1

    f.save(str(dest))
    log.info("Uploaded video saved: %s (%d bytes)", dest.name, dest.stat().st_size)
    return jsonify({"path": str(dest), "filename": dest.name, "in_drive": "My Drive" in str(dest) or "Google Drive" in str(dest)})


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


@app.route("/api/segments/hide_one", methods=["POST"])
def api_segments_hide_one():
    """Hide one segment row by file_path.

    The segment list doesn't carry DB row IDs across the multiple
    metadata.db files (main + per-demo), so file_path is the cheapest
    stable identifier. Walks every metadata.db under the output root,
    sets hidden=1 on any matching row, leaves the file on disk alone.

    Used by the per-row [X] button in the metrics table — the user just
    wants the entry off the dashboard, not the underlying file deleted.

    Author: Bloodawn (KheivenD), 2026-05-03 (cleanup of dead rows).
    """
    data = request.get_json(force=True) or {}
    file_path = (data.get("file_path") or "").strip()
    if not file_path:
        return jsonify({"error": "file_path is required"}), 400

    with _state_lock:
        cfg = _status.get("config", {})
    output_root = Path(cfg.get("output_dir", str(_ROOT / "outputs")))
    if not output_root.exists():
        return jsonify({"ok": True, "hidden": 0})

    hidden_count = 0
    for db_path in output_root.rglob("metadata.db"):
        try:
            with get_connection(str(db_path)) as conn:
                cols = [c[1] for c in conn.execute("PRAGMA table_info(segments)").fetchall()]
                if "hidden" not in cols:
                    conn.execute("ALTER TABLE segments ADD COLUMN hidden INTEGER DEFAULT 0")
                cur = conn.execute(
                    "UPDATE segments SET hidden = 1 WHERE file_path = ? AND COALESCE(hidden,0) = 0",
                    (file_path,),
                )
                hidden_count += cur.rowcount
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("hide_one: skipped %s — %s", db_path, exc)
            continue

    return jsonify({"ok": True, "hidden": hidden_count})


@app.route("/api/segments/cleanup_missing", methods=["POST"])
def api_segments_cleanup_missing():
    """Hide every segment whose file_path no longer exists on disk.

    A pipeline test or a stop-mid-run can leave dangling DB rows whose
    file got cleaned up before the row could be deleted. The user can
    see them in the dashboard but the play / encrypt buttons all do
    nothing. This sweeps them in one shot.

    Returns the count of rows hidden so the frontend can confirm.

    Author: Bloodawn (KheivenD), 2026-05-03 (cleanup of dead rows).
    """
    # Walk every plausible root — pipeline output_dir, last demo
    # output_root, project /outputs/ — same fan-out /api/segments uses.
    with _state_lock:
        cfg = _status.get("config", {})
    with _demo_lock:
        demo_last_root = _demo_state.get("last_output_root", "")

    candidate_roots: list[Path] = []
    for raw in (
        cfg.get("output_dir", ""),
        demo_last_root,
        str(_ROOT / "outputs"),
    ):
        if raw:
            try:
                p = Path(raw).resolve()
                if p not in candidate_roots and p.exists():
                    candidate_roots.append(p)
            except Exception:
                continue

    hidden_count = 0
    redundant_demo_count = 0
    for root in candidate_roots:
        for db_path in root.rglob("metadata.db"):
            try:
                with get_connection(str(db_path)) as conn:
                    cols = [c[1] for c in conn.execute("PRAGMA table_info(segments)").fetchall()]
                    if "hidden" not in cols:
                        conn.execute("ALTER TABLE segments ADD COLUMN hidden INTEGER DEFAULT 0")
                    rows = conn.execute(
                        "SELECT rowid, file_path FROM segments "
                        "WHERE COALESCE(hidden,0) = 0"
                    ).fetchall()
                    stale_ids = []
                    db_dir = db_path.parent
                    for rowid, fp in rows:
                        if not fp:
                            stale_ids.append(rowid)
                            continue
                        # Resolve path (relative paths are relative to the db's dir)
                        p = Path(fp)
                        if not p.is_absolute():
                            p = db_dir / p
                        if not p.exists():
                            stale_ids.append(rowid)
                    if stale_ids:
                        placeholders = ",".join("?" * len(stale_ids))
                        conn.execute(
                            f"UPDATE segments SET hidden = 1 WHERE rowid IN ({placeholders})",
                            stale_ids,
                        )
                        hidden_count += len(stale_ids)

                    # ── Redundant per-mode demo rows ─────────────────────
                    # Pre-2026-05-04 the demo runner indexed BOTH every
                    # per-mode rendered video AND the split-screen
                    # composite — five rows per demo run for what is
                    # effectively one output. Hide the per-mode rows in
                    # any demo_comp* dir that also has a *_split_M*
                    # composite row, so the table only shows the one
                    # video the user actually cares about.
                    # Author: Bloodawn (KheivenD), 2026-05-04 (demo dedup).
                    if "demo_comp" in str(db_path).lower():
                        has_split = conn.execute(
                            "SELECT 1 FROM segments "
                            "WHERE camera_id LIKE '%_split_%' "
                            "  AND COALESCE(hidden,0) = 0 LIMIT 1"
                        ).fetchone()
                        if has_split:
                            cur = conn.execute(
                                "UPDATE segments SET hidden = 1 "
                                "WHERE camera_id LIKE '%_demo_mode%' "
                                "  AND COALESCE(hidden,0) = 0"
                            )
                            redundant_demo_count += cur.rowcount
                    conn.commit()
            except Exception as exc:  # noqa: BLE001
                log.warning("cleanup_missing: skipped %s — %s", db_path, exc)
                continue

    total = hidden_count + redundant_demo_count
    if total:
        log.info("cleanup_missing: hid %d dangling + %d redundant demo rows",
                 hidden_count, redundant_demo_count)
    return jsonify({
        "ok": True,
        "hidden": total,
        "missing": hidden_count,
        "redundant_demo": redundant_demo_count,
    })


# ── Archive query routes (Ashleyn's DB queries) ───────────────────────────────
# _get_db_path / _get_archive_db_path / _rows_to_segment_list now live in
# gui.services.db_helpers (imported below).
try:
    from gui.services.db_helpers import (
        _get_db_path, _get_archive_db_path, _rows_to_segment_list,
    )
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services.db_helpers import (
        _get_db_path, _get_archive_db_path, _rows_to_segment_list,
    )


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
# _demo_lock / _demo_state now live in gui.state (imported at the top).


# Now that _demo_state exists, replay any persisted output paths from disk
# so the GUI can find the user's last pipeline + demo segments after a
# server restart. See _load_gui_state() above for details.
# Author: Bloodawn (KheivenD), 2026-05-04 (output-dir persistence).
_load_gui_state()


# _run_demo_thread now lives in gui.services.demo_runner (imported below); the
# /api/demo* routes spawn and read it.
try:
    from gui.services.demo_runner import _run_demo_thread
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services.demo_runner import _run_demo_thread


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
    output_root = data.get("output_root", "").strip()
    if not output_root:
        # Unified default — same OneDrive-preferred resolution as api_start
        # and api_hls_start. Author: Bloodawn (KheivenD), 2026-05-02 audit.
        output_root = _default_output_dir()
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

    resolved_root = str(Path(output_root).resolve())
    with _demo_lock:
        _demo_state.update(running=True, modes=modes, result=None, error=None, status="queued",
                           last_output_root=resolved_root)

    # Persist the demo output root so /api/segments can still find these
    # files after a server restart.
    _save_gui_state()

    t = threading.Thread(target=_run_demo_thread, args=(config,), daemon=True, name="demo-worker")
    t.start()

    return jsonify({"ok": True, "modes": modes})


@app.route("/api/demo/status")
def api_demo_status():
    """Return the current state of the background demo run."""
    with _demo_lock:
        return jsonify(dict(_demo_state))


@app.route("/api/demo/search_debug")
def api_demo_search_debug():
    """Diagnostic: show which roots are searched and what manifests are found."""
    with _state_lock:
        cfg = _status.get("config", {})
    with _demo_lock:
        last_demo_root = _demo_state.get("last_output_root", "")

    roots_info = []
    for label, raw in [
        ("pipeline output_dir", cfg.get("output_dir", "")),
        ("project outputs/", str(_ROOT / "outputs")),
        ("last demo root", last_demo_root),
    ]:
        if not raw:
            continue
        p = Path(raw).resolve()
        roots_info.append({"label": label, "path": str(p), "exists": p.exists()})

    try:
        od_root, od_label = _detect_onedrive_root(prefer_business=True)
        if od_root:
            svcs = (od_root / _CLOUD_SUBFOLDER).resolve()
            roots_info.append({"label": f"OneDrive SVCS ({od_label})", "path": str(svcs), "exists": svcs.exists()})
            roots_info.append({"label": f"OneDrive root ({od_label})", "path": str(od_root.resolve()), "exists": od_root.exists()})
    except Exception as e:
        roots_info.append({"label": "OneDrive detection error", "path": str(e), "exists": False})

    manifests_found = []
    for ri in roots_info:
        if not ri["exists"]:
            continue
        root = Path(ri["path"])
        for pattern in ["demo_comp*/manifest.json", "demo_comp/demos_stitched*/manifest.json"]:
            for mp in root.glob(pattern):
                manifests_found.append({
                    "root": ri["path"],
                    "manifest": str(mp),
                    "exists": mp.exists(),
                    "mtime": mp.stat().st_mtime if mp.exists() else None,
                })

    return jsonify({"roots": roots_info, "manifests": manifests_found})


@app.route("/api/demo/history")
def api_demo_history():
    """List previous demo runs by scanning for demo_comp*/manifest.json files.

    Returns a list of run objects (newest first), each with:
      ts, modes, split_screen (URL or None), videos {mode: {view: url}}, dir (folder name)
    """
    # Build a de-duplicated list of roots to search for manifests.
    # Priority: pipeline output_dir → project outputs/ → last demo run root → OneDrive SVCS
    with _state_lock:
        cfg = _status.get("config", {})
    with _demo_lock:
        last_demo_root = _demo_state.get("last_output_root", "")

    seen_roots: set[Path] = set()
    search_roots: list[Path] = []

    def _add_root(p: Path) -> None:
        rp = p.resolve()
        if rp not in seen_roots and rp.exists():
            seen_roots.add(rp)
            search_roots.append(rp)

    # 1. Pipeline-configured output dir (set when user configures the pipeline)
    if cfg.get("output_dir"):
        _add_root(Path(cfg["output_dir"]))
    # 2. Project-relative outputs/ folder (safe absolute reference via _ROOT)
    _add_root(_ROOT / "outputs")
    # 3. Last demo run's output root (captured when demo was started)
    if last_demo_root:
        _add_root(Path(last_demo_root))
    # 4. OneDrive SVCS folder
    try:
        od_root, _ = _detect_onedrive_root(prefer_business=True)
        if od_root:
            _add_root(od_root / _CLOUD_SUBFOLDER)
            # Also search OneDrive root directly (catches non-SVCS outputs)
            _add_root(od_root)
    except Exception:
        pass

    manifests: list[tuple[float, Path]] = []
    seen: set[Path] = set()
    for root in search_roots:
        # New-style: <root>/demo_comp_N/manifest.json
        for mp in root.glob("demo_comp*/manifest.json"):
            if mp not in seen:
                seen.add(mp)
                try:
                    manifests.append((mp.stat().st_mtime, mp))
                except OSError:
                    pass
        # Old-style: <root>/demo_comp/demos_stitched_N/manifest.json
        for mp in root.glob("demo_comp/demos_stitched*/manifest.json"):
            if mp not in seen:
                seen.add(mp)
                try:
                    manifests.append((mp.stat().st_mtime, mp))
                except OSError:
                    pass

    manifests.sort(key=lambda x: x[0], reverse=True)  # newest first

    runs = []
    for mtime, mp in manifests:
        try:
            with open(mp, encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            continue

        videos: dict = {}
        for mode, view_map in manifest.get("outputs", {}).items():
            videos[mode] = {}
            for view, file_path in view_map.items():
                p = Path(file_path).resolve()
                videos[mode][view] = f"/api/media?path={quote(str(p))}" if p.exists() else None

        split_screen_url = None
        sd = Path(manifest.get("stitched_dir", ""))
        if sd.exists():
            for c in sd.glob("demo_splitscreen*.mp4"):
                split_screen_url = f"/api/media?path={quote(str(c.resolve()))}"
                break

        runs.append({
            "ts":           mtime,
            "modes":        manifest.get("modes", []),
            "split_screen": split_screen_url,
            "videos":       videos,
            "dir":          mp.parent.name,
        })

    return jsonify(runs)


# ── HLS live streaming (task 4.1) ────────────────────────────────────────────
#
# Architecture:
#   Input → OpenCV VideoCapture → BackgroundSubtractor → ROI boxes + corner
#   overlay drawn on each frame → rawvideo piped to FFmpeg stdin → .m3u8 + .ts
#   → Flask serves /api/hls/<camera_id>/ → hls.js plays in browser
#
# Frames are annotated in Python before encoding so the live stream shows
# the same green ROI bounding boxes as the demo comparison output.

# _hls_lock / _hls_state and the latency deques (_hls_frame_ts_dq /
# _hls_segment_latencies) live in gui.state. The rebindable process/thread
# handles (_hls_process / _hls_thread / _hls_stop_event) and the annotator
# worker now live in gui.services.hls_runner; the handles are forwarded from
# this module (see _FORWARDED_GLOBALS) so the /api/hls/* routes and the test
# suite (which sets gui_module._hls_process = None) share one live value.
try:
    from gui.services import hls_runner as _hls_runner
    from gui.services.hls_runner import _hls_dir_for, _hls_annotator_thread
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services import hls_runner as _hls_runner
    from src.gui.services.hls_runner import _hls_dir_for, _hls_annotator_thread


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
    # _hls_thread / _hls_stop_event are owned by gui.services.hls_runner; assign
    # through the module so the forwarder, the annotator, and stop() agree.
    with _hls_lock:
        if _hls_state["running"]:
            return jsonify({"error": "HLS stream already running"}), 409

    data = request.get_json(force=True) or {}
    input_source = str(data.get("input_source", "0")).strip()
    camera_id = str(data.get("camera_id", "cam_00")).strip()
    # HLS .ts chunks should sync alongside saved segments — OneDrive when
    # available, local fallback otherwise. Was hard-coded to local in the
    # initial M3 implementation. Author: Bloodawn (KheivenD), 2026-05-02.
    output_dir = str(data.get("output_dir", "")).strip() or _default_output_dir()
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
        # Reset the rolling latency window so a new run does not inherit
        # samples from the previous camera/source. (ROADMAP 5.1)
        # Author: Bloodawn (KheivenD)
        _hls_frame_ts_dq.clear()
        _hls_segment_latencies.clear()
        _hls_state["ingest_latency_s"] = None
        _hls_state["latency_avg_s"]    = None
        _hls_state["latency_last_s"]   = None
        _hls_state["latency_samples"]  = 0
        _hls_state["stream_start_time"] = None

    _hls_runner._hls_stop_event = threading.Event()
    _hls_runner._hls_thread = threading.Thread(
        target=_hls_annotator_thread,
        args=(input_source, hls_dir, mode_label, _hls_runner._hls_stop_event),
        daemon=True,
        name="hls-annotator",
    )
    _hls_runner._hls_thread.start()

    log.info(f"HLS annotator started: {input_source} → {hls_dir}/playlist.m3u8")
    return jsonify({"ok": True, "playlist_url": playlist_url})


@app.route("/api/hls/stop", methods=["POST"])
def api_hls_stop():
    """Stop the running HLS annotator and FFmpeg encoder."""
    # The process/thread/stop-event handles are owned by hls_runner; read and
    # clear them through the module so the forwarder stays consistent.
    with _hls_lock:
        if not _hls_state["running"]:
            return jsonify({"error": "HLS stream not running"}), 409

    # Signal the annotator thread to stop reading frames
    if _hls_runner._hls_stop_event:
        _hls_runner._hls_stop_event.set()

    # Also terminate FFmpeg directly so we don't wait for the file to end
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


@app.route("/api/hls/status")
def api_hls_status():
    """Return current HLS stream state."""
    with _hls_lock:
        snap = dict(_hls_state)

    return jsonify(snap)


@app.route("/api/hls/latency")
def api_hls_latency():
    """Return ingest and end-to-end latency for the current HLS session.

    Two latency metrics are exposed:

    1. ``ingest_latency_s`` — one-shot startup latency from FFmpeg launch
       to first .ts segment. Useful as a "did the stream connect quickly?"
       check; set once at the start of a run.

    2. ``latency_avg_s`` / ``latency_last_s`` / ``latency_samples`` —
       rolling steady-state latency added 2026-05-02 (ROADMAP 5.1) so
       Cody's sponsor team can size hardware against real ingest → playable
       chunk delay. ``latency_avg_s`` is the median frame age across the
       last ``latency_window`` segments. ``measuring`` flips to false once
       the rolling watcher has at least one sample, even while the stream
       continues running.

    Response fields:
        stream_start_time  – epoch timestamp when FFmpeg launched (float or null)
        ingest_latency_s   – seconds from FFmpeg launch to first .ts file (float or null)
        latency_avg_s      – rolling-avg end-to-end latency, seconds (float or null)
        latency_last_s     – latency of the most recent segment, seconds (float or null)
        latency_samples    – integer count of segments in the rolling window
        latency_window     – integer max size of the rolling window
        measuring          – true while no latency sample is available yet

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

    # `measuring` is true only while we have neither a one-shot ingest sample
    # nor a rolling sample yet — the front-end uses it to keep polling.
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

    # Only serve .ts files. Reject anything else.
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

# _rtsp_mgr (the local MediaMTX server singleton) now lives in
# gui.services.rtsp; the /api/rtsp/* routes below drive it.
try:
    from gui.services.rtsp import _rtsp_mgr
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services.rtsp import _rtsp_mgr


@app.route("/api/rtsp/status")
def api_rtsp_status():
    """Return the current state of the local RTSP server manager."""
    return jsonify(_rtsp_mgr.get_state())


@app.route("/api/rtsp/download", methods=["POST"])
def api_rtsp_download():
    """Start downloading the MediaMTX binary in the background.

    Idempotent. Safe to call again if the binary is already present
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
    log.info("Local RTSP server started. Listening on rtsp://localhost:8554/")
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
    video_path  = str(data.get("video_path", "")).strip()
    stream_name = str(data.get("stream_name", "live")).strip() or "live"

    if not video_path:
        return jsonify({"error": "video_path is required"}), 400

    # Sanitize stream_name to alphanumeric + dash/underscore only.
    # Used directly in an RTSP URL — any shell metacharacter is a command injection risk.
    if not _re.match(r"^[a-zA-Z0-9_\-]{1,64}$", stream_name):
        return jsonify({"error": "stream_name must be 1–64 alphanumeric/dash/underscore chars"}), 400

    # Validate video_path is inside the output directory
    with _state_lock:
        cfg = _status.get("config", {})
    output_dir = Path(cfg.get("output_dir", str(_ROOT / "outputs"))).resolve()
    vp = Path(video_path).resolve()
    data_dir = (_ROOT / "data").resolve()
    allowed = [output_dir, data_dir, (_ROOT / "outputs").resolve()]
    if not any(vp == r or r in vp.parents for r in allowed):
        log.warning("api_rtsp_push: rejected video_path outside allowed roots: %s", vp)
        return jsonify({"error": "video_path must be inside the output or data directory"}), 403

    if not vp.exists():
        return jsonify({"error": f"File not found: {vp.name}"}), 400
    if not _rtsp_mgr.is_running():
        return jsonify({"error": "RTSP server is not running. Start it first"}), 409

    try:
        _rtsp_mgr.push(str(vp), stream_name)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    rtsp_url = f"rtsp://localhost:8554/{stream_name}"
    log.info("RTSP push started: %s → %s", vp.name, rtsp_url)
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


# ── Plate reader (post-process AI enhancement + ALPR) ────────────────────────
#
# Two routes power the in-GUI license-plate reader:
#
#   GET  /api/enhance/plates/status  – which OCR/SR backends are installed
#   POST /api/enhance/plates         – run the reader on a saved segment
#
# This is intentionally a post-process flow (matches sponsor's "AI upscaling
# for low-quality footage on offload" use case from the March 23 kickoff).
# Running heavy SR + OCR live during recording would blow the FPS budget.
#
# Author: Bloodawn (KheivenD), 2026-05-02
# ─────────────────────────────────────────────────────────────────────────────


def _import_plate_reader():
    """Lazy import so module loading doesn't pull torch / paddle at startup."""
    try:
        from enhancement.plate_reader import PlateReader  # type: ignore
    except ImportError:
        from src.enhancement.plate_reader import PlateReader  # type: ignore
    return PlateReader


@app.route("/api/enhance/plates/status")
def api_plate_reader_status():
    """Return install/availability info for the plate-reader UI.

    The GUI calls this on page load to decide whether to enable the
    "Read Plates" button or show a "OCR backend not installed" hint.
    """
    try:
        PlateReader = _import_plate_reader()
        reader = PlateReader()
        return jsonify(reader.status())
    except Exception as exc:  # noqa: BLE001
        log.warning("Plate reader status check failed: %s", exc)
        return jsonify({
            "ocr_backend":   "none",
            "ocr_available": False,
            "sr_backend":    "unknown",
            "sr_available":  False,
            "sr_scale":      4,
            "device_request":"auto",
            "error":         str(exc),
        })


def _import_enhancement_benchmark():
    """Lazy import the benchmark — keeps app startup light."""
    try:
        from enhancement.enhancement_benchmark import benchmark_enhancement  # type: ignore
    except ImportError:
        from src.enhancement.enhancement_benchmark import benchmark_enhancement  # type: ignore
    return benchmark_enhancement


@app.route("/api/enhance/benchmark", methods=["POST"])
def api_enhance_benchmark():
    """Compare no-SR vs full-frame-SR vs ROI-only-SR on a saved segment.

    POST body (JSON):
        file_path             – absolute path to a .mp4 segment (required)
        roi_box               – [x, y, w, h] ROI in original frame coords (required)
        sample_every_n_frames – stride between sampled frames (default 5)
        max_frames            – cap on total frames sampled (default 20)
        sr_scale              – 2 or 4 (default 4)
        run_ocr               – also report OCR confidence per variant (default false)
        ocr_backend           – "auto" | "paddleocr" | "easyocr" (default auto)
        device                – "cuda" | "mps" | "cpu" | null (auto)

    Returns the full ``BenchmarkResult`` JSON: per-variant sharpness /
    PSNR / SSIM / OCR confidence, deltas, and a plain-English verdict.

    Author: Bloodawn (KheivenD), 2026-05-02
    """
    data = request.get_json(force=True) or {}
    file_path = str(data.get("file_path", "")).strip()
    if not file_path:
        return jsonify({"error": "file_path is required"}), 400

    roi_raw = data.get("roi_box")
    if not roi_raw or not isinstance(roi_raw, list) or len(roi_raw) != 4:
        return jsonify({"error": "roi_box must be a 4-element [x, y, w, h] list"}), 400
    try:
        roi_box = tuple(int(v) for v in roi_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "roi_box values must be integers"}), 400

    src = Path(file_path)
    if not src.exists():
        return jsonify({"error": f"File not found: {file_path}"}), 404
    if src.suffix.lower() == ".enc":
        return jsonify({"error": "Decrypt the segment first; benchmark needs plaintext"}), 400

    try:
        benchmark_enhancement = _import_enhancement_benchmark()
        result = benchmark_enhancement(
            src,
            roi_box=roi_box,
            sample_every_n_frames=int(data.get("sample_every_n_frames", 5)),
            max_frames=int(data.get("max_frames", 20)),
            sr_scale=int(data.get("sr_scale", 4)),
            run_ocr=bool(data.get("run_ocr", False)),
            ocr_backend=str(data.get("ocr_backend", "auto")),
            device=data.get("device") or None,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("Enhancement benchmark failed on %s: %s", file_path, exc, exc_info=True)
        return jsonify({"error": f"Benchmark failed: {exc}"}), 500

    return jsonify(result.to_dict())


@app.route("/api/enhance/plates", methods=["POST"])
def api_plate_reader():
    """Run the plate reader on a saved segment.

    POST body (JSON):
        file_path             – absolute path to a .mp4/.avi/.mov clip (required)
        sample_every_n_frames – stride between sampled frames (default 5)
        max_frames            – cap on total frames sampled (default 60)
        roi_boxes             – optional list of [x, y, w, h] crops to focus on
        min_consensus_votes   – minimum agreeing-frame count (default 1)
        min_ocr_confidence    – per-frame OCR confidence floor (default 0.4)
        device                – "cuda" | "mps" | "cpu" | null (auto)
        ocr_backend           – "auto" | "paddleocr" | "easyocr" (default auto)

    Returns the full ``PlateReadResult`` as JSON, including a ``best_read``
    string (or null) and per-candidate ``verdict`` flags so the operator can
    see which reads are trustworthy.

    Author: Bloodawn (KheivenD)
    """
    data = request.get_json(force=True) or {}
    file_path = str(data.get("file_path", "")).strip()
    if not file_path:
        return jsonify({"error": "file_path is required"}), 400

    src = Path(file_path)
    if not src.exists():
        return jsonify({"error": f"File not found: {file_path}"}), 404
    if src.is_dir():
        return jsonify({"error": "file_path must be a video file, not a directory"}), 400
    if src.suffix.lower() == ".enc":
        return jsonify({"error": "Decrypt the segment first; this endpoint does not handle .enc files"}), 400

    try:
        sample_every  = int(data.get("sample_every_n_frames", 5))
        max_frames    = int(data.get("max_frames", 60))
        consensus_min = int(data.get("min_consensus_votes", 1))
        min_conf      = float(data.get("min_ocr_confidence", 0.40))
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"Invalid numeric parameter: {exc}"}), 400

    roi_raw = data.get("roi_boxes")
    roi_boxes = None
    if isinstance(roi_raw, list) and roi_raw:
        try:
            roi_boxes = [tuple(int(v) for v in r) for r in roi_raw]
        except (TypeError, ValueError):
            return jsonify({"error": "roi_boxes must be a list of [x, y, w, h] integers"}), 400

    device       = data.get("device") or None
    ocr_backend  = str(data.get("ocr_backend", "auto"))

    try:
        PlateReader = _import_plate_reader()
        reader = PlateReader(
            ocr_backend=ocr_backend,
            device=device,
            min_ocr_confidence=min_conf,
        )
        result = reader.read_plates_from_video(
            src,
            sample_every_n_frames=sample_every,
            max_frames=max_frames,
            roi_boxes=roi_boxes,
            min_consensus_votes=consensus_min,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("Plate reader failed on %s: %s", file_path, exc, exc_info=True)
        return jsonify({"error": f"Plate reader failed: {exc}"}), 500

    return jsonify(result.to_dict())


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


# ── Config import / export ────────────────────────────────────────────────────
# _VALID_MODES / _VALID_BG / _VALID_DEVICES / _VALID_MODELS now live in
# gui.state (imported at the top).


@app.route("/api/config/import", methods=["POST"])
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
        # NOTE: credentials (encrypt_password, encrypt_key_file) are never stored
    }

    with _state_lock:
        _status["last_config"] = cfg

    log.info("Config imported: mode=%s segment=%ss enhance=%s", cfg["mode"], cfg["segment_seconds"], cfg["enhance"])
    return jsonify({"ok": True, "config": cfg})


@app.route("/api/config/export", methods=["GET"])
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
    }

    filename = f"svcs_config_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    response = app.response_class(
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


@app.route("/api/gdrive/detect", methods=["GET"])
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
                "Make sure OneDrive is installed and signed in — "
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


@app.route("/api/keygen", methods=["POST"])
def api_keygen():
    """Generate a fresh 32-byte AES-256 key and save it as <output_dir>/camera.key.

    POST body (JSON, optional):
      { "filename": "camera.key" }   — override the output filename

    Returns:
      { "path": "C:/...outputs/camera.key", "size": 32 }
    """
    if not _CRYPTO_AVAILABLE:
        return jsonify({"error": "cryptography package not installed"}), 503

    body     = request.get_json(silent=True) or {}
    raw_name = body.get("filename") or "camera.key"

    # Sanitize filename — strip directories, allow only safe characters
    try:
        safe_name = _safe_filename(raw_name)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not safe_name.endswith(".key"):
        safe_name = safe_name + ".key"

    with _state_lock:
        cfg = _status.get("config", {})
    out_dir = Path(cfg.get("output_dir", str(_ROOT / "outputs"))).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    key_path = out_dir / safe_name

    key = _generate_key()
    key_path.write_bytes(key)
    try:
        key_path.chmod(0o600)   # read/write for owner only
    except Exception:
        pass
    log.info("Generated new AES-256 key file: %s", key_path)
    return jsonify({"path": str(key_path), "size": len(key)})


def _safe_segment_roots() -> list[Path]:
    """Return the set of directories the user is allowed to encrypt/decrypt
    files from. Any of these (or their descendants) is considered trusted.

    Includes:
      • the configured output_dir (default: <project>/outputs/)
      • the project root itself (so data/samples/, data/raw/, etc. work
        — those are the user's own clips checked into the repo)
      • the auto-detected OneDrive root when present (covers
        OneDrive/SVCS/, OneDrive/SVCS/Encrypted/, etc.)

    The original validation only allowed output_dir, which broke the
    common case of decrypting an .enc you have stored alongside your
    source clips in data/samples/. Author: Bloodawn (KheivenD),
    2026-05-03 (decrypt path fix).
    """
    roots: list[Path] = []
    try:
        with _state_lock:
            cfg = _status.get("config", {})
        out = Path(cfg.get("output_dir", str(_ROOT / "outputs"))).resolve()
        roots.append(out)
    except Exception:
        pass
    # Project root: lets data/, outputs/, and anything else under the repo
    # work without requiring the user to fiddle with output_dir first.
    try:
        roots.append(_ROOT.resolve())
    except Exception:
        pass
    # OneDrive root (covers files under OneDrive/SVCS/Encrypted/ even if
    # the configured output_dir points somewhere else).
    try:
        od_root, _ = _detect_onedrive_root(prefer_business=True)
        if od_root is not None:
            roots.append(od_root.resolve())
    except Exception:
        pass
    # De-dup while preserving order
    seen: set[str] = set()
    uniq: list[Path] = []
    for r in roots:
        s = str(r)
        if s and s not in seen:
            seen.add(s)
            uniq.append(r)
    return uniq


def _path_under_any(p: Path, roots: list[Path]) -> bool:
    """True if `p` equals or is under any of `roots` (after resolve)."""
    try:
        p_res = p.resolve()
    except OSError:
        return False
    for r in roots:
        if p_res == r:
            return True
        try:
            if r in p_res.parents:
                return True
        except Exception:
            continue
    return False


@app.route("/api/decrypt", methods=["POST"])
def api_decrypt():
    """Decrypt an .enc segment and stream the plaintext back to the browser.

    POST body (JSON):
      {
        "file_path": "/absolute/path/to/segment.mp4.enc",
        "password":  "s3cr3t",        // mutually exclusive with key_file
        "key_file":  "/path/to/camera.key"  // mutually exclusive with password
      }

    The decrypted .mp4 is written to a temp file alongside the .enc, streamed
    to the client, then deleted. The .enc file is NOT deleted.

    Returns the video file as application/octet-stream (or video/mp4) with
    Content-Disposition: attachment so the browser saves/plays it.
    """
    if not _CRYPTO_AVAILABLE:
        return jsonify({"error": "cryptography package not installed"}), 503

    body      = request.get_json(silent=True) or {}
    enc_path_raw = body.get("file_path", "").strip()
    password  = body.get("password") or None
    key_file  = body.get("key_file") or None

    if not enc_path_raw:
        return jsonify({"error": "file_path is required"}), 400
    if not password and not key_file:
        return jsonify({"error": "Either password or key_file is required"}), 400

    # ── Security: restrict file_path to one of the trusted roots ──────────────
    # Was strictly limited to output_dir, which rejected the common case of
    # decrypting a file you've stored under data/samples/ or anywhere else
    # in the repo. Now allows output_dir, project root, OR OneDrive root.
    # Author: Bloodawn (KheivenD), 2026-05-03 (decrypt path fix).
    safe_roots = _safe_segment_roots()
    enc_path = Path(enc_path_raw).resolve()
    if not _path_under_any(enc_path, safe_roots):
        log.warning("api_decrypt: rejected path outside trusted roots: %s "
                    "(roots=%s)", enc_path, [str(r) for r in safe_roots])
        return jsonify({
            "error": "file_path is outside the trusted folders. Allowed: "
                     + " | ".join(str(r) for r in safe_roots)
        }), 403

    if not enc_path.exists():
        return jsonify({"error": f"File not found: {enc_path.name}"}), 404   # name only, no full path

    if enc_path.suffix.lower() != ".enc":
        return jsonify({"error": "Only .enc files can be decrypted via this endpoint"}), 400

    # ── Security: same trust check for the key file ───────────────────────────
    raw_key = None
    if key_file:
        kf_path = Path(key_file).resolve()
        if not _path_under_any(kf_path, safe_roots):
            log.warning("api_decrypt: rejected key_file outside trusted roots: %s", kf_path)
            return jsonify({"error": "key_file is outside the trusted folders"}), 403
        try:
            with open(kf_path, "rb") as kf:
                raw_key = kf.read()
        except OSError as e:
            return jsonify({"error": f"Cannot read key file: {e}"}), 400

    # ── Save the decrypted plaintext to <enc_dir>/Decrypted/<name>.mp4 ──
    # Was previously written to a temp file, streamed back, then deleted —
    # which left the user asking "where did the file go?" since browsers
    # treat the response as a download/play but don't expose the path.
    # Now we keep a persistent copy on disk AND stream the bytes to the
    # browser, so the metrics player can play it AND the file is sitting
    # in a known folder for later use.
    # Author: Bloodawn (KheivenD), 2026-05-03 (decrypt destination fix).
    dec_dir = enc_path.parent / "Decrypted"
    try:
        dec_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return jsonify({"error": f"Could not create Decrypted/ folder: {e}"}), 500

    # Strip the trailing ".enc" — leaves e.g. "segment.mp4"
    plain_name = enc_path.name[:-4] if enc_path.name.lower().endswith(".enc") else enc_path.stem
    out_path = dec_dir / plain_name

    # If a stale copy already exists (re-decrypt), overwrite it. The user
    # always wants the freshest plaintext and the original .enc is the
    # source of truth.
    try:
        if out_path.exists():
            out_path.unlink()
    except OSError:
        pass

    try:
        out = _decrypt_file(
            enc_path,
            password=password,
            key=raw_key,
            output_path=out_path,
        )
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Decryption failed: {e}"}), 500

    # Stream the bytes back AND keep the on-disk copy. The frontend can
    # also call /api/media?path=<dec_path> later to replay without
    # re-decrypting.
    try:
        data = out.read_bytes()
    except OSError as e:
        return jsonify({"error": f"Could not read decrypted file: {e}"}), 500

    stem = enc_path.stem  # e.g.  cam_01_20260501T120000Z.mp4
    log.info("Decrypted %s → %s (%d KB)", enc_path.name, out, len(data) // 1024)
    return Response(
        data,
        mimetype="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="{stem}"',
            "Content-Length": str(len(data)),
            # Surface the on-disk path so the frontend can show "saved to"
            # without parsing the binary body.
            "X-Decrypted-Path": str(out),
        },
    )


@app.route("/api/encrypt", methods=["POST"])
def api_encrypt():
    """Encrypt a plaintext segment to a SIBLING ``Encrypted/`` folder.

    POST body (JSON):
      {
        "file_path": "/absolute/path/to/segment.mp4",
        "password":  "s3cr3t",              // mutually exclusive with key_file
        "key_file":  "/path/to/camera.key"  // mutually exclusive with password
      }

    Behavior change 2026-05-03 (Bloodawn / KheivenD): the original .mp4
    is now PRESERVED. Previously the segment was encrypted in-place and
    the original was deleted, which meant a typo in the password
    permanently lost the recording. Now we:

      1. Create ``<src_dir>/Encrypted/``  (mkdir -p)
      2. Encrypt to ``<src_dir>/Encrypted/<segment>.mp4.enc``
      3. Leave the original .mp4 untouched
      4. Add a NEW DB row pointing at the .enc (so the metrics table
         shows both the unencrypted clip and its locked copy) instead
         of replacing the original row

    Returns:
      { "enc_path": "...", "size_kb": <int>, "original_kept": True }
    """
    if not _CRYPTO_AVAILABLE:
        return jsonify({"error": "cryptography package not installed. "
                                  "Run: uv sync   (or: pip install cryptography)"}), 503

    body         = request.get_json(silent=True) or {}
    raw_path     = body.get("file_path", "").strip()
    password     = body.get("password") or None
    key_file     = body.get("key_file") or None

    if not raw_path:
        return jsonify({"error": "file_path is required"}), 400
    if not password and not key_file:
        return jsonify({"error": "Either password or key_file is required"}), 400

    src_path = Path(raw_path).resolve()

    # Same trust check the decrypt route uses — only allow encrypting
    # files inside the trusted roots so a misclick can't read arbitrary
    # files off disk.
    safe_roots = _safe_segment_roots()
    if not _path_under_any(src_path, safe_roots):
        log.warning("api_encrypt: rejected path outside trusted roots: %s", src_path)
        return jsonify({
            "error": "file_path is outside the trusted folders. Allowed: "
                     + " | ".join(str(r) for r in safe_roots)
        }), 403

    if not src_path.exists():
        return jsonify({"error": f"File not found: {src_path.name}"}), 404

    if src_path.suffix.lower() == ".enc":
        return jsonify({"error": "File is already encrypted (.enc)"}), 400

    # ── Load key file if provided ─────────────────────────────────────────────
    raw_key = None
    if key_file:
        kf_path = Path(key_file).resolve()
        try:
            raw_key = kf_path.read_bytes()
        except OSError as e:
            return jsonify({"error": f"Cannot read key file: {e}"}), 400

    # ── Pick the destination folder (NEW: don't overwrite source) ─────────────
    # Default: a sibling "Encrypted/" folder next to the source clip.
    # If OneDrive is detected, prefer OneDrive/SVCS/Encrypted/ so the
    # locked copy syncs to the cloud automatically — but ONLY when the
    # source is already somewhere in OneDrive (we don't want to silently
    # leak a file from data/samples/ into OneDrive).
    enc_subdir = src_path.parent / "Encrypted"
    try:
        od_root, _ = _detect_onedrive_root(prefer_business=True)
        if od_root is not None and od_root in src_path.parents:
            enc_subdir = od_root / "SVCS" / "Encrypted"
    except Exception:
        pass

    try:
        enc_subdir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return jsonify({"error": f"Could not create Encrypted/ folder: {e}"}), 500

    target_enc = enc_subdir / (src_path.name + ".enc")

    # ── Encrypt to the target path, KEEPING the original ─────────────────────
    try:
        enc_path = _encrypt_file(
            src_path,
            password=password,
            key=raw_key,
            delete_original=False,    # ← KEEP the source mp4
            output_path=target_enc,   # ← write to the Encrypted/ folder
        )
    except TypeError:
        # Older _encrypt_file signature without output_path. Fall back to
        # in-place encrypt + move-and-restore-original.
        log.warning("api_encrypt: _encrypt_file lacks output_path; using fallback")
        try:
            tmp_enc = _encrypt_file(
                src_path,
                password=password,
                key=raw_key,
                delete_original=False,
            )
            # Move into Encrypted/ (it landed next to src by default)
            enc_path = Path(tmp_enc).rename(target_enc)
        except (ValueError, FileNotFoundError) as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:  # noqa: BLE001
            return jsonify({"error": f"Encryption failed: {e}"}), 500
    except (ValueError, FileNotFoundError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Encryption failed: {e}"}), 500

    # ── DB: ADD a new row for the .enc copy instead of replacing the original.
    # The metrics table will show both rows so the user can see "this
    # recording has been locked" without losing the unlocked entry.
    try:
        db_path = _get_db_path()
        with get_connection(str(db_path)) as conn:
            # Check the original row exists so we can clone its metadata
            row = conn.execute(
                "SELECT timestamp, camera_id, target_detected, roi_count, "
                "       file_size, duration, object_type, "
                "       COALESCE(avg_sharpness, 0), sharpness_label, "
                "       COALESCE(object_classes, '[]'), dominant_color, "
                "       COALESCE(scene_type, 'unknown'), time_of_day, "
                "       COALESCE(vehicle_count, 0), COALESCE(person_count, 0) "
                "FROM segments WHERE file_path = ?",
                (str(src_path),),
            ).fetchone()
            enc_size = enc_path.stat().st_size
            if row:
                conn.execute(
                    "INSERT INTO segments (timestamp, camera_id, target_detected, "
                    "  roi_count, file_size, duration, file_path, object_type, "
                    "  avg_sharpness, sharpness_label, object_classes, "
                    "  dominant_color, scene_type, time_of_day, "
                    "  vehicle_count, person_count) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (row[0], row[1], row[2], row[3], enc_size, row[5],
                     str(enc_path), row[6], row[7], row[8], row[9],
                     row[10], row[11], row[12], row[13], row[14]),
                )
            else:
                # No prior row (file was outside the pipeline). Insert a
                # minimal row so the .enc still shows up in the dashboard.
                conn.execute(
                    "INSERT INTO segments (timestamp, camera_id, target_detected, "
                    "  roi_count, file_size, duration, file_path, object_type) "
                    "VALUES (datetime('now'), ?, 0, 0, ?, 0, ?, 'unknown')",
                    (src_path.stem, enc_size, str(enc_path)),
                )
            conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("api_encrypt: DB update failed: %s", e)
        # Don't fail the request — file was encrypted successfully

    size_kb = int(enc_path.stat().st_size / 1024)
    log.info("Encrypted segment: %s → %s (%d KB)  [original kept]",
             src_path.name, enc_path, size_kb)
    return jsonify({
        "enc_path": str(enc_path),
        "size_kb": size_kb,
        "original_kept": True,
        "original_path": str(src_path),
    })


# ── Rebound-global forwarding (REFACTOR-PLAN §5) ─────────────────────────────
# Most state names are mutable containers re-exported from gui.state as the
# SAME object, so `gui.app.<name>` and `gui.state.<name>` are identical and
# in-place mutation round-trips for free. A few names are *rebound* (reassigned,
# not mutated in place) inside the owning submodule — e.g. the SSE log handler
# does `state._log_id += 1`. A plain re-import would bind a stale copy here, and
# the gui.app.* test contract reaches into these names for both reads AND
# writes. We swap this module's class so those specific names are forwarded to
# their owning module in both directions. The map below covers every rebound
# name now owned by an extracted submodule (gui.state / hls_runner /
# pipeline_runner); add to it whenever a future move relocates a rebound global.
# Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — rebound forwarding).
import types as _types

# name -> owning module object. Forwarded names must NOT be bound in this
# module's __dict__, or normal attribute lookup would shadow __getattr__.
_FORWARDED_GLOBALS: dict = {
    "_log_id": _state,                       # gui.state; rebound by the SSE log handler
    "_hls_process": _hls_runner,             # gui.services.hls_runner; rebound by start/stop + annotator
    "_hls_thread": _hls_runner,
    "_hls_stop_event": _hls_runner,
    "_pipeline_thread": _pipeline_runner,    # gui.services.pipeline_runner; rebound by /api/start + tests
    "_stop_event": _pipeline_runner,
    "_active_encoder": _pipeline_runner,
}


class _ForwardingModule(_types.ModuleType):
    """gui.app module class: forwards rebound globals to their owning module."""

    def __getattr__(self, name):          # called only when normal lookup misses
        owner = _FORWARDED_GLOBALS.get(name)
        if owner is not None:
            return getattr(owner, name)
        raise AttributeError(f"module {self.__name__!r} has no attribute {name!r}")

    def __setattr__(self, name, value):
        owner = _FORWARDED_GLOBALS.get(name)
        if owner is not None:
            setattr(owner, name, value)
        else:
            super().__setattr__(name, value)


sys.modules[__name__].__class__ = _ForwardingModule


# ── Entry point ───────────────────────────────────────────────────────────────

def create_app() -> Flask:
    # Start the always-on hardware sampler here rather than at import time so
    # that merely importing gui.app stays side-effect-free (TASK 1.2). All real
    # entry points (run_gui.py, the PyInstaller launcher, and __main__ below)
    # go through create_app(), so the dashboard's CPU/RAM strip is live.
    start_hw_sampler()

    # Pre-create OneDrive/SVCS/Encrypted/ if OneDrive is available
    try:
        od_root, _ = _detect_onedrive_root(prefer_business=True)
        if od_root is not None:
            enc_dir = od_root / "SVCS" / "Encrypted"
            enc_dir.mkdir(parents=True, exist_ok=True)
            log.info("OneDrive Encrypted folder ready: %s", enc_dir)
    except Exception:
        pass
    return app


if __name__ == "__main__":
    log.info("=" * 60)
    log.info("SVCS SERVER STARTUP: %s", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
    log.info("Project root:  %s", _ROOT)
    log.info("Dashboard:     http://localhost:5000")
    log.info("Log file:      %s", _LOG_FILE)
    log.info("=" * 60)
    create_app().run(host="0.0.0.0", port=5000, debug=False, threaded=True)
