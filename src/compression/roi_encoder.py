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
import logging
import numpy as np
import subprocess
import re
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)


def _ffmpeg_pipe_process(args: list) -> subprocess.Popen:
    """Spawn an FFmpeg process with stdin as a pipe and stdout/stderr discarded.

    ffmpeg-python's quiet=True routes both stdout AND stderr to subprocess.PIPE.
    If nothing reads those pipes, FFmpeg blocks when the OS pipe buffer fills
    (~65 KB on Windows). This causes process.wait() to deadlock.

    Fix: pass stdout=DEVNULL, stderr=DEVNULL so FFmpeg can always write without
    blocking, while we still get stdin as a pipe for frame input.
    """
    return subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

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
    "mode0": "MODE 0 - 24/7",
    "mode1": "MODE 1 - EVENT",
    "mode2": "MODE 2 - PATCHES",
    "mode3": "MODE 3 - OBJ ONLY",
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
        preset: str = "ultrafast",
        db_path: str = "outputs/metadata.db",
        draw_roi_boxes: bool = False,
    ):
        """
        Args:
            output_dir: Where to write compressed output files.
            foreground_crf: CRF for foreground ROIs. 18 is visually lossless.
            background_crf: CRF for background. 40 gives heavy compression.
            preset: FFmpeg speed preset. ultrafast is the default — it trades
                    a modest file-size increase for significantly faster encoding,
                    which matters most for Mode 2/3 where per-frame compositing
                    already uses CPU. Use veryfast/fast for archival runs where
                    you can afford more encoding time.
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

        # Streaming API state — None when no segment is open
        self._stream_process: Optional[object] = None
        self._stream_path: Optional[Path] = None
        self._stream_timestamp: Optional[str] = None
        self._stream_camera_id: str = "cam_unknown"
        self._stream_fps: float = 30.0
        self._stream_object_type: str = "unknown"
        self._stream_frame_count: int = 0
        self._stream_roi_count: int = 0
        self._stream_has_targets: bool = False
        self._stream_sharpness_scores: list = []

        # Cache the audio-presence check so we don't probe every segment.
        # Surveillance cameras virtually never have audio; probing is wasted I/O.
        # Set to None = not yet determined; probe lazily on first encode call.
        self._source_has_audio: Optional[bool] = None

        # Streaming API audio state
        self._stream_source_path: Optional[str] = None

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

    @staticmethod
    def _compress_background_outside_bboxes(
        frame: np.ndarray,
        boxes: List[Tuple[int, int, int, int]],
        *,
        downscale: int = 8,
    ) -> np.ndarray:
        """
        Visually degrade pixels outside ROI boxes while preserving ROI pixels.

        H.264 cannot use two CRFs inside a single frame in this pipeline. This
        preprocessing creates the practical equivalent for normal MP4 output:
        background pixels are made low-detail/easy to compress, then foreground
        boxes are copied back at full detail before encoding.
        """
        if downscale <= 1:
            return frame

        h, w = frame.shape[:2]
        small_w = max(1, w // downscale)
        small_h = max(1, h // downscale)
        low_detail = cv2.resize(frame, (small_w, small_h), interpolation=cv2.INTER_AREA)
        low_detail = cv2.resize(low_detail, (w, h), interpolation=cv2.INTER_LINEAR)
        out = low_detail

        for bx, by, bw, bh in boxes:
            x1 = max(0, int(bx))
            y1 = max(0, int(by))
            x2 = min(w, int(bx) + int(bw))
            y2 = min(h, int(by) + int(bh))
            if x2 > x1 and y2 > y1:
                out[y1:y2, x1:x2] = frame[y1:y2, x1:x2]
        return out

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
        avg_sharpness: Optional[float] = None,
        sharpness_label: Optional[str] = None,
        source_path: Optional[str] = None,
    ) -> dict:
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
            Dict with keys:
              file_path      – str path to the compressed output MP4
              avg_sharpness  – mean Laplacian variance of target ROIs (float or None)
              sharpness_label – perceptual resolution label e.g. "~720p (sharp)" (or None)

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
        # Use _ffmpeg_pipe_process instead of run_async(quiet=True) to avoid
        # a Windows deadlock: quiet=True routes stderr to PIPE but nothing reads
        # it, so when the buffer fills FFmpeg blocks and process.wait() deadlocks.
        _ffmpeg_args = (
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
            .compile()
        )
        process = _ffmpeg_pipe_process(_ffmpeg_args)

        should_draw_boxes = self.draw_roi_boxes if draw_roi_boxes is None else draw_roi_boxes
        safe_fps = fps if fps and fps > 0 else 30.0

        try:
            for frame_idx, (frame, boxes) in enumerate(zip(frames, bboxes_per_frame)):
                # Step 1: apply mode-specific compositing.
                # _copy_bboxes_* functions always return a NEW writable array,
                # so mode2/3 frames are safe to draw on without an extra copy.
                if object_only:
                    frame_to_write = self._copy_bboxes_to_black_frame(frame, boxes)
                elif background_frame is not None:
                    frame_to_write = self._copy_bboxes_to_background_frame(
                        background_frame, frame, boxes
                    )
                else:
                    frame_to_write = frame  # still aliased to original; copy below if needed

                # Step 2: draw green ROI boxes if requested.
                # For mode 0/1 (frame_to_write is frame) we need a copy before
                # drawing. For mode 2/3 the compositing above already produced a
                # fresh array — no need to re-composite.
                if should_draw_boxes and boxes:
                    if frame_to_write is frame:
                        frame_to_write = frame.copy()
                    for bx, by, bw, bh in boxes:
                        x1 = max(0, bx)
                        y1 = max(0, by)
                        x2 = min(w, bx + bw)
                        y2 = min(h, by + bh)
                        if x2 > x1 and y2 > y1:
                            cv2.rectangle(frame_to_write, (x1, y1), (x2, y2), (0, 255, 0), 2)

                # Step 3: burn mode label + elapsed timer into top-left corner.
                if mode_label:
                    if frame_to_write is frame:
                        frame_to_write = frame.copy()
                    elapsed_s = int(frame_idx / safe_fps)
                    draw_corner_overlay(frame_to_write, mode_label, elapsed_s)

                process.stdin.write(frame_to_write.tobytes())

            process.stdin.close()
            try:
                return_code = process.wait(timeout=30.0)
            except Exception:
                process.kill()
                process.wait()
                raise RuntimeError("FFmpeg timed out encoding segment") from None
        except (BrokenPipeError, OSError) as exc:
            try:
                process.stdin.close()
            except Exception:
                pass
            try:
                process.kill()
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

        # Mux audio from source file (if it has audio) — pipeline pipes video-only
        if source_path:
            self._mux_audio_from_source(output_path, source_path)
            file_size = output_path.stat().st_size  # update after mux

        insert_segment(
            timestamp=timestamp,
            camera_id=camera_id,
            target_detected=has_targets,
            roi_count=roi_count,
            file_size=file_size,
            duration=duration,
            file_path=str(output_path),
            object_type=object_type,
            avg_sharpness=avg_sharpness,
            sharpness_label=sharpness_label,
            db_path=self.db_path,
        )

        return {
            "file_path": str(output_path),
            "avg_sharpness": avg_sharpness,
            "sharpness_label": sharpness_label,
        }

    # ------------------------------------------------------------------
    # Streaming API: open → write frames one-by-one → close
    # Use this instead of encode_segment() to avoid buffering all frames
    # in RAM. Encoding runs in parallel with decoding — much faster.
    # ------------------------------------------------------------------

    def begin_segment(
        self,
        frame_shape: tuple,
        fps: float,
        camera_id: str = "cam_unknown",
        has_targets: bool = True,
        object_type: str = "unknown",
        source_path: Optional[str] = None,
    ) -> None:
        """Open an FFmpeg pipe and start a new streaming segment.

        Must be followed by one or more write_frame() calls and exactly
        one finish_segment() call. Raises if a segment is already open.
        """
        if hasattr(self, "_stream_process") and self._stream_process is not None:
            raise RuntimeError("begin_segment() called while a segment is already open")

        h, w = frame_shape[:2]
        crf = self.foreground_crf if has_targets else self.background_crf
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        output_path = self.output_dir / f"{camera_id}_{timestamp}.mp4"

        _ffmpeg_args = (
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
            .compile()
        )
        process = _ffmpeg_pipe_process(_ffmpeg_args)

        self._stream_process     = process
        self._stream_path        = output_path
        self._stream_timestamp   = timestamp
        self._stream_camera_id   = camera_id
        self._stream_fps         = fps if fps and fps > 0 else 30.0
        self._stream_object_type = object_type
        self._stream_frame_count = 0
        self._stream_roi_count   = 0
        self._stream_has_targets = has_targets
        self._stream_sharpness_scores: list = []
        self._stream_source_path = source_path  # for audio mux after finish

    def write_frame(
        self,
        frame: np.ndarray,
        boxes: Optional[List[Tuple[int, int, int, int]]] = None,
        background_frame: Optional[np.ndarray] = None,
        object_only: bool = False,
        mode_label: str = "",
        draw_roi_boxes: Optional[bool] = None,
        measure_sharpness: bool = True,
        compress_background: bool = False,
    ) -> None:
        """Write one frame to the open streaming segment.

        Applies mode compositing, ROI boxes, and corner overlay exactly as
        encode_segment() does, but one frame at a time so no frame buffer
        is needed in the calling code.
        """
        if self._stream_process is None:
            raise RuntimeError("write_frame() called before begin_segment()")

        if boxes is None:
            boxes = []

        h, w = frame.shape[:2]
        should_draw = self.draw_roi_boxes if draw_roi_boxes is None else draw_roi_boxes

        # Step 1: mode compositing
        if object_only:
            frame_out = self._copy_bboxes_to_black_frame(frame, boxes)
        elif background_frame is not None:
            frame_out = self._copy_bboxes_to_background_frame(background_frame, frame, boxes)
        elif compress_background:
            frame_out = self._compress_background_outside_bboxes(frame, boxes)
        else:
            frame_out = frame

        # Step 2: green ROI boxes
        if should_draw and boxes:
            if frame_out is frame:
                frame_out = frame.copy()
            for bx, by, bw, bh in boxes:
                x1 = max(0, bx); y1 = max(0, by)
                x2 = min(w, bx + bw); y2 = min(h, by + bh)
                if x2 > x1 and y2 > y1:
                    cv2.rectangle(frame_out, (x1, y1), (x2, y2), (0, 255, 0), 2)

        # Step 3: corner overlay
        if mode_label:
            if frame_out is frame:
                frame_out = frame.copy()
            elapsed_s = int(self._stream_frame_count / self._stream_fps)
            draw_corner_overlay(frame_out, mode_label, elapsed_s)

        # Step 4: optional sharpness measurement on target ROI crops
        if measure_sharpness and boxes:
            from utils.metrics import compute_sharpness  # type: ignore
            for bx, by, bw, bh in boxes:
                x1 = max(0, bx); y1 = max(0, by)
                x2 = min(w, bx + bw); y2 = min(h, by + bh)
                if x2 > x1 and y2 > y1:
                    self._stream_sharpness_scores.append(
                        compute_sharpness(frame[y1:y2, x1:x2])
                    )

        self._stream_process.stdin.write(frame_out.tobytes())
        self._stream_frame_count += 1
        self._stream_roi_count   += len(boxes)
        if boxes:
            self._stream_has_targets = True

    def abort_segment(self) -> None:
        """Kill the FFmpeg process immediately, discarding the current segment.

        Safe to call from any thread — used by the stop handler to unblock
        a finish_segment() call that is waiting for FFmpeg to flush output.
        """
        proc = self._stream_process
        if proc is None:
            return
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass

    def finish_segment(self, timeout: float = 30.0) -> dict:
        """Close the FFmpeg pipe, save DB record, and return segment metadata.

        Args:
            timeout: Seconds to wait for FFmpeg to exit before force-killing.
                     Default 30s is generous; real encodes finish in <5s.

        Returns the same dict as encode_segment():
          file_path, avg_sharpness, sharpness_label
        """
        if self._stream_process is None:
            raise RuntimeError("finish_segment() called without a matching begin_segment()")

        proc = self._stream_process
        try:
            proc.stdin.close()
        except Exception:
            pass

        try:
            return_code = proc.wait(timeout=timeout)
        except Exception:
            # Timed out or other error — kill FFmpeg and give up on this segment
            log.warning("FFmpeg did not exit within %.0fs — killing process.", timeout)
            try:
                proc.kill()
                proc.wait()
            except Exception:
                pass
            self._stream_process = None
            raise RuntimeError(
                f"FFmpeg timed out encoding segment {self._stream_timestamp}. "
                "The output file may be incomplete."
            )

        output_path = self._stream_path
        self._stream_process = None

        if return_code != 0:
            raise RuntimeError(f"FFmpeg failed (exit {return_code}) for segment {self._stream_timestamp}")

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(f"FFmpeg produced no output for segment {self._stream_timestamp}")

        # Mux audio from the original source file (AAC 128k) if it has audio.
        # The streaming pipe sends only raw video bytes — audio must be re-attached here.
        if self._stream_source_path:
            self._mux_audio_from_source(output_path, self._stream_source_path)

        file_size = output_path.stat().st_size
        duration  = self._stream_frame_count / self._stream_fps

        scores = self._stream_sharpness_scores
        if scores:
            from utils.metrics import estimate_perceptual_resolution  # type: ignore
            avg_sharpness = round(sum(scores) / len(scores), 1)
            sharpness_label = estimate_perceptual_resolution(avg_sharpness)
        else:
            avg_sharpness = None
            sharpness_label = None

        insert_segment(
            timestamp    = self._stream_timestamp,
            camera_id    = self._stream_camera_id,
            target_detected = self._stream_has_targets,
            roi_count    = self._stream_roi_count,
            file_size    = file_size,
            duration     = duration,
            file_path    = str(output_path),
            object_type  = self._stream_object_type,
            avg_sharpness   = avg_sharpness,
            sharpness_label = sharpness_label,
            db_path      = self.db_path,
        )

        return {
            "file_path":       str(output_path),
            "avg_sharpness":   avg_sharpness,
            "sharpness_label": sharpness_label,
        }

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

    def _mux_audio_from_source(self, video_path: Path, source_path: str) -> None:
        """
        Mux audio from source_path into video_path (in-place replacement).

        The pipeline pipes only raw video frames to FFmpeg — audio is stripped
        at that stage.  This post-processing step re-attaches the original audio
        track so output segments contain sound.

        Strategy:
          1. Probe source to check for an audio stream (cached per session).
          2. Build an FFmpeg command:
               ffmpeg -i video_only.mp4 -i source_file
                      -c:v copy -c:a aac -b:a 128k
                      -map 0:v:0 -map 1:a:0 -shortest
                      temp_with_audio.mp4
          3. Replace video_path with the muxed file.

        AAC at 128 kbps is chosen for universal browser compatibility —
        most MP4/H.264 files served from a web app need AAC audio to play
        inline in Chrome/Safari/Firefox without extra codec installs.

        Args:
            video_path:  Path to the video-only MP4 just written by FFmpeg.
            source_path: Path to the original input file that has audio.
        """
        if self._source_has_audio is None:
            self._source_has_audio = self._probe_has_audio(source_path)

        if not self._source_has_audio:
            return  # Source has no audio — nothing to mux

        temp_path = video_path.with_suffix(".audio_tmp.mp4")
        try:
            mux_args = [
                "ffmpeg",
                "-y",                         # overwrite temp
                "-i", str(video_path),        # input 0 — video only
                "-i", str(source_path),       # input 1 — source with audio
                "-map", "0:v:0",              # take video stream from input 0
                "-map", "1:a:0",              # take audio stream from input 1
                "-c:v", "copy",               # copy video bitstream unchanged
                "-c:a", "aac",                # re-encode audio to AAC
                "-b:a", "128k",               # 128 kbps — good quality, small size
                "-shortest",                  # trim to shorter of the two streams
                str(temp_path),
            ]
            proc = subprocess.run(
                mux_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if proc.returncode != 0:
                log.warning(
                    "Audio mux failed (exit %d) for %s — keeping video-only output.",
                    proc.returncode, video_path.name,
                )
                if temp_path.exists():
                    temp_path.unlink()
                return

            # Atomically replace the video-only file with the muxed version
            temp_path.replace(video_path)
            log.debug("Audio muxed into %s (AAC 128k from %s)", video_path.name, source_path)

        except Exception as exc:
            log.warning(
                "Audio mux raised %s for %s — keeping video-only output. Error: %s",
                type(exc).__name__, video_path.name, exc,
            )
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

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
