"""
src/gui/routes/savings_bp.py

GET /api/savings - how much space compression actually saved (M2.3).

Why this exists at all: nothing server-side recorded a savings figure. The
pipeline writes each segment's size to the metadata DB but never records what
the input was worth, and `_record_job_history` omits bytes_in/bytes_out for
pipeline runs entirely. The desktop dashboard therefore derives its headline
ratio in JavaScript as:

    raw = duration_s * width * height * 3 * fps        (files.js:177)
    ratio = raw / compressed

That is the size of the clip as RAW UNCOMPRESSED RGB frames, which for 1080p30
over 60s is about 11 GB, and it is where the "277.8x smaller" figure in the
mobile mockup comes from.

The problem is not that the arithmetic is wrong, it is that the number answers a
question nobody asked. A camera never delivers raw RGB; it delivers H.264
already. So most of that 277x is "video compression exists", not "SVCS shrank
your files". An operator reading "277x smaller" on a dashboard will reasonably
conclude SVCS did that, and it did not.

So this endpoint reports the two things separately and refuses to blend them:

  * ``measured`` - REAL source-versus-output bytes, only for files SVCS actually
    compressed from an existing file. This is the honest "we made it smaller"
    number. No schema change was needed: compressed_index signatures are
    ``<path>|<size>|<mtime>``, so the source size at compression time is already
    recorded, and the output size is on disk.
  * ``recorded`` - total bytes the recording pipeline has written. There is no
    source file for a live camera capture, so no ratio is offered here. Reporting
    one would mean inventing the denominator.

Author: Bloodawn (KheivenD), 2026-07-19 (M2.3).
"""

from pathlib import Path

from flask import Blueprint, jsonify

try:
    from utils import compressed_index as _cidx
    from utils.db.schema import get_connection
    from gui.services.db_helpers import _get_db_path
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils import compressed_index as _cidx
    from src.utils.db.schema import get_connection
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


def measured_savings() -> dict:
    """Real source-versus-output totals over files SVCS compressed.

    Only counts entries whose output still exists on disk: a compressed file the
    user has since deleted did not save them anything, and retention purges do
    delete them.
    """
    files = 0
    source_bytes = 0
    output_bytes = 0
    try:
        entries = (_cidx._load().get("entries", {}) or {}).values()
    except Exception:  # noqa: BLE001 - a broken index must not 500 the endpoint
        entries = []

    for e in entries:
        out = (e or {}).get("output") or ""
        sig = (e or {}).get("signature") or ""
        if not out or not sig:
            continue
        try:
            p = Path(out)
            if not p.is_file():
                continue
            osz = p.stat().st_size
        except OSError:
            continue
        ssz = _parse_source_size(sig)
        # A source size of 0 means the signature was written for a file that
        # could not be stat'd. Counting it would make the saving look larger
        # than it was, so skip the pair entirely.
        if ssz <= 0 or osz <= 0:
            continue
        files += 1
        source_bytes += ssz
        output_bytes += osz

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
            # Column names are the SCHEMA ones (file_size in bytes, duration in
            # seconds); the API layer renames them for its own payloads, and
            # querying the renamed forms here would silently return zeros.
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
        # Spelled out so a client cannot accidentally present the recording
        # total as a compression achievement.
        "note": (
            "measured covers files compressed from an existing source, where "
            "both sizes are known. recorded covers live capture, which has no "
            "source file and therefore no ratio."
        ),
    })
