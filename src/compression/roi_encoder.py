"""
roi_encoder.py

ROI-aware video encoding using FFmpeg.
Foreground regions (people, vehicles) are encoded at high quality.
Background is encoded at aggressive compression or as periodic keyframes only.

Requires: ffmpeg installed and on PATH, ffmpeg-python package.
All encoding uses libx264 (open source, royalty-free, runs on CPU).
"""

import ffmpeg
import numpy as np
import subprocess
import re
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple

# Import from sibling modules
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from background_subtraction.background_subtraction import ForegroundRegion
from utils.db import initialize_database, insert_segment, get_connection


class ROIEncoder:
    """
    Encodes video with separate quality tiers for foreground and background.

    Strategy:
      - Background: encoded at high CRF (low quality, small size).
      - Foreground ROIs: encoded at low CRF (high quality, preserves detail).

    encode_segment() accepts raw numpy frames and pipes them directly to FFmpeg
    via stdin, avoiding any lossy intermediate file format.

    encode_frame_sequence() is kept for backward compatibility with code that
    passes a pre-written video file path.
    """

    def __init__(
        self,
        output_dir: str = "outputs/",
        foreground_crf: int = 18,
        background_crf: int = 40,
        preset: str = "veryfast",
        db_path: str = "outputs/metadata.db",
    ):
        """
        Args:
            output_dir: Where to write compressed output files.
            foreground_crf: CRF for foreground ROIs. 18 is visually lossless.
            background_crf: CRF for background. 40 gives heavy compression.
            preset: FFmpeg speed preset. veryfast is good for low-spec hardware.
            db_path: SQLite database path for the metadata index.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.foreground_crf = foreground_crf
        self.background_crf = background_crf
        self.preset = preset
        self.db_path = db_path
        # db.py owns the schema — delegate initialization so encoder and
        # pipeline always agree on column names and indexes.
        initialize_database(db_path)

        # Cache the audio-presence check so we don't probe every segment.
        # Surveillance cameras virtually never have audio; probing is wasted I/O.
        # Set to None = not yet determined; probe lazily on first encode_frame_sequence call.
        self._source_has_audio: Optional[bool] = None

    # ------------------------------------------------------------------
    # Primary API: encode raw numpy frames (no lossy intermediate file)
    # ------------------------------------------------------------------

    def encode_segment(
        self,
        frames: List[np.ndarray],
        bboxes_per_frame: Optional[List[List[Tuple[int, int, int, int]]]] = None,
        camera_id: str = "cam_unknown",
        fps: float = 30.0,
    ) -> str:
        """
        Encode a list of raw BGR numpy frames into a compressed MP4.

        Frames are piped directly to FFmpeg via stdin — no intermediate file,
        no quality loss from a lossy codec like XVID. The CRF is chosen based
        on whether any bounding boxes are present: foreground_crf when targets
        are detected, background_crf otherwise.

        Args:
            frames: List of BGR uint8 numpy arrays, all the same shape.
            bboxes_per_frame: Optional bounding boxes per frame as (x,y,w,h) tuples.
                              Used to determine foreground/background CRF selection.
                              If None, treated as background-only.
            camera_id: Camera identifier for output filename and DB row.
            fps: Frames per second for the output video.

        Returns:
            Path to the compressed output MP4 file.

        Raises:
            ValueError: If frames is empty or frames have inconsistent shapes.
            RuntimeError: If FFmpeg fails or the output file is missing/empty.
        """
        if not frames:
            raise ValueError("frames must not be empty")

        shape = frames[0].shape
        if any(f.shape != shape for f in frames):
            raise ValueError("All frames must have the same shape")

        if bboxes_per_frame is None:
            bboxes_per_frame = [[] for _ in frames]
        if len(bboxes_per_frame) != len(frames):
            raise ValueError(
                f"bboxes_per_frame length {len(bboxes_per_frame)} "
                f"must match frames length {len(frames)}"
            )

        has_targets = any(len(b) > 0 for b in bboxes_per_frame)
        crf = self.foreground_crf if has_targets else self.background_crf
        roi_count = sum(len(b) for b in bboxes_per_frame)

        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        output_path = self.output_dir / f"{camera_id}_{timestamp}.mp4"

        h, w = shape[:2]
        # Pipe raw BGR frames to FFmpeg. Input format is rawvideo (BGR24).
        # FFmpeg encodes to H.264 (libx264) at the chosen CRF.
        process = (
            ffmpeg
            .input(
                "pipe:0",
                format="rawvideo",
                pix_fmt="bgr24",
                s=f"{w}x{h}",
                framerate=fps,
            )
            .output(
                str(output_path),
                vcodec="libx264",
                crf=crf,
                preset=self.preset,
                pix_fmt="yuv420p",
            )
            .overwrite_output()
            .run_async(pipe_stdin=True, quiet=True)
        )

        # Build the full raw byte buffer and send it in one communicate() call.
        # This drains stdout AND stderr automatically, preventing the deadlock
        # that occurs when quiet=True pipes stderr — if the pipe buffer fills
        # and nobody reads it, FFmpeg blocks and pytest freezes indefinitely.
        raw = b"".join(f.tobytes() for f in frames)
        process.communicate(input=raw)

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(
                f"FFmpeg produced no output for segment {timestamp}. "
                "Check that ffmpeg is installed and on PATH."
            )

        file_size = output_path.stat().st_size
        duration = len(frames) / fps

        insert_segment(
            timestamp=timestamp,
            camera_id=camera_id,
            target_detected=has_targets,
            roi_count=roi_count,
            file_size=file_size,
            duration=duration,
            file_path=str(output_path),
            db_path=self.db_path,
        )

        return str(output_path)

    # ------------------------------------------------------------------
    # Legacy API: encode from a pre-written video file path
    # ------------------------------------------------------------------

    def encode_frame_sequence(
        self,
        input_path: str,
        regions_per_frame: List[List[ForegroundRegion]],
        camera_id: str = "cam_unknown",
        segment_duration_s: int = 60,
    ) -> str:
        """
        Encode a video segment from a file path with ROI-aware compression.

        Kept for backward compatibility. New code should use encode_segment()
        which accepts raw numpy frames and avoids lossy intermediates.

        Args:
            input_path: Path to raw video segment file.
            regions_per_frame: ForegroundRegion lists, one per frame.
            camera_id: Camera identifier for output filename and DB row.
            segment_duration_s: Duration of this segment in seconds.

        Returns:
            Path to the compressed output MP4 file.
        """
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        has_targets = any(len(r) > 0 for r in regions_per_frame)
        output_path = self.output_dir / f"{camera_id}_{timestamp}.mp4"

        crf = self.foreground_crf if has_targets else self.background_crf

        # Probe for audio once and cache the result.
        # Avoids a subprocess call per segment for sources that never have audio.
        if self._source_has_audio is None:
            self._source_has_audio = self._probe_has_audio(input_path)

        output_kwargs: dict = dict(vcodec="libx264", crf=crf, preset=self.preset)
        if self._source_has_audio:
            output_kwargs["acodec"] = "copy"

        (
            ffmpeg
            .input(input_path)
            .output(str(output_path), **output_kwargs)
            .overwrite_output()
            .run(quiet=True)
        )

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(
                f"FFmpeg produced no output for {input_path}. "
                "Check that ffmpeg is installed and the input file is valid."
            )

        file_size = output_path.stat().st_size
        roi_count = sum(len(r) for r in regions_per_frame)

        insert_segment(
            timestamp=timestamp,
            camera_id=camera_id,
            target_detected=has_targets,
            roi_count=roi_count,
            file_size=file_size,
            duration=float(segment_duration_s),
            file_path=str(output_path),
            db_path=self.db_path,
        )

        return str(output_path)

    def get_file_size(self, path: str) -> int:
        """Return file size in bytes, or 0 if the file does not exist."""
        p = Path(path)
        return p.stat().st_size if p.exists() else 0

    def _probe_has_audio(self, path: str) -> bool:
        """Return True if the file has at least one audio stream."""
        try:
            probe = ffmpeg.probe(path)
            return any(s["codec_type"] == "audio" for s in probe["streams"])
        except Exception:
            return False

    def get_storage_report(self) -> dict:
        """
        Return aggregate statistics from the metadata index.

        Uses get_connection() and a context manager so the connection is
        always closed even if the query raises.

        Returns:
            Dict with keys: total_segments, total_bytes, total_gb,
            segments_with_targets, total_roi_detections, total_duration_hours.
        """
        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT
                    COUNT(*)                 AS total_segments,
                    COALESCE(SUM(file_size), 0)   AS total_bytes,
                    COALESCE(SUM(target_detected), 0) AS segments_with_targets,
                    COALESCE(SUM(roi_count), 0)   AS total_roi_detections,
                    COALESCE(SUM(duration),  0.0) AS total_duration_s
                FROM segments
                """
            )
            row = cursor.fetchone()

        return {
            "total_segments":       row[0],
            "total_bytes":          row[1],
            "total_gb":             round(row[1] / 1e9, 3),
            "segments_with_targets": row[2],
            "total_roi_detections": row[3],
            "total_duration_hours": round(row[4] / 3600, 2),
        }
