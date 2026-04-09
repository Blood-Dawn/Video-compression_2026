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
from typing import Optional

# sys.path must be set before any local imports so this module can be run
# directly (python src/pipeline/pipeline.py) or imported from the project root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.db import initialize_database                                    # fix: was 'from src.utils.db'
from utils.frame_source import FrameSource                                  # fix: use FrameSource instead of raw VideoCapture
from utils.encryption import encrypt_file, _CRYPTO_AVAILABLE
from background_subtraction.background_subtraction import BackgroundSubtractor
from compression.roi_encoder import ROIEncoder
from pipeline.modes import validate_mode, get_mode_decision
from demo.demo_metadata import DemoMetadataWriter
from enhancement.enhancer import Enhancer

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
    demo: bool = False,
    show_preview: bool = False,
    warmup_frames: int = 120,
    enhance: bool = False,
    enhance_model: str = "espcn",
    enhance_scale: int = 4,
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

    MODES:
    mode0 (default): All post-warmup frames are buffered and encoded. Baseline
                     H.264 dual-CRF ROI encoding on every frame.
    mode1:           Frame gating. Only frames with detected foreground activity
                     are buffered. Segments are formed from active frames only,
                     reducing storage when the scene is mostly static.

    Args:
        input_source: Camera index (int) or video file / CDnet scene path (str).
        camera_id: Identifier for this camera. Used in output filenames and the
                   SQLite metadata index. Sanitized to prevent path traversal.
        output_dir: Directory where compressed output segments are written.
        segment_seconds: Seconds of footage per output segment.
        bg_method: Background subtraction algorithm. "MOG2" recommended.
        show_preview: Show live bounding-box preview. Disable on headless servers.
        warmup_frames: Frames to feed through the background model before encoding.
                       Overridden by FrameSource.get_warmup_frames() for CDnet sources.
        demo: Demo mode toggle
        mode: Compression mode. "mode0" encodes all frames; "mode1" gates on
              foreground activity (event clip / frame gating).
        enhance: If True, apply super-resolution to segment frames before
                 encoding. Uses the Enhancer class. Silently skipped when the
                 requested model is not available (missing weights / package).
        enhance_model: SR model backend. "espcn" or "fsrcnn" (fast CPU) or
                       "realesrgan" / "realesrnet" (high quality, slow CPU).
        enhance_scale: Upscale factor passed to Enhancer. Typically 2 or 4.
        encrypt: If True, encrypt each output segment with AES-256-CBC after
                 encoding. Requires `encrypt_password` or `encrypt_key_file`.
                 The plaintext .mp4 is deleted; only the .mp4.enc file is kept.
                 Requires the `cryptography` package.
        encrypt_password: Passphrase for AES key derivation (PBKDF2-HMAC-SHA256,
                          600,000 iterations). Mutually exclusive with
                          encrypt_key_file.
        encrypt_key_file: Path to a file containing a raw 32-byte AES-256 key.
                          Mutually exclusive with encrypt_password.
    """
    # Validate mode at function entry — not inside the per-frame loop.
    validate_mode(mode)

    # Validate and prepare encryption settings.
    # Resolve the raw key from a key file early so file-not-found errors surface
    # immediately rather than after the first segment is encoded.
    _enc_key: Optional[bytes] = None
    if encrypt:
        if not _CRYPTO_AVAILABLE:
            raise RuntimeError(
                "--encrypt requires the `cryptography` package. "
                "Install with:  pip install cryptography"
            )
        if encrypt_password is None and encrypt_key_file is None:
            raise ValueError(
                "--encrypt requires either --password or --key-file."
            )
        if encrypt_password is not None and encrypt_key_file is not None:
            raise ValueError(
                "Provide --password or --key-file, not both."
            )
        if encrypt_key_file is not None:
            key_path = Path(encrypt_key_file)
            if not key_path.exists():
                raise FileNotFoundError(f"Key file not found: {key_path}")
            _enc_key = key_path.read_bytes()
            if len(_enc_key) != 32:
                raise ValueError(
                    f"Key file must contain exactly 32 bytes (AES-256); "
                    f"got {len(_enc_key)} bytes."
                )
        log.info(
            f"Encryption enabled: AES-256-CBC | "
            f"key mode: {'key-file' if encrypt_key_file else 'password/PBKDF2'}"
        )

    # Sanitize camera_id to prevent path traversal in output filenames.
    safe_camera_id = _sanitize_camera_id(camera_id)
    if safe_camera_id != camera_id:
        log.warning(f"camera_id sanitized: {camera_id!r} -> {safe_camera_id!r}")
    camera_id = safe_camera_id

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # demo metadata for processing
    demo_writer = None
    if demo:
        demo_metadata_path = Path(output_dir) / f"{camera_id}_{mode}_demo_frames.jsonl"
        demo_writer = DemoMetadataWriter(demo_metadata_path)
        log.info(f"Demo metadata enabled: {demo_metadata_path}")

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

    # Optional super-resolution enhancement pass.
    # Initialized here so the model is loaded once, not once per segment.
    enhancer = None
    if enhance:
        enhancer = Enhancer(scale=enhance_scale, model=enhance_model)
        if enhancer.is_available():
            log.info(f"Enhancement enabled: {repr(enhancer)}")
        else:
            log.warning(
                f"Enhancement requested (--enhance) but model '{enhance_model}' "
                "is not available. Pipeline will run without enhancement. "
                "See DEV.md → Enhancement Module Setup for install instructions."
            )
            enhancer = None  # treat as disabled so segment loop logic is simple

    segment_frames: list = []       # in-memory frame buffer (numpy arrays)
    segment_regions: list = []
    frame_count = 0
    encode_count = 0
    target_frames_this_segment = 0
    segment_index = 0
    frame_index_within_segment = 0

    log.info("Pipeline running. Press Ctrl+C to stop.")

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                log.info("Stop signal received. Flushing final segment.")
                break
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
            
            
            
            mode_decision = get_mode_decision(mode, regions)
            
            if mode_decision.buffer_frame:
                segment_frames.append(frame.copy())
                segment_regions.append(regions)
                
                if demo_writer is not None:
                    source_time_seconds = frame_count / fps
                    demo_writer.write_record(
                        source_frame_index=frame_count,
                        source_time_seconds=source_time_seconds,
                        mode=mode,
                        segment_index=segment_index,
                        frame_index_within_segment=frame_index_within_segment,
                        regions=regions,
                    )

                frame_index_within_segment += 1
                
            if mode_decision.target_detected:
                target_frames_this_segment += 1

            if show_preview:
                vis = subtractor.draw_regions(frame, regions)
                cv2.imshow("Pipeline Preview", vis)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            frame_count += 1
            # encode_count tracks frames actually buffered for output
            encode_count = len(segment_frames)

            if encode_count > 0 and encode_count % frames_per_segment == 0 and len(segment_frames) > 0:
                seg_num = encode_count // frames_per_segment
                log.info(
                    f"Encoding segment {segment_index + 1} | "
                    f"targets in {target_frames_this_segment}/{frames_per_segment} frames"
                )
                frames_to_encode = segment_frames
                if enhancer is not None:
                    log.info(f"Enhancing {len(segment_frames)} frames (scale x{enhance_scale})...")
                    frames_to_encode = enhancer.enhance_batch(segment_frames)
                out = encoder.encode_segment(
                    frames=frames_to_encode,
                    bboxes_per_frame=[
                        [r.to_tuple() for r in regions]
                        for regions in segment_regions
                    ],
                    camera_id=camera_id,
                    fps=fps,
                )
                if encrypt:
                    enc_out = encrypt_file(
                        out,
                        password=encrypt_password,
                        key=_enc_key,
                        delete_original=True,
                    )
                    log.info(f"Saved (encrypted): {enc_out}")
                else:
                    log.info(f"Saved: {out}")

                segment_frames = []
                segment_regions = []
                target_frames_this_segment = 0
                encode_count = 0
                segment_index += 1
                frame_index_within_segment = 0

    except KeyboardInterrupt:
        log.info("Interrupted by user.")
    finally:
        src.release()        
        # Flush any frames that didn't fill a complete segment.
        # This handles two cases: short clips shorter than one full segment,
        # and leftover frames after the last full segment was encoded.
        if len(segment_frames) > 0 and len(segment_regions) > 0:
            log.info(
                f"Encoding final partial segment | "
                f"{len(segment_frames)} frames | "
                f"targets in {target_frames_this_segment}/{len(segment_frames)} frames"
            )
            frames_to_encode = segment_frames
            if enhancer is not None:
                log.info(f"Enhancing {len(segment_frames)} frames (final segment)...")
                frames_to_encode = enhancer.enhance_batch(segment_frames)
            out = encoder.encode_segment(
                frames=frames_to_encode,
                bboxes_per_frame=[
                    [r.to_tuple() for r in regions]
                    for regions in segment_regions
                ],
                camera_id=camera_id,
                fps=fps,
            )
            
            segment_index += 1
            frame_index_within_segment = 0

            if encrypt:
                enc_out = encrypt_file(
                    out,
                    password=encrypt_password,
                    key=_enc_key,
                    delete_original=True,
                )
                log.info(f"Saved final partial segment (encrypted): {enc_out}")
            else:
                log.info(f"Saved final partial segment: {out}")

        # These always run on exit regardless of whether a partial segment existed.
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
    parser.add_argument("--mode", default="mode0", choices=["mode0", "mode1"], 
        help=(
        "Pipeline mode: "
        "mode0 = current full-segment pipeline (store all post-warmup frames), "
        "mode1 = standard event recording (store only frames with detected foreground objects)"),
    )
    parser.add_argument("--demo", action="store_true", help="Demo mode toggle")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument(
        "--warmup",
        type=int,
        default=120,
        help="Warmup frames before encoding starts. Overridden by CDnet temporalROI if available."
    )
    parser.add_argument(
        "--enhance",
        action="store_true",
        help="Apply super-resolution to frames before encoding. Requires model weights in models/. "
             "See DEV.md for setup. Silently skipped if model is unavailable."
    )
    parser.add_argument(
        "--enhance-model",
        default="espcn",
        choices=["espcn", "fsrcnn", "edsr", "lapsrn", "realesrgan", "realesrnet", "realesr-general"],
        help="SR model to use with --enhance. espcn/fsrcnn are fast CPU options; "
             "realesrgan/realesrnet are highest quality but much slower."
    )
    parser.add_argument(
        "--enhance-scale",
        type=int,
        default=4,
        choices=[2, 4, 8],
        help="Upscale factor for --enhance. Default 4x."
    )

    # ── Encryption arguments ───────────────────────────────────────────────
    parser.add_argument(
        "--encrypt",
        action="store_true",
        help="Encrypt each output segment with AES-256-CBC after encoding. "
             "The plaintext .mp4 is deleted; only the .mp4.enc file is kept. "
             "Requires --password or --key-file. "
             "Requires:  pip install cryptography"
    )
    enc_key_group = parser.add_mutually_exclusive_group()
    enc_key_group.add_argument(
        "--password",
        default=None,
        help="Passphrase for AES key derivation (PBKDF2-HMAC-SHA256, 600k iters). "
             "Used with --encrypt."
    )
    enc_key_group.add_argument(
        "--key-file",
        default=None,
        help="Path to a file containing a raw 32-byte AES-256 key. "
             "Used with --encrypt. Generate with: python -c "
             "\"import os; open('camera.key','wb').write(os.urandom(32))\""
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
        args.demo,
        args.preview,
        args.warmup,
        enhance=args.enhance,
        enhance_model=args.enhance_model,
        enhance_scale=args.enhance_scale,
        encrypt=args.encrypt,
        encrypt_password=args.password,
        encrypt_key_file=args.key_file,
    )
