"""
pipeline.py

End-to-end orchestration: read camera feed, run background subtraction,
encode with ROI-aware compression, index metadata.

Designed to run continuously on low-spec hardware (Raspberry Pi, old x86 box).
No GPU required.

Author: Bloodawn (KheivenD)

Usage:
    python pipeline.py --input /dev/video0 --camera-id cam_01 --output outputs/
    python pipeline.py --input footage/test_clip.mp4 --camera-id cam_test
    python pipeline.py --input footage/test_clip.mp4 --camera-id cam_test --warmup 150
"""

import cv2
import argparse
import logging
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
    mode: str = "mode0",
    show_preview: bool = False,
    warmup_frames: int = 120,
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
    
    MODE BEHAVIOR:
    - mode0:
        Current baseline pipeline. Buffers all post-warmup frames and encodes
        them in segment-sized chunks, regardless of whether foreground objects
        are detected.
    - mode1:
        Standard Event Recording mode. Buffers and stores only frames where
        foreground regions are detected. This acts as the sponsor-style event
        clip baseline, where only footage containing activity is preserved.

    Args:
        input_source: Camera index (int) or video file / CDnet scene path (str).
        camera_id: Identifier for this camera. Used in output filenames and the
                   SQLite metadata index. Sanitized to prevent path traversal.
        output_dir: Directory where compressed output segments are written.
        segment_seconds: Seconds of footage per output segment.
        bg_method: Background subtraction algorithm. "MOG2" recommended.
        mode: Pipeline mode selector.
        show_preview: Show live bounding-box preview. Disable on headless servers.
        warmup_frames: Frames to feed through the background model before encoding.
                       Overridden by FrameSource.get_warmup_frames() for CDnet sources.
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
    log.info(f"Mode: {mode}")
    log.info(f"Warmup: {effective_warmup} frames (~{effective_warmup/fps:.1f}s)")

    subtractor = BackgroundSubtractor(method=bg_method)
    encoder = ROIEncoder(output_dir=output_dir, db_path=db_path)
    initialize_database(db_path)   # fix: explicit path, consistent with encoder

    segment_frames: list = []       # in-memory frame buffer (numpy arrays)
    segment_regions: list = []
    frame_count = 0
    encode_count = 0
    target_frames_this_segment = 0

    log.info("Pipeline running. Press Ctrl+C to stop.")

    try:
        while True:
            ret, frame = src.read()
            if not ret:
                log.info("End of source. Flushing final segment.")
                break

            mask = subtractor.apply(frame)
            regions = subtractor.get_foreground_regions(mask)

            # --- WARMUP GATE ---
            if frame_count < effective_warmup:
                frame_count += 1
                if frame_count == effective_warmup:
                    log.info(f"Warmup complete after {effective_warmup} frames. Encoding started.")
                continue
            # --- END WARMUP GATE ---

            # Buffer frames in memory — no lossy intermediate file.
            # Previously XVID AVI was used, which compressed frames before FFmpeg,
            # degrading quality. Raw numpy arrays are lossless.
            # Buffer frames selectively depending on mode
            
            # Default Mode
            if(mode == "mode0"):
                segment_frames.append(frame.copy())
                segment_regions.append(regions)

                if regions:
                    target_frames_this_segment += 1
                    
            # Standard Event Recording
            # Only buffer frames when motion/foreground regions are detected
            elif mode == "mode1":
                if regions:
                    segment_frames.append(frame.copy())
                    segment_regions.append(regions)
                    target_frames_this_segment += 1

            if show_preview:
                vis = subtractor.draw_regions(frame, regions)
                cv2.imshow("Pipeline Preview", vis)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            frame_count += 1
            # encode_count tracks frames actually buffered for output
            encode_count = len(segment_frames)

            if encode_count > 0 and encode_count % frames_per_segment == 0 and len(segment_frames > 0):
                seg_num = encode_count // frames_per_segment
                log.info(
                    f"Encoding segment {seg_num} | "
                    f"targets in {target_frames_this_segment}/{frames_per_segment} frames"
                )
                out = encoder.encode_segment(
                    frames=segment_frames,
                    bboxes_per_frame=[
                        [r.to_tuple() for r in regions]
                        for regions in segment_regions
                    ],
                    camera_id=camera_id,
                    fps=fps,
                )
                log.info(f"Saved: {out}")

                segment_frames = []
                segment_regions = []
                target_frames_this_segment = 0
                encode_count = 0

    except KeyboardInterrupt:
        log.info("Interrupted by user.")
    finally:
        src.release()

        # If the video ends before reaching a full segment (short clips or leftover
        # frames after one or more full segments), encode whatever remains in the
        # in-memory buffers as a final partial segment.
        if len(segment_frames) > 0 and len(segment_regions) > 0:
            partial_duration_s = len(segment_frames) / fps
            log.info(
                f"Encoding final partial segment | "
                f"{len(segment_frames)} frames | "
                f"targets in {target_frames_this_segment}/{len(segment_frames)} frames"
            )
            out = encoder.encode_segment(
                frames=segment_frames,
                bboxes_per_frame=[
                    [r.to_tuple() for r in regions]
                    for regions in segment_regions
                ],
                camera_id=camera_id,
                fps=fps,
            )
            log.info(f"Saved final partial segment: {out}")

            if show_preview:
                cv2.destroyAllWindows()

            report = encoder.get_storage_report()
            log.info("Storage report: " + str(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Selective compression pipeline")
    parser.add_argument("--input", default=0, help="Camera index or video file path")
    parser.add_argument("--camera-id", default="cam_00")
    parser.add_argument("--output", default="outputs/")
    parser.add_argument("--segment", type=int, default=60, help="Segment duration in seconds")
    parser.add_argument("--method", default="MOG2", choices=["MOG2", "KNN"])
    parser.add_argument("--mode", default="mode0", choices=["mode0", "mode1"], 
        help=(
        "Pipeline mode: "
        "mode0 = current full-segment pipeline (store all post-warmup frames), "
        "mode1 = standard event recording (store only frames with detected foreground objects)"),
    )
    parser.add_argument("--preview", action="store_true")
    parser.add_argument(
        "--warmup",
        type=int,
        default=120,
        help="Warmup frames before encoding starts. Overridden by CDnet temporalROI if available."
    )
    args = parser.parse_args()

    input_src = args.input
    if input_src != 0:
        input_src = int(input_src) if str(input_src).isdigit() else input_src

    run_pipeline(
        input_src,
        args.camera_id,
        args.output,
        args.segment,
        args.method,
        args.mode,
        args.preview,
        args.warmup,
    )
