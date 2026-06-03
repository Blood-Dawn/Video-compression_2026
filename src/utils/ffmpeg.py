"""
src/utils/ffmpeg.py

FFmpeg / FFprobe binary resolution (M2 TASK 2.3).

The app used to assume `ffmpeg` was on PATH and would simply fail if it wasn't.
For the packaged installer we vendor an LGPL FFmpeg build inside the bundle, so
resolution order is now:

    1. The bundled binary (shipped next to the frozen app / in the dev tree).
    2. A binary on PATH (shutil.which).
    3. The bare name "ffmpeg" / "ffprobe" as a last resort (lets the OS resolve
       it, preserving the old behavior and any clear error message).

This makes the installed app self-contained (no "install FFmpeg first" step)
while a dev clone still uses whatever FFmpeg is on PATH.

Search locations for the bundled binary:
  * frozen:  <_MEIPASS>/ffmpeg/bin/ and <_MEIPASS>/   (PyInstaller datas dest)
  * source:  <repo>/tools/ffmpeg/bin/ and <repo>/tools/ffmpeg/

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 2.3 - bundled FFmpeg).
"""

from __future__ import annotations

import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

_IS_WINDOWS = os.name == "nt"


def _exe(name: str) -> str:
    return name + ".exe" if _IS_WINDOWS else name


def _bundle_roots() -> List[Path]:
    """Directories that may contain a vendored ffmpeg/ffprobe, most-preferred
    first.

    In a PyInstaller build, datas land under ``sys._MEIPASS``; in a source
    checkout we look under ``<repo>/tools/ffmpeg``.
    """
    roots: List[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(meipass)
        roots += [base / "ffmpeg" / "bin", base / "ffmpeg", base]
    # repo root: src/utils/ffmpeg.py -> parents[2]
    repo = Path(__file__).resolve().parents[2]
    roots += [repo / "tools" / "ffmpeg" / "bin", repo / "tools" / "ffmpeg"]
    return roots


def _resolve(tool: str) -> str:
    """Resolve a tool name ("ffmpeg" / "ffprobe") to an absolute path or bare name."""
    fname = _exe(tool)
    for root in _bundle_roots():
        cand = root / fname
        try:
            if cand.is_file():
                return str(cand)
        except OSError:
            continue
    on_path = shutil.which(tool)
    if on_path:
        return on_path
    return tool  # last resort: let the OS resolve it (old behavior)


@lru_cache(maxsize=None)
def ffmpeg_path() -> str:
    """Absolute path to a usable ffmpeg, or the bare name "ffmpeg" as a fallback."""
    return _resolve("ffmpeg")


@lru_cache(maxsize=None)
def ffprobe_path() -> str:
    """Absolute path to a usable ffprobe, or the bare name "ffprobe" as a fallback."""
    return _resolve("ffprobe")


def ffmpeg_available() -> bool:
    """True if a real ffmpeg binary was found (bundled or on PATH)."""
    return ffmpeg_path() != "ffmpeg" or shutil.which("ffmpeg") is not None


def _clear_cache() -> None:
    """Reset the memoized resolutions (used by tests that move binaries around)."""
    ffmpeg_path.cache_clear()
    ffprobe_path.cache_clear()
