"""
run_benchmark.py

Benchmarks the selective compression pipeline against a set of test clips.
Compares our approach against naive full-frame H.264 encoding (the baseline)
and reports compression ratios, quality metrics, and per-algorithm performance.

This script generates the numbers needed for the progress reports.
Target: beat the sponsor's baseline of 6x compression from their YOLO experiment.

Supports two input formats:
  - Video files (.mp4, .avi)
  - CDnet image sequence folders (data/dataset/baseline/highway/, etc.)
    For CDnet clips, frames are temporarily assembled into a video so FFmpeg
    can run its standard encoding pipeline.

Author: Bloodawn (KheivenD)

Usage:
    # Benchmark a CDnet scene:
    python scripts/run_benchmark.py --input data/dataset/baseline/highway/

    # Benchmark all CDnet baseline scenes:
    python scripts/run_benchmark.py --input data/dataset/baseline/

    # Benchmark a specific video file:
    python scripts/run_benchmark.py --input data/clip.mp4

    # Compare MOG2 and KNN:
    python scripts/run_benchmark.py --input data/dataset/baseline/highway/ --all-methods

    # Save results to CSV:
    python scripts/run_benchmark.py --input data/dataset/baseline/ --csv outputs/benchmark.csv

Output:
    Prints a formatted table to stdout. Each row is one (scene, method) combination.
    Columns: scene, method, orig_mb, baseline_mb, selective_mb, base_x, sel_x, fg%, psnr, ssim
"""

import cv2
import time
import csv
import argparse
import logging
import tempfile
import subprocess
import shutil
from pathlib import Path

import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from background_subtraction.background_subtraction import BackgroundSubtractor
from utils.metrics import compute_psnr, compute_ssim, foreground_coverage, storage_savings_report
from utils.frame_source import FrameSource

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CDnet image sequence -> temp video (needed so FFmpeg can encode it)
# ---------------------------------------------------------------------------

def sequence_to_video(src: FrameSource, output_path: str) -> bool:
    """
    Writes all frames from a FrameSource into a temporary lossless AVI file
    so that FFmpeg can use it as input for the baseline and selective encoders.

    For CDnet sequences, this assembles the individual JPEG frames into a
    single container without re-compressing them (uses XVID at quality 100
    as a near-lossless intermediate). The resulting file is used only as a
    temporary encoding input and is deleted after benchmarking.

    Args:
        src: An open FrameSource (video file or CDnet sequence).
        output_path: Where to write the assembled video.

    Returns:
        True if the video was written successfully, False otherwise.
    """
    fourcc = cv2.VideoWriter_fourcc(*"XVID")
    writer = cv2.VideoWriter(output_path, fourcc, src.fps, (src.width, src.height))
    if not writer.isOpened():
        return False

    frame_count = 0
    while True:
        ok, frame = src.read()
        if not ok:
            break
        writer.write(frame)
        frame_count += 1

    writer.release()
    return frame_count > 0


def resolve_input_scenes(input_path: str) -> list:
    """
    Resolves an input path to a list of individual scenes to benchmark.

    Handles three cases:
      1. A video file -> returns [input_path]
      2. A CDnet scene folder (contains input/ subfolder) -> returns [input_path]
      3. A CDnet category folder (contains scene subfolders, e.g. baseline/) ->
         returns a list of all scene subfolder paths found inside it

    Args:
        input_path: Path provided by the user on the command line.

    Returns:
        List of path strings, each pointing to one scene to benchmark.
    """
    path = Path(input_path)

    # Plain file
    if path.is_file():
        return [str(path)]

    # Folder with an input/ subfolder = single CDnet scene
    if (path / "input").is_dir():
        return [str(path)]

    # Folder whose children have input/ subfolders = CDnet category dir
    scenes = [str(child) for child in sorted(path.iterdir())
              if child.is_dir() and (child / "input").is_dir()]
    if scenes:
        return scenes

    # Fallback: treat as single path
    return [str(path)]


# ---------------------------------------------------------------------------
# Baseline encoder: naive full-frame H.264 at default CRF 23
# ---------------------------------------------------------------------------

def encode_baseline(input_path: str, output_path: str, crf: int = 23) -> bool:
    """
    Encodes the input video with standard H.264 at a uniform CRF.
    This is the "naive" baseline that treats every pixel equally.
    We compare against this to show how much our selective approach saves.

    Args:
        input_path: Path to the original video file.
        output_path: Where to write the baseline-encoded output.
        crf: H.264 CRF value. 23 is the FFmpeg default. Lower = higher quality/size.

    Returns:
        True if encoding succeeded, False otherwise.
    """
    if not shutil.which("ffmpeg"):
        log.error("ffmpeg not found on PATH. Install FFmpeg to run baseline encoding.")
        return False
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast",
        "-an",  # drop audio -- we're measuring video compression only
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0


