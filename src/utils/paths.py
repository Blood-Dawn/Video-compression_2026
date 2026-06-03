"""
src/utils/paths.py

Platform-aware file paths for SVCS.

Why this exists:
    Up until 2026-05-14 the app wrote three small state files
    (.flask_secret, .mode_cpu_avgs.json, .svcs_gui_state.json) into the
    repo root. That works fine in dev because we run from the repo
    itself, but it does NOT work in an installed app on Windows or
    macOS because the install location is read-only for normal users
    (Program Files, /Applications). The launcher would crash on first
    run trying to open .flask_secret for write.

    This module wraps `platformdirs` to return the OS-standard data,
    config, cache, and output directories for SVCS. Every state file
    now goes through `state_file(name)` which returns the right path
    for the current platform and creates parent dirs as needed.

    A one-shot migration runs on first import: if a state file exists
    in the old repo-root location but not in the new platform location,
    it gets copied over. The old file is left in place so existing
    dev clones still work if someone reverts.

Platform map (APP_NAME = "SVCS"):

    Windows:  C:\\Users\\<user>\\AppData\\Local\\SVCS\\<file>
    macOS:    ~/Library/Application Support/SVCS/<file>
    Linux:    ~/.local/share/SVCS/<file>  (XDG_DATA_HOME)

Cache dir is a separate location (e.g. ~/Library/Caches/SVCS on macOS)
used for things that can be regenerated, like the uv sync stamp and
downloaded model weights.

Output dir defaults to ~/Videos/SVCS on every platform (or
~/Movies/SVCS on macOS) but is overridable through the GUI.

Author: Bloodawn (KheivenD), 2026-05-14.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

import platformdirs

log = logging.getLogger(__name__)

# ── App identity used by platformdirs ─────────────────────────────────────
# The author string lets platformdirs build vendor-prefixed paths on
# Windows where that's the convention. Set both args to "SVCS" so we
# land in C:\Users\<user>\AppData\Local\SVCS\ instead of nesting.
APP_NAME = "SVCS"
APP_AUTHOR = "SVCS"

_PDIRS = platformdirs.PlatformDirs(APP_NAME, APP_AUTHOR, roaming=False)

# Repo root, used only for the one-shot dev-machine migration below.
# Path(__file__).parent is src/utils/, so two parents up is the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ── Public helpers ────────────────────────────────────────────────────────


def data_dir() -> Path:
    """Return the OS-standard user data directory for SVCS.

    On Windows this is %LOCALAPPDATA%\\SVCS. On macOS it is
    ~/Library/Application Support/SVCS. On Linux it is
    $XDG_DATA_HOME/SVCS (default ~/.local/share/SVCS).

    The directory is created if it does not exist.
    """
    d = Path(_PDIRS.user_data_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_dir() -> Path:
    """Return the OS-standard user config directory for SVCS.

    Used for things the user might want to edit by hand: presets,
    custom keybindings, exported settings JSON.
    """
    d = Path(_PDIRS.user_config_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir() -> Path:
    """Return the OS-standard user cache directory for SVCS.

    Used for things that can be regenerated: the uv sync stamp,
    downloaded model weights, transient FFmpeg work files.
    """
    d = Path(_PDIRS.user_cache_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_file(name: str) -> Path:
    """Return the full path to a named state file in the data dir.

    Example:
        state_file("flask_secret")
        # -> C:\\Users\\kheiven\\AppData\\Local\\SVCS\\flask_secret  (Windows)
        # -> ~/Library/Application Support/SVCS/flask_secret         (macOS)

    The parent dir is created on first call. The file itself is not
    created here; callers handle that.
    """
    return data_dir() / name


# Names of the per-install state files SVCS writes under data_dir(). Used by the
# factory-reset action (FIX 2) so a machine with prior state can be returned to
# a genuine first-run condition. These are the platform-location names (no
# leading dot), matching what state_file() / the services actually write.
STATE_FILE_NAMES = [
    "flask_secret",
    "mode_cpu_avgs.json",
    "gui_state.json",
    "usage_consent.json",
    "usage_events.jsonl",
]


def reset_state() -> list:
    """Delete the per-install state files, returning the names removed.

    Factory reset (FIX 2): removes the persisted CPU averages, saved
    destination prefs, usage-consent record, and Flask secret from data_dir()
    so the next launch behaves like a fresh install (Setup re-triggers, the CPU
    panel starts empty). Best effort and never raises; missing files are
    skipped. The output folders the user created are NOT touched.
    """
    removed = []
    try:
        d = data_dir()
    except Exception:  # noqa: BLE001
        return removed
    for name in STATE_FILE_NAMES:
        p = d / name
        try:
            if p.exists():
                p.unlink()
                removed.append(name)
        except OSError:
            continue
    return removed


def default_videos_dir() -> Path:
    """Best-effort guess at the user's "videos" folder.

    Looks for ~/Videos (Windows / Linux) or ~/Movies (macOS). Falls
    back to ~/Documents/Videos if neither exists, then to ~/SVCS as
    a last resort.

    This is the FIRST suggestion the dashboard offers when the user
    hasn't picked an output directory. They can override via the GUI;
    the choice is persisted in .svcs_gui_state.json (which now lives
    in data_dir() per state_file()).
    """
    home = Path.home()
    for candidate in (home / "Videos", home / "Movies", home / "Documents" / "Videos"):
        if candidate.is_dir():
            return candidate / "SVCS"
    return home / "SVCS"


# ── One-shot migration from repo-root state files ─────────────────────────
# Runs once at module import. If a state file exists in the repo root
# (from a pre-2026-05-14 install) but NOT in the new platform location,
# copy it across so the user's saved Flask secret, CPU benchmarks, and
# GUI prefs survive the upgrade. The original file is intentionally
# left in place so older code paths still work during the transition.

_MIGRATE = [
    ".flask_secret",
    ".mode_cpu_avgs.json",
    ".svcs_gui_state.json",
]

# uv_sync_stamp lives in the cache dir going forward, but we should
# still migrate any pre-existing copy in the repo root.
_MIGRATE_CACHE = [
    ".uv_sync_stamp",
]


def _migrate_once() -> None:
    """Best-effort copy of legacy state files. Never raises."""
    try:
        target_data = data_dir()
        for name in _MIGRATE:
            src = _REPO_ROOT / name
            dst = target_data / name.lstrip(".")
            if src.is_file() and not dst.exists():
                shutil.copy2(src, dst)
                log.info("Migrated %s -> %s", src.name, dst)

        target_cache = cache_dir()
        for name in _MIGRATE_CACHE:
            src = _REPO_ROOT / name
            dst = target_cache / name.lstrip(".")
            if src.is_file() and not dst.exists():
                shutil.copy2(src, dst)
                log.info("Migrated %s -> %s", src.name, dst)
    except Exception as exc:  # noqa: BLE001
        # Migration is best-effort. If anything goes wrong (permissions,
        # missing parents, weird filesystem), we silently skip and the
        # app starts fresh in the new location.
        log.debug("State migration skipped: %s", exc)


# Run the migration unconditionally on import. It is idempotent (it
# only copies when the destination doesn't already exist) so importing
# this module multiple times is safe.
_migrate_once()
