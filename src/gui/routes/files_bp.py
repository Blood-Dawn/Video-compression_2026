"""
src/gui/routes/files_bp.py

Segment list, storage stats, media serving, uploads and the hide/cleanup
actions for the dashboard's metrics table.
Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - blueprints).
"""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, unquote
from flask import Blueprint, jsonify, request, Response, send_from_directory, abort

try:
    from gui.state import _state_lock, _status, _demo_lock, _demo_state, _ALLOWED_EXTENSIONS
    from gui.logging_setup import log
    from gui.services import path_safety as _ps
    from gui.services.db_helpers import _is_empty_db_error
    from gui.services.cloud_detection import _detect_cloud_root  # noqa: F401 (test seam, see below)
    from utils.db import (get_connection)
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.state import (_state_lock, _status, _demo_lock, _demo_state, _ALLOWED_EXTENSIONS)
    from src.gui.logging_setup import log
    from src.gui.services import path_safety as _ps
    from src.gui.services.db_helpers import _is_empty_db_error
    from src.gui.services.cloud_detection import _detect_cloud_root  # noqa: F401 (test seam, see below)
    from src.utils.db import (get_connection)

# _detect_cloud_root is deliberately in scope but never called here: M0.7 says
# uploads must not fall into a detected OneDrive/Drive root on the app's own
# initiative. tests/test_upload_dir_policy.py patches this name to a fake cloud
# root and proves _upload_dir() still picks the local folder.

# Extensions /media/<path> may serve (SEC-004): media + a few preview image
# types, so it can never hand back source code, the metadata DB, configs, etc.
_MEDIA_SERVE_EXTS = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".ts", ".m4v",
                     ".jpg", ".jpeg", ".png", ".gif", ".webp"}

# Containers /api/media will stream, and the type it sends for each.
_VIDEO_MIME = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
}
# Containers a browser <video> tag plays, so a segment row gets a play link.
_PLAYABLE_EXTS = {".mp4", ".webm", ".mov", ".avi"}

_STREAM_CHUNK = 64 * 1024

# A client filename past the filesystem's per-component limit (255 bytes)
# makes save() raise OSError; trim well under it, extension kept.
_MAX_STEM_LEN = 150

# Repo root (.../src/gui/routes/<bp>_bp.py -> parents[3]).
_ROOT = Path(__file__).resolve().parents[3]

files_bp = Blueprint("files", __name__)

def _segment_absolute_path(file_path: str, output_dir: str) -> Path:
    """Resolve a segment path from DB into an absolute path."""
    p = Path(file_path)
    if not p.is_absolute():
        p = Path(output_dir) / p
    return p.resolve()


def _candidate_roots() -> list[Path]:
    """Every folder that may hold a metadata.db, resolved, de-duplicated.

    The pipeline writes <output_dir>/metadata.db. Demo runs write under the
    demo's last output root, which can legitimately differ (./outputs vs
    OneDrive/SVCS), and demo recordings went missing from the metrics tab
    when only the pipeline root was walked. ./outputs is the fallback for a
    fresh clone.
    Author: Bloodawn (KheivenD), 2026-05-04 (demo-output discovery).
    """
    with _state_lock:
        cfg = _status.get("config", {})
    with _demo_lock:
        demo_last_root = _demo_state.get("last_output_root", "")

    roots: list[Path] = []
    for raw in (cfg.get("output_dir", ""), demo_last_root, str(_ROOT / "outputs")):
        if not raw:
            continue
        try:
            p = Path(raw).resolve()
        except (OSError, ValueError, RuntimeError, TypeError):
            continue
        if p not in roots:
            roots.append(p)
    return roots


def _metadata_dbs(roots: list[Path]) -> list[Path]:
    """Every metadata.db under the existing roots, each once, sorted.

    A root nested inside another root is not walked a second time: the outer
    rglob already reaches it, and the walk is the expensive part.
    """
    existing = [r for r in roots if r.exists()]
    outermost = [r for r in existing
                 if not any(o != r and o in r.parents for o in existing)]
    found: set[Path] = set()
    for root in outermost:
        for db in root.rglob("metadata.db"):
            found.add(db.resolve())
    return sorted(found)


