"""
tests/test_launcher_host.py

Guards the frozen-app launcher host binding.

The dashboard auth gate (TASK 4.4) refuses to start on a non-localhost bind
without credentials. The double-click desktop app must therefore bind localhost,
or it would exit on launch. installer/launcher.py splices "--host 127.0.0.1" into
argv when frozen (unless the user already passed a host).

Author: Bloodawn (KheivenD), 2026-06-03 (FIX round 1 - frozen launch fix).
"""

import importlib.util
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).parent.parent / "installer" / "launcher.py"


def _load():
    spec = importlib.util.spec_from_file_location("svcs_launcher_test", LAUNCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_frozen_binds_localhost(monkeypatch):
    m = _load()
    monkeypatch.setattr(m.sys, "frozen", True, raising=False)
    monkeypatch.setattr(m.sys, "argv", ["SVCS.exe"])
    m._set_frozen_env()
    assert "--host" in m.sys.argv
    i = m.sys.argv.index("--host")
    assert m.sys.argv[i + 1] == "127.0.0.1"
    assert "--no-sync" in m.sys.argv


def test_frozen_respects_explicit_host(monkeypatch):
    m = _load()
    monkeypatch.setattr(m.sys, "frozen", True, raising=False)
    monkeypatch.setattr(m.sys, "argv", ["SVCS.exe", "--host", "0.0.0.0"])
    m._set_frozen_env()
    assert m.sys.argv.count("--host") == 1  # not doubled
    i = m.sys.argv.index("--host")
    assert m.sys.argv[i + 1] == "0.0.0.0"


def test_source_mode_does_not_force_host(monkeypatch):
    m = _load()
    monkeypatch.setattr(m.sys, "frozen", False, raising=False)
    monkeypatch.setattr(m.sys, "argv", ["x"])
    m._set_frozen_env()
    assert "--host" not in m.sys.argv
