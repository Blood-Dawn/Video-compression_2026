"""
tests/test_default_output_dir.py

Verifies the new resolution order in src/gui/app.py::_default_output_dir
after the 2026-05-14 productization change. OneDrive is no longer the
implicit default; the order is now:

    1. Persisted output_dir from last pipeline run
    2. Cloud sync root (only when prefer_cloud_output=True)
    3. platforms.default_videos_dir() — Videos/Movies/Documents
    4. <repo>/outputs/  as a dev fallback

If any of these slip out of order the casual user gets a surprising
output location on first run.

Author: Bloodawn (KheivenD), 2026-05-14.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# We import gui.app lazily inside each test because importing the module
# spins up Flask, the SSE log queue, and platform path migration. Doing
# that once per test isolates the global mutable state we need to poke.


def _import_app():
    import importlib
    import sys
    for k in list(sys.modules):
        if k == "gui.app" or k.startswith("gui.app."):
            del sys.modules[k]
    from gui import app
    return app


def _cloud_mod():
    # TASK 1.2: _default_output_dir + the cloud-root detectors moved out of
    # gui.app into gui.services.cloud_detection. _default_output_dir resolves
    # _detect_cloud_root via that module's globals, so the cloud-opt-in tests
    # must patch it there, not on gui.app (where it's only a re-export).
    from gui.services import cloud_detection
    return cloud_detection


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def app_mod():
    """Fresh import of gui.app."""
    return _import_app()


@pytest.fixture
def cloud_mod():
    """The cloud_detection service module — home of _detect_cloud_root."""
    return _cloud_mod()


@pytest.fixture
def reset_state(app_mod):
    """Clear _status['config'] so prior tests don't leak persisted state."""
    with app_mod._state_lock:
        app_mod._status["config"] = {}
    yield
    with app_mod._state_lock:
        app_mod._status["config"] = {}


# ── Resolution order ──────────────────────────────────────────────────────


class TestPersistedTakesPriority:

    def test_persisted_absolute_path_wins(self, app_mod, reset_state, tmp_path):
        with app_mod._state_lock:
            app_mod._status["config"] = {"output_dir": str(tmp_path / "persisted")}

        result = app_mod._default_output_dir()
        assert result == str(tmp_path / "persisted")

    def test_persisted_relative_path_skipped(self, app_mod, reset_state):
        """Relative paths must not win; we want absolute installer-safe paths."""
        with app_mod._state_lock:
            app_mod._status["config"] = {"output_dir": "outputs/relative"}

        result = app_mod._default_output_dir()
        # Should fall through to videos dir or final fallback
        assert "relative" not in result

    def test_empty_persisted_string_falls_through(self, app_mod, reset_state):
        with app_mod._state_lock:
            app_mod._status["config"] = {"output_dir": "   "}

        result = app_mod._default_output_dir()
        assert "   " not in result


class TestPlatformVideosDir:

    def test_falls_back_to_videos_dir(self, app_mod, reset_state):
        """No persisted, no cloud opt-in -> default_videos_dir."""
        with app_mod._state_lock:
            app_mod._status["config"] = {}

        result = app_mod._default_output_dir()
        # Should end with /SVCS at minimum
        assert result.endswith("SVCS") or "outputs" in result


class TestCloudOptIn:

    def test_cloud_not_used_when_flag_off(self, app_mod, cloud_mod, reset_state):
        with app_mod._state_lock:
            app_mod._status["config"] = {"prefer_cloud_output": False}

        # Even if cloud detection would succeed, we must not return its path
        fake_cloud = Path("/fake/cloud/root")
        with mock.patch.object(
            cloud_mod, "_detect_cloud_root",
            return_value=(fake_cloud, "OneDrive", "https://example.com"),
        ):
            result = app_mod._default_output_dir()
        assert "fake/cloud" not in result.replace("\\", "/")

    def test_cloud_used_when_flag_on(self, app_mod, cloud_mod, reset_state, tmp_path):
        with app_mod._state_lock:
            app_mod._status["config"] = {"prefer_cloud_output": True}

        fake_cloud = tmp_path / "fake_cloud_root"
        fake_cloud.mkdir()
        with mock.patch.object(
            cloud_mod, "_detect_cloud_root",
            return_value=(fake_cloud, "OneDrive", "https://example.com"),
        ):
            result = app_mod._default_output_dir()
        # Cloud subfolder name comes from the _CLOUD_SUBFOLDER constant (gui.state)
        assert str(fake_cloud) in result

    def test_cloud_flag_on_but_detection_fails(self, app_mod, cloud_mod, reset_state):
        with app_mod._state_lock:
            app_mod._status["config"] = {"prefer_cloud_output": True}

        with mock.patch.object(
            cloud_mod, "_detect_cloud_root",
            return_value=(None, None, None),
        ):
            result = app_mod._default_output_dir()
        # Should fall through to videos dir
        assert result  # non-empty
        assert "None" not in result


class TestAbsoluteness:
    """No matter which branch fires, the returned path must be absolute."""

    @pytest.mark.parametrize("cfg", [
        {},
        {"output_dir": ""},
        {"output_dir": "   "},
        {"prefer_cloud_output": False},
    ])
    def test_result_is_absolute(self, app_mod, reset_state, cfg):
        with app_mod._state_lock:
            app_mod._status["config"] = cfg

        result = app_mod._default_output_dir()
        assert Path(result).is_absolute(), f"got non-absolute: {result}"
