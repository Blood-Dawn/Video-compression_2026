"""
src/gui/logging_setup.py

Logging wiring for the Flask dashboard, extracted from ``gui/app.py``.

Owns the three handlers (SSE queue, plain file, console), the root logger
configuration, and the atexit shutdown marker. The file handler and
``_write_shutdown_log`` live together so the marker always lands in
``svcs.log``.

Import layer: this module imports only ``gui.state`` and ``utils.paths``;
nothing in the ``services``/``routes`` layers may be imported here.

Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - logging extraction).
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

    Each record gets a monotonic event ID so SSE clients can resume after a
    reconnect without duplicates. ``state._log_id`` is rebound on every record,
    so it is read through the ``state`` module; a plain import would bind a
    stale copy.
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


# The log file lives in the platform cache dir: an installed app cannot write
# beside itself.
# Author: Bloodawn (KheivenD), 2026-05-14 (installer prep + logging fix).
_LOG_FMT = logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s: %(message)s")

_queue_handler = _QueueLogHandler()
_queue_handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s"))

_LOG_FILE = _paths.cache_dir() / "logs" / "svcs.log"
_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
_file_handler = logging.FileHandler(str(_LOG_FILE), encoding="utf-8")
_file_handler.setFormatter(_LOG_FMT)

_console_handler = logging.StreamHandler(sys.stderr)
_console_handler.setFormatter(_LOG_FMT)

_root_logger = logging.getLogger()
_root_logger.addHandler(_queue_handler)
_root_logger.addHandler(_file_handler)
_root_logger.addHandler(_console_handler)
_root_logger.setLevel(logging.DEBUG)   # filtered per handler below

# INFO+ to the browser SSE stream and the terminal; DEBUG goes to the file only.
_queue_handler.setLevel(logging.INFO)
_console_handler.setLevel(logging.INFO)
_file_handler.setLevel(logging.DEBUG)

# Quiet noisy third-party libraries so the SSE log isn't drowned.
for _noisy in ("PIL", "matplotlib", "urllib3", "werkzeug",
               "ultralytics", "easyocr", "torch"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# The name stays "gui.app" so existing log lines and filters read the same.
log = logging.getLogger("gui.app")


def _write_shutdown_log():
    """Write a clean shutdown marker to the log file on process exit.

    atexit can fire after a test runner closed stdout/stderr, and
    Handler.emit() catches that ValueError itself and prints "--- Logging
    error ---", so handlers on closed streams are detached before logging. The
    file handler stays, so the marker still lands in svcs.log.
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
