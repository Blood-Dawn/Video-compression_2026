"""
src/gui/routes/library_bp.py

Library / gallery routes (FIX 6).

Browse compressed (or any) videos in-app as a gallery, then send one into the
compress flow. Endpoints:

  * GET  /api/library/videos   - list videos in a folder (paginated)
  * GET  /api/library/meta     - ffprobe metadata for one video
  * GET  /api/library/thumb    - a cached JPEG thumbnail (generated lazily)
  * GET  /api/library/file     - stream the video file (range-enabled) for the
                                 inline detail player
  * POST /api/library/compress - validate a path and hand it to the start flow

Thumbnails are generated with one ffmpeg frame and cached under the OS cache dir
so listing stays fast and the request thread is never blocked twice for the same
clip. Folder defaults to the user's chosen output directory.

Author: Bloodawn (KheivenD), 2026-06-03 (FIX 6 - library/gallery).
"""

import hashlib
import subprocess
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

try:
    from gui.logging_setup import log
    from gui.services.cloud_detection import _default_output_dir
    from utils.ffmpeg import ffmpeg_path, ffprobe_path
    from utils import paths as _paths
    from utils import compressed_index as _cidx
    from gui.services import path_safety as _ps
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.logging_setup import log
    from src.gui.services.cloud_detection import _default_output_dir
    from src.utils.ffmpeg import ffmpeg_path, ffprobe_path
    from src.utils import paths as _paths
    from src.utils import compressed_index as _cidx
    from src.gui.services import path_safety as _ps

library_bp = Blueprint("library", __name__)

# R4 Phase 6: the universal ingest set so vendor/DVR exports show in the Library
# and can be compressed. Thumbnails use FFmpeg (broad format support); a vendor
# ORIGINAL will not play in the browser <video> tag, but its compressed OUTPUT
# is mp4 and does.
try:
    from utils.video_formats import ALL_INGEST_EXTS as _ALL_INGEST_EXTS
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils.video_formats import ALL_INGEST_EXTS as _ALL_INGEST_EXTS
VIDEO_EXTS = set(_ALL_INGEST_EXTS)

_MIME = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
    ".mkv": "video/x-matroska", ".webm": "video/webm", ".avi": "video/x-msvideo",
    ".ts": "video/mp2t", ".mpg": "video/mpeg", ".mpeg": "video/mpeg",
    ".wmv": "video/x-ms-wmv", ".flv": "video/x-flv",
}


def _resolve_folder(raw: str) -> Path:
    """Resolve the requested library folder, defaulting to the output dir."""
    raw = (raw or "").strip()
    if not raw:
        return Path(_default_output_dir())
    return Path(raw).resolve()


