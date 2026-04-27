"""
multi_source.py

Multi-source frame reader that handles multiple simultaneous RTSP streams.

Extends the single-source FrameSource pattern to support N cameras running
in parallel. Each stream runs in its own background thread so a slow or
stalled camera does not block the others.

Author: Jorge Sanchez (JS)

Usage:
    sources = [
        "rtsp://192.168.1.10/stream1",
        "rtsp://192.168.1.11/stream1",
        "rtsp://192.168.1.12/stream1",
    ]
    with MultiFrameSource(sources) as msrc:
        while True:
            frames = msrc.read_all()
            if not any(ok for ok, _ in frames):
                break
            for cam_idx, (ok, frame) in enumerate(frames):
                if ok:
                    process(frame, cam_idx)
"""

import threading
import time
import logging
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)

# How long (seconds) to wait for a frame before declaring a stream stalled.
FRAME_TIMEOUT = 5.0

# Maximum frames to buffer per stream. Oldest frames are dropped when full.
BUFFER_SIZE = 2


class _StreamReader:
    """
    Background thread that continuously reads frames from a single RTSP stream.

    Frames are stored in a small buffer. The main thread calls get_frame()
    to retrieve the latest frame without blocking on network I/O.
    """

    def __init__(self, source: str, cam_index: int):
        """
        Args:
            source: RTSP URL or video file path for this stream.
            cam_index: Index of this stream in the MultiFrameSource list.
        """
        self.source = source
        self.cam_index = cam_index
        self.cam_id = f"cam_{cam_index:02d}"

        self._cap: Optional[cv2.VideoCapture] = None
        self._lock = threading.Lock()
        self._buffer: List[np.ndarray] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_frame_time: float = 0.0
        self._error: Optional[str] = None

        # Metadata (set after capture opens)
        self.fps: float = 30.0
        self.width: int = 0
        self.height: int = 0
        self.is_open: bool = False

    def start(self) -> bool:
        """
        Open the stream and start the background reader thread.

        Returns:
            True if the stream opened successfully, False otherwise.
        """
        self._cap = cv2.VideoCapture(self.source)
        if not self._cap.isOpened():
            self._error = f"Cannot open stream: {self.source}"
            log.error(self._error)
            return False

        self.fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.is_open = True
        self._running = True
        self._last_frame_time = time.time()

        self._thread = threading.Thread(
            target=self._read_loop,
            name=f"StreamReader-{self.cam_id}",
            daemon=True,
        )
        self._thread.start()
        log.info(f"[{self.cam_id}] Stream opened: {self.source} ({self.width}x{self.height}@{self.fps:.0f}fps)")
        return True

    def _read_loop(self) -> None:
        """Continuously read frames and store them in the buffer."""
        while self._running:
            if self._cap is None:
                break
            try:
                ret, frame = self._cap.read()
            except StopIteration:
                self._running = False
                break
            if not ret:
                log.warning(f"[{self.cam_id}] Stream ended or read failed.")
                self._running = False
                break
            with self._lock:
                if len(self._buffer) >= BUFFER_SIZE:
                    self._buffer.pop(0)
                self._buffer.append(frame)
                self._last_frame_time = time.time()

    def get_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Return the latest buffered frame.

        Returns:
            (True, frame) if a frame is available.
            (False, None) if the stream is stalled or ended.
        """
        if not self._running and not self._buffer:
            return False, None

        # Check for stall (no new frame within timeout)
        if time.time() - self._last_frame_time > FRAME_TIMEOUT:
            log.warning(f"[{self.cam_id}] Stream stalled (no frame for {FRAME_TIMEOUT}s).")
            return False, None

        with self._lock:
            if not self._buffer:
                return False, None
            frame = self._buffer.pop(0)
        return True, frame

    def is_alive(self) -> bool:
        """Return True if the stream is still running."""
        return self._running

    def stop(self) -> None:
        """Stop the reader thread and release the capture."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self.is_open = False
        log.info(f"[{self.cam_id}] Stream released.")


class MultiFrameSource:
    """
    Manages multiple simultaneous RTSP (or file) video streams.

    Each stream runs in a background thread. The main thread calls
    read_all() to get the latest frame from every stream at once.

    Streams that fail to open are skipped with a warning. Streams that
    stall or end mid-session are marked inactive but do not crash the others.

    Usage:
        with MultiFrameSource(["rtsp://cam1", "rtsp://cam2"]) as msrc:
            while msrc.any_alive():
                frames = msrc.read_all()
                for cam_idx, (ok, frame) in enumerate(frames):
                    if ok:
                        process(frame)
    """

    def __init__(self, sources: List[str]):
        """
        Args:
            sources: List of RTSP URLs or video file paths.

        Raises:
            ValueError: If sources list is empty.
        """
        if not sources:
            raise ValueError("MultiFrameSource requires at least one source.")

        self._readers: List[_StreamReader] = [
            _StreamReader(src, idx) for idx, src in enumerate(sources)
        ]
        self.source_count = len(sources)

    def open(self) -> int:
        """
        Open all streams and start background reader threads.

        Returns:
            Number of streams that opened successfully.
        """
        opened = sum(r.start() for r in self._readers)
        log.info(f"MultiFrameSource: {opened}/{self.source_count} streams opened.")
        return opened

    def read_all(self) -> List[Tuple[bool, Optional[np.ndarray]]]:
        """
        Read the latest frame from every stream.

        Returns:
            List of (ok, frame) tuples, one per source, in the same order
            as the sources list passed to __init__. ok=False means the
            stream has no frame available (stalled, ended, or failed to open).
        """
        return [r.get_frame() for r in self._readers]

    def any_alive(self) -> bool:
        """Return True if at least one stream is still running."""
        return any(r.is_alive() for r in self._readers)

    def active_count(self) -> int:
        """Return the number of streams currently running."""
        return sum(r.is_alive() for r in self._readers)

    def get_metadata(self) -> List[dict]:
        """
        Return metadata for all streams.

        Returns:
            List of dicts with keys: cam_id, source, fps, width, height, is_open.
        """
        return [
            {
                "cam_id": r.cam_id,
                "source": r.source,
                "fps": r.fps,
                "width": r.width,
                "height": r.height,
                "is_open": r.is_open,
            }
            for r in self._readers
        ]

    def release(self) -> None:
        """Stop all reader threads and release all captures."""
        for r in self._readers:
            r.stop()
        log.info("MultiFrameSource: all streams released.")

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.release()

    def __repr__(self):
        active = self.active_count()
        return f"MultiFrameSource({active}/{self.source_count} streams active)"