"""
tests/test_paths.py

Covers src/utils/paths.py: platform-aware data / config / cache dirs,
state_file() helper, default_videos_dir() picker, and the one-shot
migration from repo-root state files.

Why this module gets serious test coverage:
    Every installer (Windows, macOS, Linux, Android) routes its state
    through this module. A bug here means the app launches but can't
    save anything, or worse, silently writes to the wrong place.

Author: Bloodawn (KheivenD), 2026-05-14.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest


# Importing the module triggers _migrate_once() against the REAL repo
# root and real platform dirs. The tests below pin platformdirs to a
# tmp_path so that's harmless, but to be safe we always reset state
# in fixtures rather than relying on global state.

def _reimport_paths(monkeypatch, tmp_data: Path, tmp_cache: Path,
                    tmp_config: Path, repo_root: Path):
    """Re-import src.utils.paths with platformdirs pinned to tmp dirs.

    Returns the freshly imported module. We re-import per test so the
    module-level migration step runs against the test fixture state.
    """
    import importlib
    import sys

    import platformdirs

    # Patch the four directory-resolvers BEFORE the import so the
    # module's _PDIRS = PlatformDirs(...) picks up the test values.
    class _StubPDirs:
        user_data_dir = str(tmp_data)
        user_config_dir = str(tmp_config)
        user_cache_dir = str(tmp_cache)

    monkeypatch.setattr(platformdirs, "PlatformDirs",
                        lambda *a, **kw: _StubPDirs())

    # Repo root for the migration check
    monkeypatch.setenv("_TEST_REPO_ROOT_OVERRIDE", str(repo_root))

    # Force a fresh import so module-level state runs again
    if "utils.paths" in sys.modules:
        del sys.modules["utils.paths"]
    if "src.utils.paths" in sys.modules:
        del sys.modules["src.utils.paths"]

    import utils.paths as paths  # noqa: E402
    # Pin _REPO_ROOT so the migration looks at our fixture, not the
    # actual repo on disk.
    paths._REPO_ROOT = repo_root  # type: ignore[attr-defined]
    return paths


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_dirs(tmp_path):
    """Provide tmp data / config / cache / fake-repo-root dirs."""
    data = tmp_path / "data"
    cfg = tmp_path / "cfg"
    cache = tmp_path / "cache"
    repo = tmp_path / "repo"
    repo.mkdir()
    return {
        "data": data, "config": cfg, "cache": cache, "repo": repo,
    }


@pytest.fixture
def paths_module(monkeypatch, tmp_dirs):
    """Freshly imported paths module pinned to the tmp dirs."""
    return _reimport_paths(
        monkeypatch,
        tmp_data=tmp_dirs["data"],
        tmp_cache=tmp_dirs["cache"],
        tmp_config=tmp_dirs["config"],
        repo_root=tmp_dirs["repo"],
    )


# ── Basic resolution ──────────────────────────────────────────────────────


class TestDirectoryResolvers:
    """data_dir / config_dir / cache_dir return expected paths and create them."""

    def test_data_dir_returns_path(self, paths_module, tmp_dirs):
        result = paths_module.data_dir()
        assert isinstance(result, Path)
        assert result == tmp_dirs["data"]
        assert result.exists()

    def test_config_dir_returns_path(self, paths_module, tmp_dirs):
        result = paths_module.config_dir()
        assert result == tmp_dirs["config"]
        assert result.exists()

    def test_cache_dir_returns_path(self, paths_module, tmp_dirs):
        result = paths_module.cache_dir()
        assert result == tmp_dirs["cache"]
        assert result.exists()

    def test_resolvers_are_idempotent(self, paths_module):
        """Calling twice doesn't re-mkdir (mkdir uses exist_ok=True)."""
        a = paths_module.data_dir()
        b = paths_module.data_dir()
        assert a == b
        assert a.exists()

    def test_data_config_cache_are_distinct(self, paths_module):
        d = paths_module.data_dir()
        c = paths_module.config_dir()
        ca = paths_module.cache_dir()
        # All three should be different folders on every modern OS
        assert d != c
        assert d != ca
        assert c != ca


# ── state_file() ──────────────────────────────────────────────────────────


class TestStateFile:
    """state_file(name) returns the right path under data_dir."""

    def test_returns_path_under_data_dir(self, paths_module, tmp_dirs):
        p = paths_module.state_file("flask_secret")
        assert p.parent == tmp_dirs["data"]
        assert p.name == "flask_secret"

    def test_does_not_create_the_file(self, paths_module):
        """state_file is path-only. Caller is responsible for the file."""
        p = paths_module.state_file("not_yet.json")
        assert not p.exists()

    def test_creates_parent_dir(self, paths_module, tmp_dirs):
        # Wipe the data dir and confirm state_file rebuilds it
        import shutil
        shutil.rmtree(tmp_dirs["data"])
        assert not tmp_dirs["data"].exists()

        p = paths_module.state_file("flask_secret")
        assert p.parent.exists()

    def test_different_names_give_different_paths(self, paths_module):
        a = paths_module.state_file("a.json")
        b = paths_module.state_file("b.json")
        assert a != b
        assert a.parent == b.parent


# ── default_videos_dir() ──────────────────────────────────────────────────


