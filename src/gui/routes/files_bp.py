"""
src/gui/routes/files_bp.py

files routes blueprint, carved from gui/app.py (TASK 1.3).
Pure relocation: every URL, method, and response shape is unchanged.
Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - blueprints).
"""

import sys
import json
import subprocess
from pathlib import Path
from urllib.parse import quote, unquote
from flask import Blueprint, jsonify, request, Response, send_from_directory, abort

try:
    from gui.state import (_state_lock, _status, _demo_lock, _demo_state, _CLOUD_SUBFOLDER, _ALLOWED_EXTENSIONS)
    from gui.logging_setup import log
    from gui.services.cloud_detection import _detect_cloud_root
    from gui.services.db_helpers import _get_db_path, _get_archive_db_path, _rows_to_segment_list
    from gui.services import path_safety as _ps
    from utils.db import (get_connection)
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.state import (_state_lock, _status, _demo_lock, _demo_state, _CLOUD_SUBFOLDER, _ALLOWED_EXTENSIONS)
    from src.gui.logging_setup import log
    from src.gui.services.cloud_detection import _detect_cloud_root
    from src.gui.services.db_helpers import _get_db_path, _get_archive_db_path, _rows_to_segment_list
    from src.gui.services import path_safety as _ps
    from src.utils.db import (get_connection)

# Extensions /media/<path> may serve (SEC-004): media + a few preview image
# types, so it can never hand back source code, the metadata DB, configs, etc.
_MEDIA_SERVE_EXTS = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".ts", ".m4v",
                     ".jpg", ".jpeg", ".png", ".gif", ".webp"}

# Repo root (…/src/gui/routes/<bp>_bp.py -> parents[3]).
_ROOT = Path(__file__).resolve().parents[3]

files_bp = Blueprint("files", __name__)

def _segment_absolute_path(file_path: str, output_dir: str) -> Path:
    """Resolve a segment path from DB into an absolute path."""
    p = Path(file_path)
    if not p.is_absolute():
        p = Path(output_dir) / p
    return p.resolve()


@files_bp.route("/api/segments")
def api_segments():
    """Return the 50 most recent segments from the metadata DB.

    Query params (all optional):
      object_type   - vehicle | person | person+vehicle | animal | unknown
      color         - red | orange | yellow | green | blue | white | black | gray | ...
      scene_type    - highway | intersection | parking | street | unknown
      time_of_day   - day | night | dusk_dawn
      camera_id     - filter by camera
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
    # OneDrive/SVCS/) - the user's report was that demo recordings
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
                        "note": "No metadata.db found - run the pipeline or a demo first.",
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

    # Cache cpu_stats.json reads - many segments share the same db_dir.
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


@files_bp.route("/api/storage")
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


@files_bp.route("/api/scan_videos")
def api_scan_videos():
    """Return .mp4/.avi/.mov files found in the project data/ folder."""
    data_dir = _ROOT / "data"
    videos = []
    if data_dir.exists():
        for ext in ("*.mp4", "*.avi", "*.mov", "*.mkv"):
            for f in sorted(data_dir.glob(ext)):
                videos.append(str(f))
    return jsonify({"videos": videos, "data_dir": str(data_dir)})


@files_bp.route("/media/<path:rel_path>")
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
    # SEC-004: only serve media/preview files - never source, the metadata DB,
    # configs, or other repo files that happen to live under the project root.
    if abs_path.suffix.lower() not in _MEDIA_SERVE_EXTS:
        abort(404)
    return send_from_directory(str(root), rel_path, as_attachment=False)


@files_bp.route("/api/media_debug")
def api_media_debug():
    """Diagnostic: check whether a given path would be served by /api/media."""
    path = unquote(request.args.get("path", "").strip())
    if not path:
        return jsonify({"error": "no path param"})
    p = Path(path).resolve()
    # SEC-015: do not act as a filesystem existence/path oracle for arbitrary
    # paths. Only report details for paths inside the operator's media folders;
    # everything else is reported as simply not-servable, with no resolved path.
    if not _ps.is_path_allowed(p, _ps.allowed_media_roots()):
        return jsonify({"raw_path": path, "allowed": False, "would_serve": False})
    return jsonify({
        "raw_path": path,
        "allowed": True,
        "resolved": str(p),
        "is_absolute": p.is_absolute(),
        "exists": p.exists(),
        "is_file": p.is_file() if p.exists() else False,
        "suffix": p.suffix.lower(),
        "allowed_suffix": p.suffix.lower() in {".mp4", ".webm", ".mov", ".avi", ".mkv"},
        "would_serve": p.is_absolute() and p.exists() and p.is_file()
                       and p.suffix.lower() in {".mp4", ".webm", ".mov", ".avi", ".mkv"},
    })


@files_bp.route("/api/media")
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
    # We allow any absolute path to a video file that exists on disk - this
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
    # SEC-002: confine to the operator's media folders. The dashboard binds
    # 0.0.0.0, so the old "localhost only, already trusted" assumption is false;
    # without this a LAN/CSRF client could read ANY video file on the host.
    if not _ps.is_path_allowed(p, _ps.allowed_media_roots()):
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


@files_bp.route("/api/browse")
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


@files_bp.route("/api/open_folder", methods=["POST"])
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
        log.warning("api_open_folder: failed to open %s - %s", folder, exc)
        return jsonify({"error": str(exc)}), 500

    return jsonify({"ok": True, "path": str(folder)})


@files_bp.route("/api/upload", methods=["POST"])
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


@files_bp.route("/api/segments/clear", methods=["POST"])
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


@files_bp.route("/api/segments/hide_one", methods=["POST"])
def api_segments_hide_one():
    """Hide one segment row by file_path.

    The segment list doesn't carry DB row IDs across the multiple
    metadata.db files (main + per-demo), so file_path is the cheapest
    stable identifier. Walks every metadata.db under the output root,
    sets hidden=1 on any matching row, leaves the file on disk alone.

    Used by the per-row [X] button in the metrics table - the user just
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
            log.warning("hide_one: skipped %s - %s", db_path, exc)
            continue

    return jsonify({"ok": True, "hidden": hidden_count})


@files_bp.route("/api/segments/cleanup_missing", methods=["POST"])
def api_segments_cleanup_missing():
    """Hide every segment whose file_path no longer exists on disk.

    A pipeline test or a stop-mid-run can leave dangling DB rows whose
    file got cleaned up before the row could be deleted. The user can
    see them in the dashboard but the play / encrypt buttons all do
    nothing. This sweeps them in one shot.

    Returns the count of rows hidden so the frontend can confirm.

    Author: Bloodawn (KheivenD), 2026-05-03 (cleanup of dead rows).
    """
    # Walk every plausible root - pipeline output_dir, last demo
    # output_root, project /outputs/ - same fan-out /api/segments uses.
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
                    # composite - five rows per demo run for what is
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
                log.warning("cleanup_missing: skipped %s - %s", db_path, exc)
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


