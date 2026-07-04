"""
src/utils/video_formats.py

Universal surveillance video format support (R4 Phase 6).

Different camera / DVR / NVR vendors export footage in a wide range of
containers - not just mp4/avi. This module is the ONE place that lists which
file extensions SVCS treats as ingestible video, so the upload, watch-folder,
library, and file-browser gates all agree and a vendor's format is not rejected
before it ever reaches the decoder.

Two tiers:
  * STANDARD_VIDEO_EXTS - the common containers OpenCV usually opens directly.
  * PROPRIETARY_VIDEO_EXTS - vendor / DVR containers and raw elementary streams
    that OpenCV's build often cannot demux. FrameSource falls back to piping the
    file through the bundled FFmpeg (which supports far more demuxers) for these.

"Universal" is bounded honestly: it means "anything the bundled FFmpeg can
demux". A few vendor formats are ENCRYPTED or fully proprietary (e.g. some
Hikvision .g64, certain Dahua exports) and need the vendor's own player/export
tool first - FFmpeg (and therefore SVCS) cannot read those, and ingest fails
with a clear error rather than silently.

Author: Bloodawn (KheivenD), 2026-07-04 (R4 Phase 6 - universal formats).
"""

from __future__ import annotations

from pathlib import Path

# Common containers OpenCV's VideoCapture generally opens on its own.
STANDARD_VIDEO_EXTS = frozenset({
    ".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm",
    ".ts", ".mts", ".m2ts", ".m2t", ".mpg", ".mpeg", ".mpe",
    ".wmv", ".asf", ".flv", ".3gp", ".3g2", ".ogv", ".vob",
})

# Vendor / DVR / NVR containers and raw elementary streams. OpenCV's build
# often can't demux these; the FFmpeg-pipe fallback in FrameSource handles the
# ones FFmpeg can read. Extensions gathered from common surveillance exports:
#   .dav       Dahua DVR/NVR export
#   .264/.h264 raw H.264 elementary stream (many DVRs dump these)
#   .265/.hevc/.h265  raw H.265 elementary stream
#   .g64/.g64x Genetec / some Hikvision exports
#   .sdv       Panasonic / Samsung DVR
#   .av/.avr   AVTECH / assorted DVR exports
#   .bu        Brickcom / assorted
#   .irf       iDVR / assorted
#   .mxf       Material Exchange Format (pro/broadcast + some NVRs)
#   .dat       generic MPEG program stream (VCD/DVR dumps)
#   .raw       raw stream dumps
PROPRIETARY_VIDEO_EXTS = frozenset({
    ".dav", ".264", ".h264", ".265", ".h265", ".hevc",
    ".g64", ".g64x", ".sdv", ".av", ".avr", ".bu", ".irf",
    ".mxf", ".dat", ".raw",
})

# Everything SVCS will ACCEPT as a video to ingest/compress.
ALL_INGEST_EXTS = frozenset(STANDARD_VIDEO_EXTS | PROPRIETARY_VIDEO_EXTS)

# Browser-playable subset (for /media serving in the library detail player). A
# proprietary original will not play in a <video> tag regardless; the compressed
# OUTPUT is always mp4, which does.
BROWSER_PLAYABLE_EXTS = frozenset({".mp4", ".m4v", ".webm", ".mov", ".ogv"})


def _ext(path) -> str:
    try:
        return Path(str(path)).suffix.lower()
    except (TypeError, ValueError):
        return ""


def is_video_ext(path) -> bool:
    """True if ``path``'s extension is an ingestible video (standard or vendor)."""
    return _ext(path) in ALL_INGEST_EXTS


def is_proprietary(path) -> bool:
    """True if ``path`` is a vendor / raw container that likely needs the
    FFmpeg-pipe decode fallback rather than direct OpenCV."""
    return _ext(path) in PROPRIETARY_VIDEO_EXTS
