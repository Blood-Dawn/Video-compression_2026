"""
src/gui/routes/savings_bp.py

GET /api/savings - how much space compression actually saved.

The dashboard's headline ratio is computed in JavaScript against the size of
the clip as raw uncompressed RGB frames. A camera never delivers raw RGB (it
delivers H.264), so most of that ratio is "video compression exists", not
"SVCS shrank your files". This endpoint reports two things separately and
never blends them:

  * ``measured``: real source-versus-output bytes, only for files SVCS
    compressed from an existing file. compressed_index signatures are
    ``<path>|<size>|<mtime>``, so the source size is already recorded and the
    output size is on disk.
  * ``recorded``: total bytes the recording pipeline has written. A live
    capture has no source file, so no ratio is offered; it would need an
    invented denominator.

Author: Bloodawn (KheivenD), 2026-07-19 (M2.3).
"""

import stat
import subprocess
from pathlib import Path

from flask import Blueprint, jsonify, request

try:
    from utils import compressed_index as _cidx
    from utils.db.schema import get_connection
    from utils.ffmpeg import ffprobe_path
    from utils.result_numbers import format_result, plan_segments, summarize_result
    from gui.services import path_safety as _ps
    from gui.services.db_helpers import _get_db_path
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils import compressed_index as _cidx
    from src.utils.db.schema import get_connection
    from src.utils.ffmpeg import ffprobe_path
    from src.utils.result_numbers import format_result, plan_segments, summarize_result
    from src.gui.services import path_safety as _ps
    from src.gui.services.db_helpers import _get_db_path

savings_bp = Blueprint("savings", __name__)


def _parse_source_size(signature: str) -> int:
    """Recover the source size from a compressed_index signature.

    Signatures are "<path>|<size>|<mtime>". Returns 0 when the signature is the
    path-only fallback form the index writes for a missing file, so an
    unreadable entry contributes nothing rather than corrupting the total.
    """
    try:
        parts = signature.rsplit("|", 2)
        if len(parts) == 3:
            return max(0, int(parts[1]))
    except (ValueError, AttributeError):
        pass
    return 0


def _result_block(source_bytes: int, output_bytes: int) -> dict:
    """The numbers and the sentences the dashboard shows, from one algorithm."""
    r = summarize_result([(source_bytes, output_bytes)])
    r.update(format_result(r))
    return r


def _output_size(entry: dict, on_disk: int) -> int:
    """Combined output size of a job: a split job recorded all its files."""
    try:
        recorded = int((entry or {}).get("output_bytes") or 0)
    except (TypeError, ValueError):
        recorded = 0
    return recorded if recorded > 0 else on_disk


def measured_savings() -> dict:
    """Real source-versus-output totals over files SVCS compressed.

    Only counts entries whose output still exists on disk: a compressed file the
    user has since deleted did not save them anything, and retention purges do
    delete them.
    """
    files = 0
    source_bytes = 0
    output_bytes = 0
    last_when = -1.0
    last = None
    try:
        entries = (_cidx._load().get("entries", {}) or {}).values()
    except Exception:  # noqa: BLE001 - a broken index must not 500 the endpoint
        entries = []

    for e in entries:
        out = (e or {}).get("output") or ""
        sig = (e or {}).get("signature") or ""
        if not out or not sig:
            continue
        # One stat per entry: is_file() followed by stat() paid for two.
        try:
            st = Path(out).stat()
        except (OSError, ValueError):
            continue
        if not stat.S_ISREG(st.st_mode):
            continue
        osz = _output_size(e, st.st_size)
        ssz = _parse_source_size(sig)
        # A source size of 0 means the signature was written for a file that
        # could not be stat'd; counting it would overstate the saving.
        if ssz <= 0 or osz <= 0:
            continue
        files += 1
        source_bytes += ssz
        output_bytes += osz
        when = float((e or {}).get("when") or 0)
        if when >= last_when:
            last_when = when
            last = (Path(out).name, ssz, osz)

    saved = max(0, source_bytes - output_bytes)
    ratio = (source_bytes / output_bytes) if output_bytes else None
    pct = (saved / source_bytes * 100.0) if source_bytes else None
    return {
        "files": files,
        "source_bytes": source_bytes,
        "output_bytes": output_bytes,
        "saved_bytes": saved,
        "ratio": round(ratio, 2) if ratio else None,
        "saved_pct": round(pct, 1) if pct is not None else None,
        # One set of display numbers for the totals and for the newest job,
        # so every screen shows the same figures.
        "result": _result_block(source_bytes, output_bytes) if files else None,
        "last": ({"name": last[0], **_result_block(last[1], last[2])}
                 if last else None),
    }


def recorded_totals() -> dict:
    """Bytes the recording pipeline has written, with NO ratio.

    A live camera capture has no source file, so any "x smaller" here would need
    an invented denominator. The size and duration are real; the comparison is
    deliberately absent.
    """
    segments = 0
    out_bytes = 0
    hours = 0.0
    try:
        db = _get_db_path()
        if db.exists():
            # Schema column names (file_size bytes, duration seconds); the API
            # layer's renamed forms would silently return zeros here.
            with get_connection(str(db)) as conn:
                row = conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(file_size), 0), "
                    "COALESCE(SUM(duration), 0) FROM segments"
                ).fetchone()
            if row:
                segments = int(row[0] or 0)
                out_bytes = int(row[1] or 0)
                hours = float(row[2] or 0) / 3600.0
    except Exception:  # noqa: BLE001 - never 500 a read-only summary
        pass
    return {
        "segments": segments,
        "output_bytes": out_bytes,
        "duration_hours": round(hours, 2),
    }


@savings_bp.route("/api/savings", methods=["GET"])
def api_savings():
    """Report compression savings, separating measured from merely recorded."""
    measured = measured_savings()
    recorded = recorded_totals()
    return jsonify({
        "measured": measured,
        "recorded": recorded,
        # Keeps a client from presenting the recording total as a saving.
        "note": (
            "measured covers files compressed from an existing source, where "
            "both sizes are known. recorded covers live capture, which has no "
            "source file and therefore no ratio."
        ),
    })


def _probe_duration(path: Path):
    """Length of a video in seconds from ffprobe, or None if it cannot be read."""
    try:
        out = subprocess.run(
            [ffprobe_path(), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=20,
        )
        value = float((out.stdout or "").strip().splitlines()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None
    return value if value > 0 else None


@savings_bp.route("/api/segment-plan", methods=["GET"])
def api_segment_plan():
    """Segment length choices for a file (``path``) or a live source (no path).

    The default is the whole video as one file; the recommendation is half of
    it. Paths are confined to the allowed media roots like every other route
    that reads a caller-supplied path.
    """
    raw = (request.args.get("path") or "").strip()
    if not raw:
        return jsonify(plan_segments(None))
    target = Path(raw).resolve()
    if not _ps.is_path_allowed(target, _ps.allowed_media_roots()):
        return jsonify({"error": "Path is outside the allowed media folders."}), 403
    if not target.is_file():
        return jsonify({"error": "File not found."}), 404
    duration = _probe_duration(target)
    if duration is None:
        return jsonify({"error": "The video length could not be read."}), 422
    plan = plan_segments(duration)
    plan["duration_s"] = round(duration, 1)
    plan["source_bytes"] = target.stat().st_size
    return jsonify(plan)
