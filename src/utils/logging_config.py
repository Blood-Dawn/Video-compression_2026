"""
src/utils/logging_config.py

One place to configure logging for the whole SVCS app.

What this does:
  * Console output: human-readable, single-line per record. The kind
    of thing a developer wants to skim while running ``python
    run_gui.py`` in a terminal.
  * File output: JSON Lines, one record per line. Goes to
    ``<cache_dir>/logs/svcs-YYYYMMDD.log`` with daily rotation.
    Structured fields make this easy to grep, ship to Sentry / a SaaS
    log aggregator, or post-process with jq.
  * Stdlib ``logging`` everywhere. We deliberately do NOT pull in
    structlog as a dependency because the stdlib formatter is good
    enough and one less dep is one less thing to ship.

Why bother:
  * ``print()`` calls in long-running services lose timestamps and
    levels. They're impossible to filter or aggregate.
  * Crash reporting (Sentry hookup, future work) consumes stdlib
    ``logging`` events natively. Build the structured layer once and
    Sentry slots in for free later.

Usage:

    from utils.logging_config import setup_logging
    setup_logging(level="INFO", json_file=True)

    import logging
    log = logging.getLogger(__name__)
    log.info("Pipeline starting", extra={"camera_id": "cam_00", "mode": "mode2"})

Author: Bloodawn (KheivenD), 2026-05-14 (audit cleanup, code smell E).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Console formatter: human-readable single-line ─────────────────────────

class _ConsoleFormatter(logging.Formatter):
    """Friendly single-line output for the developer terminal."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        msg = record.getMessage()
        level = record.levelname.ljust(5)
        name = record.name
        return f"{ts} {level} {name}  {msg}"


# ── JSON-lines formatter: one record per line, machine-readable ───────────

class _JsonFormatter(logging.Formatter):
    """Structured output for the rotating log file.

    Each record becomes a single JSON object with stable keys. Any
    ``extra=`` kwargs passed to the logger call show up as additional
    top-level fields, so adding context is trivial:

        log.info("Encoded segment", extra={"camera_id": cam, "size_kb": sz})

    Author: Bloodawn (KheivenD).
    """

    _RESERVED = {
        "name", "msg", "args", "levelname", "levelno", "pathname",
        "filename", "module", "exc_info", "exc_text", "stack_info",
        "lineno", "funcName", "created", "msecs", "relativeCreated",
        "thread", "threadName", "processName", "process", "message",
        "taskName",  # 3.12+
    }

    def format(self, record: logging.LogRecord) -> str:
        # Base record fields
        out = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
            "thread": record.threadName,
        }
        # Anything attached via extra=... ends up on the record dict
        # but is not in _RESERVED. Pull it out as top-level JSON fields.
        for k, v in record.__dict__.items():
            if k in self._RESERVED or k.startswith("_"):
                continue
            try:
                json.dumps(v)  # is it JSON-serializable?
                out[k] = v
            except (TypeError, ValueError):
                out[k] = repr(v)
        # Exception info, if any
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


# ── Public entry point ────────────────────────────────────────────────────


def setup_logging(
    level: str = "INFO",
    json_file: bool = True,
    log_dir: Optional[Path] = None,
) -> Path | None:
    """Configure root logger with console + optional rotating JSON file.

    Idempotent: calling twice replaces the handlers cleanly, useful in
    test suites that re-enter the entry point.

    Args:
        level: log level for both handlers ("DEBUG", "INFO", "WARNING", ...).
        json_file: if True, also writes JSONL to a daily-rotating file
                   under ``log_dir``. Defaults to the platform cache dir
                   under ``logs/``.
        log_dir: explicit log directory override. None means use the
                 cache dir from src.utils.paths.

    Returns:
        Path to the active log file, or None when json_file=False.

    Author: Bloodawn (KheivenD), 2026-05-14.
    """
    root = logging.getLogger()
    # Clear any pre-existing handlers from a prior call or third-party setup.
    for h in list(root.handlers):
        root.removeHandler(h)

    root.setLevel(level.upper())

    # ── Console handler (stderr, human format) ────────────────────────
    ch = logging.StreamHandler(stream=sys.stderr)
    ch.setLevel(level.upper())
    ch.setFormatter(_ConsoleFormatter())
    root.addHandler(ch)

    log_file: Path | None = None
    if json_file:
        # Resolve the log directory. Importing lazily so tests can call
        # setup_logging() without the paths module being importable.
        if log_dir is None:
            try:
                from utils.paths import cache_dir
            except ImportError:
                from src.utils.paths import cache_dir
            log_dir = cache_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "svcs.log"

        fh = logging.handlers.TimedRotatingFileHandler(
            log_file,
            when="midnight",
            backupCount=7,        # keep one week of history
            encoding="utf-8",
            utc=True,
        )
        fh.setLevel(level.upper())
        fh.setFormatter(_JsonFormatter())
        root.addHandler(fh)

    # Quiet the libraries that flood DEBUG by default.
    for noisy in (
        "PIL", "matplotlib", "urllib3", "asyncio", "werkzeug",
        "ultralytics", "easyocr", "torch",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return log_file
