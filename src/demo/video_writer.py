"""
H264Writer — drop-in replacement for cv2.VideoWriter that produces H.264 MP4
files playable in Chrome/Firefox/Safari without plugins.

cv2.VideoWriter with fourcc "mp4v" produces MPEG-4 Part 2, which modern
browsers refuse to play.  H.264 (AVC) in an MP4 container is the universally
supported web codec.

Usage (identical API to cv2.VideoWriter):

    writer = H264Writer(output_path, fps, width, height)
    for frame in frames:
        writer.write(frame)          # frame is a BGR numpy array
    writer.release()

Or as a context manager:

    with H264Writer(output_path, fps, width, height) as w:
        w.write(frame)
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

try:                                       # bundled-first ffmpeg resolution (TASK 2.3)
    from utils.ffmpeg import ffmpeg_path
except ImportError:                        # pragma: no cover - import path shim
    from src.utils.ffmpeg import ffmpeg_path


class H264Writer:
    """Write BGR frames to an H.264 MP4 via an FFmpeg stdin pipe."""

    def __init__(self, output_path: str | Path, fps: float, width: int, height: int):
        self._width = int(width)
        self._height = int(height)
        self._fps = float(fps)
        self._output_path = str(output_path)
        self._proc: subprocess.Popen | None = None
        self._opened = False

        ffmpeg = ffmpeg_path()

        cmd = [
            ffmpeg, "-y",
            # Input: raw BGR frames from stdin
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{self._width}x{self._height}",
            "-r", str(self._fps),
            "-i", "pipe:0",
            # Output: H.264 in MP4, faststart for web streaming
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",   # required: libx264 needs planar YUV
            "-movflags", "+faststart",
            self._output_path,
        ]

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._opened = True

    # ── cv2.VideoWriter-compatible API ────────────────────────────────────────

    def isOpened(self) -> bool:
        return self._opened and self._proc is not None and self._proc.poll() is None

    def write(self, frame) -> None:
        """Write one BGR frame (numpy array, shape HxWx3)."""
        if self._proc is None or self._proc.stdin is None:
            return
        # Resize if dimensions don't match (safety guard)
        if frame.shape[0] != self._height or frame.shape[1] != self._width:
            import cv2
            frame = cv2.resize(frame, (self._width, self._height))
        self._proc.stdin.write(frame.tobytes())

    def release(self) -> None:
        if self._proc is not None:
            if self._proc.stdin:
                try:
                    self._proc.stdin.close()
                except Exception:
                    pass
            try:
                self._proc.wait(timeout=30)
            except Exception:
                # FFmpeg did not exit within 30 s — kill it so we don't hang forever.
                try:
                    self._proc.kill()
                    self._proc.wait()
                except Exception:
                    pass
            self._proc = None
        self._opened = False

    # ── context manager ───────────────────────────────────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.release()
