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

import argparse
import logging
from typing import Optional
import re
import sys
from pathlib import Path

import cv2
import numpy as np

# sys.path must be set before any local imports so this module can be run
# directly (python src/pipeline/pipeline.py) or imported from the project root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.db import initialize_database                                    # fix: was 'from src.utils.db'
from utils.frame_source import FrameSource                                  # fix: use FrameSource instead of raw VideoCapture
from background_subtraction.background_subtraction import BackgroundSubtractor
from compression.roi_encoder import ROIEncoder
from enhancement.enhancer import Enhancer
from demo.demo_metadata import DemoMetadataWriter
from pipeline.modes import get_mode_decision, validate_mode
from compression.roi_encoder import _MODE_LABELS

def classify_object(roi_count):
    if roi_count > 10:
        return "vehicle"
    elif roi_count > 2:
        return "person"
    else:
        return "unknown"


def _stop_requested(stop_event) -> bool:
    return (
        stop_event is not None
        and hasattr(stop_event, "is_set")
        and stop_event.is_set()
    )


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
    mode2_clean_seconds: float = 2.0,
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

    MODES:
    mode0 (default): All post-warmup frames are buffered and encoded. Baseline
                     H.264 dual-CRF ROI encoding on every frame.
    mode1:           Frame gating. Only frames with detected foreground activity
                     are buffered. Segments are formed from active frames only,
                     reducing storage when the scene is mostly static.
    mode2:           Background keyframe plus object patches. Only frames with
                     foreground detections are buffered; the encoded segment is
                     built by compositing each detected bounding box over the
                     latest clean background frame.
    mode3:           Object-only segment output. Only frames with foreground
                     detections are buffered, and pixels outside each detected
                     bounding box are blacked out before normal MP4 encoding.

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
        demo: Demo mode toggle
        mode: Compression mode. "mode0" encodes all frames; "mode1" gates on
              foreground activity; "mode2" composites foreground bbox patches
              over a clean background; "mode3" encodes foreground bbox pixels
              on a black canvas.
        enhance: When True, apply super-resolution sharpening to foreground ROIs
                 before writing each frame to the segment buffer. Requires
                 Real-ESRGAN weights in models/ (falls back to bicubic if absent).
                 Adds per-frame CPU cost; not recommended for real-time sources.
        enhance_scale: Intermediate upscale factor used by the Enhancer.
                       Default 4 (matches RealESRGAN_x4plus weights).
        encrypt: If True, encrypt each output segment with AES-256-CBC after
                 encoding. Requires `encrypt_password` or `encrypt_key_file`.
                 The plaintext .mp4 is deleted; only the .mp4.enc file is kept.
                 Requires the `cryptography` package.
        encrypt_password: Passphrase for AES key derivation (PBKDF2-HMAC-SHA256,
                          600,000 iterations). Mutually exclusive with
                          encrypt_key_file.
        encrypt_key_file: Path to a file containing a raw 32-byte AES-256 key.
                          Mutually exclusive with encrypt_password.
        mode2_clean_seconds: Number of consecutive detection-free seconds
                             required before a frame can refresh the mode2
                             background keyframe. Default 2.0 seconds.
    """
    validate_mode(mode)

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
    mode2_clean_frames = max(1, int(round(fps * mode2_clean_seconds)))

    # Single consistent database path: output_dir/metadata.db.
    # Previously pipeline.py called initialize_database() with no args, which
    # defaulted to "metadata.db" in the cwd — a different file than the encoder's
    # "outputs/metadata.db". Now both use the same explicit path.
    db_path = str(Path(output_dir) / "metadata.db")

    log.info(f"Source: {input_source} | {frame_w}x{frame_h} @ {fps:.1f}fps")
    log.info(f"Segment length: {segment_seconds}s ({frames_per_segment} frames)")
    log.info(f"Mode: {mode}")
    log.info(f"Warmup: {effective_warmup} frames (~{effective_warmup/fps:.1f}s)")
    if mode == "mode2":
        log.info(
            "Mode2 clean background guard: %.1fs (%d consecutive frames)",
            mode2_clean_seconds,
            mode2_clean_frames,
        )

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

    segment_frames: list = []       # in-memory frame buffer (numpy arrays)
    segment_regions: list = []
    segment_background = None
    last_clean_background = None
    clean_frame_streak = 0
    source_frame_index = -1
    target_frames_this_segment = 0
    segment_index = 0

    log.info("Pipeline running. Press Ctrl+C to stop.")

    try:
        while True:
            if _stop_requested(stop_event):
                log.info("Stop event received. Ending pipeline loop.")
                break

            ret, frame = src.read()
            if not ret:
                log.info("End of source. Flushing final segment.")
                break

            source_frame_index += 1

            mask = subtractor.apply(frame)
            regions = subtractor.get_foreground_regions(mask)
            has_regions = len(regions) > 0

            # --- WARMUP GATE ---
            if source_frame_index < effective_warmup:
                if has_regions:
                    clean_frame_streak = 0
                else:
                    clean_frame_streak += 1
                    if clean_frame_streak >= mode2_clean_frames:
                        last_clean_background = frame.copy()
                if source_frame_index + 1 == effective_warmup:
                    log.info(f"Warmup complete after {effective_warmup} frames. Encoding started.")
                continue
            # --- END WARMUP GATE ---

            # Optional: sharpen foreground ROIs before writing to the buffer.
            # Each detected region is enhanced in-place at original resolution.
            if enhancer is not None and regions:
                for region in regions:
                    frame = enhancer.upscale_roi(frame, (region.x, region.y, region.w, region.h))

            mode_decision = get_mode_decision(mode, regions)

            if has_regions:
                clean_frame_streak = 0
            else:
                clean_frame_streak += 1
                if clean_frame_streak >= mode2_clean_frames:
                    last_clean_background = frame.copy()

            if mode_decision.buffer_frame:
                if mode == "mode2" and not segment_frames:
                    segment_background = (
                        last_clean_background.copy()
                        if last_clean_background is not None
                        else None
                    )
                segment_frames.append(frame.copy())
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

            if mode_decision.target_detected:
                target_frames_this_segment += 1

            if show_preview:
                vis = subtractor.draw_regions(frame, regions)
                cv2.imshow("Pipeline Preview", vis)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            if len(segment_frames) >= frames_per_segment:
                log.info(
                    f"Encoding segment {segment_index + 1} | "
                    f"targets in {target_frames_this_segment}/{frames_per_segment} frames"
                )
                roi_count = sum(len(r) for r in segment_regions)
                object_type = classify_object(roi_count)
                mode2_background = None
                if mode == "mode2":
                    mode2_background = (
                        segment_background
                        if segment_background is not None
                        else np.zeros_like(segment_frames[0])
                    )
                out = encoder.encode_segment(
                    frames=segment_frames,
                    bboxes_per_frame=[
                        [r.to_tuple() for r in regions]
                        for regions in segment_regions
                    ],
                    camera_id=camera_id,
                    fps=fps,
                    object_type=object_type,
                    object_only=(mode == "mode3"),
                    background_frame=mode2_background,
                    mode_label=_MODE_LABELS.get(mode, ""),
                )
                log.info(f"Saved: {out}")

                segment_frames = []
                segment_regions = []
                segment_background = None
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
            mode2_background = None
            if mode == "mode2":
                mode2_background = (
                    segment_background
                    if segment_background is not None
                    else np.zeros_like(segment_frames[0])
                )

            out = encoder.encode_segment(
                frames=segment_frames,
                bboxes_per_frame=[
                    [r.to_tuple() for r in regions]
                    for regions in segment_regions
                ],
                camera_id=camera_id,
                fps=fps,
                object_type=object_type,
                object_only=(mode == "mode3"),
                background_frame=mode2_background,
                mode_label=_MODE_LABELS.get(mode, ""),
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
    parser.add_argument("--segment", type=int, default=60, help="Segment duration in seconds")
    parser.add_argument("--method", default="MOG2", choices=["MOG2", "KNN"])
    parser.add_argument(
        "--mode",
        default="mode0",
        choices=["mode0", "mode1", "mode2", "mode3"],
        help=(
            "Pipeline mode: "
            "mode0 = continuous stream, "
            "mode1 = event recording with foreground activity, "
            "mode2 = background keyframe plus bbox patches, "
            "mode3 = object-only bbox pixels on black canvas"
        ),
    )
    parser.add_argument("--demo", action="store_true", help="Write demo JSONL metadata")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument(
        "--warmup",
        type=int,
        default=120,
        help="Warmup frames before encoding starts. Overridden by CDnet temporalROI if available.",
    )
    parser.add_argument(
        "--enhance",
        action="store_true",
        help="Apply super-resolution sharpening to foreground ROIs before encoding.",
    )
    parser.add_argument(
        "--enhance-model",
        default="bicubic",
        help="Enhancement backend label. The current Enhancer auto-selects available backend.",
    )
    parser.add_argument(
        "--enhance-scale",
        type=int,
        default=4,
        choices=[2, 4],
        help="Upscale factor for --enhance.",
    )
    parser.add_argument(
        "--encrypt",
        action="store_true",
        help="Accepted for GUI/CLI compatibility; encryption is not wired in run_pipeline yet.",
    )
    parser.add_argument(
        "--mode2-clean-seconds",
        type=float,
        default=2.0,
        help="Consecutive detection-free seconds before mode2 refreshes the clean background.",
    )
    parser.add_argument("--password", default=None, help="Encryption password placeholder.")
    parser.add_argument("--key-file", default=None, help="Encryption key file placeholder.")
    args = parser.parse_args()

    input_src = args.input
    if input_src != 0:
        input_src = int(input_src) if str(input_src).isdigit() else input_src

    run_pipeline(
        input_source=input_src,
        camera_id=args.camera_id,
        output_dir=args.output,
        segment_seconds=args.segment,
        bg_method=args.method,
        show_preview=args.preview,
        warmup_frames=args.warmup,
        enhance=args.enhance,
        enhance_scale=args.enhance_scale,
        mode=args.mode,
        demo=args.demo,
        enhance_model=args.enhance_model,
        encrypt=args.encrypt,
        encrypt_password=args.password,
        encrypt_key_file=args.key_file,
        mode2_clean_seconds=args.mode2_clean_seconds,
    )
