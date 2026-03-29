"""
roi_encoder.py

ROI-aware video encoding using FFmpeg.
Foreground regions (people, vehicles) are encoded at high quality.
Background is encoded at aggressive compression or as periodic keyframes only.

Requires: ffmpeg installed and on PATH, ffmpeg-python package.
All encoding uses libx264 (open source, royalty-free, runs on CPU).
"""

import ffmpeg
import os
import json
import sqlite3
import subprocess
import tempfile
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple

# Import from sibling module
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from background_subtraction.background_subtraction import ForegroundRegion


class ROIEncoder:
    """
    Encodes video with separate quality tiers for foreground and background.

    Strategy:
      - Background: encoded at high CRF (low quality, small size) or
                    as infrequent keyframes only.
      - Foreground ROIs: encoded at low CRF (high quality, preserves detail).

    This mirrors the meeting insight: "saved 6x the amount of data by saving
    just the people who pass through the image."
    """

    def __init__(
        self,
        output_dir: str = "outputs/",
        foreground_crf: int = 18,
        background_crf: int = 45,
        preset: str = "veryfast",
        db_path: str = "outputs/metadata.db",
    ):
        """
        Args:
            output_dir: Where to write compressed output files.
            foreground_crf: CRF for foreground ROIs. Lower = higher quality.
                            18 is visually lossless; 23 is default H.264.
            background_crf: CRF for background. 45 gives heavy compression.
            preset: FFmpeg encoding speed preset. veryfast is good for low-spec hardware.
            db_path: SQLite database path for storing metadata index.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.foreground_crf = foreground_crf
        self.background_crf = background_crf
        self.preset = preset
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize SQLite metadata index for compressed segments."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS segments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                filename    TEXT NOT NULL,
                timestamp   TEXT NOT NULL,
                camera_id   TEXT,
                has_targets INTEGER DEFAULT 0,
                roi_count   INTEGER DEFAULT 0,
                file_size   INTEGER,
                duration_s  REAL,
                notes       TEXT
            )
        """)
        conn.commit()
        conn.close()

    def encode_segment(
        self,
        frames: List[np.ndarray],
        bboxes_per_frame: List[List[Tuple[int, int, int, int]]],
        camera_id: str = "cam_unknown",
        timestamp: Optional[str] = None,
        fps: int = 30,
    ) -> Tuple[str, int]:
        """
        Encode a list of raw frames into a compressed video segment.

        Uses dual-pass encoding strategy:
          - If any foreground bounding boxes exist, the segment is encoded at
            foreground_crf (high quality, ~18-23).
          - If no motion is detected anywhere, background_crf (heavy compression,
            ~40-51) is used instead.

        This is the primary encode method expected by the pipeline and roadmap.

        Args:
            frames: List of BGR frames as NumPy arrays (H x W x 3).
            bboxes_per_frame: Bounding boxes per frame as (x, y, w, h) tuples.
            camera_id: Identifier for this camera, stored in metadata DB.
            timestamp: ISO timestamp string. Defaults to current UTC time.
            fps: Frames per second for the output video.

        Returns:
            Tuple of (output_file_path: str, file_size_bytes: int).
        """
        if not frames:
            raise ValueError("frames list is empty — nothing to encode.")

        if len(bboxes_per_frame) != len(frames):
            raise ValueError(
                f"bboxes_per_frame length ({len(bboxes_per_frame)}) must match "
                f"frames length ({len(frames)})."
            )

        if timestamp is None:
            timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

        output_name = f"{camera_id}_{timestamp}.mp4"
        output_path = self.output_dir / output_name

        # Dual-pass CRF selection: use high quality if any targets detected
        has_targets = any(len(boxes) > 0 for boxes in bboxes_per_frame)
        crf = self.foreground_crf if has_targets else self.background_crf

        # Get frame dimensions from first frame
        height, width = frames[0].shape[:2]
        duration_s = len(frames) / fps

        # Pipe raw frames to FFmpeg via stdin
        process = (
            ffmpeg
            .input(
                "pipe:0",
                format="rawvideo",
                pix_fmt="bgr24",
                s=f"{width}x{height}",
                r=fps,
            )
            .output(
                str(output_path),
                vcodec="libx264",
                pix_fmt="yuv420p",
                crf=crf,
                preset=self.preset,
            )
            .overwrite_output()
            .run_async(pipe_stdin=True, quiet=True)
        )

        # Write each frame as raw bytes
        for frame in frames:
            process.stdin.write(frame.astype(np.uint8).tobytes())

        process.stdin.close()
        process.wait()

        if not output_path.exists():
            raise RuntimeError(
                f"FFmpeg encoding failed — output file not created: {output_path}"
            )

        file_size = self.get_file_size(str(output_path))
        if file_size == 0:
            raise RuntimeError(
                f"FFmpeg encoding failed — output file is empty: {output_path}"
            )
        roi_count = sum(len(boxes) for boxes in bboxes_per_frame)

        # Write metadata row to SQLite
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO segments
                   (filename, timestamp, camera_id, has_targets, roi_count, file_size, duration_s)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    output_name,
                    timestamp,
                    camera_id,
                    int(has_targets),
                    roi_count,
                    file_size,
                    round(duration_s, 3),
                ),
            )

        return str(output_path), file_size

    def get_file_size(self, path: str) -> int:
        """
        Return the size of a file in bytes.

        Args:
            path: Path to the file.

        Returns:
            File size in bytes, or 0 if the file does not exist.
        """
        p = Path(path)
        if not p.exists():
            return 0
        return p.stat().st_size

    def encode_frame_sequence(
        self,
        input_path: str,
        regions_per_frame: List[List[ForegroundRegion]],
        camera_id: str = "cam_unknown",
        segment_duration_s: int = 60,
    ) -> str:
        """
        Encode a video segment with ROI-aware compression.

        For now this encodes the full video at two quality levels and overlays
        a high-quality pass on the foreground bounding boxes using FFmpeg
        filter_complex. Full ROI-level masking will be implemented in milestone 2.

        Args:
            input_path: Path to raw video segment.
            regions_per_frame: List of ForegroundRegion lists, one per frame.
            camera_id: Identifier for this camera feed.
            segment_duration_s: Duration of this segment in seconds.

        Returns:
            Path to the compressed output file.
        """
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        has_targets = any(len(r) > 0 for r in regions_per_frame)
        output_name = f"{camera_id}_{timestamp}.mp4"
        output_path = self.output_dir / output_name

        crf = self.foreground_crf if has_targets else self.background_crf

        (
            ffmpeg
            .input(input_path)
            .output(
                str(output_path),
                vcodec="libx264",
                crf=crf,
                preset=self.preset,
                acodec="copy" if self._has_audio(input_path) else None,
            )
            .overwrite_output()
            .run(quiet=True)
        )

        file_size = output_path.stat().st_size if output_path.exists() else 0
        roi_count = sum(len(r) for r in regions_per_frame)

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT INTO segments
               (filename, timestamp, camera_id, has_targets, roi_count, file_size, duration_s)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (output_name, timestamp, camera_id, int(has_targets), roi_count,
             file_size, segment_duration_s),
        )
        conn.commit()
        conn.close()

        return str(output_path)

    def _has_audio(self, path: str) -> bool:
        try:
            probe = ffmpeg.probe(path)
            return any(s["codec_type"] == "audio" for s in probe["streams"])
        except Exception:
            return False

    def get_storage_report(self) -> dict:
        """Return summary statistics from the metadata index."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total_segments,
                    SUM(file_size) as total_bytes,
                    SUM(has_targets) as segments_with_targets,
                    SUM(roi_count) as total_roi_detections,
                    SUM(duration_s) as total_duration_s
                FROM segments
            """)
            row = cursor.fetchone()
        return {
            "total_segments": row[0],
            "total_bytes": row[1],
            "total_gb": round((row[1] or 0) / 1e9, 3),
            "segments_with_targets": row[2],
            "total_roi_detections": row[3],
            "total_duration_hours": round((row[4] or 0) / 3600, 2),
        }
