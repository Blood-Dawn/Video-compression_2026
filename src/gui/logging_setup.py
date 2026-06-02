"""
src/gui/logging_setup.py

Logging wiring for the Flask dashboard, extracted from ``gui/app.py``.

Owns the three handlers (SSE queue, rotating-less file, console), the root
logger configuration, and the atexit shutdown marker. The file handler and
``_write_shutdown_log`` deliberately live together so the shutdown marker is
guaranteed to land in ``svcs.log`` (atexit ordering — see REFACTOR-PLAN §5).

Import layer: this module imports ``gui.state`` (for the live-log ring
buffers and the rebound ``_log_id`` counter) and ``utils.paths`` (for the
cache directory). Nothing in the ``services``/``routes`` layers may be
imported here — the direction is one-way.

Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — logging extraction).
"""

import atexit
import logging
import queue
import sys
from datetime import datetime

try:
    from gui import state
except ModuleNotFoundError:                # pragma: no cover - import path shim
    from src.gui import state

try:
    from utils import paths as _paths
except ModuleNotFoundError:                # pragma: no cover - import path shim
    from src.utils import paths as _paths


class _QueueLogHandler(logging.Handler):
    """Forwards log records to the shared queue for SSE streaming.

    Each record is stamped with a monotonic event ID so SSE clients can
    resume without replaying duplicate lines after a reconnect.

    The ID counter (``state._log_id``) is *rebound* on every record, so it is
    referenced through the ``state`` module rather than a local import — a
    plain ``from gui.state import _log_id`` would bind a stale copy.
    """

    def emit(self, record: logging.LogRecord) -> None:
        line = self.format(record)
        with state._log_lock:
            state._log_id += 1
            item = (state._log_id, line)
            state._log_history.append(item)
        try:
            state._log_queue.put_nowait(item)
        except queue.Full:
            pass  # drop oldest; client will re-fetch on reconnect


# ── Log formatter and handlers ────────────────────────────────────────────────
# Log file lives in the platform cache dir, not next to the user's video
# outputs. Required for any real installer to work on Windows / macOS.
# Also fixes a pre-existing bug where the console handler was defined
# but never attached to the root logger.
# Author: Bloodawn (KheivenD), 2026-05-14 (installer prep + logging fix).
_LOG_FMT = logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s: %(message)s")

# Queue handler: forwards records to the SSE stream for the browser
_queue_handler = _QueueLogHandler()
_queue_handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s"))

# File handler: writes all records to <cache_dir>/logs/svcs.log for
# offline debugging. Was previously in outputs/svcs.log under the user's
# video output folder, which breaks installed-app sandboxes.
_LOG_FILE = _paths.cache_dir() / "logs" / "svcs.log"
_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
_file_handler = logging.FileHandler(str(_LOG_FILE), encoding="utf-8")
_file_handler.setFormatter(_LOG_FMT)

# Console handler: mirrors to terminal
_console_handler = logging.StreamHandler(sys.stderr)
_console_handler.setFormatter(_LOG_FMT)

_root_logger = logging.getLogger()
_root_logger.addHandler(_queue_handler)
_root_logger.addHandler(_file_handler)
_root_logger.addHandler(_console_handler)   # bug fix: was defined but never added
_root_logger.setLevel(logging.DEBUG)   # capture DEBUG level; filter per-handler below

# Only forward INFO+ to browser SSE and terminal (DEBUG goes to file only)
_queue_handler.setLevel(logging.INFO)
_console_handler.setLevel(logging.INFO)
_file_handler.setLevel(logging.DEBUG)

# Quiet down noisy third-party libraries so the SSE log isn't drowned.
for _noisy in ("PIL", "matplotlib", "urllib3", "werkzeug",
               "ultralytics", "easyocr", "torch"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# Keep the logger name stable as "gui.app" so existing log lines / filters
# read identically after the split (this module is gui.logging_setup).
log = logging.getLogger("gui.app")


def _write_shutdown_log():
    """Write a clean shutdown marker to the log file on process exit.

    Guards against the case where atexit fires after the test runner (or
    any parent process) has already closed stdout/stderr. The naive
    approach of wrapping log.info() in try/except doesn't work, because
    Python's logging.Handler.emit() catches the ValueError internally and
    routes it to its own error-handling path (printing "--- Logging
    error ---" to stderr). To actually silence that, we have to detach
    handlers whose underlying stream is already closed BEFORE logging.
    The file handler is preserved either way so the shutdown marker
    still lands in svcs.log.
    """
    try:
        root = logging.getLogger()
        for h in list(root.handlers):
            stream = getattr(h, "stream", None)
            if stream is not None and getattr(stream, "closed", False):
                root.removeHandler(h)
    except Exception:  # noqa: BLE001  shutdown best-effort
        pass
    try:
        log.info("=" * 60)
        log.info("SVCS SERVER SHUTDOWN: %s",
                 datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
        log.info("=" * 60)
    except (ValueError, OSError):
        pass
    try:
        _file_handler.flush()
    except (ValueError, OSError):
        pass


atexit.register(_write_shutdown_log)
