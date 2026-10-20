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
import os
import subprocess
import sys
import threading
import time
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

# The universal ingest set, so vendor/DVR exports show in the Library. A vendor
# original will not play in a browser <video> tag, but its mp4 output does.
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
    """Resolve the requested library folder.

    Order: the explicitly requested folder, then the one the user last browsed
    (so the Library reopens where the user left off; the phone sends no folder
    at all and depends on this), then the output dir.
    """
    raw = (raw or "").strip()
    if raw:
        return Path(raw).resolve()
    try:
        from gui.services.gui_state_persist import get_library_folder
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.gui.services.gui_state_persist import get_library_folder
    remembered = (get_library_folder() or "").strip()
    if remembered:
        p = Path(remembered)
        # The folder may be unmounted or renamed; fall back instead of
        # showing an empty library.
        if p.is_dir():
            return p
    return Path(_default_output_dir())


def _safe_video(raw: str, context_folder: str = ""):
    """Resolve a video path; return Path if it is an existing video file, else None.

    ``context_folder`` is the folder the client is browsing. Clients share the
    server-global "last library folder" that allowed_media_roots() derives
    from, so when the desktop browses elsewhere a phone's listed paths would
    fall out of the allowed set mid-session. An authenticated client can
    already make any folder the library root via /api/library/videos?folder=,
    so honoring it per request grants nothing new. The path must still be a
    real video file strictly inside that folder.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        p = Path(raw).resolve()
    except (OSError, ValueError):
        return None
    # Must be an existing video file AND confined to one of the operator's media
    # folders (SEC-003); without the confinement /api/library/file could stream
    # any video on the host.
    try:
        is_video = p.is_file() and p.suffix.lower() in VIDEO_EXTS
    except OSError:  # name too long and similar: not a video, not a 500
        return None
    if not is_video:
        return None
    if _ps.is_path_allowed(p, _ps.allowed_media_roots()):
        return p
    ctx = (context_folder or "").strip()
    if ctx:
        try:
            root = Path(ctx).resolve()
            if root.is_dir():
                p.relative_to(root)  # ValueError if p is not inside root
                return p
        except (OSError, ValueError):
            return None
    return None


def _int_arg(name: str, default=None):
    raw = (request.args.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


# Listing cache. The walk (directory listing, a stat per file, classification
# against the compressed index) is linear in file count and does not depend on
# the request's filters, so it is cached per (folder, recursive); filter and
# sort run per request.
#
# TTL rather than mtime-watching: a nested tree changes without the root's
# mtime moving. `refresh=1` forces an exact rebuild.
_LIB_CACHE_TTL_S = 10.0
_LIB_CACHE_MAX_FOLDERS = 4      # ~1 MB per cached folder at the 5000 cap
_LIB_CACHE_CAP = 5000           # max files listed per folder

_lib_cache_lock = threading.Lock()
_lib_cache: dict = {}           # key -> {"at": float, "items": [...], ...}


def _reset_library_cache() -> None:
    """Drop every cached listing. For tests, and for a factory reset."""
    with _lib_cache_lock:
        _lib_cache.clear()


def _suffix(name: str) -> str:
    """Lower-cased extension, with the same edge cases as Path.suffix."""
    dot = name.rfind(".")
    return name[dot:].lower() if 0 < dot < len(name) - 1 else ""


def _iter_video_entries(folder: Path, recursive: bool):
    """Yield (DirEntry, posix path relative to folder, resolved folder or None).

    A folder's entries come in directory order, then each subfolder depth
    first. os.scandir answers is_file()/is_dir() from the listing itself (no
    extra stat per file on Windows), and each folder is resolved once.

    hls/ subfolders are not entered: the HLS runner writes transient
    playlist*.ts chunks there while a stream runs, and they are not clips to
    offer for compression. Pointing the library AT an hls folder still lists
    it, since only subfolders below the listing root are skipped.
    """
    stack = [(str(folder), "")]
    while stack:
        dirpath, rel_prefix = stack.pop()
        try:
            with os.scandir(dirpath) as it:
                entries = list(it)
        except PermissionError:
            # rglob skipped unreadable folders silently; iterdir raised.
            if not recursive:
                raise
            continue
        try:
            resolved_dir = str(Path(dirpath).resolve())
        except (OSError, ValueError):
            resolved_dir = None

        subdirs = []
        for entry in entries:
            try:
                if recursive and entry.is_dir() and not entry.is_symlink():
                    if entry.name.lower() != "hls":
                        subdirs.append((entry.path, rel_prefix + entry.name + "/"))
                    continue
                if not entry.is_file():
                    continue
            except OSError:
                continue
            if _suffix(entry.name) in VIDEO_EXTS:
                yield entry, rel_prefix + entry.name, resolved_dir
        # Reversed so the first subfolder is popped (walked) first.
        stack.extend(reversed(subdirs))


def _walk_and_classify(folder: Path, recursive: bool) -> dict:
    """Walk one folder and classify every video in it. The expensive half.

    Returns the shape the cache stores. Classification lives here because it
    needs each file's resolved path, which is I/O.
    """
    items = []
    truncated = False
    try:
        for entry, rel, resolved_dir in _iter_video_entries(folder, recursive):
            try:
                st = os.stat(entry.path)
            except OSError:
                continue
            # A symlinked file resolves somewhere else; anything else lives
            # in its (already resolved) folder.
            if resolved_dir is not None and not entry.is_symlink():
                resolved = os.path.join(resolved_dir, entry.name)
            else:
                resolved = None
            items.append({"name": rel, "path": entry.path,
                          "size": st.st_size, "mtime": st.st_mtime,
                          "_ext": _suffix(entry.name), "_resolved": resolved})
            if len(items) >= _LIB_CACHE_CAP:
                truncated = True
                break
    except OSError as exc:
        return {"items": [], "exts": [], "truncated": False, "error": str(exc)}

    # Load the compressed index once. out_to_src maps a recorded output back to
    # its source so a compressed clip can show where it came from.
    _idx = _cidx._load()
    _entries = _idx.get("entries", {})
    out_to_src = {e.get("output", ""): e.get("source", "") for e in _entries.values()}
    _comp_dirname = _cidx.COMPRESSED_DIRNAME

    for i in items:
        path_str = i["path"]
        rp = i.pop("_resolved")
        if rp is None:
            try:
                rp = str(Path(path_str).resolve())
            except (OSError, ValueError):
                rp = path_str
        in_comp_loc = _comp_dirname in {p.lower() for p in Path(rp).parts}
        if in_comp_loc or rp in out_to_src:
            i["kind"] = "compressed"
            i["source"] = out_to_src.get(rp)
        else:
            entry = _entries.get(_cidx.signature(path_str))
            i["kind"] = "original"
            i["compressed"] = bool(
                entry and entry.get("output") and Path(entry["output"]).is_file())

    exts = sorted({i["_ext"].lstrip(".") for i in items})
    return {"items": items, "exts": exts, "truncated": truncated, "error": None}


def _cached_listing(folder: Path, recursive: bool, force: bool = False) -> dict:
    """Return the walked+classified listing for a folder, from cache if fresh.

    The lock is held across the walk on purpose, so two clients asking for the
    same cold folder do not both walk it.
    """
    key = (str(folder), bool(recursive))
    now = time.monotonic()
    with _lib_cache_lock:
        hit = _lib_cache.get(key)
        if hit and not force and (now - hit["at"]) < _LIB_CACHE_TTL_S:
            return hit

        built = _walk_and_classify(folder, recursive)
        built["at"] = now
        _lib_cache[key] = built

        # Bound the table: drop the least recently built entries.
        if len(_lib_cache) > _LIB_CACHE_MAX_FOLDERS:
            for stale in sorted(_lib_cache, key=lambda k: _lib_cache[k]["at"])[
                    :len(_lib_cache) - _LIB_CACHE_MAX_FOLDERS]:
                _lib_cache.pop(stale, None)
        return built


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
    kind = (request.args.get("kind", "all") or "all").strip().lower()
    if kind not in ("all", "original", "compressed"):
        kind = "all"
    page = max(1, _int_arg("page", 1))
    page_size = min(200, max(1, _int_arg("page_size", 60)))

    if not folder.is_dir():
        return jsonify({"folder": str(folder), "exists": False,
                        "total": 0, "videos": []})

    # Remember the folder so the Library reopens there.
    try:
        from gui.services.gui_state_persist import set_library_folder
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.gui.services.gui_state_persist import set_library_folder
    set_library_folder(str(folder))

    # Recurse by default so a parent folder finds nested clips (the walk is
    # capped). ``recursive=0`` lists the top level only.
    recursive = (request.args.get("recursive", "1") or "1").strip() not in ("0", "false", "no")
    # refresh=1 forces a rebuild past the cache TTL.
    force = (request.args.get("refresh", "") or "").strip() in ("1", "true", "yes")

    listing = _cached_listing(folder, recursive, force=force)
    all_items = listing["items"]
    exts = listing["exts"]
    truncated = listing["truncated"]
    if listing.get("error"):
        return jsonify({"folder": str(folder), "exists": True,
                        "error": listing["error"], "total": 0, "videos": []}), 200

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
        ikind = i["kind"]
        if kind != "all" and ikind != kind:
            continue
        item = {"name": i["name"], "path": i["path"],
                "size": i["size"], "mtime": i["mtime"], "kind": ikind}
        if ikind == "compressed":
            item["source"] = i.get("source")
        else:
            item["compressed"] = i.get("compressed", False)
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

    A native dialog cannot run from the frozen app (sys.executable is the
    bundled exe) or for a remote browser. This returns the immediate
    subdirectories of ``path`` plus the parent so the UI can walk the tree.
    With no path it returns the drive roots (Windows) or "/".

    Returns: {"path": str, "parent": str|null, "is_root": bool,
              "dirs": [{"name": str, "path": str}],
              "video_count": int}   # videos directly in this folder
    """
    raw = (request.args.get("path", "") or "").strip()

    # No path -> top level: drive letters on Windows, "/" elsewhere.
    if not raw:
        if os.name == "nt":
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
    # scandir answers is_dir()/is_file() without a stat per entry.
    try:
        with os.scandir(base) as it:
            entries = sorted(it, key=lambda e: e.name.lower())
    except OSError as exc:
        return jsonify({"error": str(exc), "path": str(base)}), 200
    for entry in entries:
        try:
            if entry.is_dir():
                dirs.append({"name": entry.name, "path": entry.path})
            elif entry.is_file() and _suffix(entry.name) in VIDEO_EXTS:
                video_count += 1
        except OSError:
            continue

    parent = str(base.parent) if base.parent != base else None
    # On Windows a drive root's parent is itself; expose "" so the UI can go to
    # the drive list.
    if os.name == "nt" and base.parent == base:
        parent = ""
    return jsonify({"path": str(base), "parent": parent, "is_root": False,
                    "dirs": dirs, "video_count": video_count})


