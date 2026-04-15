"""
pipeline.py

End-to-end orchestration: read camera feed, run background subtraction,
encode with ROI-aware compression, index metadata.

Designed to run continuously on low-spec hardware (Raspberry Pi, old x86 box).
No GPU required.

Author: Bloodawn (KheivenD)
Enhancement module integration: Victor Teixeira

Usage:
    python pipeline.py --input /dev/video0 --camera-id cam_01 --output outputs/
    python pipeline.py --input footage/test_clip.mp4 --camera-id cam_test
    python pipeline.py --input footage/test_clip.mp4 --camera-id cam_test --warmup 150
    python pipeline.py --input footage/test_clip.mp4 --camera-id cam_test --enhance
    python pipeline.py --input footage/test_clip.mp4 --camera-id cam_test --enhance --enhance-scale 2
"""

import cv2
import argparse
import logging
import time
from pathlib import Path
from collections import deque
from typing import Optional

from src.utils.db import initialize_database
import os
import re
import sys
import numpy as np
from pathlib import Path

# sys.path must be set before any local imports so this module can be run
# directly (python src/pipeline/pipeline.py) or imported from the project root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.db import initialize_database                                    # fix: was 'from src.utils.db'
from utils.frame_source import FrameSource                                  # fix: use FrameSource instead of raw VideoCapture
from background_subtraction.background_subtraction import BackgroundSubtractor
from compression.roi_encoder import ROIEncoder
from enhancement.enhancer import Enhancer
from demo.demo_metadata import DemoMetadataWriter

def classify_object(roi_count):
    if roi_count > 10:
        return "vehicle"
    elif roi_count > 2:
        return "person"
    else:
        return "unknown"
    

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)


def _sanitize_camera_id(camera_id: str) -> str:
    """
    Strip any characters from camera_id that are unsafe in file paths.

    Allows only alphanumeric characters, underscores, and hyphens.
    A camera_id like '../../etc/passwd' becomes '______etc_passwd'.
    This prevents path traversal when camera_id is embedded in output filenames.
    """
    return re.sub(r"[^a-zA-Z0-9_-]", "_", camera_id)


