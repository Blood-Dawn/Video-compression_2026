"""
frame_source.py

Unified frame reader that transparently handles two input formats:
  1. Video files (.mp4, .avi, .mov, etc.) -- standard OpenCV VideoCapture
  2. CDnet image sequences -- folders of JPEG/PNG frames named in000001.jpg, etc.

CDnet 2014 stores each clip as:
    <scene>/
        input/          <- individual frames: in000001.jpg, in000002.jpg, ...
        groundtruth/    <- gt000001.png, gt000002.png, ...
        temporalROI.txt <- "start_frame end_frame" (valid annotation range)

You can point FrameSource at any of:
  - A video file path:               data/clip.mp4
  - A CDnet scene folder:            data/dataset/baseline/highway/
  - A CDnet input subfolder directly: data/dataset/baseline/highway/input/

Author: Bloodawn (KheivenD)
"""

import json
import logging
import os
import subprocess
import cv2
import numpy as np
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger(__name__)


class FrameSource:
    """
    Abstracts over video files and CDnet-style image sequence folders.

    Drop-in replacement for cv2.VideoCapture.read() in any loop.
    Exposes fps, width, height, total_frames, and (for CDnet) temporal_roi.

    Usage:
        with FrameSource("data/dataset/baseline/highway") as src:
            while True:
                ok, frame = src.read()
                if not ok:
                    break
                # ... process frame
    """

    def __init__(self, input_path):
        """
        Initializes the frame source by detecting whether input_path is a
        video file, CDnet image sequence folder, network URL, or device index.

        For CDnet folders, automatically finds the input/ subfolder if the
        top-level scene folder is provided. Also reads temporalROI.txt to
        expose the valid frame range (frames outside this range have no
        ground truth annotations).

        Args:
            input_path: An integer camera device index (e.g. 0 for the first
                        webcam), a network URL string (rtsp://, http://, etc.),
                        a video file path, or a CDnet scene folder path.

        Raises:
            RuntimeError: If the path cannot be opened or no frames are found.
        """
        self.is_sequence = False
        self.frame_files = []
        self._seq_idx = 0
        self._cap = None
        self.fps = 30.0
        self.width = 0
        self.height = 0
        self.total_frames = 0
        self.temporal_roi: Optional[Tuple[int, int]] = None  # (start, end) frame numbers
        # R4 Phase 6: FFmpeg-pipe decode mode for vendor/DVR containers OpenCV
        # cannot demux. None unless the FFmpeg fallback is active.
        self._ff_proc: Optional[subprocess.Popen] = None
        self._ff_frame_bytes = 0
        self.decoder = "opencv"

        # Integer device index (e.g. 0 for the built-in webcam)
        if isinstance(input_path, int):
            self.input_path = str(input_path)
            self._init_device(input_path)
            return

        input_path = str(input_path)
        path = Path(input_path)
        self.input_path = str(path)

        # Network stream URLs must bypass filesystem checks. Path() may mangle
        # RTSP URLs on Windows (backslash-separating the host/path portions).
        _URL_SCHEMES = ("rtsp://", "rtsps://", "rtmp://", "http://", "https://")
        if any(input_path.lower().startswith(s) for s in _URL_SCHEMES):
            self._init_video_url(input_path)
            return

        # Numeric string "0", "1", ... also treated as a device index so the
        # GUI can pass camera_index as a plain string.
        if input_path.strip().isdigit():
            self._init_device(int(input_path.strip()))
            return

        if path.is_dir():
            self._init_sequence(path)
        elif path.is_file():
            self._init_video(path)
        else:
            raise RuntimeError(f"Input path does not exist: {input_path}")

    def _init_device(self, index: int):
        """Set up reading from a local camera device by index (e.g. 0 for webcam).

        cv2.VideoCapture reports 0x0 dimensions on some platforms until the
        first frame is read; callers should read a probe frame if exact
        dimensions are needed before the main loop starts.
        """
        self._cap = cv2.VideoCapture(index)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open camera device {index}")
        fps = self._cap.get(cv2.CAP_PROP_FPS)
        self.fps = fps if (fps and 0 < fps <= 120) else 30.0
        w = self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        h = self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        self.width = int(w) if w > 0 else 0
        self.height = int(h) if h > 0 else 0
        self.total_frames = 0  # live device; frame count unknown
        self.is_sequence = False

    def _init_video_url(self, url: str):
        """Set up reading from a network stream URL (RTSP, HTTP, RTMP, etc.).

        cv2.VideoCapture can handle these natively; dimensions may read as 0×0
        until the first frame arrives (normal for live RTSP streams; the caller
        should probe the first frame to get real dimensions).
        """
        self.input_path = url
        self._cap = cv2.VideoCapture(url)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open stream: {url}")
        fps = self._cap.get(cv2.CAP_PROP_FPS)
        self.fps = fps if (fps and 0 < fps <= 120) else 25.0
        w = self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        h = self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        self.width = int(w) if w > 0 else 0
        self.height = int(h) if h > 0 else 0
        self.total_frames = 0  # live stream; frame count unknown
        self.is_sequence = False

    def _init_sequence(self, path: Path):
        """
        Sets up reading from a CDnet-style image sequence folder.

        Handles two folder layouts:
          - Scene folder (contains an input/ subfolder): data/baseline/highway/
          - Input folder directly: data/baseline/highway/input/

        Also reads temporalROI.txt from the scene folder to get the valid
        annotation range. Frames before temporal_roi[0] are warmup frames
        in the CDnet benchmark -- use this value as warmup_frames.
        """
        # Determine where the actual image files are
        if (path / "input").is_dir():
            input_dir = path / "input"
            scene_dir = path
        else:
            # We were given the input/ folder directly
            input_dir = path
            scene_dir = path.parent

        # Read temporalROI.txt if available (CDnet valid frame range)
        roi_file = scene_dir / "temporalROI.txt"
        if roi_file.exists():
            parts = roi_file.read_text().strip().split()
            if len(parts) >= 2:
                self.temporal_roi = (int(parts[0]), int(parts[1]))

        # Collect and sort all image files in the input folder
        IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
        self.frame_files = sorted([
            f for f in input_dir.iterdir()
            if f.suffix.lower() in IMAGE_EXTS
        ])

        if not self.frame_files:
            raise RuntimeError(f"No image files found in {input_dir}")

        # Read first frame to get spatial dimensions
        first_frame = cv2.imread(str(self.frame_files[0]))
        if first_frame is None:
            raise RuntimeError(f"Cannot decode first frame: {self.frame_files[0]}")

        self.height, self.width = first_frame.shape[:2]
        self.fps = 30.0          # CDnet does not store FPS -- 30 is a safe default
        self.total_frames = len(self.frame_files)
        self.is_sequence = True
        self._seq_idx = 0

    def _init_video(self, path: Path):
        """
        Sets up reading from a video file.

        Tries cv2.VideoCapture first (fast, the common path). If OpenCV's build
        cannot open the container - which happens for many vendor / DVR / NVR
        formats and raw elementary streams - it falls back to decoding via the
        bundled FFmpeg, which supports far more demuxers (R4 Phase 6). The env
        var SVCS_FORCE_FFMPEG_DECODE=1 forces the FFmpeg path (used by tests and
        as an escape hatch).
        """
        force_ffmpeg = os.environ.get("SVCS_FORCE_FFMPEG_DECODE") == "1"

        if not force_ffmpeg:
            cap = cv2.VideoCapture(str(path))
            if cap.isOpened():
                # Trust OpenCV only if it can actually produce a frame; some
                # builds report isOpened() True yet fail on the first read for
                # an unsupported codec. Probe once, then rewind.
                ok, _frame = cap.read()
                if ok:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self._cap = cap
                    self.fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                    self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    self.is_sequence = False
                    self.decoder = "opencv"
                    return
                cap.release()
            else:
                cap.release()

        # OpenCV could not decode it (or FFmpeg was forced): universal fallback.
        if self._init_video_ffmpeg(path):
            return
        raise RuntimeError(
            f"Cannot open video file: {path} (OpenCV failed and the FFmpeg "
            "fallback could not decode it - the format may be encrypted or need "
            "the vendor's own export tool)."
        )

    def _init_video_ffmpeg(self, path: Path) -> bool:
        """Decode ``path`` by piping raw BGR frames from the bundled FFmpeg.

        Returns True on success (self._ff_proc is live and metadata is set),
        False if FFmpeg is unavailable or the file has no decodable video stream.
        Universal for any container FFmpeg can demux (R4 Phase 6).
        """
        try:
            from utils.ffmpeg import ffmpeg_path, ffprobe_path, ffmpeg_available
        except ModuleNotFoundError:  # pragma: no cover - import path shim
            from src.utils.ffmpeg import ffmpeg_path, ffprobe_path, ffmpeg_available
        if not ffmpeg_available():
            return False

        # 1) Probe stream geometry (width/height/fps/frame count).
        try:
            probe = subprocess.run(
                [ffprobe_path(), "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
                 "-of", "json", str(path)],
                capture_output=True, text=True, timeout=30,
            )
            info = (json.loads(probe.stdout or "{}").get("streams") or [{}])[0]
            w = int(info.get("width") or 0)
            h = int(info.get("height") or 0)
        except (OSError, subprocess.SubprocessError, ValueError, KeyError):
            return False
        if w <= 0 or h <= 0:
            return False

        # r_frame_rate is "num/den"; fall back to 25 fps if unparseable.
        fps = 25.0
        try:
            num, _, den = str(info.get("r_frame_rate", "25/1")).partition("/")
            fps = (float(num) / float(den)) if float(den) else float(num)
            if not (0 < fps <= 240):
                fps = 25.0
        except (TypeError, ValueError, ZeroDivisionError):
            fps = 25.0
        try:
            total = int(info.get("nb_frames") or 0)
        except (TypeError, ValueError):
            total = 0

        # 2) Spawn FFmpeg to emit raw BGR24 frames on stdout.
        try:
            proc = subprocess.Popen(
                [ffmpeg_path(), "-v", "error", "-nostdin", "-i", str(path),
                 "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
        except OSError:
            return False

        self._ff_proc = proc
        self._ff_frame_bytes = w * h * 3
        self.width, self.height = w, h
        self.fps = fps
        self.total_frames = total
        self.is_sequence = False
        self.decoder = "ffmpeg"
        log.info("FrameSource: OpenCV could not open %s; decoding via FFmpeg "
                 "(%dx%d @ %.0ffps).", Path(path).name, w, h, fps)
        return True

    def _read_ffmpeg(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Read exactly one raw BGR frame from the FFmpeg stdout pipe."""
        proc = self._ff_proc
        if proc is None or proc.stdout is None:
            return False, None
        need = self._ff_frame_bytes
        buf = bytearray()
        # stdout.read may return short chunks; loop until we have a full frame.
        while len(buf) < need:
            chunk = proc.stdout.read(need - len(buf))
            if not chunk:
                return False, None   # EOF / stream ended
            buf.extend(chunk)
        frame = np.frombuffer(bytes(buf), np.uint8).reshape((self.height, self.width, 3))
        return True, frame

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Read the next frame. Identical signature to cv2.VideoCapture.read().

        Returns:
            (True, frame_array) on success.
            (False, None) when the source is exhausted.
        """
        if self.is_sequence:
            if self._seq_idx >= len(self.frame_files):
                return False, None
            frame = cv2.imread(str(self.frame_files[self._seq_idx]))
            self._seq_idx += 1
            if frame is None:
                return False, None
            return True, frame
        elif self._ff_proc is not None:
            return self._read_ffmpeg()
        else:
            return self._cap.read()

    def release(self):
        """Release the underlying video capture / FFmpeg decode process."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        if self._ff_proc is not None:
            proc = self._ff_proc
            self._ff_proc = None
            try:
                if proc.stdout is not None:
                    proc.stdout.close()
            except OSError:
                pass
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except (OSError, subprocess.SubprocessError):
                    pass

    def get_scene_name(self) -> str:
        """
        Returns a human-readable scene name for logging and file naming.
        For CDnet sequences, returns the scene folder name (e.g., 'highway').
        For video files, returns the stem (e.g., 'test_clip').
        """
        if self.is_sequence and self.frame_files:
            p = Path(self.frame_files[0])
            # parent is input/, parent.parent is the scene folder
            return p.parent.parent.name
        return Path(self.input_path).stem

    def get_warmup_frames(self, fallback: int = 120) -> int:
        """
        Returns the recommended warmup frame count for this source.

        For CDnet sequences, the temporalROI start frame is the number of
        frames the CDnet benchmark expects to be used for background model
        initialization. Using this value ensures our results are comparable
        to published CDnet benchmark scores.

        For video files, returns the fallback value (default 120 frames).

        Args:
            fallback: Warmup frame count to use when temporalROI is not available.

        Returns:
            Number of frames to feed through BackgroundSubtractor before
            using its output for detection or encoding decisions.
        """
        if self.temporal_roi is not None:
            # temporal_roi[0] is 1-indexed; subtract 1 for 0-indexed frame count
            return max(0, self.temporal_roi[0] - 1)
        return fallback

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.release()

    def __repr__(self):
        roi = f"  temporalROI={self.temporal_roi}" if self.temporal_roi else ""
        fmt = "sequence" if self.is_sequence else "video"
        return (
            f"FrameSource({self.get_scene_name()!r}, {fmt}, "
            f"{self.total_frames} frames, {self.width}x{self.height}@{self.fps:.0f}fps{roi})"
        )