def _ensure_hidden_column(conn) -> None:
    """Add segments.hidden to a database created before the column existed."""
    cols = {c[1] for c in conn.execute("PRAGMA table_info(segments)").fetchall()}
    if "hidden" not in cols:
        conn.execute("ALTER TABLE segments ADD COLUMN hidden INTEGER DEFAULT 0")


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
    candidate_roots = _candidate_roots()
    all_dbs = _metadata_dbs(candidate_roots)

    output_root = candidate_roots[0] if candidate_roots else (_ROOT / "outputs")

    if not all_dbs:
        return jsonify({"segments": [], "db_path": str(output_root / "metadata.db"),
                        "note": "No metadata.db found - run the pipeline or a demo first.",
                        "roots_searched": [str(r) for r in candidate_roots]})

    # Same WHERE clause and params for every db.
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
    # Persons whose bbox was also confirmed by YOLO pose keypoints
    # (detection/pose_onnx_backend.py), not just the bbox classifier.
    f_pose_only = request.args.get("pose_verified_only", "").strip() == "1"

    if f_type:
        if f_type in ("person", "vehicle", "animal"):
            # A single-class pick must also match combo labels such as
            # "person+vehicle", or mixed-type segments vanish from the
            # filter. An explicit combo pick falls to the exact match below.
            filters.append(
                "(COALESCE(object_type,'unknown') = ?"
                " OR COALESCE(object_type,'unknown') LIKE ?"
                " OR COALESCE(object_type,'unknown') LIKE ?)"
            )
            params.extend([f_type, f"{f_type}+%", f"%+{f_type}"])
        else:
            filters.append("COALESCE(object_type,'unknown') = ?")
            params.append(f_type)
    for clause, value in (
        ("dominant_color = ?", f_color),
        ("COALESCE(scene_type,'unknown') = ?", f_scene),
        ("time_of_day = ?", f_tod),
        ("camera_id = ?", f_cam),
        ("timestamp >= ?", f_start),
        ("timestamp <= ?", f_end),
    ):
        if value:
            filters.append(clause)
            params.append(value)
    if f_min_rois:
        try:
            params.append(int(f_min_rois))
            filters.append("roi_count >= ?")
        except ValueError:
            pass
    if f_enc_only:
        filters.append("file_path LIKE ?")
        params.append("%.enc")
    if f_pose_only:
        filters.append("COALESCE(pose_verified_person_count, 0) > 0")

    has_filters = any([f_type, f_color, f_scene, f_tod, f_cam, f_start, f_end, f_min_rois, f_enc_only, f_pose_only])
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
               COALESCE(person_count, 0)         AS person_count,
               COALESCE(pose_verified_person_count, 0) AS pose_verified_person_count
        FROM segments
        WHERE {where}
        ORDER BY timestamp DESC
        LIMIT {row_limit}
    """

    # Query every db, tagging each row with its db folder so relative file
    # paths resolve, then merge and re-sort.
    all_rows: list[tuple] = []
    for db_path in all_dbs:
        db_dir = str(db_path.parent)
        try:
            with get_connection(str(db_path)) as conn:
                rows = conn.execute(query, params).fetchall()
        except sqlite3.Error:
            continue  # corrupt or schema-mismatched db
        all_rows.extend((r, db_dir) for r in rows)

    all_rows.sort(key=lambda x: x[0][0], reverse=True)
    all_rows = all_rows[:row_limit]

    # cpu_stats.json is read once per db folder; many segments share one.
    # Author: Bloodawn (KheivenD), 2026-05-03 (per-clip CPU stats).
    cpu_cache: dict[str, dict | None] = {}

    def _cpu_for_dir(d: str) -> dict | None:
        if d not in cpu_cache:
            stats_file = Path(d) / "cpu_stats.json"
            try:
                cpu_cache[d] = json.loads(stats_file.read_text()) if stats_file.exists() else None
            except (OSError, ValueError):
                cpu_cache[d] = None
        return cpu_cache[d]

    segs = []
    for r, db_dir in all_rows:
        abs_path = _segment_absolute_path(r[6], db_dir)
        playable_url = None
        if abs_path.exists() and abs_path.suffix.lower() in _PLAYABLE_EXTS:
            playable_url = f"/api/media?path={quote(str(abs_path))}"

        try:
            obj_classes = json.loads(r[10]) if r[10] else []
        except (TypeError, ValueError):
            obj_classes = []

        # None for every cpu_* field when no sampler ran for this folder.
        cpu_stats = _cpu_for_dir(db_dir) or {}

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
            "pose_verified_person_count": r[16],
            "cpu_avg":         cpu_stats.get("avg"),
            "cpu_max":         cpu_stats.get("max"),
            "cpu_min":         cpu_stats.get("min"),
            "cpu_samples":     cpu_stats.get("samples"),
            "cpu_duration_s":  cpu_stats.get("duration_s"),
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
        if _is_empty_db_error(exc):
            return jsonify({"available": False})
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
            videos.extend(str(f) for f in sorted(data_dir.glob(ext)))
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
    suffix = p.suffix.lower()
    exists = p.exists()
    is_file = exists and p.is_file()
    return jsonify({
        "raw_path": path,
        "allowed": True,
        "resolved": str(p),
        "is_absolute": p.is_absolute(),
        "exists": exists,
        "is_file": is_file,
        "suffix": suffix,
        "allowed_suffix": suffix in _VIDEO_MIME,
        "would_serve": p.is_absolute() and is_file and suffix in _VIDEO_MIME,
    })


@files_bp.route("/api/media")
def api_media():
    """Serve any local video file by absolute path with HTTP range support.

    Called as /api/media?path=<url-encoded-absolute-path>.
    Rejects non-video extensions and non-existent files.

    Browser <video> elements need Range support to seek, and Flask's
    send_from_directory does not handle Range headers.
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
    if suffix not in _VIDEO_MIME:
        abort(403)
    # SEC-002: confine to the operator's media folders. The dashboard binds
    # 0.0.0.0, so the old "localhost only, already trusted" assumption is false;
    # without this a LAN/CSRF client could read ANY video file on the host.
    if not _ps.is_path_allowed(p, _ps.allowed_media_roots()):
        abort(403)

    mime = _VIDEO_MIME[suffix]
    file_size = p.stat().st_size

    def _read_span(start: int, length: int):
        with open(p, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                data = f.read(min(_STREAM_CHUNK, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    range_header = request.headers.get("Range")
    if range_header:
        # "bytes=start-end"; either end may be blank.
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
        resp = Response(
            _read_span(start, length),
            status=206,
            mimetype=mime,
            direct_passthrough=True,
        )
        resp.headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        resp.headers["Content-Length"] = str(length)
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    resp = Response(_read_span(0, file_size), status=200, mimetype=mime,
                    direct_passthrough=True)
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
        # R4 Phase 6: offer the common containers plus vendor/DVR exports; the
        # 'All files' entry still lets the user pick anything FFmpeg can decode.
        "    filetypes=[('Video files', '*.mp4 *.avi *.mov *.mkv *.ts *.m4v *.wmv "
        "*.flv *.mpg *.mpeg *.dav *.264 *.h264 *.265 *.hevc *.g64 *.sdv *.mxf'), "
        "('All files', '*.*')]"
        "); root.destroy(); print(path or '', end='')"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
        path = (result.stdout or "").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("File picker failed: %s", exc)
        path = ""
    return jsonify({"path": path})


_UPLOAD_DIR_LOCAL = _ROOT / "data" / "uploads"


#: Path fragments that mean "this is inside a third-party sync root". Used only
#: to TELL the user where their upload landed, never to choose the destination.
_CLOUD_MARKERS = ("onedrive", "google drive", "my drive", "googledrive",
                  "icloud", "dropbox", "box sync")


def _is_cloud_path(p: Path) -> bool:
    """True if the path sits inside a recognizable cloud sync root."""
    s = str(p).replace("\\", "/").lower()
    return any(m in s for m in _CLOUD_MARKERS)


def _upload_dir() -> Path:
    """Return the upload directory, never auto-selecting a cloud folder.

    Resolution order, mirroring _default_output_dir():
      1. ``<the user's explicitly chosen output_dir>/uploads``. A cloud
         destination is only ever used when the user chose it in Setup.
      2. Local ``data/uploads/``.

    Policy: the app never falls through to a OneDrive / Google Drive / iCloud
    root on its own. Uploads are footage of real people, and the product
    promises nothing goes to a cloud unless the user picks a cloud folder.
    """
    with _state_lock:
        cfg = _status.get("config", {}) or {}
        persisted = (cfg.get("output_dir") or "").strip()
    if persisted and Path(persisted).is_absolute():
        d = Path(persisted) / "uploads"
    else:
        d = _UPLOAD_DIR_LOCAL
    d.mkdir(parents=True, exist_ok=True)
    return d


@files_bp.route("/api/open_folder", methods=["POST"])
def api_open_folder():
    """Open a folder in the native OS file explorer on the host machine.

    This route takes a caller-supplied path and spawns a process on the
    SERVER host, and the app binds 0.0.0.0, so it is confined to
    allowed_media_roots(), the same guard /api/media and /media/<path> use.
    Outside-roots answers are identical whether or not the target exists, so
    the route is not a filesystem existence oracle (SEC-015).
    """
    data = request.get_json(silent=True) or {}
    raw = data.get("path", "").strip()
    if not raw:
        return jsonify({"error": "No path provided"}), 400

    folder = Path(raw).resolve()

    # Confine BEFORE touching the filesystem, so existence is never revealed
    # for anything outside the allowed roots. One identical response for
    # "outside the roots" regardless of whether the path is real.
    roots = _ps.allowed_media_roots()
    probe = folder if folder.suffix == "" else folder.parent
    if not (_ps.is_path_allowed(folder, roots) or _ps.is_path_allowed(probe, roots)):
        return jsonify({"error": "Path is outside the allowed media folders."}), 403

    if not folder.exists():
        return jsonify({"error": f"Path not found: {folder}"}), 404
    if not folder.is_dir():
        # If caller passed a file path, open its parent directory
        folder = folder.parent
    if not folder.is_dir():
        return jsonify({"error": "Not a directory"}), 400
    # Re-check after the parent hop: the parent must also be inside the roots.
    if not _ps.is_path_allowed(folder, roots):
        return jsonify({"error": "Path is outside the allowed media folders."}), 403

    # sys.platform, not platform.system(): the latter shells out to `ver` on
    # its first call on Windows.
    opener = {"win32": "explorer", "darwin": "open"}.get(sys.platform, "xdg-open")
    try:
        subprocess.Popen([opener, str(folder)])
    except OSError as exc:
        log.warning("api_open_folder: failed to open %s - %s", folder, exc)
        return jsonify({"error": str(exc)}), 500

    return jsonify({"ok": True, "path": str(folder)})


@files_bp.route("/api/upload", methods=["POST"])
def api_upload():
    """Accept a video file upload from a remote browser.

    Saves into _upload_dir() (the chosen output folder's uploads/, else local
    data/uploads/) and returns the server-side path so the pipeline can use
    it as input_source.
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
    # Strip any path components the client might inject, then cap the length.
    safe_name = Path(f.filename).name
    stem = Path(safe_name).stem[:_MAX_STEM_LEN] or "upload"
    safe_name = f"{stem}{suffix}"

    dest = upload_dir / safe_name
    try:
        # Avoid clobbering existing files by appending a counter.
        counter = 1
        while dest.exists():
            dest = upload_dir / f"{stem}_{counter}{suffix}"
            counter += 1
        f.save(str(dest))
    except OSError as exc:
        # Illegal characters on Windows, a path-length limit even after the
        # trim, or a full disk: a clean 400, not a 500 with a stack trace.
        log.warning("Upload rejected: could not save %r: %s", f.filename, exc)
        return jsonify({"error": "Could not save that file (invalid or "
                                 "unsupported filename)."}), 400

    log.info("Uploaded video saved: %s (%d bytes)", dest.name, dest.stat().st_size)
    in_cloud = _is_cloud_path(dest)
    return jsonify({"path": str(dest), "filename": dest.name,
                    "in_cloud": in_cloud,
                    # Kept for the existing dashboard JS, which reads in_drive.
                    "in_drive": in_cloud})


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
                _ensure_hidden_column(conn)
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

    The segment list carries no row IDs across the several metadata.db files
    (main + per-demo), so file_path is the identifier. Sets hidden=1 on any
    matching row under the output root and leaves the file on disk.

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
                _ensure_hidden_column(conn)
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

    A test run or a stop mid-run can leave rows whose file is gone, so the
    play / encrypt buttons do nothing. Returns the count hidden.

    Author: Bloodawn (KheivenD), 2026-05-03 (cleanup of dead rows).
    """
    hidden_count = 0
    redundant_demo_count = 0
    for db_path in _metadata_dbs(_candidate_roots()):
        try:
            with get_connection(str(db_path)) as conn:
                _ensure_hidden_column(conn)
                rows = conn.execute(
                    "SELECT rowid, file_path FROM segments "
                    "WHERE COALESCE(hidden,0) = 0"
                ).fetchall()
                db_dir = db_path.parent
                # Relative paths are relative to the db's folder.
                stale_ids = [rowid for rowid, fp in rows
                             if not fp or not (db_dir / fp).exists()]
                if stale_ids:
                    placeholders = ",".join("?" * len(stale_ids))
                    conn.execute(
                        f"UPDATE segments SET hidden = 1 WHERE rowid IN ({placeholders})",
                        stale_ids,
                    )
                    hidden_count += len(stale_ids)

                # Older demo runs indexed every per-mode render plus the
                # split-screen composite. In a demo_comp* db with a *_split_*
                # row, hide the per-mode rows.
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
        except Exception as exc:  # noqa: BLE001 - one bad db must not stop the sweep
            log.warning("cleanup_missing: skipped %s - %s", db_path, exc)

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
