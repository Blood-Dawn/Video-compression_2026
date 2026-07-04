"""
tests/test_universal_formats.py

R4 Phase 6: universal multi-vendor surveillance video format support.

  * utils.video_formats: the central standard/proprietary/all-ingest sets and
    the is_video_ext / is_proprietary helpers;
  * the five ingest gates (upload, watch-folder, library, browse) accept vendor
    /DVR extensions via the shared set;
  * FrameSource: the FFmpeg-pipe decode fallback (forced via env) decodes a real
    file OpenCV also handles, producing correct dimensions and frames, and
    releases the FFmpeg process cleanly; the normal OpenCV path is unchanged.

The fallback is exercised on a normal mp4 with SVCS_FORCE_FFMPEG_DECODE=1, which
proves the machinery without needing a genuinely OpenCV-hostile vendor file in
the repo.

Author: Bloodawn (KheivenD), 2026-07-04 (R4 Phase 6 - universal formats).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils import video_formats as vf                 # noqa: E402
from utils.ffmpeg import ffmpeg_available             # noqa: E402

_SAMPLE = ROOT / "data" / "samples" / "parking_input.mp4"


# ── the central format sets ───────────────────────────────────────────────────

def test_all_ingest_is_union():
    assert vf.ALL_INGEST_EXTS == (vf.STANDARD_VIDEO_EXTS | vf.PROPRIETARY_VIDEO_EXTS)
    # No accidental overlap between the two tiers.
    assert not (vf.STANDARD_VIDEO_EXTS & vf.PROPRIETARY_VIDEO_EXTS)


def test_standard_and_vendor_exts_present():
    for e in (".mp4", ".avi", ".mkv", ".ts", ".mov"):
        assert e in vf.STANDARD_VIDEO_EXTS
    # Vendor / DVR containers a real camera might export.
    for e in (".dav", ".264", ".h264", ".265", ".hevc", ".g64", ".sdv", ".mxf"):
        assert e in vf.PROPRIETARY_VIDEO_EXTS


def test_is_video_ext_and_proprietary():
    assert vf.is_video_ext("clip.mp4")
    assert vf.is_video_ext("C:/dvr/EXPORT.DAV")   # case-insensitive
    assert vf.is_video_ext("stream.h264")
    assert not vf.is_video_ext("notes.txt")
    assert not vf.is_video_ext("key.enc")
    assert vf.is_proprietary("cam.dav")
    assert not vf.is_proprietary("cam.mp4")
    assert not vf.is_proprietary(None)


# ── the ingest gates reference the shared set ─────────────────────────────────

def test_upload_gate_accepts_vendor_exts():
    from gui.state import _ALLOWED_EXTENSIONS
    assert ".dav" in _ALLOWED_EXTENSIONS and ".mp4" in _ALLOWED_EXTENSIONS


def test_watchfolder_gate_accepts_vendor_exts():
    from utils.watchfolder import SUPPORTED_EXTENSIONS
    assert vf.PROPRIETARY_VIDEO_EXTS <= SUPPORTED_EXTENSIONS
    assert ".mp4" in SUPPORTED_EXTENSIONS


def test_library_gate_accepts_vendor_exts():
    from gui.routes.library_bp import VIDEO_EXTS
    assert ".dav" in VIDEO_EXTS and ".264" in VIDEO_EXTS


# ── FrameSource FFmpeg decode fallback ────────────────────────────────────────

@pytest.mark.skipif(not _SAMPLE.is_file(), reason="sample clip not present")
def test_opencv_path_unchanged(monkeypatch):
    monkeypatch.delenv("SVCS_FORCE_FFMPEG_DECODE", raising=False)
    from utils.frame_source import FrameSource
    fs = FrameSource(str(_SAMPLE))
    try:
        assert fs.decoder == "opencv"
        assert fs.width > 0 and fs.height > 0
        ok, frame = fs.read()
        assert ok and frame is not None
    finally:
        fs.release()


@pytest.mark.skipif(not (_SAMPLE.is_file() and ffmpeg_available()),
                    reason="sample clip or ffmpeg not available")
def test_ffmpeg_fallback_decodes(monkeypatch):
    monkeypatch.setenv("SVCS_FORCE_FFMPEG_DECODE", "1")
    from utils.frame_source import FrameSource
    fs = FrameSource(str(_SAMPLE))
    try:
        assert fs.decoder == "ffmpeg"
        assert fs.width > 0 and fs.height > 0 and fs.fps > 0
        count = 0
        last = None
        while count < 8:
            ok, frame = fs.read()
            if not ok:
                break
            last = frame
            count += 1
        assert count == 8
        assert last.shape == (fs.height, fs.width, 3)
    finally:
        fs.release()
    # The FFmpeg process is terminated on release.
    assert fs._ff_proc is None


@pytest.mark.skipif(not (_SAMPLE.is_file() and ffmpeg_available()),
                    reason="sample clip or ffmpeg not available")
def test_ffmpeg_and_opencv_agree_on_dimensions(monkeypatch):
    from utils.frame_source import FrameSource
    monkeypatch.delenv("SVCS_FORCE_FFMPEG_DECODE", raising=False)
    a = FrameSource(str(_SAMPLE)); a.release()
    monkeypatch.setenv("SVCS_FORCE_FFMPEG_DECODE", "1")
    b = FrameSource(str(_SAMPLE)); b.release()
    assert (a.width, a.height) == (b.width, b.height)


def test_missing_file_raises():
    from utils.frame_source import FrameSource
    with pytest.raises(RuntimeError):
        FrameSource(str(ROOT / "does_not_exist.dav"))
