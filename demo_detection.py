"""
demo_detection.py

Visual demonstration of the background subtraction pipeline.
Generates a side-by-side comparison grid showing:
  - Column 1: Original frame
  - Column 2: Foreground mask (raw output from MOG2/KNN)
  - Column 3: Annotated frame (original + bounding boxes + coverage %)

Supports two input formats:
  - Video files:   python demo_detection.py --input data/clip.mp4
  - CDnet scenes:  python demo_detection.py --input data/dataset/baseline/highway/
  - CDnet input/:  python demo_detection.py --input data/dataset/baseline/highway/input/

For CDnet scenes, warmup_frames is automatically set from temporalROI.txt
(the CDnet-standard initialization range) so results match the benchmark spec.

Saves one composite image per sampled frame to outputs/demo_frames/.
Also prints a coverage report: what percentage of pixels are foreground
across the full clip -- this is the core data point that justifies the
compression approach. If only 3% of pixels are foreground, we can compress
the other 97% extremely aggressively.

Author: Bloodawn (KheivenD)

Usage:
    # CDnet baseline scene (recommended starting point):
    python demo_detection.py --input data/dataset/baseline/highway/

    # CDnet night scene:
    python demo_detection.py --input data/dataset/nightVideos/bridgeEntry/ --all-methods

    # Standard video file:
    python demo_detection.py --input data/clip.mp4

    # Sample every 30th frame (faster on long clips):
    python demo_detection.py --input data/dataset/baseline/highway/ --sample-rate 30
"""

import cv2
import numpy as np
import argparse
import logging
from pathlib import Path

