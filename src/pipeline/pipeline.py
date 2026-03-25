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
import time
from pathlib import Path
from collections import deque

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from background_subtraction.background_subtraction import BackgroundSubtractor
from compression.roi_encoder import ROIEncoder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)


def run_pipeline(
    input_source,
    camera_id: str = "cam_00",
    output_dir: str = "outputs/",
    segment_seconds: int = 60,
    bg_method: str = "MOG2",
    show_preview: bool = False,
    warmup_frames: int = 120,
):
    """
    Main pipeline loop.

    Reads frames from a camera or video file, runs background subtraction on each
    frame, accumulates frame buffers into segments, then encodes each segment with
    ROI-aware compression (foreground at high quality, background at low quality).

    WARMUP PERIOD:
    MOG2 and KNN both need time to build an accurate background model. During the
    first `warmup_frames` frames the mask output is essentially noise -- the model
    has not seen enough history to know what is background. If we start encoding
    immediately, the first few seconds of every segment will be miscompressed.
    The fix: feed frames through the subtractor during warmup but do NOT write them
    to the output segment or accumulate their region lists. Encoding only begins
    after warmup is complete.

    Args:
        input_source: Camera index (int) or video file path (str).
        camera_id: Identifier string for this camera, used in output filenames
                   and the SQLite metadata index.
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
    """
    cap = cv2.VideoCapture(input_source)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video source: {input_source}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frames_per_segment = int(fps * segment_seconds)

    log.info(f"Source: {input_source} | {frame_w}x{frame_h} @ {fps:.1f}fps")
    log.info(f"Segment length: {segment_seconds}s ({frames_per_segment} frames)")
    log.info(f"Warmup period: {warmup_frames} frames (~{warmup_frames/fps:.1f}s) -- output suppressed during init")

    subtractor = BackgroundSubtractor(method=bg_method)
    encoder = ROIEncoder(output_dir=output_dir)

    segment_regions = []
    segment_writer = None
    temp_path = Path(output_dir) / f"_tmp_{camera_id}.avi"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    fourcc = cv2.VideoWriter_fourcc(*"XVID")
    segment_writer = cv2.VideoWriter(str(temp_path), fourcc, fps, (frame_w, frame_h))

    # frame_count counts ALL frames including warmup.
    # encode_count counts only frames written to output (post-warmup).
    frame_count = 0
    encode_count = 0
    target_frames_this_segment = 0

    log.info("Pipeline running. Press Ctrl+C to stop.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                log.info("End of source. Flushing final segment.")
                break

            # Always apply the subtractor -- it needs every frame to build
            # and update its background model, even during warmup.
            mask = subtractor.apply(frame)
            regions = subtractor.get_foreground_regions(mask)

            # --- WARMUP GATE ---
            # During warmup we run the subtractor (above) but skip everything
            # that depends on having a stable mask: writing frames to the segment
            # buffer and accumulating region lists.
            if frame_count < warmup_frames:
                frame_count += 1
                if frame_count == warmup_frames:
                    log.info(f"Warmup complete after {warmup_frames} frames. Encoding started.")
                continue
            # --- END WARMUP GATE ---

            segment_writer.write(frame)
            segment_regions.append(regions)

            if regions:
                target_frames_this_segment += 1

            if show_preview:
                vis = subtractor.draw_regions(frame, regions)
                cv2.imshow("Pipeline Preview", vis)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            frame_count += 1
            encode_count += 1

            if encode_count > 0 and encode_count % frames_per_segment == 0:
                segment_writer.release()
                log.info(
                    f"Encoding segment {encode_count // frames_per_segment} | "
                    f"targets in {target_frames_this_segment}/{frames_per_segment} frames"
                )
                out = encoder.encode_frame_sequence(
                    str(temp_path),
                    segment_regions,
                    camera_id=camera_id,
                    segment_duration_s=segment_seconds,
                )
                log.info(f"Saved: {out}")
                segment_regions = []
                target_frames_this_segment = 0
                segment_writer = cv2.VideoWriter(str(temp_path), fourcc, fps, (frame_w, frame_h))

    except KeyboardInterrupt:
        log.info("Interrupted by user.")
    finally:
        cap.release()
        if segment_writer:
            segment_writer.release()
        if show_preview:
            cv2.destroyAllWindows()
        temp_path.unlink(missing_ok=True)

        report = encoder.get_storage_report()
        log.info("Storage report: " + str(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Selective compression pipeline")
    parser.add_argument("--input", default=0, help="Camera index or video file path")
    parser.add_argument("--camera-id", default="cam_00")
    parser.add_argument("--output", default="outputs/")
    parser.add_argument("--segment", type=int, default=60, help="Segment duration in seconds")
    parser.add_argument("--method", default="MOG2", choices=["MOG2", "KNN", "GMG"])
    parser.add_argument("--preview", action="store_true")
    parser.add_argument(
        "--warmup",
        type=int,
        default=120,
        help="Number of frames to feed through background model before encoding starts. "
             "Default 120 (~4s at 30fps). Increase for complex outdoor scenes."
    )
    args = parser.parse_args()

    src = args.input if args.input == 0 else (
        int(args.input) if str(args.input).isdigit() else args.input
    )
    run_pipeline(src, args.camera_id, args.output, args.segment, args.method, args.preview, args.warmup)
