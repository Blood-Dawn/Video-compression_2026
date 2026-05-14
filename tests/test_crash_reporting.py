"""
tests/test_crash_reporting.py

Guards the opt-in semantics of src/utils/crash_reporting.py.

Critical invariants this test suite protects:
  1. With NO env vars set, init_crash_reporting() returns False and
     no traces are sent. The casual install must never phone home.
  2. SVCS_ENABLE_SENTRY=1 without SENTRY_DSN is still a no-op.
  3. Both flags set + sentry-sdk installed -> Sentry initialized.
  4. capture_exception() is a no-op when Sentry isn't enabled — it
     must never raise, even if called with a non-Exception.

Author: Bloodawn (KheivenD), 2026-05-14 (audit item: crash reporting).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _reimport_crash_reporting():
    """Fresh import to reset the module-level _SENTRY_ENABLED flag."""
    for k in list(sys.modules):
        if k == "utils.crash_reporting" or k.startswith("utils.crash_reporting."):
            del sys.modules[k]
    from utils import crash_reporting
    return crash_reporting


# ── Defaults — must be off ─────────────────────────────────────────────────


class TestDefaultsAreOff:

    def test_no_env_vars_returns_false(self, monkeypatch):
        monkeypatch.delenv("SVCS_ENABLE_SENTRY", raising=False)
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        cr = _reimport_crash_reporting()
        assert cr.init_crash_reporting() is False
        assert cr.is_enabled() is False

    def test_capture_exception_is_safe_no_op_when_disabled(self, monkeypatch):
        monkeypatch.delenv("SVCS_ENABLE_SENTRY", raising=False)
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        cr = _reimport_crash_reporting()
        # Must not raise even though Sentry isn't initialized.
        cr.capture_exception(ValueError("nothing should happen"))


# ── Opt-in flag without DSN is still a no-op ───────────────────────────────


class TestPartialOptInIsOff:

    def test_flag_set_but_dsn_empty(self, monkeypatch):
        monkeypatch.setenv("SVCS_ENABLE_SENTRY", "1")
        monkeypatch.setenv("SENTRY_DSN", "")
        cr = _reimport_crash_reporting()
        assert cr.init_crash_reporting() is False

    def test_flag_set_but_dsn_unset(self, monkeypatch):
        monkeypatch.setenv("SVCS_ENABLE_SENTRY", "1")
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        cr = _reimport_crash_reporting()
        assert cr.init_crash_reporting() is False

    def test_dsn_set_but_flag_off(self, monkeypatch):
        """DSN present without the explicit opt-in flag must not enable."""
        monkeypatch.setenv("SENTRY_DSN", "https://fake@example.com/1")
        monkeypatch.delenv("SVCS_ENABLE_SENTRY", raising=False)
        cr = _reimport_crash_reporting()
        assert cr.init_crash_reporting() is False


# ── Truthy variants of the opt-in flag ─────────────────────────────────────


class TestTruthyEnvParsing:

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 "])
    def test_truthy_values_recognized(self, monkeypatch, value):
        monkeypatch.setenv("SVCS_ENABLE_SENTRY", value)
        monkeypatch.setenv("SENTRY_DSN", "https://fake@example.com/1")
        cr = _reimport_crash_reporting()

        # Force the sentry import to succeed with a stub so we don't
        # actually phone home in CI. The stub records that init() was
        # called with our expected kwargs.
        sentry_stub = mock.MagicMock()
        with mock.patch.dict(sys.modules, {"sentry_sdk": sentry_stub}):
            ok = cr.init_crash_reporting(release="test", environment="dev")
        assert ok is True
        assert sentry_stub.init.called

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "anything"])
    def test_falsy_values_keep_it_off(self, monkeypatch, value):
        monkeypatch.setenv("SVCS_ENABLE_SENTRY", value)
        monkeypatch.setenv("SENTRY_DSN", "https://fake@example.com/1")
        cr = _reimport_crash_reporting()
        assert cr.init_crash_reporting() is False


# ── SDK missing is gracefully handled ──────────────────────────────────────


class TestSdkMissingIsGraceful:

    def test_missing_sentry_sdk_is_no_op(self, monkeypatch):
        monkeypatch.setenv("SVCS_ENABLE_SENTRY", "1")
        monkeypatch.setenv("SENTRY_DSN", "https://fake@example.com/1")
        cr = _reimport_crash_reporting()

        # Patch the import to raise ImportError as if the SDK weren't
        # installed in this venv.
        orig_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

        def _fail_import(name, *a, **kw):
            if name == "sentry_sdk" or name.startswith("sentry_sdk."):
                raise ImportError("nope")
            return orig_import(name, *a, **kw)

        with mock.patch("builtins.__import__", side_effect=_fail_import):
            assert cr.init_crash_reporting() is False


# ── Initialization passes PII-off and traces=0 defaults ────────────────────


class TestSensibleDefaults:

    def test_pii_off_and_traces_disabled_by_default(self, monkeypatch):
        monkeypatch.setenv("SVCS_ENABLE_SENTRY", "1")
        monkeypatch.setenv("SENTRY_DSN", "https://fake@example.com/1")
        cr = _reimport_crash_reporting()

        sentry_stub = mock.MagicMock()
        with mock.patch.dict(sys.modules, {"sentry_sdk": sentry_stub}):
            cr.init_crash_reporting(release="v0.1.0", environment="prod")

        kwargs = sentry_stub.init.call_args.kwargs
        assert kwargs["send_default_pii"] is False
        assert kwargs["traces_sample_rate"] == 0.0
        assert kwargs["include_local_variables"] is False
        assert kwargs["release"] == "v0.1.0"
        assert kwargs["environment"] == "prod"


# ── Idempotency ────────────────────────────────────────────────────────────


class TestIdempotency:

    def test_calling_init_twice_only_inits_once(self, monkeypatch):
        monkeypatch.setenv("SVCS_ENABLE_SENTRY", "1")
        monkeypatch.setenv("SENTRY_DSN", "https://fake@example.com/1")
        cr = _reimport_crash_reporting()

        sentry_stub = mock.MagicMock()
        with mock.patch.dict(sys.modules, {"sentry_sdk": sentry_stub}):
            assert cr.init_crash_reporting() is True
            assert cr.init_crash_reporting() is True  # second call is no-op

        assert sentry_stub.init.call_count == 1