def run_pipeline(
    input_source,
    camera_id: str = "cam_00",
    output_dir: str = "outputs/",
    segment_seconds: int = 60,
    bg_method: str = "MOG2",
    show_preview: bool = False,
    warmup_frames: int = 120,
    enhance: bool = False,
    enhance_scale: int = 4,
    mode: str = "mode0",
    demo: bool = False,
    enhance_model: str = "bicubic",
    encrypt: bool = False,
    encrypt_password: Optional[str] = None,
    encrypt_key_file: Optional[str] = None,
    stop_event=None,
):
    """
    Main pipeline loop.

    Reads frames from a camera or video file, runs background subtraction on each
    frame, accumulates frames in memory, then encodes each segment with ROI-aware
    compression (foreground at high quality, background at low quality).

    Uses FrameSource to transparently support both video files and CDnet-style
    image sequence folders. If the source provides a temporal_roi (CDnet), the
    warmup_frames argument is overridden with the scene's recommended warmup count
    so benchmark results are comparable to published CDnet scores.

    WARMUP PERIOD:
    MOG2 and KNN both need time to build an accurate background model. During the
    first `warmup_frames` frames the mask output is essentially noise. The fix:
    feed frames through the subtractor during warmup but do NOT accumulate them
    for encoding. Encoding only begins after warmup is complete.

    INTERMEDIATE FORMAT:
    Frames are buffered in memory as a list of numpy arrays and piped directly to
    FFmpeg via stdin. This avoids the lossy XVID intermediate AVI that was used
    previously, which degraded quality before the final encode step.

    Args:
        input_source: Camera index (int) or video file / CDnet scene path (str).
        camera_id: Identifier for this camera. Used in output filenames and the
                   SQLite metadata index. Sanitized to prevent path traversal.
        output_dir: Directory where compressed output segments are written.
        segment_seconds: How many seconds of footage to accumulate before
                         flushing and encoding one segment.
        bg_method: Which background subtraction algorithm to use.
                   "MOG2" is the recommended default for outdoor static cameras.
        show_preview: Display a live preview window with bounding boxes drawn.
                      Disable this on headless servers.
        warmup_frames: Number of frames to feed through the background model
                       before beginning to encode output. Default 120 frames
                       (approximately 4 seconds at 30fps). Increase to 250-500
                       for scenes with complex dynamic backgrounds (trees, flags).
        enhance: When True, apply super-resolution sharpening to foreground ROIs
                 before writing each frame to the segment buffer. Requires
                 Real-ESRGAN weights in models/ (falls back to bicubic if absent).
                 Adds per-frame CPU cost; not recommended for real-time sources.
        enhance_scale: Intermediate upscale factor used by the Enhancer.
                       Default 4 (matches RealESRGAN_x4plus weights).
    """
    # Sanitize camera_id to prevent path traversal in output filenames.
    safe_camera_id = _sanitize_camera_id(camera_id)
    if safe_camera_id != camera_id:
        log.warning(f"camera_id sanitized: {camera_id!r} -> {safe_camera_id!r}")
    camera_id = safe_camera_id

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Use FrameSource to support both video files and CDnet image sequences.
    src = FrameSource(str(input_source) if not isinstance(input_source, int) else input_source)

    # If the source provides a temporal_roi (CDnet benchmark), use that as the
    # warmup count so results are comparable to published CDnet scores.
    effective_warmup = src.get_warmup_frames(fallback=warmup_frames)

    fps = src.fps
    frame_w = src.width
    frame_h = src.height
    frames_per_segment = max(1, int(fps * segment_seconds))

    # Single consistent database path: output_dir/metadata.db.
    # Previously pipeline.py called initialize_database() with no args, which
    # defaulted to "metadata.db" in the cwd — a different file than the encoder's
    # "outputs/metadata.db". Now both use the same explicit path.
    db_path = str(Path(output_dir) / "metadata.db")

    log.info(f"Source: {input_source} | {frame_w}x{frame_h} @ {fps:.1f}fps")
    log.info(f"Segment length: {segment_seconds}s ({frames_per_segment} frames)")
    log.info(f"Warmup: {effective_warmup} frames (~{effective_warmup/fps:.1f}s)")

    subtractor = BackgroundSubtractor(method=bg_method)
    encoder = ROIEncoder(output_dir=output_dir, db_path=db_path)
    initialize_database(db_path)

    enhancer: Optional[Enhancer] = None
    if enhance:
        if enhance_model != "bicubic":
            log.info(
                "enhance_model='%s' requested; current pipeline uses Enhancer backend auto-selection.",
                enhance_model,
            )
        enhancer = Enhancer(scale=enhance_scale)
        log.info(
            f"Enhancement enabled (backend={enhancer.backend}, scale={enhance_scale}). "
            "Foreground ROIs will be sharpened before encoding."
        )

    if encrypt:
        log.warning(
            "encrypt=True requested but encryption is not wired in run_pipeline yet; output will remain unencrypted."
        )

    if encrypt_password or encrypt_key_file:
        log.warning(
            "Encryption credentials provided but encryption is not wired in run_pipeline yet; values are ignored."
        )

    demo_writer: Optional[DemoMetadataWriter] = None
    if demo:
        demo_jsonl = Path(output_dir) / f"{camera_id}_{mode}_demo_frames.jsonl"
        demo_writer = DemoMetadataWriter(demo_jsonl)
        log.info(f"Demo metadata enabled: {demo_jsonl}")

    segment_regions = []
    segment_writer = None
    temp_path = Path(output_dir) / f"_tmp_{camera_id}.avi"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    fourcc = cv2.VideoWriter_fourcc(*"XVID")
    segment_writer = cv2.VideoWriter(str(temp_path), fourcc, fps, (frame_w, frame_h))

    segment_frames: list = []       # in-memory frame buffer (numpy arrays)
    segment_regions: list = []
    source_frame_index = -1
    encode_count = 0
    target_frames_this_segment = 0
    segment_index = 0

    log.info("Pipeline running. Press Ctrl+C to stop.")

    try:
        while True:
            if stop_event is not None and hasattr(stop_event, "is_set") and stop_event.is_set():
                log.info("Stop event received. Ending pipeline loop.")
                break

            ret, frame = src.read()
            if not ret:
                log.info("End of source. Flushing final segment.")
                break

            source_frame_index += 1

            mask = subtractor.apply(frame)
            regions = subtractor.get_foreground_regions(mask)

            # --- WARMUP GATE ---
            if source_frame_index < effective_warmup:
                if source_frame_index + 1 == effective_warmup:
                    log.info(f"Warmup complete after {effective_warmup} frames. Encoding started.")
                continue
            # --- END WARMUP GATE ---

            # Optional: sharpen foreground ROIs before writing to the buffer.
            # Each detected region is enhanced in-place at original resolution.
            if enhancer is not None and regions:
                for region in regions:
                    frame = enhancer.upscale_roi(frame, (region.x, region.y, region.w, region.h))

            # Mode 1: event-only — only buffer frames that contain foreground regions.
            # Mode 0: continuous — buffer every frame.
            if mode == "mode1" and not regions:
                continue

            segment_writer.write(frame)
            segment_frames.append(frame)
            segment_regions.append(regions)

            if demo_writer is not None:
                demo_writer.write_record(
                    source_frame_index=source_frame_index,
                    source_time_seconds=(source_frame_index / fps) if fps > 0 else 0.0,
                    mode=mode,
                    segment_index=segment_index,
                    frame_index_within_segment=len(segment_frames) - 1,
                    regions=regions,
                )

            if regions:
                target_frames_this_segment += 1

            if show_preview:
                vis = subtractor.draw_regions(frame, regions)
                cv2.imshow("Pipeline Preview", vis)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            encode_count += 1

            if encode_count > 0 and encode_count % frames_per_segment == 0:
                seg_num = encode_count // frames_per_segment
                log.info(
                    f"Encoding segment {seg_num} | "
                    f"targets in {target_frames_this_segment}/{frames_per_segment} frames"
                )
                roi_count = sum(len(r) for r in segment_regions)
                object_type = classify_object(roi_count)
                out = encoder.encode_segment(
                    frames=segment_frames,
                    bboxes_per_frame=[
                        [r.to_tuple() for r in regions]
                        for regions in segment_regions
                    ],
                    camera_id=camera_id,
                    fps=fps,
                    object_type=object_type
                )
                log.info(f"Saved: {out}")

                segment_frames = []
                segment_regions = []
                target_frames_this_segment = 0
                segment_index += 1

    except KeyboardInterrupt:
        log.info("Interrupted by user.")
    finally:
        # Flush any remaining buffered frames as a final partial segment.
        if segment_frames:
            log.info(
                f"Flushing final partial segment ({len(segment_frames)} frames)."
            )
            roi_count = sum(len(r) for r in segment_regions)
            object_type = classify_object(roi_count)

            out = encoder.encode_segment(
                frames=segment_frames,
                bboxes_per_frame=[
                    [r.to_tuple() for r in regions]
                    for regions in segment_regions
                ],
                camera_id=camera_id,
                fps=fps,
                object_type=object_type,
            )
            log.info(f"Saved final segment: {out}")

        src.release()
        if show_preview:
            cv2.destroyAllWindows()

        report = encoder.get_storage_report()
        log.info("Storage report: " + str(report))

        if demo_writer is not None:
            demo_writer.close()
    


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Selective compression pipeline")
    parser.add_argument("--input", default=0, help="Camera index or video file path")
    parser.add_argument("--camera-id", default="cam_00")
    parser.add_argument("--output", default="outputs/")
    parser.a