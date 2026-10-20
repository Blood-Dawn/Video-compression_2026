"""
src/gui/routes/ingest_bp.py - chunked, resumable upload (R6 Track B, the M4
ingest tail).

Why not /api/upload: a phone on flaky Wi-Fi that retries a plain multipart POST
restarts at byte 0. This protocol resumes where the connection died:

    POST /api/upload/begin   {"name": "clip.mp4", "size": N}
        -> {"upload_id": hex, "offset": 0, "chunk_hint": 1048576}
    POST /api/upload/chunk?upload_id=X&offset=K   (raw bytes body)
        -> {"offset": K+len}    or 409 {"offset": current} when K is stale;
           the 409 IS the resume mechanism: the client reseeks and continues.
    GET  /api/upload/status?upload_id=X -> {"offset": current}
    POST /api/upload/finish  {"upload_id": X, "sha256": hex}
        -> verifies size, whole-file hash, and a decodable video stream, then
           moves the file into the same uploads folder the classic route uses
           and returns {"ok", "path", "filename"} for /api/start.

Temp parts live under data_dir()/upload_tmp/<upload_id>.part with a JSON
sidecar; upload_id is server-minted hex, so no client string ever becomes a
path. Author: Bloodawn (KheivenD), 2026-08-17 (R6 Track B).
"""

import hashlib
import json
import os
import re as _re
import subprocess
import threading
import time
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request

try:
    from gui.logging_setup import log
    from gui.routes.files_bp import _ALLOWED_EXTENSIONS, _upload_dir
    from utils.ffmpeg import ffprobe_path
    from utils.paths import data_dir
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.logging_setup import log
    from src.gui.routes.files_bp import _ALLOWED_EXTENSIONS, _upload_dir
    from src.utils.ffmpeg import ffprobe_path
    from src.utils.paths import data_dir

ingest_bp = Blueprint("ingest", __name__)

_ID_RE = _re.compile(r"^[a-f0-9]{16,32}$")
# 8 GB cap per upload. gui/app.py sets MAX_CONTENT_LENGTH to the same value for
# the single shot /api/upload route; keep the two in step.
_MAX_SIZE = 8 * 1024 * 1024 * 1024
CHUNK_HINT = 1024 * 1024

# Two guards:
#
# 1. A per-upload_id lock around the chunk route's read-check-write. Without
#    it, two concurrent chunks both read the same size, both pass the offset
#    check and both append, so the file can exceed the declared size.
#
# 2. Abandoned uploads (killed app, picker cancelled after /begin) would leave
#    their .part/.json pair forever. _sweep_stale_uploads() runs at the top of
#    every /begin, so no scheduler thread is needed.
_UPLOAD_TTL_SECONDS = 48 * 60 * 60  # an abandoned upload is stale after 2 days
_locks_guard = threading.Lock()
_upload_locks: dict[str, threading.Lock] = {}


def _lock_for(upload_id: str) -> threading.Lock:
    """One lock per upload_id, created under _locks_guard so two requests
    cannot create different Locks for the same id."""
    with _locks_guard:
        lock = _upload_locks.get(upload_id)
        if lock is None:
            lock = threading.Lock()
            _upload_locks[upload_id] = lock
        return lock


def _forget_lock(upload_id: str) -> None:
    """Drop a finished upload's lock so the dict stays bounded."""
    with _locks_guard:
        _upload_locks.pop(upload_id, None)


def _sweep_stale_uploads() -> None:
    """Best-effort cleanup of .part/.json pairs from uploads nobody ever
    finished. Never raises: a cleanup bug must not break a real upload."""
    try:
        tmp_dir = _tmp_dir()
        if not tmp_dir.exists():
            return
        cutoff = time.time() - _UPLOAD_TTL_SECONDS
        for meta_path in tmp_dir.glob("*.json"):
            try:
                if meta_path.stat().st_mtime >= cutoff:
                    continue
                upload_id = meta_path.stem
                part_path = meta_path.with_suffix(".part")
                part_path.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
                _forget_lock(upload_id)
                log.info("Swept stale upload: id=%s (older than %ds)", upload_id, _UPLOAD_TTL_SECONDS)
            except OSError:
                continue  # one bad entry does not stop the sweep
    except OSError:
        pass


def _safe_leaf_name(raw: str, fallback: str = "upload.mp4") -> str:
    """Return just the filename component of an untrusted client-supplied
    name, treating BOTH '/' and '\\' as directory separators on every OS.

    Path(...).name only strips the host's separator, so on a POSIX host
    (Docker/AppImage builds) "..\\..\\escape\\clip.mp4" would come back
    unchanged as one literal filename.
    """
    normalized = str(raw).replace("\\", "/")
    leaf = Path(normalized).name.strip()
    # Path.name is empty for "", ".", ".." and all-separator strings.
    return leaf if leaf not in ("", ".", "..") else fallback


def _tmp_dir() -> Path:
    d = data_dir() / "upload_tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _paths(upload_id: str):
    d = _tmp_dir()
    return d / f"{upload_id}.part", d / f"{upload_id}.json"