def _safe_video(raw: str):
    """Resolve a video path; return Path if it is an existing video file, else None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        p = Path(raw).resolve()
    except (OSError, ValueError):
        return None
    # Must be an existing video file AND confined to one of the operator's media
    # folders (SEC-003). The old `'..' in p.parts` check was dead code: resolve()
    # collapses traversal before it runs, and an absolute path bypassed it
    # entirely, so /api/library/file could stream any video on the host.
    if not (p.is_file() and p.suffix.lower() in VIDEO_EXTS):
        return None
    if not _ps.is_path_allowed(p, _ps.allowed_media_roots()):
        return None
    return p


def _int_arg(name: str, default=None):
    raw = (request.args.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


@library_bp.route("/api/library/videos", methods=["GET"])
def api_library_videos():
    """List videos in a folder, with search / filters / sort, paginated.

    Query params (all optional):
      folder      - directory to list (defaults to the chosen output folder)
      q           - case-insensitive filename substring filter (R2.3 search)
      ext         - comma-separated extensions to keep (e.g. "mp4,mkv")
      min_size    - minimum size in BYTES
      max_size    - maximum size in BYTES
      sort        - name | size | date   (default: date)
      order       - asc | desc           (default: desc)
      page, page_size

    Thumbnails are NOT generated here (the grid loads them lazily). The chosen
    folder is remembered so the Library reopens where the user left off.
    """
    folder = _resolve_folder(request.args.get("folder", ""))
    q = (request.args.get("q", "") or "").strip().lower()
    ext_raw = (request.args.get("ext", "") or "").strip().lower()
    allowed_exts = None
    if ext_raw:
        allowed_exts = {("." + e.lstrip(".")) for e in ext_raw.split(",") if e.strip()}
    min_size = _int_arg("min_size")
    max_size = _int_arg("max_size")
    sort = (request.args.get("sort", "date") or "date").strip().lower()
    order = (request.args.get("order", "desc") or "desc").strip().lower()
    # R3.1d: filter by whether a clip is an original or a compressed output.
    kind = (request.args.get("kind", "all") or "all").strip().lower()
    if kind not in ("all", "original", "compressed"):
        kind = "all"
    page = max(1, _int_arg("page", 1))
    page_size = min(200, max(1, _int_arg("page_size", 60)))

    if not folder.is_dir():
        return jsonify({"folder": str(folder), "exists": False,
                        "total": 0, "videos": []})

    # Remember the folder for next time (R2.3 - persist last library folder).
    try:
        from gui.services.gui_state_persist import set_library_folder
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.gui.services.gui_state_persist import set_library_folder
    set_library_folder(str(folder))

    # Recurse by default so pointing at a parent folder (e.g. a corpus with
    # per-scene subfolders) finds the clips nested beneath it. Capped so a huge
    # tree cannot hang the request. ``recursive=0`` lists the top level only.
    recursive = (request.args.get("recursive", "1") or "1").strip() not in ("0", "false", "no")
    cap = 5000
    # Gather all video files first (so the type-filter dropdown reflects every
    # type in the folder, independent of the active q/ext/size filters). For
    # nested files the display name carries the relative subpath.
    all_items = []
    truncated = False
    try:
        walker = folder.rglob("*") if recursive else folder.iterdir()
        for f in walker:
            if not (f.is_file() and f.suffix.lower() in VIDEO_EXTS):
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            try:
                rel = f.relative_to(folder).as_posix()
            except ValueError:
                rel = f.name
            all_items.append({"name": rel, "path": str(f),
                              "size": st.st_size, "mtime": st.st_mtime,
                              "_ext": f.suffix.lower()})
            if len(all_items) >= cap:
                truncated = True
                break
    except OSError as exc:
        return jsonify({"folder": str(folder), "exists": True, "error": str(exc),
                        "total": 0, "videos": []}), 200

    exts = sorted({i["_ext"].lstrip(".") for i in all_items})

    # R3.1d: load the compressed index ONCE and build lookups so we can classify
    # every listed file (original vs compressed output) without re-reading the
    # index per item. ``out_to_src`` maps a recorded output back to its source so
    # a compressed clip can show where it came from.
    _idx = _cidx._load()
    _entries = _idx.get("entries", {})
    out_to_src = {e.get("output", ""): e.get("source", "") for e in _entries.values()}
    _comp_dirname = _cidx.COMPRESSED_DIRNAME

    def _classify(path_str):
        """Return (kind, source_or_None, has_compressed_bool) for one file.

        Mirrors compressed_index.classify / is_compressed but uses the preloaded
        index. ``has_compressed`` is only meaningful for originals (True when a
        verified compressed output for this exact file still exists on disk).
        """
        try:
            rp = str(Path(path_str).resolve())
        except (OSError, ValueError):
            rp = path_str
        in_comp_loc = _comp_dirname in {p.lower() for p in Path(rp).parts}
        if in_comp_loc or rp in out_to_src:
            return "compressed", out_to_src.get(rp), False
        # An original: does a current, on-disk compressed version exist?
        entry = _entries.get(_cidx.signature(path_str))
        has = bool(entry and entry.get("output") and Path(entry["output"]).is_file())
        return "original", None, has

    # Apply search / type / size / kind filters.
    items = []
    for i in all_items:
        if allowed_exts is not None and i["_ext"] not in allowed_exts:
            continue
        if q and q not in i["name"].lower():
            continue
        if min_size is not None and i["size"] < min_size:
            continue
        if max_size is not None and i["size"] > max_size:
            continue
        ikind, isource, ihas = _classify(i["path"])
        if kind == "compressed" and ikind != "compressed":
            continue
        if kind == "original" and ikind != "original":
            continue
        item = {"name": i["name"], "path": i["path"],
                "size": i["size"], "mtime": i["mtime"], "kind": ikind}
        if ikind == "compressed":
            item["source"] = isource
        else:
            item["compressed"] = ihas
        items.append(item)

    key = {"name": lambda x: x["name"].lower(),
           "size": lambda x: x["size"],
           "date": lambda x: x["mtime"]}.get(sort, lambda x: x["mtime"])
    items.sort(key=key, reverse=(order != "asc"))

    total = len(items)
    start = (page - 1) * page_size
    return jsonify({
        "folder": str(folder), "exists": True, "total": total,
        "page": page, "page_size": page_size,
        "sort": sort, "order": order, "extensions": exts, "kind": kind,
        "recursive": recursive, "truncated": truncated,
        "videos": items[start:start + page_size],
    })


@library_bp.route("/api/library/list_dirs", methods=["GET"])
def api_library_list_dirs():
    """List subdirectories for the in-app folder browser (R2.3 follow-up).

    A native dialog cannot be opened from the frozen app (sys.executable is the
    bundled exe, not a Python interpreter), and would not work for a remote or
    Docker browser anyway. This server-side navigator returns the immediate
    subdirectories of ``path`` plus the parent, so the UI can walk the tree and
    pick a folder. With no path it returns the drive roots (Windows) or "/".

    Returns: {"path": str, "parent": str|null, "is_root": bool,
              "dirs": [{"name": str, "path": str}],
              "video_count": int}   # videos directly in this folder
    """
    import os as _os
    raw = (request.args.get("path", "") or "").strip()

    # No path -> top level: drive letters on Windows, "/" elsewhere.
    if not raw:
        if _os.name == "nt":
            try:
                from gui.services.cloud_detection import _windows_drive_roots
            except ModuleNotFoundError:  # pragma: no cover - import path shim
                from src.gui.services.cloud_detection import _windows_drive_roots
            roots = _windows_drive_roots()
            dirs = [{"name": str(r), "path": str(r)} for r in roots]
            return jsonify({"path": "", "parent": None, "is_root": True,
                            "dirs": dirs, "video_count": 0})
        raw = "/"

    try:
        base = Path(raw).resolve()
    except (OSError, ValueError):
        return jsonify({"error": "invalid path"}), 400
    if not base.is_dir():
        return jsonify({"error": "not a directory", "path": str(base)}), 400

    dirs = []
    video_count = 0
    try:
        for entry in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            try:
                if entry.is_dir():
                    dirs.append({"name": entry.name, "path": str(entry)})
                elif entry.is_file() and entry.suffix.lower() in VIDEO_EXTS:
                    video_count += 1
            except OSError:
                continue
    except OSError as exc:
        return jsonify({"error": str(exc), "path": str(base)}), 200

    parent = str(base.parent) if base.parent != base else None
    # On Windows a drive root's parent is itself; expose "" so the UI can go to
    # the drive list.
    if _os.name == "nt" and base.parent == base:
        parent = ""
    return jsonify({"path": str(base), "parent": parent, "is_root": False,
                    "dirs": dirs, "video_count": video_count})


@library_bp.route("/api/library/browse_folder", methods=["GET"])
def api_library_browse_folder():
    """Open a NATIVE folder picker on the host and return the chosen directory.

    Windows uses a PowerShell ``FolderBrowserDialog`` so it also works in the
    FROZEN app, where ``sys.executable`` is the bundled SVCS.exe and cannot run a
    ``python -c`` script. Other platforms shell out to a tkinter askdirectory
    dialog (works from source). The dialog runs in a separate process so it never
    blocks or crashes the Flask worker thread.

    Remote/Docker users (where the dialog would open on the server, not their
    screen) type a path instead, and the Library falls back to its in-app browser
    if this returns nothing. Returns {"path": "..."} (empty if cancelled).
    """
    import subprocess
    import sys
    path = ""
    try:
        if sys.platform == "win32":
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms | Out-Null; "
                "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "$d.Description = 'Select a folder of videos'; "
                "$d.ShowNewFolderButton = $true; "
                "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
                "{ [Console]::Out.Write($d.SelectedPath) }"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", ps],
                capture_output=True, text=True, timeout=300)
        else:
            script = (
                "import tkinter as tk; from tkinter import filedialog; "
                "root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True); "
                "path = filedialog.askdirectory(title='Select a folder of videos'); "
                "root.destroy(); print(path or '', end='')"
            )
            result = subprocess.run([sys.executable, "-c", script],
                                    capture_output=True, text=True, timeout=300)
        path = (result.stdout or "").strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("Library folder picker failed: %s", exc)
        path = ""
    return jsonify({"path": path})


@library_bp.route("/api/library/meta", methods=["GET"])
def api_library_meta():
    """Return ffprobe metadata (duration, dims, fps, codec) for one video."""
    p = _safe_video(request.args.get("path", ""))
    if p is None:
        return jsonify({"error": "not a video file"}), 400
    meta = {"name": p.name, "path": str(p), "size": p.stat().st_size}
    try:
        out = subprocess.run(
            [ffprobe_path(), "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate,codec_name:format=duration",
             "-of", "default=noprint_wrappers=1:nokey=0", str(p)],
            capture_output=True, text=True, timeout=20,
        )
        for line in out.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                meta[k.strip()] = v.strip()
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - env dependent
        pass
    return jsonify(meta)


def _thumb_path(video: Path) -> Path:
    st = video.stat()
    key = hashlib.sha1(f"{video}|{int(st.st_mtime)}|{st.st_size}".encode("utf-8")).hexdigest()
    return _paths.thumbs_dir() / (key + ".jpg")


@library_bp.route("/api/library/thumb", methods=["GET"])
def api_library_thumb():
    """Return a cached JPEG thumbnail, generating it once with ffmpeg if needed."""
    p = _safe_video(request.args.get("path", ""))
    if p is None:
        return jsonify({"error": "not a video file"}), 400
    thumb = _thumb_path(p)
    if not thumb.exists():
        ok = False
        for ss in ("1", "0"):  # try 1s in, then the very first frame
            try:
                r = subprocess.run(
                    [ffmpeg_path(), "-y", "-ss", ss, "-i", str(p),
                     "-frames:v", "1", "-vf", "scale=320:-2", str(thumb)],
                    capture_output=True, timeout=30,
                )
                if r.returncode == 0 and thumb.exists() and thumb.stat().st_size > 0:
                    ok = True
                    break
            except (OSError, subprocess.SubprocessError):  # pragma: no cover
                break
        if not ok:
            return jsonify({"error": "could not generate thumbnail"}), 404
    return send_file(str(thumb), mimetype="image/jpeg", conditional=True)


@library_bp.route("/api/library/file", methods=["GET"])
def api_library_file():
    """Stream a video file (range-enabled) for the inline detail player."""
    p = _safe_video(request.args.get("path", ""))
    if p is None:
        return jsonify({"error": "not a video file"}), 400
    mime = _MIME.get(p.suffix.lower(), "application/octet-stream")
    return send_file(str(p), mimetype=mime, conditional=True)


@library_bp.route("/api/library/compress", methods=["POST"])
def api_library_compress():
    """Validate a chosen library video and hand its path back to the UI.

    The front-end then drops the path into the source field and routes it through
    the existing start/upload flow.
    """
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400
    p = _safe_video(data.get("path", ""))
    if p is None:
        return jsonify({"error": "not a video file"}), 400
    log.info("Library: selected %s for compression", p.name)
    return jsonify({"ok": True, "path": str(p), "name": p.name})
