"""
tests/test_logging_config.py

Covers src/utils/logging_config.py: setup_logging() wires the console
and JSON file handlers correctly, the JSON formatter survives weird
extras, and the setup is idempotent.

Author: Bloodawn (KheivenD), 2026-05-14.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest


# Pull the module under test. Importing it does NOT call setup_logging
# at import time; each test calls it explicitly.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from utils.logging_config import (  # noqa: E402
    setup_logging, _ConsoleFormatter, _JsonFormatter,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_logging(tmp_path):
    """Wipe root logger handlers before/after each test so they don't leak."""
    root = logging.getLogger()
    saved = list(root.handlers)
    saved_level = root.level
    for h in saved:
        root.removeHandler(h)

    yield tmp_path

    # Tear down: restore the original handlers so other tests don't see
    # the test handlers we just installed.
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in saved:
        root.addHandler(h)
    root.setLevel(saved_level)


# ── setup_logging() ───────────────────────────────────────────────────────


class TestSetupLogging:

    def test_returns_log_file_path_when_json_enabled(self, isolated_logging):
        log_dir = isolated_logging / "logs"
        path = setup_logging(level="INFO", json_file=True, log_dir=log_dir)
        assert path is not None
        assert path == log_dir / "svcs.log"
        assert log_dir.exists()

    def test_returns_none_when_json_disabled(self, isolated_logging):
        path = setup_logging(level="INFO", json_file=False)
        assert path is None

    def test_adds_console_handler(self, isolated_logging):
        setup_logging(level="INFO", json_file=False)
        root = logging.getLogger()
        # At minimum a stream handler should be present
        streams = [h for h in root.handlers
                   if isinstance(h, logging.StreamHandler)
                   and not isinstance(h, logging.FileHandler)]
        assert len(streams) >= 1

    def test_adds_file_handler_when_json_enabled(self, isolated_logging):
        log_dir = isolated_logging / "logs"
        setup_logging(level="INFO", json_file=True, log_dir=log_dir)
        root = logging.getLogger()
        file_handlers = [h for h in root.handlers
                         if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 1

    def test_level_is_respected(self, isolated_logging):
        setup_logging(level="DEBUG", json_file=False)
        assert logging.getLogger().level == logging.DEBUG

        setup_logging(level="WARNING", json_file=False)
        assert logging.getLogger().level == logging.WARNING

    def test_is_idempotent_replaces_handlers(self, isolated_logging):
        """Calling setup twice should leave us with one set, not two."""
        log_dir = isolated_logging / "logs"
        setup_logging(level="INFO", json_file=True, log_dir=log_dir)
        n_first = len(logging.getLogger().handlers)
        setup_logging(level="INFO", json_file=True, log_dir=log_dir)
        n_second = len(logging.getLogger().handlers)
        assert n_first == n_second

    def test_quiets_noisy_libraries(self, isolated_logging):
        setup_logging(level="INFO", json_file=False)
        for noisy in ("PIL", "matplotlib", "urllib3", "werkzeug",
                      "ultralytics", "easyocr", "torch"):
            assert logging.getLogger(noisy).level == logging.WARNING


# ── _ConsoleFormatter ─────────────────────────────────────────────────────


class TestConsoleFormatter:

    def test_format_includes_time_level_logger_message(self):
        fmt = _ConsoleFormatter()
        rec = logging.LogRecord(
            name="my.module", level=logging.INFO, pathname="x.py",
            lineno=1, msg="hello %s", args=("world",), exc_info=None,
        )
        out = fmt.format(rec)
        assert "INFO" in out
        assert "my.module" in out
        assert "hello world" in out

    def test_format_handles_error_level(self):
        fmt = _ConsoleFormatter()
        rec = logging.LogRecord(
            name="x", level=logging.ERROR, pathname="x.py", lineno=1,
            msg="bang", args=(), exc_info=None,
        )
        out = fmt.format(rec)
        assert "ERROR" in out


# ── _JsonFormatter ────────────────────────────────────────────────────────


class TestJsonFormatter:

    def _make_record(self, **extras):
        rec = logging.LogRecord(
            name="test", level=logging.INFO, pathname="t.py", lineno=10,
            msg="hello", args=(), exc_info=None, func="myfn",
        )
        for k, v in extras.items():
            setattr(rec, k, v)
        return rec

    def test_emits_valid_json(self):
        fmt = _JsonFormatter()
        out = fmt.format(self._make_record())
        data = json.loads(out)
        assert data["msg"] == "hello"
        assert data["level"] == "INFO"
        assert data["logger"] == "test"

    def test_required_fields_present(self):
        fmt = _JsonFormatter()
        out = fmt.format(self._make_record())
        data = json.loads(out)
        for k in ("ts", "level", "logger", "msg", "module", "func",
                  "line", "thread"):
            assert k in data, f"missing key: {k}"

    def test_extra_kwargs_become_top_level_fields(self):
        fmt = _JsonFormatter()
        rec = self._make_record(camera_id="cam_00", size_kb=512)
        out = fmt.format(rec)
        data = json.loads(out)
        assert data["camera_id"] == "cam_00"
        assert data["size_kb"] == 512

    def test_non_serializable_extra_gets_repr(self):
        fmt = _JsonFormatter()

        class Weird:
            def __repr__(self): return "<Weird>"

        rec = self._make_record(blob=Weird())
        out = fmt.format(rec)
        data = json.loads(out)
        assert data["blob"] == "<Weird>"

    def test_exception_info_serialized(self):
        fmt = _JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            rec = logging.LogRecord(
                name="x", level=logging.ERROR, pathname="x.py",
                lineno=1, msg="caught", args=(), exc_info=sys.exc_info(),
            )
        out = fmt.format(rec)
        data = json.loads(out)
        assert "exc" in data
        assert "ValueError: boom" in data["exc"]

    def test_reserved_record_attrs_not_duplicated(self):
        fmt = _JsonFormatter()
        rec = self._make_record()
        out = fmt.format(rec)
        data = json.loads(out)
        # These are stdlib LogRecord internals that should NOT show up
        # alongside our cleaner field names
        for k in ("name", "msg", "levelname", "args", "pathname"):
            if k == "msg":
                # 'msg' is our key, present
                continue
            assert k not in data, f"leaked stdlib attr: {k}"


# ── End-to-end smoke ──────────────────────────────────────────────────────


class TestEndToEnd:
    """Write a real log line, then read the JSON back and verify."""

    def test_full_roundtrip(self, isolated_logging):
        log_dir = isolated_logging / "logs"
        path = setup_logging(level="INFO", json_file=True, log_dir=log_dir)
        assert path is not None

        log = logging.getLogger("test.roundtrip")
        log.info("encode finished",
                 extra={"camera_id": "cam_42", "size_kb": 1234})

        # Force flush
        for h in logging.getLogger().handlers:
            h.flush()

        lines = path.read_text().splitlines()
        assert lines, "no log line written"
        last = json.loads(lines[-1])
        assert last["msg"] == "encode finished"
        assert last["camera_id"] == "cam_42"
        assert last["size_kb"] == 1234
        assert last["logger"] == "test.roundtrip"