@library_bp.route("/api/library/browse_folder", methods=["GET"])
def api_library_browse_folder():
    """Open a NATIVE folder picker on the host and return the chosen directory.

    Windows uses a PowerShell ``FolderBrowserDialog`` because the frozen app's
    ``sys.executable`` cannot run ``python -c``; other platforms use tkinter.
    The dialog runs in a separate process so it never blocks the Flask worker.
    Returns {"path": "..."} (empty if cancelled).
    """
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
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # ValueError covers a stdout that does not decode in the locale.
        log.warning("Library folder picker failed: %s", exc)
        path = ""
    return jsonify({"path": path})


@library_bp.route("/api/library/meta", methods=["GET"])
def api_library_meta():
    """Return ffprobe metadata (duration, dims, fps, codec) for one video."""
    p = _safe_video(request.args.get("path", ""), request.args.get("folder", ""))
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
    p = _safe_video(request.args.get("path", ""), request.args.get("folder", ""))
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
    p = _safe_video(request.args.get("path", ""), request.args.get("folder", ""))
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
    p = _safe_video(data.get("path", ""), str(data.get("folder", "") or ""))
    if p is None:
        return jsonify({"error": "not a video file"}), 400
    log.info("Library: selected %s for compression", p.name)
    return jsonify({"ok": True, "path": str(p), "name": p.name})
