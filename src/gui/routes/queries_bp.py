"""
src/gui/routes/queries_bp.py

queries routes blueprint, carved from gui/app.py (TASK 1.3).
Pure relocation: every URL, method, and response shape is unchanged.
Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - blueprints).
"""

from flask import Blueprint, jsonify, request

try:
    from gui.state import (_demo_lock, _demo_state)
    from gui.services.gui_state_persist import _load_gui_state
    from gui.services.db_helpers import _get_archive_db_path, _rows_to_segment_list
    from gui.services.demo_runner import _run_demo_thread
    from utils.db import (query_by_type, query_daily_storage_summary, query_segments_by_target_count)
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.state import (_demo_lock, _demo_state)
    from src.gui.services.gui_state_persist import _load_gui_state
    from src.gui.services.db_helpers import _get_archive_db_path, _rows_to_segment_list
    from src.gui.services.demo_runner import _run_demo_thread
    from src.utils.db import (query_by_type, query_daily_storage_summary, query_segments_by_target_count)

queries_bp = Blueprint("queries", __name__)

@queries_bp.route("/api/query_segments")
def api_query_segments():
    """Filter segments by object_type (and optionally camera_id, time range).

    Query params:
        object_type  - required (e.g. 'vehicle', 'person', 'unknown')
        camera_id    - optional
        start_time   - optional ISO-style timestamp prefix
        end_time     - optional ISO-style timestamp prefix
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


@queries_bp.route("/api/daily_summary")
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


@queries_bp.route("/api/busiest")
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


