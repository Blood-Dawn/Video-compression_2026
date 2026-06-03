"""
src/gui/routes/sse_bp.py

sse routes blueprint, carved from gui/app.py (TASK 1.3).
Pure relocation: every URL, method, and response shape is unchanged.
Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - blueprints).
"""

import queue
import json
from flask import Blueprint, request, Response

try:
    from gui.state import (_log_queue, _log_history, _log_lock)
    from gui.logging_setup import log
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.state import (_log_queue, _log_history, _log_lock)
    from src.gui.logging_setup import log

sse_bp = Blueprint("sse", __name__)

@sse_bp.route("/api/logs")
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