class TestDefaultVideosDir:
    """Picks a sensible default video output directory per platform."""

    def test_returns_path(self, paths_module):
        result = paths_module.default_videos_dir()
        assert isinstance(result, Path)
        assert result.name == "SVCS"

    def test_prefers_videos_when_present(self, paths_module, monkeypatch, tmp_path):
        """If ~/Videos exists, that's the chosen root."""
        fake_home = tmp_path / "home"
        (fake_home / "Videos").mkdir(parents=True)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        result = paths_module.default_videos_dir()
        assert result == fake_home / "Videos" / "SVCS"

    def test_falls_back_to_movies(self, paths_module, monkeypatch, tmp_path):
        """If ~/Videos doesn't exist but ~/Movies does, pick that."""
        fake_home = tmp_path / "home"
        (fake_home / "Movies").mkdir(parents=True)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        result = paths_module.default_videos_dir()
        assert result == fake_home / "Movies" / "SVCS"

    def test_falls_back_to_documents(self, paths_module, monkeypatch, tmp_path):
        fake_home = tmp_path / "home"
        (fake_home / "Documents" / "Videos").mkdir(parents=True)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        result = paths_module.default_videos_dir()
        assert result == fake_home / "Documents" / "Videos" / "SVCS"

    def test_last_resort_home_svcs(self, paths_module, monkeypatch, tmp_path):
        """When none of the standard folders exist, fall back to ~/SVCS."""
        fake_home = tmp_path / "barren_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        result = paths_module.default_videos_dir()
        assert result == fake_home / "SVCS"


# ── Migration of legacy repo-root state files ─────────────────────────────


class TestMigration:
    """One-shot copy of pre-2026-05-14 state files to the new locations."""

    def test_migrates_existing_files(self, monkeypatch, tmp_dirs):
        # Plant legacy files in the fake repo root BEFORE importing paths
        repo = tmp_dirs["repo"]
        (repo / ".flask_secret").write_bytes(b"deadbeef" * 4)
        (repo / ".mode_cpu_avgs.json").write_text(
            json.dumps({"mode0": {"cpu_sum": 1.0, "n": 1, "avg": 1.0}})
        )
        (repo / ".svcs_gui_state.json").write_text(
            json.dumps({"output_dir": "/tmp/foo"})
        )
        (repo / ".uv_sync_stamp").write_text("abc123")

        paths = _reimport_paths(
            monkeypatch,
            tmp_data=tmp_dirs["data"],
            tmp_cache=tmp_dirs["cache"],
            tmp_config=tmp_dirs["config"],
            repo_root=repo,
        )
        # Re-run migration now that _REPO_ROOT is correctly pinned
        paths._migrate_once()

        assert (tmp_dirs["data"] / "flask_secret").exists()
        assert (tmp_dirs["data"] / "mode_cpu_avgs.json").exists()
        assert (tmp_dirs["data"] / "svcs_gui_state.json").exists()
        assert (tmp_dirs["cache"] / "uv_sync_stamp").exists()

        # Originals stay in place so older code paths still work
        assert (repo / ".flask_secret").exists()
        assert (repo / ".mode_cpu_avgs.json").exists()

    def test_migration_does_not_overwrite(self, monkeypatch, tmp_dirs):
        """If the new location already has a file, do NOT clobber it."""
        repo = tmp_dirs["repo"]
        (repo / ".flask_secret").write_bytes(b"OLD")
        tmp_dirs["data"].mkdir(parents=True, exist_ok=True)
        (tmp_dirs["data"] / "flask_secret").write_bytes(b"NEW")

        paths = _reimport_paths(
            monkeypatch,
            tmp_data=tmp_dirs["data"],
            tmp_cache=tmp_dirs["cache"],
            tmp_config=tmp_dirs["config"],
            repo_root=repo,
        )
        paths._migrate_once()

        # The newer file is preserved, the migration is skipped
        assert (tmp_dirs["data"] / "flask_secret").read_bytes() == b"NEW"

    def test_migration_with_no_legacy_files(self, paths_module, tmp_dirs):
        """No legacy files = no migration, no error."""
        # Run migration explicitly; nothing should appear
        paths_module._migrate_once()
        assert not (tmp_dirs["data"] / "flask_secret").exists()
        assert not (tmp_dirs["data"] / "mode_cpu_avgs.json").exists()

    def test_migration_is_idempotent(self, monkeypatch, tmp_dirs):
        """Running migration twice doesn't error and doesn't change anything."""
        repo = tmp_dirs["repo"]
        (repo / ".flask_secret").write_bytes(b"X")

        paths = _reimport_paths(
            monkeypatch,
            tmp_data=tmp_dirs["data"],
            tmp_cache=tmp_dirs["cache"],
            tmp_config=tmp_dirs["config"],
            repo_root=repo,
        )
        paths._migrate_once()
        paths._migrate_once()  # second pass should be a no-op

        assert (tmp_dirs["data"] / "flask_secret").read_bytes() == b"X"

    def test_migration_survives_permission_error(self, monkeypatch, tmp_dirs):
        """If shutil.copy2 raises, we log and move on instead of crashing."""
        repo = tmp_dirs["repo"]
        (repo / ".flask_secret").write_bytes(b"X")

        paths = _reimport_paths(
            monkeypatch,
            tmp_data=tmp_dirs["data"],
            tmp_cache=tmp_dirs["cache"],
            tmp_config=tmp_dirs["config"],
            repo_root=repo,
        )

        def explode(*args, **kwargs):
            raise PermissionError("simulated")

        monkeypatch.setattr("shutil.copy2", explode)

        # Must NOT raise. The migration is best-effort.
        paths._migrate_once()
