"""
tests/test_default_output_dir.py

Verifies the resolution order in _default_output_dir after FIX 1
(2026-06-03). There is NO implicit cloud default anymore; the order is:

    1. The user's explicit / persisted output_dir (a cloud folder only
       appears here if the user chose it in Setup)
    2. paths.default_videos_dir() - a neutral LOCAL Videos/Movies folder
    3. <repo>/outputs/  as a dev fallback

The app must never fall through to a OneDrive / Google Drive / iCloud root
on its own. Cloud roots are only OFFERED in Setup.

Author: Bloodawn (KheivenD), 2026-06-03 (FIX 1).
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
        """No persisted choice -> neutral LOCAL default_videos_dir."""
        with app_mod._state_lock:
            app_mod._status["config"] = {}

        result = app_mod._default_output_dir()
        # Should end with /SVCS at minimum
        assert result.endswith("SVCS") or "outputs" in result


class TestNoImplicitCloud:
    """FIX 1: the app must never return a cloud root it detected on its own."""

    def test_cloud_never_used_even_if_detected(self, app_mod, cloud_mod, reset_state):
        # Empty config: even if a cloud root is detectable, it must NOT be used.
        with app_mod._state_lock:
            app_mod._status["config"] = {}

        fake_cloud = Path("/fake/cloud/root")
        with mock.patch.object(
            cloud_mod, "_detect_cloud_root",
            return_value=(fake_cloud, "OneDrive", "https://example.com"),
        ):
            result = app_mod._default_output_dir()
        assert "fake/cloud" not in result.replace("\\", "/")

    def test_legacy_prefer_cloud_flag_is_ignored(self, app_mod, cloud_mod, reset_state):
        # The old prefer_cloud_output opt-in no longer derives a cloud path.
        with app_mod._state_lock:
            app_mod._status["config"] = {"prefer_cloud_output": True}

        fake_cloud = Path("/fake/cloud/root")
        with mock.patch.object(
            cloud_mod, "_detect_cloud_root",
            return_value=(fake_cloud, "OneDrive", "https://example.com"),
        ):
            result = app_mod._default_output_dir()
        assert "fake/cloud" not in result.replace("\\", "/")

    def test_explicit_chosen_path_is_honored(self, app_mod, reset_state, tmp_path):
        # A user who chose a cloud (or any) folder in Setup gets exactly it.
        chosen = tmp_path / "MyCloud" / "SVCS"
        with app_mod._state_lock:
            app_mod._status["config"] = {"output_dir": str(chosen)}
        assert app_mod._default_output_dir() == str(chosen)


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
