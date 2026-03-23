"""
pipeline.py

End-to-end orchestration: read camera feed, run background subtraction,
encode with ROI-aware compression, index metadata.

Designed to run continuously on low-spec hardware (Raspberry Pi, old x86 box).
No GPU required.

Usage:
    python pipeline.py --input /dev/video0 --camera-id cam_01 --output outputs/
    python pipeline.py --input footage/test_clip.mp4 --camera-id cam_test
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
):
    """
    Main pipeline loop.

    Args:
        input_source: Camera index (int) or video file path (str).
        camera_id: Identifier string for this camera.
        output_dir: Directory for compressed output segments.
        segment_seconds: How many seconds of footage to buffer before encoding.
        bg_method: Background subtraction algorithm.
        show_preview: Show live preview window (disable on headless servers).
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

    subtractor = BackgroundSubtractor(method=bg_method)
    encoder = ROIEncoder(output_dir=output_dir)

    segment_frames = []
    segment_regions = []
    segment_writer = None
    temp_path = Path(output_dir) / f"_tmp_{camera_id}.avi"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    fourcc = cv2.VideoWriter_fourcc(*"XVID")
    segment_writer = cv2.VideoWriter(str(temp_path), fourcc, fps, (frame_w, frame_h))

    frame_count = 0
    target_frames_this_segment = 0

    log.info("Pipeline running. Press Ctrl+C to stop.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                log.info("End of source. Flushing final segment.")
                break

            mask = subtractor.apply(frame)
            regions = subtractor.get_foreground_regions(mask)

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

            if frame_count % frames_per_segment == 0:
                segment_writer.release()
                has_targets = target_frames_this_segment > 0
                log.info(
                    f"Encoding segment {frame_count // frames_per_segment} | "
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
    args = parser.parse_args()

    src = args.input if args.input == 0 else (
        int(args.input) if str(args.input).isdigit() else args.input
    )
    run_pipeline(src, args.camera_id, args.output, args.segment, args.method, args.preview)
