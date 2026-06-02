"""
tests/test_gui_state_reexports.py

Guard test for the M1 gui refactor (TASK 1.1).

When `gui/app.py` was split into `gui/state.py` + `gui/logging_setup.py`, the
private names that `tests/test_gui_api.py` and `run_gui.py` reach for via
`gui.app.<name>` had to keep resolving through `gui.app`. This test pins that
contract so a future move can't silently break it:

  * every re-exported name resolves via `gui.app`;
  * the mutable containers are the SAME object on `gui.app` and `gui.state`
    (so in-place mutation round-trips for free);
  * the one *rebound* scalar (`_log_id`) round-trips reads AND writes in both
    directions through the forwarding module class installed in `app.py`.

Modules are resolved *live* inside each test via importlib, because
`tests/test_default_output_dir.py` deletes `gui.app` from `sys.modules` and
re-imports it per test — a module captured at collection time would be stale
depending on test order. Resolving live keeps this guard order-independent.

Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — re-export safety net).
"""

import importlib
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _gui_app():
    return importlib.import_module("gui.app")


def _gui_state():
    return importlib.import_module("gui.state")


def _gui_logging():
    return importlib.import_module("gui.logging_setup")


# Mutable state objects re-exported from gui.state as the SAME object.
SHARED_STATE_NAMES = [
    "_state_lock", "_status",
    "_power_lock", "_power_state",
    "_demo_lock", "_demo_state",
    "_hls_lock", "_hls_state", "_hls_frame_ts_dq", "_hls_segment_latencies",
    "_log_queue", "_log_history", "_log_lock",
    "_VALID_MODES", "_VALID_BG", "_VALID_DEVICES", "_VALID_MODELS",
    "_CLOUD_SUBFOLDER", "_SAFE_FILENAME_RE", "_ALLOWED_EXTENSIONS",
]

# Names forwarded to gui.state because they are rebound, not mutated in place.
FORWARDED_NAMES = ["_log_id"]

# Names re-exported from gui.logging_setup.
LOGGING_NAMES = ["log", "_LOG_FILE"]

# Private names the legacy gui.app.* contract must keep exposing (REFACTOR-PLAN
# §0). Some (e.g. _pipeline_thread) still live in app.py for now; this asserts
# the whole surface resolves regardless of which module currently owns it.
CONTRACT_NAMES = [
    "_state_lock", "_status", "_pipeline_thread", "_stop_event",
    "_run_pipeline_thread", "_demo_lock", "_demo_state", "_hls_lock",
    "_hls_state", "_hls_frame_ts_dq", "_hls_segment_latencies",
    "_default_output_dir", "_CLOUD_SUBFOLDER",
]


@pytest.mark.parametrize("name", SHARED_STATE_NAMES)
def test_shared_name_is_same_object(name):
    """Re-exported state objects are identical on gui.app and gui.state."""
    gui_app, gui_state = _gui_app(), _gui_state()
    assert hasattr(gui_app, name), f"gui.app is missing {name!r}"
    assert hasattr(gui_state, name), f"gui.state is missing {name!r}"
    assert getattr(gui_app, name) is getattr(gui_state, name), (
        f"{name!r} is not the same object on gui.app and gui.state"
    )


@pytest.mark.parametrize("name", CONTRACT_NAMES)
def test_legacy_contract_name_resolves(name):
    """Every private name the test/legacy contract relies on resolves."""
    assert hasattr(_gui_app(), name), f"gui.app must expose {name!r}"


@pytest.mark.parametrize("name", LOGGING_NAMES)
def test_logging_name_reexported(name):
    """log / _LOG_FILE are re-exported from gui.logging_setup via gui.app."""
    gui_app, gui_logging = _gui_app(), _gui_logging()
    assert hasattr(gui_app, name)
    assert getattr(gui_app, name) is getattr(gui_logging, name)


def test_log_id_forwarding_round_trips():
    """The rebound `_log_id` scalar round-trips reads and writes both ways."""
    gui_app, gui_state = _gui_app(), _gui_state()
    original = gui_state._log_id
    try:
        # gui.app read reflects gui.state.
        assert gui_app._log_id == gui_state._log_id

        # Write via gui.app forwards to gui.state.
        gui_app._log_id = 4242
        assert gui_state._log_id == 4242
        assert gui_app._log_id == 4242

        # Write via gui.state is visible through gui.app.
        gui_state._log_id = 99
        assert gui_app._log_id == 99

        # Forwarded names must NOT shadow in gui.app.__dict__, or __getattr__
        # would never fire and the forwarding would silently rot.
        assert "_log_id" not in gui_app.__dict__
    finally:
        gui_state._log_id = original


def test_app_importable_and_named():
    """`from gui.app import app` still works and the logger name is stable."""
    from flask import Flask
    from gui.app import app as flask_app
    # Compare against the live module (NOT a collection-time alias, which can be
    # stale after test_default_output_dir re-imports gui.app).
    assert flask_app is _gui_app().app
    assert isinstance(flask_app, Flask)
    assert _gui_app().log.name == "gui.app"
