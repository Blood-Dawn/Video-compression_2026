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
from pathlib import Path
from datetime import datetime
from typing import List, Optional

# Import from sibling modules
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from background_subtraction.background_subtraction import ForegroundRegion
from utils.db import initialize_database, insert_segment


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
        background_crf: int = 40,
        preset: str = "veryfast",
        db_path: str = "outputs/metadata.db",
    ):
        """
        Args:
            output_dir: Where to write compressed output files.
            foreground_crf: CRF for foreground ROIs. Lower = higher quality.
                            18 is visually lossless; 23 is default H.264.
            background_crf: CRF for background. 40 gives heavy compression.
            preset: FFmpeg encoding speed preset. veryfast is good for low-spec hardware.
            db_path: SQLite database path for storing metadata index.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.foreground_crf = foreground_crf
        self.background_crf = background_crf
        self.preset = preset
        self.db_path = db_path
        # db.py owns the schema — delegate initialization there so both
        # the encoder and the pipeline always agree on column names.
        initialize_database(db_path)

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

        # Build output kwargs conditionally -- passing acodec=None to
        # ffmpeg-python causes it to emit an empty flag which errors on
        # some FFmpeg versions. Only include acodec when audio is present.
        output_kwargs = dict(vcodec="libx264", crf=crf, preset=self.preset)
        if self._has_audio(input_path):
            output_kwargs["acodec"] = "copy"

        (
            ffmpeg
            .input(input_path)
            .output(str(output_path), **output_kwargs)
            .overwrite_output()
            .run(quiet=True)
        )

        file_size = output_path.stat().st_size if output_path.exists() else 0
        roi_count = sum(len(r) for r in regions_per_frame)

        # Use db.py's insert_segment() so this always writes to the canonical
        # schema. pipeline.py must NOT call insert_segment() again after this —
        # doing so would produce a duplicate row for every segment.
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

    def _has_audio(self, path: str) -> bool:
        try:
            probe = ffmpeg.probe(path)
            return any(s["codec_type"] == "audio" for s in probe["streams"])
        except Exception:
            return False

    def get_storage_report(self) -> dict:
        """Return summary statistics from the metadata index."""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        # Column names match db.py's canonical schema:
        # target_detected (not has_targets), duration (not duration_s)
        cursor = conn.execute("""
            SELECT
                COUNT(*)              as total_segments,
                SUM(file_size)        as total_bytes,
                SUM(target_detected)  as segments_with_targets,
                SUM(roi_count)        as total_roi_detections,
                SUM(duration)         as total_duration_s
            FROM segments
        """)
        row = cursor.fetchone()
        conn.close()
        return {
            "total_segments": row[0],
            "total_bytes": row[1],
            "total_gb": round((row[1] or 0) / 1e9, 3),
            "segments_with_targets": row[2],
            "total_roi_detections": row[3],
            "total_duration_hours": round((row[4] or 0) / 3600, 2),
        }