def encode_selective(
    input_path: str,
    output_path: str,
    method: str = "MOG2",
    fg_crf: int = 20,
    bg_crf: int = 40,
    warmup_frames: int = -1,
) -> dict:
    """
    Encodes the input video using our selective compression approach.
    Foreground regions use fg_crf (high quality); background uses bg_crf (low quality).

    Currently implemented as a two-pass approach:
      Pass 1: Run background subtraction on all frames, determine if the segment
              has targets. If it does, encode at fg_crf. If not, encode at bg_crf.
      Pass 2 (future - Milestone 2): Per-macroblock QP control via FFmpeg addroi filter.

    Args:
        input_path: Path to the original video file.
        output_path: Where to write the selectively compressed output.
        method: Background subtraction algorithm to use.
        fg_crf: CRF for segments containing foreground objects.
        bg_crf: CRF for segments with no detected activity.
        warmup_frames: Frames to feed through model before making encoding decisions.

    Returns:
        A dict with:
            - has_targets: bool -- did this clip contain any foreground activity?
            - crf_used: int -- which CRF was applied
            - avg_fg_coverage: float -- average foreground pixel coverage
            - frames_analyzed: int
    """
    if not shutil.which("ffmpeg"):
        log.error("ffmpeg not found on PATH.")
        return {}

    src = FrameSource(input_path)
    if warmup_frames < 0:
        warmup_frames = src.get_warmup_frames(fallback=120)

    subtractor = BackgroundSubtractor(method=method)
    coverage_values = []
    has_targets = False
    frame_idx = 0

    while True:
        ok, frame = src.read()
        if not ok:
            break
        mask = subtractor.apply(frame)

        # Skip warmup frames -- model output is not yet reliable
        if frame_idx < warmup_frames:
            frame_idx += 1
            continue

        cov = foreground_coverage(mask)
        coverage_values.append(cov)
        if cov > 0.001:  # 0.1% threshold -- at least a tiny object visible
            has_targets = True
        frame_idx += 1

    src.release()

    # Choose CRF based on whether we detected any foreground in this clip
    crf = fg_crf if has_targets else bg_crf

    # Encode using the chosen CRF
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast",
        "-an",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True)

    avg_cov = float(np.mean(coverage_values)) if coverage_values else 0.0
    return {
        "has_targets": has_targets,
        "crf_used": crf,
        "avg_fg_coverage": round(avg_cov * 100, 2),
        "frames_analyzed": len(coverage_values),
    }


# ---------------------------------------------------------------------------
# Quality measurement between original and compressed output
# ---------------------------------------------------------------------------

def measure_quality(original_path: str, compressed_path: str, num_samples: int = 30) -> dict:
    """
    Computes PSNR and SSIM between the original video and the compressed version.

    Samples `num_samples` frames evenly spaced through the video to avoid
    spending minutes computing metrics on every single frame.

    PSNR > 40 dB is generally considered excellent.
    SSIM > 0.95 is generally considered excellent.

    Args:
        original_path: Path to the uncompressed source video.
        compressed_path: Path to the encoded output to evaluate.
        num_samples: How many frames to sample for the quality estimate.

    Returns:
        A dict with:
            - avg_psnr: float (dB)
            - avg_ssim: float (0-1)
            - samples_used: int
    """
    cap_orig = cv2.VideoCapture(original_path)
    cap_comp = cv2.VideoCapture(compressed_path)

    total = int(cap_orig.get(cv2.CAP_PROP_FRAME_COUNT))
    if total == 0:
        return {"avg_psnr": 0.0, "avg_ssim": 0.0, "samples_used": 0}

    # Sample evenly across the video (skip very first and last frames)
    sample_indices = set(
        int(i * (total - 1) / max(num_samples - 1, 1))
        for i in range(num_samples)
    )

    psnr_values, ssim_values = [], []
    frame_idx = 0

    while True:
        ret_o, frame_o = cap_orig.read()
        ret_c, frame_c = cap_comp.read()
        if not ret_o or not ret_c:
            break

        if frame_idx in sample_indices:
            # Resize compressed to match original if dimensions differ
            if frame_o.shape != frame_c.shape:
                frame_c = cv2.resize(frame_c, (frame_o.shape[1], frame_o.shape[0]))
            psnr_values.append(compute_psnr(frame_o, frame_c))
            ssim_values.append(compute_ssim(frame_o, frame_c))

        frame_idx += 1

    cap_orig.release()
    cap_comp.release()

    return {
        "avg_psnr": round(float(np.mean(psnr_values)), 2) if psnr_values else 0.0,
        "avg_ssim": round(float(np.mean(ssim_values)), 4) if ssim_values else 0.0,
        "samples_used": len(psnr_values),
    }