def _load_meta(upload_id: str):
    if not _ID_RE.match(upload_id or ""):
        return None
    part, meta = _paths(upload_id)
    try:
        return json.loads(meta.read_text(encoding="utf-8")), part
    except (OSError, json.JSONDecodeError):
        return None


def _discard(upload_id: str, part: Path) -> None:
    """Delete an upload's part file and sidecar and forget its lock."""
    part.unlink(missing_ok=True)
    _paths(upload_id)[1].unlink(missing_ok=True)
    _forget_lock(upload_id)


def _verify_video(path: Path) -> bool:
    """ffprobe decode check, same bar every other ingest path applies."""
    try:
        proc = subprocess.run(
            [ffprobe_path(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return proc.returncode == 0 and "video" in (proc.stdout or "")
    except (OSError, subprocess.SubprocessError):
        return False


@ingest_bp.route("/api/upload/begin", methods=["POST"])
def api_upload_begin():
    _sweep_stale_uploads()
    data = request.get_json(silent=True) or {}
    name = _safe_leaf_name(data.get("name", ""), fallback="")
    try:
        size = int(data.get("size", 0))
    except (TypeError, ValueError):
        size = 0
    suffix = Path(name).suffix.lower()
    if not name or suffix not in _ALLOWED_EXTENSIONS:
        return jsonify({"error": f"File type {suffix or '?'} not allowed"}), 400
    if size <= 0 or size > _MAX_SIZE:
        return jsonify({"error": "size must be positive and under 8 GB"}), 400
    upload_id = uuid.uuid4().hex[:24]
    part, meta = _paths(upload_id)
    part.write_bytes(b"")
    meta.write_text(json.dumps({"name": name, "size": size}), encoding="utf-8")
    log.info("Chunked upload begun: %s (%d bytes) id=%s", name, size, upload_id)
    return jsonify({"upload_id": upload_id, "offset": 0, "chunk_hint": CHUNK_HINT})


@ingest_bp.route("/api/upload/status", methods=["GET"])
def api_upload_status():
    got = _load_meta(request.args.get("upload_id", ""))
    if got is None:
        return jsonify({"error": "unknown upload_id"}), 404
    _meta, part = got
    return jsonify({"offset": part.stat().st_size if part.exists() else 0})


@ingest_bp.route("/api/upload/chunk", methods=["POST"])
def api_upload_chunk():
    upload_id = request.args.get("upload_id", "")
    got = _load_meta(upload_id)
    if got is None:
        return jsonify({"error": "unknown upload_id"}), 404
    meta, part = got
    try:
        offset = int(request.args.get("offset", "-1"))
    except (TypeError, ValueError):
        offset = -1
    blob = request.get_data(cache=False)
    if not blob:
        return jsonify({"error": "empty chunk"}), 400
    # The read-check-write sequence is the critical section.
    with _lock_for(upload_id):
        current = part.stat().st_size if part.exists() else 0
        if offset != current:
            # Stale offset after a dropped connection: the 409 is the resume
            # protocol.
            return jsonify({"offset": current}), 409
        if current + len(blob) > int(meta.get("size", 0)):
            return jsonify({"error": "more bytes than declared at begin"}), 413
        with open(part, "ab") as fh:
            fh.write(blob)
            fh.flush()
            os.fsync(fh.fileno())
        return jsonify({"offset": current + len(blob)})


@ingest_bp.route("/api/upload/finish", methods=["POST"])
def api_upload_finish():
    data = request.get_json(silent=True) or {}
    upload_id = str(data.get("upload_id", ""))
    got = _load_meta(upload_id)
    if got is None:
        return jsonify({"error": "unknown upload_id"}), 404
    meta, part = got
    declared = int(meta.get("size", 0))
    actual = part.stat().st_size if part.exists() else 0
    if actual != declared:
        return jsonify({"error": f"incomplete: have {actual} of {declared} bytes",
                        "offset": actual}), 400
    claimed = str(data.get("sha256", "")).lower()
    h = hashlib.sha256()
    with open(part, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    if not claimed or h.hexdigest() != claimed:
        # Corruption in transit makes the part untrustworthy at any offset, so
        # discard it instead of letting a resume preserve the damage.
        _discard(upload_id, part)
        return jsonify({"error": "sha256 mismatch; upload discarded, start over"}), 400
    if not _verify_video(part):
        _discard(upload_id, part)
        return jsonify({"error": "not a decodable video; upload discarded"}), 400
    upload_dir = _upload_dir()
    safe_name = _safe_leaf_name(meta.get("name", "upload.mp4"))
    stem, suffix = Path(safe_name).stem, Path(safe_name).suffix
    dest = upload_dir / safe_name
    counter = 1
    while dest.exists():
        dest = upload_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    part.replace(dest)
    _paths(upload_id)[1].unlink(missing_ok=True)
    _forget_lock(upload_id)
    log.info("Chunked upload finished: %s (%d bytes)", dest.name, declared)
    return jsonify({"ok": True, "path": str(dest), "filename": dest.name})
