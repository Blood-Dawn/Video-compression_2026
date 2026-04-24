"""
roi_encoder.py

ROI-aware video encoding using FFmpeg.
Foreground regions (people, vehicles) are encoded at high quality.
Background is encoded at aggressive compression or as periodic keyframes only.

Requires: ffmpeg installed and on PATH, ffmpeg-python package.
All encoding uses libx264 (open source, royalty-free, runs on CPU).
"""

import cv2
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


# ── Corner overlay ────────────────────────────────────────────────────────────

def draw_corner_overlay(frame: np.ndarray, mode_label: str, elapsed_s: int) -> None:
    """Burn a semi-transparent info box into the top-left corner of *frame*.

    Modifies the array in-place. Shows the mode name on the first line and
    a MM:SS elapsed timer on the second. Designed to match the HLS live-stream
    overlay so saved segments and the live preview look identical.

    Args:
        frame:      BGR uint8 numpy array — modified in-place.
        mode_label: Short mode string, e.g. "MODE 0 · 24/7".
        elapsed_s:  Seconds elapsed since the segment started.
    """
    mins, secs = divmod(elapsed_s, 60)
    lines = [mode_label, f"{mins:02d}:{secs:02d}"]

    font       = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.42
    thickness  = 1
    line_h     = 18
    padding    = 6

    sizes = [cv2.getTextSize(ln, font, font_scale, thickness)[0] for ln in lines]
    box_w = max(sz[0] for sz in sizes) + 2 * padding
    box_h = len(lines) * line_h + 2 * padding

    bx1, by1 = 8, 8
    bx2, by2 = bx1 + box_w, by1 + box_h

    # Semi-transparent black background
    overlay = frame.copy()
    cv2.rectangle(overlay, (bx1, by1), (bx2, by2), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, dst=frame)

    y = by1 + padding + line_h - 4
    for ln in lines:
        cv2.putText(frame, ln, (bx1 + padding, y),
                    font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
        y += line_h


_MODE_LABELS = {
    "mode0": "MODE 0 \u00b7 24/7",
    "mode1": "MODE 1 \u00b7 EVENT",
    "mode2": "MODE 2 \u00b7 PATCHES",
    "mode3": "MODE 3 \u00b7 OBJ ONLY",
}


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
        draw_roi_boxes: bool = False,
    ):
        """
        Args:
            output_dir: Where to write compressed output files.
            foreground_crf: CRF for foreground ROIs. 18 is visually lossless.
            background_crf: CRF for background. 40 gives heavy compression.
            preset: FFmpeg speed preset. veryfast is good for low-spec hardware.
            db_path: SQLite database path for the metadata index.
            draw_roi_boxes: When True, burn green ROI boxes into encoded output.
                            Keep False for archival/integrity-preserving output.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.foreground_crf = foreground_crf
        self.background_crf = background_crf
        self.preset = preset
        self.db_path = db_path
        self.draw_roi_boxes = draw_roi_boxes
        # db.py owns the schema — delegate initialization so encoder and
        # pipeline always agree on column names and indexes.
        initialize_database(db_path)

        # Cache the audio-presence check so we don't probe every segment.
        # Surveillance cameras virtually never have audio; probing is wasted I/O.
        # Set to None = not yet determined; probe lazily on first encode_frame_sequence call.
        self._source_has_audio: Optional[bool] = None

    @staticmethod
    def _copy_bboxes_to_black_frame(
        frame: np.ndarray,
        boxes: List[Tuple[int, int, int, int]],
    ) -> np.ndarray:
        """
        Return a full-size black frame with only bbox rectangles copied through.

        This keeps output playable as a normal MP4 while making pixels outside
        the detected object boxes trivially compressible.
        """
        object_only = np.zeros_like(frame)
        h, w = frame.shape[:2]
        for bx, by, bw, bh in boxes:
            x1 = max(0, int(bx))
            y1 = max(0, int(by))
            x2 = min(w, int(bx) + int(bw))
            y2 = min(h, int(by) + int(bh))
            if x2 > x1 and y2 > y1:
                object_only[y1:y2, x1:x2] = frame[y1:y2, x1:x2]
        return object_only

    @staticmethod
    def _copy_bboxes_to_background_frame(
        background_frame: np.ndarray,
        frame: np.ndarray,
        boxes: List[Tuple[int, int, int, int]],
    ) -> np.ndarray:
        """
        Return a frame made from one background keyframe plus current bbox patches.

        This is the mode2 representation: keep static scene context from a clean
        background frame while updating only the detected moving-object boxes.
        """
        composed = background_frame.copy()
        h, w = frame.shape[:2]
        for bx, by, bw, bh in boxes:
            x1 = max(0, int(bx))
            y1 = max(0, int(by))
            x2 = min(w, int(bx) + int(bw))
            y2 = min(h, int(by) + int(bh))
            if x2 > x1 and y2 > y1:
                composed[y1:y2, x1:x2] = frame[y1:y2, x1:x2]
        return composed

    # ------------------------------------------------------------------
    # Primary API: encode raw numpy frames (no lossy intermediate file)
    # ------------------------------------------------------------------

    def encode_segment(
        self,
        frames: List[np.ndarray],
        bboxes_per_frame: Optional[List[List[Tuple[int, int, int, int]]]] = None,
        camera_id: str = "cam_unknown",
        fps: float = 30.0,
        object_type="unknown",
        draw_roi_boxes: Optional[bool] = None,
        object_only: bool = False,
        background_frame: Optional[np.ndarray] = None,
        mode_label: str = "",
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
            object_type: Metadata label stored with this segment.
            draw_roi_boxes: Override for whether ROI boxes are burned into this
                            encoded output. Defaults to the encoder instance setting.
            object_only: When True, encode normal full-size MP4 frames but copy
                         only bbox rectangles onto a black canvas before
                         compression. Used by mode3.
            background_frame: Optional clean BGR background keyframe. When
                              provided, encode each frame by copying only bbox
                              rectangles from that frame onto this background.
                              Used by mode2.

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
        if background_frame is not None and background_frame.shape != shape:
            raise ValueError("background_frame must have the same shape as frames")

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

        should_draw_boxes = self.draw_roi_boxes if draw_roi_boxes is None else draw_roi_boxes
        safe_fps = fps if fps and fps > 0 else 30.0

        try:
            for frame_idx, (frame, boxes) in enumerate(zip(frames, bboxes_per_frame)):
                if object_only:
                    frame_to_write = self._copy_bboxes_to_black_frame(frame, boxes)
                elif background_frame is not None:
                    frame_to_write = self._copy_bboxes_to_background_frame(
                        background_frame, frame, boxes
                    )
                else:
                    frame_to_write = frame
                if should_draw_boxes and boxes:
                    if object_only:
                        frame_to_write = self._copy_bboxes_to_black_frame(frame, boxes)
                    elif background_frame is not None:
                        frame_to_write = self._copy_bboxes_to_background_frame(
                            background_frame, frame, boxes
                        )
                    else:
                        frame_to_write = frame.copy()
                    for bx, by, bw, bh in boxes:
                        x1 = max(0, bx)
                        y1 = max(0, by)
                        x2 = min(w, bx + bw)
                        y2 = min(h, by + bh)
                        if x2 > x1 and y2 > y1:
                            cv2.rectangle(frame_to_write, (x1, y1), (x2, y2), (0, 255, 0), 2)

                # Burn mode label + per-frame elapsed time into every frame.
                # Copy first if frame_to_write still points at the original array.
                if mode_label:
                    if frame_to_write is frame:
                        frame_to_write = frame.copy()
                    elapsed_s = int(frame_idx / safe_fps)
                    draw_corner_overlay(frame_to_write, mode_label, elapsed_s)

                process.stdin.write(frame_to_write.tobytes())

            process.stdin.close()
            return_code = process.wait()
        except BrokenPipeError as exc:
            try:
                process.stdin.close()
            except Exception:
                pass
            process.wait()
            raise RuntimeError("FFmpeg pipe closed while encoding segment") from exc

        if return_code != 0:
            raise RuntimeError(
                f"FFmpeg failed while encoding segment {timestamp} "
                f"(exit code {return_code})."
            )

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
            object_type=object_type,
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