# Add the src directory to sys.path so we can import our own modules
import sys
sys.path.insert(0, str(Path(__file__).parent / "src"))
from background_subtraction.background_subtraction import BackgroundSubtractor
from utils.metrics import foreground_coverage, storage_savings_report
from utils.frame_source import FrameSource

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def add_label(image: np.ndarray, text: str, color=(255, 255, 255)) -> np.ndarray:
    """
    Overlays a text label at the bottom-left of an image.
    Returns a copy with the label burned in.

    Args:
        image: The image to annotate (BGR numpy array).
        text: Label string to draw.
        color: Font color in BGR. Default is white.

    Returns:
        A new numpy array with the label drawn on it.
    """
    out = image.copy()
    h, w = out.shape[:2]
    # Semi-transparent black bar at the bottom for readability
    cv2.rectangle(out, (0, h - 30), (w, h), (0, 0, 0), -1)
    cv2.putText(out, text, (8, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1, cv2.LINE_AA)
    return out


def mask_to_bgr(mask: np.ndarray) -> np.ndarray:
    """
    Converts a single-channel binary mask to a 3-channel BGR image
    so it can be concatenated with color frames for side-by-side display.

    White pixels (255) become bright green -- visually intuitive for "active".
    Black pixels (0) remain black.

    Args:
        mask: Single-channel uint8 array from BackgroundSubtractor.apply().

    Returns:
        3-channel BGR image of the same spatial dimensions.
    """
    colored = np.zeros((*mask.shape, 3), dtype=np.uint8)
    colored[mask > 0] = (0, 220, 80)  # BGR green for foreground pixels
    return colored


def build_comparison_grid(
    original: np.ndarray,
    mask: np.ndarray,
    annotated: np.ndarray,
    frame_idx: int,
    coverage_pct: float,
    method: str,
) -> np.ndarray:
    """
    Assembles the three-panel comparison image for one frame.

    Layout: [Original] | [Foreground Mask] | [Annotated + Boxes]

    Args:
        original: The raw input frame in BGR.
        mask: The binary foreground mask (single channel).
        annotated: The original frame with bounding boxes drawn on it.
        frame_idx: Frame number, displayed in the label.
        coverage_pct: Percentage of pixels that are foreground (0-100).
        method: Name of the background subtraction algorithm.

    Returns:
        A single wide numpy array containing all three panels side by side.
    """
    mask_bgr = mask_to_bgr(mask)

    panel_orig = add_label(original, f"Original  [frame {frame_idx}]")
    panel_mask = add_label(mask_bgr, f"{method} Mask  |  FG: {coverage_pct:.1f}% of pixels", color=(0, 220, 80))
    panel_anno = add_label(annotated, f"Detected Regions")

    return np.hstack([panel_orig, panel_mask, panel_anno])


# ---------------------------------------------------------------------------
# Per-video analysis
# ---------------------------------------------------------------------------

def analyze_video(
    input_path: str,
    method: str = "MOG2",
    sample_rate: int = 15,
    warmup_frames: int = -1,
    output_dir: str = "outputs/demo_frames",
) -> dict:
    """
    Runs background subtraction on a clip and produces demo output images.

    Accepts both video files and CDnet image sequence folders. For CDnet
    scenes, the warmup_frames value is automatically read from temporalROI.txt
    (the CDnet benchmark standard) unless you override it explicitly.

    Samples one frame every `sample_rate` frames (after warmup) and saves
    a three-panel comparison image for each sampled frame. Also computes
    aggregate coverage statistics across all frames.

    Args:
        input_path: Path to a video file, CDnet scene folder, or CDnet input/ folder.
        method: Background subtraction method: "MOG2", "KNN", or "GMG".
        sample_rate: Save a comparison image every N post-warmup frames.
        warmup_frames: Frames to discard from the front while the model stabilizes.
                       Pass -1 (default) to auto-detect from temporalROI.txt for
                       CDnet clips, or fall back to 120 for plain video files.
        output_dir: Directory where comparison JPEG images are saved.

    Returns:
        A dict with aggregate stats:
            - input: str           -- original input path
            - scene: str           -- scene/clip name for display
            - method: str
            - total_frames: int
            - analyzed_frames: int -- frames after warmup
            - avg_coverage_pct: float  -- average % of pixels that are foreground
            - max_coverage_pct: float  -- peak foreground density (busiest frame)
            - frames_with_activity: int
            - activity_rate_pct: float
            - sample_images_saved: int
            - output_dir: str
    """
    src = FrameSource(input_path)

    # Auto-detect warmup: -1 means "use whatever the source recommends"
    if warmup_frames < 0:
        warmup_frames = src.get_warmup_frames(fallback=120)

    log.info(str(src))
    log.info(f"Method: {method}  |  Warmup: {warmup_frames} frames  |  Sample: every {sample_rate} frames")

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    scene_name = src.get_scene_name()

    subtractor = BackgroundSubtractor(method=method)
    coverage_values = []
    frames_with_activity = 0
    sample_images_saved = 0
    frame_idx = 0
    post_warmup_idx = 0

    try:
        while True:
            ok, frame = src.read()
            if not ok:
                break

            # Always feed every frame into the subtractor so it can keep
            # building and updating its background model, even during warmup
            mask = subtractor.apply(frame)

            # Warmup gate: discard noisy early-model output
            if frame_idx < warmup_frames:
                frame_idx += 1
                continue

            # Compute what fraction of this frame's pixels are foreground
            cov = foreground_coverage(mask) * 100.0
            coverage_values.append(cov)

            if cov > 0.1:  # 0.1% threshold -- at least a small object visible
                frames_with_activity += 1

            # Save a three-panel comparison image at the requested sample rate
            if post_warmup_idx % sample_rate == 0:
                regions = subtractor.get_foreground_regions(mask)
                annotated = subtractor.draw_regions(frame, regions)
                grid = build_comparison_grid(frame, mask, annotated, frame_idx, cov, method)

                out_name = f"{scene_name}_{method}_frame{frame_idx:05d}.jpg"
                out_path = Path(output_dir) / out_name
                cv2.imwrite(str(out_path), grid, [cv2.IMWRITE_JPEG_QUALITY, 92])
                sample_images_saved += 1

            frame_idx += 1
            post_warmup_idx += 1

    finally:
        src.release()

    avg_cov = float(np.mean(coverage_values)) if coverage_values else 0.0
    max_cov = float(np.max(coverage_values)) if coverage_values else 0.0

    return {
        "input": input_path,
        "scene": scene_name,
        "method": method,
        "total_frames": src.total_frames,
        "analyzed_frames": len(coverage_values),
        "avg_coverage_pct": round(avg_cov, 2),
        "max_coverage_pct": round(max_cov, 2),
        "frames_with_activity": frames_with_activity,
        "activity_rate_pct": round(frames_with_activity / max(len(coverage_values), 1) * 100, 1),
        "sample_images_saved": sample_images_saved,
        "output_dir": output_dir,
    }


# ---------------------------------------------------------------------------
# Multi-method comparison
# ---------------------------------------------------------------------------

def compare_all_methods(
    video_path: str,
    sample_rate: int = 15,
    warmup_frames: int = 120,
    output_dir: str = "outputs/demo_frames",
) -> list:
    """
    Runs MOG2 and KNN sequentially on the same video and prints a comparison table.

    This is useful for choosing which algorithm to use for a specific camera type.
    GMG is skipped here because its 10fps performance makes it impractical.

    Args:
        video_path: Path to the input video.
        sample_rate: Save a grid image every N post-warmup frames.
        warmup_frames: Warmup duration for both algorithms.
        output_dir: Where to save comparison images.

    Returns:
        List of result dicts, one per method.
    """
    results = []
    for method in ("MOG2", "KNN"):
        log.info(f"\n{'='*50}\nRunning {method}...\n{'='*50}")
        r = analyze_video(video_path, method=method, sample_rate=sample_rate,
                          warmup_frames=warmup_frames, output_dir=output_dir)
        results.append(r)
    return results


# ---------------------------------------------------------------------------
# Report printing
# ---------------------------------------------------------------------------

def print_coverage_report(results: list):
    """
    Prints a formatted table of coverage statistics to stdout.

    The key metric is avg_coverage_pct: if only 5% of pixels are foreground
    on average, that means 95% of pixels can be heavily compressed or stored
    as low-frequency background without losing any intelligence value.

    Args:
        results: List of result dicts from analyze_video() or compare_all_methods().
    """
    print("\n" + "=" * 70)
    print("  FOREGROUND COVERAGE REPORT")
    print("  Author: Bloodawn (KheivenD)")
    print("=" * 70)

    for r in results:
        print(f"\n  Scene   : {r.get('scene', Path(r.get('input', r.get('video', '?'))).name)}")
        print(f"  Method  : {r['method']}")
        print(f"  Frames  : {r['analyzed_frames']} analyzed (of {r['total_frames']} total)")
        print(f"  Avg FG coverage : {r['avg_coverage_pct']:5.2f}%  -- only this % needs high-quality encoding")
        print(f"  Max FG coverage : {r['max_coverage_pct']:5.2f}%  -- busiest frame")
        print(f"  Frames w/ activity : {r['frames_with_activity']} ({r['activity_rate_pct']}% of analyzed frames)")
        print(f"  Images saved : {r['sample_images_saved']} frames in {r['output_dir']}")
        print()

        # Plain-English interpretation for the report
        bg_pct = 100.0 - r["avg_coverage_pct"]
        print(f"  INTERPRETATION:")
        print(f"    On average, {bg_pct:.1f}% of each frame is static background.")
        print(f"    A standard encoder wastes quality bits on all of those pixels.")
        print(f"    Selective compression can target CRF 40+ on the background and")
        print(f"    CRF 18-20 only on the {r['avg_coverage_pct']:.1f}% that actually matters.")
        print()

    print("=" * 70 + "\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Demo: background subtraction visualization and coverage report"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to input video file (e.g. data/test_clip.mp4)"
    )
    parser.add_argument(
        "--method",
        default="MOG2",
        choices=["MOG2", "KNN", "GMG"],
        help="Background subtraction algorithm. Default: MOG2"
    )
    parser.add_argument(
        "--all-methods",
        action="store_true",
        help="Run both MOG2 and KNN and compare results side by side in the report"
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=15,
        help="Save a comparison image every N frames after warmup. Default: 15"
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=120,
        help="Frames to feed through model before saving output. Default: 120 (~4s at 30fps)"
    )
    parser.add_argument(
        "--output",
        default="outputs/demo_frames",
        help="Directory to save comparison images. Default: outputs/demo_frames"
    )

    args = parser.parse_args()

    if args.all_methods:
        results = compare_all_methods(
            args.input,
            sample_rate=args.sample_rate,
            warmup_frames=args.warmup,
            output_dir=args.output,
        )
    else:
        r = analyze_video(
            args.input,
            method=args.method,
            sample_rate=args.sample_rate,
            warmup_frames=args.warmup,
            output_dir=args.output,
        )
        results = [r]

    print_coverage_report(results)
    log.info(f"Done. Comparison images saved to: {args.output}")
