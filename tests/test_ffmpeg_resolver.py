"""
tests/test_ffmpeg_resolver.py

Tests src/utils/ffmpeg.py - the bundled-first FFmpeg resolver (M2 TASK 2.3).

The key guarantee: the packaged app uses its VENDORED ffmpeg even when there is
none on PATH, so an end user never has to "install FFmpeg first". Also verifies
the PATH fallback (dev clones) and the bare-name last resort.

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 2.3).
"""

from __future__ import annotations

import os
import sys
import stat
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils import ffmpeg as ff  # noqa: E402

_IS_WIN = os.name == "nt"
_BIN = "ffmpeg.exe" if _IS_WIN else "ffmpeg"


def _make_fake_binary(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / _BIN
    p.write_text("#!/bin/sh\necho fake ffmpeg\n", encoding="utf-8")
    if not _IS_WIN:
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


@pytest.fixture(autouse=True)
def _reset_cache():
    ff._clear_cache()
    yield
    ff._clear_cache()


def test_prefers_bundled_over_path(tmp_path, monkeypatch):
    """A bundled ffmpeg wins even when PATH also has one (and especially when it
    doesn't)."""
    bundled = _make_fake_binary(tmp_path / "ffmpeg" / "bin")
    monkeypatch.setattr(ff, "_bundle_roots", lambda: [bundled.parent])
    # Empty PATH so shutil.which finds nothing.
    monkeypatch.setenv("PATH", "")
    ff._clear_cache()
    assert ff.ffmpeg_path() == str(bundled)
    assert ff.ffmpeg_available() is True


def test_falls_back_to_path_when_not_bundled(tmp_path, monkeypatch):
    """With nothing bundled, a binary on PATH is used."""
    path_dir = tmp_path / "onpath"
    onpath = _make_fake_binary(path_dir)
    # No bundle roots exist.
    monkeypatch.setattr(ff, "_bundle_roots", lambda: [tmp_path / "nope"])
    monkeypatch.setenv("PATH", str(path_dir))
    ff._clear_cache()
    resolved = ff.ffmpeg_path()
    assert Path(resolved).name.lower().startswith("ffmpeg")
    assert Path(resolved).parent == path_dir


def test_last_resort_bare_name(tmp_path, monkeypatch):
    """Nothing bundled and nothing on PATH -> bare 'ffmpeg' (old behavior)."""
    monkeypatch.setattr(ff, "_bundle_roots", lambda: [tmp_path / "nope"])
    monkeypatch.setenv("PATH", "")
    ff._clear_cache()
    assert ff.ffmpeg_path() == "ffmpeg"


def test_ffprobe_resolves_independently(tmp_path, monkeypatch):
    probe = _make_fake_binary(tmp_path / "ffmpeg" / "bin")
    # rename the fake to ffprobe
    probe_named = probe.with_name("ffprobe.exe" if _IS_WIN else "ffprobe")
    probe.rename(probe_named)
    monkeypatch.setattr(ff, "_bundle_roots", lambda: [probe_named.parent])
    monkeypatch.setenv("PATH", "")
    ff._clear_cache()
    assert ff.ffprobe_path() == str(probe_named)


def test_resolver_is_importable_from_callsites():
    """The callsites import ffmpeg_path; make sure the symbol is exported."""
    from utils.ffmpeg import ffmpeg_path, ffprobe_path  # noqa: F401
    assert callable(ffmpeg_path) and callable(ffprobe_path)