# ---------------------------------------------------------------------------
# One full benchmark run for a single (video, method) pair
# ---------------------------------------------------------------------------

def benchmark_one(
    input_path: str,
    method: str = "MOG2",
    warmup_frames: int = -1,
) -> dict:
    """
    Runs a complete benchmark for one scene with one background subtraction method.

    Handles both video files and CDnet image sequence folders. For CDnet
    sequences, the frames are first assembled into a temporary AVI so FFmpeg
    can encode them -- the temp file is deleted after the run.

    Steps:
      1. If CDnet sequence: assemble frames into temp AVI
      2. Encode baseline (full-frame uniform CRF 23)
      3. Encode selective (our pipeline)
      4. Measure PSNR/SSIM of both outputs vs. source
      5. Compute compression ratios and storage savings

    Args:
        input_path: Path to a video file or CDnet scene folder.
        method: Background subtraction method.
        warmup_frames: Pass -1 to auto-detect from temporalROI.txt (CDnet) or
                       default to 120 frames.

    Returns:
        A dict containing all benchmark metrics for this (scene, method) run.
    """
    src_meta = FrameSource(input_path)
    scene_name = src_meta.get_scene_name()

    if warmup_frames < 0:
        warmup_frames = src_meta.get_warmup_frames(fallback=120)
    src_meta.release()

    log.info(f"Benchmarking: {scene_name} | method={method} | warmup={warmup_frames}")

    with tempfile.TemporaryDirectory() as tmpdir:
        # For CDnet sequences, create a temp video so FFmpeg has a single-file input
        path = Path(input_path)
        if path.is_dir():
            assembled_path = str(Path(tmpdir) / "assembled.avi")
            log.info(f"  Assembling {src_meta.total_frames} frames into temp video...")
            src_asm = FrameSource(input_path)
            ok = sequence_to_video(src_asm, assembled_path)
            if not ok:
                log.error(f"  Failed to assemble frames from {input_path}")
                return {}
            encode_input = assembled_path
            # "Original" size = size of assembled temp video as reference baseline
            orig_size = Path(assembled_path).stat().st_size
        else:
            encode_input = input_path
            orig_size = path.stat().st_size

        baseline_path = str(Path(tmpdir) / "baseline.mp4")
        selective_path = str(Path(tmpdir) / "selective.mp4")

        # --- Baseline encode ---
        t0 = time.time()
        baseline_ok = encode_baseline(encode_input, baseline_path)
        baseline_time = time.time() - t0

        # --- Selective encode ---
        t0 = time.time()
        sel_info = encode_selective(
            encode_input, selective_path,
            method=method, warmup_frames=warmup_frames
        )
        selective_time = time.time() - t0

        baseline_size = Path(baseline_path).stat().st_size if baseline_ok and Path(baseline_path).exists() else 0
        selective_size = Path(selective_path).stat().st_size if Path(selective_path).exists() else 0

        # --- Quality metrics ---
        if baseline_ok and baseline_size > 0:
            baseline_quality = measure_quality(encode_input, baseline_path)
        else:
            baseline_quality = {"avg_psnr": 0.0, "avg_ssim": 0.0, "samples_used": 0}

        if selective_size > 0:
            selective_quality = measure_quality(encode_input, selective_path)
        else:
            selective_quality = {"avg_psnr": 0.0, "avg_ssim": 0.0, "samples_used": 0}

    baseline_ratio = orig_size / max(baseline_size, 1)
    selective_ratio = orig_size / max(selective_size, 1)

    return {
        "scene": scene_name,
        "method": method,
        "original_mb": round(orig_size / 1e6, 2),
        "baseline_mb": round(baseline_size / 1e6, 2),
        "selective_mb": round(selective_size / 1e6, 2),
        "baseline_ratio": round(baseline_ratio, 2),
        "selective_ratio": round(selective_ratio, 2),
        "ratio_improvement": round(selective_ratio / max(baseline_ratio, 0.001), 2),
        "baseline_psnr": baseline_quality["avg_psnr"],
        "selective_psnr": selective_quality["avg_psnr"],
        "baseline_ssim": baseline_quality["avg_ssim"],
        "selective_ssim": selective_quality["avg_ssim"],
        "avg_fg_pct": sel_info.get("avg_fg_coverage", 0.0),
        "has_targets": sel_info.get("has_targets", False),
        "crf_used": sel_info.get("crf_used", "N/A"),
        "selective_runtime_s": round(selective_time, 1),
    }


