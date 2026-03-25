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

import cv2
import numpy as np
from pathlib import Path
from typing import Optional, Tuple


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

    def __init__(self, input_path: str):
        """
        Initializes the frame source by detecting whether input_path is a
        video file or a CDnet image sequence folder.

        For CDnet folders, automatically finds the input/ subfolder if the
        top-level scene folder is provided. Also reads temporalROI.txt to
        expose the valid frame range (frames outside this range have no
        ground truth annotations).

        Args:
            input_path: Path to a video file, CDnet scene folder, or CDnet
                        input/ subfolder.

        Raises:
            RuntimeError: If the path cannot be opened or no frames are found.
        """
        path = Path(input_path)
        self.input_path = str(path)
        self.is_sequence = False
        self.frame_files = []
        self._seq_idx = 0
        self._cap = None
        self.fps = 30.0
        self.width = 0
        self.height = 0
        self.total_frames = 0
        self.temporal_roi: Optional[Tuple[int, int]] = None  # (start, end) frame numbers

        if path.is_dir():
            self._init_sequence(path)
        elif path.is_file():
            self._init_video(path)
        else:
            raise RuntimeError(f"Input path does not exist: {input_path}")

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
        Sets up reading from a standard video file via cv2.VideoCapture.
        Queries metadata (fps, resolution, frame count) from the container.
        """
        self._cap = cv2.VideoCapture(str(path))
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open video file: {path}")

        self.fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.is_sequence = False

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
        else:
            return self._cap.read()

    def release(self):
        """Release the underlying video capture if open."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

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