# ---------------------------------------------------------------------------
# Report printing and CSV export
# ---------------------------------------------------------------------------

def print_benchmark_table(results: list):
    """
    Prints a formatted benchmark results table to stdout.

    The most important columns to highlight in the report:
      - selective_ratio vs baseline_ratio: did we beat the baseline?
      - selective_psnr: is quality still acceptable? (>35 dB = good)
      - avg_fg_pct: confirms the hypothesis that most pixels are background

    Args:
        results: List of result dicts from benchmark_one().
    """
    print("\n" + "=" * 90)
    print("  SELECTIVE COMPRESSION BENCHMARK RESULTS")
    print("  Author: Bloodawn (KheivenD)")
    print("  Target: beat 6x compression (sponsor YOLO baseline)")
    print("=" * 90)

    header = (
        f"{'Video':<22} {'Method':<6} {'Orig MB':>8} {'Base MB':>8} {'Sel MB':>8} "
        f"{'Base x':>7} {'Sel x':>7} {'FG%':>6} {'Sel PSNR':>9} {'Sel SSIM':>9}"
    )
    print(header)
    print("-" * 90)

    for r in results:
        beat_target = "YES" if r["selective_ratio"] >= 6.0 else "   "
        row = (
            f"{r['scene']:<22} {r['method']:<6} {r['original_mb']:>8.1f} "
            f"{r['baseline_mb']:>8.1f} {r['selective_mb']:>8.1f} "
            f"{r['baseline_ratio']:>7.1f}x {r['selective_ratio']:>6.1f}x "
            f"{r['avg_fg_pct']:>5.1f}% {r['selective_psnr']:>8.1f}dB "
            f"{r['selective_ssim']:>9.4f}  {beat_target}"
        )
        print(row)

    print("=" * 90)
    print("  Sel x >= 6.0x --> marked YES (beats sponsor YOLO baseline)")
    print("  PSNR > 35dB = acceptable | > 40dB = excellent")
    print("  SSIM > 0.95 = excellent")
    print("=" * 90 + "\n")


def save_csv(results: list, csv_path: str):
    """
    Writes all benchmark results to a CSV file.
    Useful for generating charts in the progress report or notebook.

    Args:
        results: List of result dicts from benchmark_one().
        csv_path: Destination path for the CSV file.
    """
    if not results:
        return
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    log.info(f"CSV saved to: {csv_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Selective compression benchmark")
    parser.add_argument(
        "--input",
        default=None,
        help="Path to a specific video file. If omitted, all .mp4 files in data/ are used."
    )
    parser.add_argument(
        "--all-methods",
        action="store_true",
        help="Run both MOG2 and KNN for each video (doubles runtime)"
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=120,
        help="Background model warmup frames. Default: 120"
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="If provided, write results to this CSV path (e.g. outputs/benchmark_results.csv)"
    )
    args = parser.parse_args()

    # Resolve input to a list of individual scenes
    if args.input:
        scenes = resolve_input_scenes(args.input)
    else:
        # Default: all CDnet baseline scenes + any .mp4/.avi in data/
        data_dir = Path(__file__).parent.parent / "data"
        scenes = resolve_input_scenes(str(data_dir / "dataset" / "baseline"))
        video_files = (list(data_dir.glob("*.mp4")) + list(data_dir.glob("*.avi")))
        scenes += [str(v) for v in video_files]
        if not scenes:
            log.error(f"No input found. Use --input to specify a scene or video file.")
            sys.exit(1)

    log.info(f"Scenes to benchmark: {len(scenes)}")
    methods = ["MOG2", "KNN"] if args.all_methods else ["MOG2"]

    results = []
    for scene in scenes:
        for m in methods:
            try:
                r = benchmark_one(scene, method=m, warmup_frames=args.warmup)
                if r:
                    results.append(r)
            except Exception as e:
                log.error(f"Failed on {scene} / {m}: {e}")

    if results:
        print_benchmark_table(results)
        if args.csv:
            save_csv(results, args.csv)
    else:
        log.warning("No results collected. Check that FFmpeg is on PATH and videos are valid.")
