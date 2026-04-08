"""
scripts/benchmark_enhancer.py

CPU per-frame timing benchmark for the Enhancer super-resolution module.

Measures wall-clock time for upscale_frame() and upscale_roi() across
resolutions and model backends. Produces a summary table and writes results
to docs/enhancement_benchmark_results.md.

Usage:
    python scripts/benchmark_enhancer.py                      # default: espcn x4
    python scripts/benchmark_enhancer.py --model fsrcnn --scale 4
    python scripts/benchmark_enhancer.py --model realesrgan --scale 4
    python scripts/benchmark_enhancer.py --all                # run all available models

Requirements:
    - Model weights must be present in models/
    - opencv-contrib-python for espcn/fsrcnn/edsr/lapsrn
    - realesrgan + basicsr for realesrgan/realesrnet
    See DEV.md → Enhancement Module Setup.

Author: Bloodawn (KheivenD)
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from enhancement.enhancer import Enhancer

logging.basicConfig(level=logging.WARNING)  # suppress enhancer load warnings during benchmark

# ─── Benchmark config ─────────────────────────────────────────────────────────

# Resolutions to test (label, height, width)
RESOLUTIONS: List[Tuple[str, int, int]] = [
    ("240p",  240,  320),
    ("480p",  480,  640),
    ("720p",  720, 1280),
    ("1080p", 1080, 1920),
]

# ROI size as fraction of frame area for upscale_roi benchmarks
ROI_FRACTION = 0.10  # 10% of frame (typical person/vehicle bbox in surveillance)

# Number of warm-up runs (discarded) and timed runs
WARMUP_RUNS  = 3
TIMED_RUNS   = 10

MODELS_TO_TEST = ["espcn", "fsrcnn", "edsr", "realesrgan", "realesrnet"]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_frame(h: int, w: int) -> np.ndarray:
    """Synthetic BGR frame for benchmarking."""
    rng = np.random.default_rng(42)
    return rng.integers(0, 256, (h, w, 3), dtype=np.uint8)


def _roi_bbox(h: int, w: int, fraction: float = ROI_FRACTION) -> Tuple[int, int, int, int]:
    """Return a centered bbox covering approximately `fraction` of the frame area."""
    roi_h = max(1, int(h * fraction ** 0.5))
    roi_w = max(1, int(w * fraction ** 0.5))
    x = (w - roi_w) // 2
    y = (h - roi_h) // 2
    return (x, y, roi_w, roi_h)


def _time_call(fn, *args, warmup=WARMUP_RUNS, runs=TIMED_RUNS) -> Dict:
    """
    Run `fn(*args)` `warmup` times (discarded), then `runs` times (timed).
    Returns dict with mean_ms, min_ms, max_ms, std_ms, fps.
    """
    for _ in range(warmup):
        fn(*args)

    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn(*args)
        times.append(time.perf_counter() - t0)

    times_ms = [t * 1000 for t in times]
    mean_ms = sum(times_ms) / len(times_ms)
    return {
        "mean_ms": mean_ms,
        "min_ms":  min(times_ms),
        "max_ms":  max(times_ms),
        "std_ms":  float(np.std(times_ms)),
        "fps":     1000.0 / mean_ms if mean_ms > 0 else 0.0,
    }


# ─── Benchmark ────────────────────────────────────────────────────────────────

def run_benchmark(model: str, scale: int, output_md: bool = True) -> List[Dict]:
    """
    Benchmark `model` at `scale` across all RESOLUTIONS.
    Returns list of result dicts. Writes markdown table if output_md is True.
    """
    print(f"\nInitializing Enhancer(model={model!r}, scale={scale}) ...")
    enhancer = Enhancer(scale=scale, model=model)

    if not enhancer.is_available():
        print(f"  SKIP — model '{model}' not available (weights missing or package not installed).")
        print(f"  See DEV.md → Enhancement Module Setup for setup instructions.")
        return []

    print(f"  {repr(enhancer)}")
    print(f"  Warm-up runs: {WARMUP_RUNS} | Timed runs: {TIMED_RUNS}")

    results = []
    header = f"\n{'Resolution':<10} {'full-frame mean':>18} {'full-frame fps':>16} {'roi mean':>14} {'roi fps':>10}"
    separator = "-" * len(header)
    print(header)
    print(separator)

    for label, h, w in RESOLUTIONS:
        frame = _make_frame(h, w)
        bbox  = _roi_bbox(h, w)

        # Full-frame upscale
        full_stats = _time_call(enhancer.upscale_frame, frame)

        # ROI-only upscale
        roi_stats = _time_call(enhancer.upscale_roi, frame, bbox)

        results.append({
            "model":        model,
            "scale":        scale,
            "resolution":   label,
            "h": h, "w": w,
            "roi_bbox":     bbox,
            "full_mean_ms": full_stats["mean_ms"],
            "full_fps":     full_stats["fps"],
            "roi_mean_ms":  roi_stats["mean_ms"],
            "roi_fps":      roi_stats["fps"],
        })

        print(
            f"{label:<10} "
            f"{full_stats['mean_ms']:>14.1f} ms   "
            f"{full_stats['fps']:>10.1f} fps   "
            f"{roi_stats['mean_ms']:>8.1f} ms   "
            f"{roi_stats['fps']:>7.1f} fps"
        )

    if output_md:
        _write_markdown(model, scale, results)

    return results


def _write_markdown(model: str, scale: int, results: List[Dict]) -> None:
    """Append benchmark results to docs/enhancement_benchmark_results.md."""
    out_path = Path(__file__).parent.parent / "docs" / "enhancement_benchmark_results.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    import datetime
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = []
    # Only write header if file is new
    if not out_path.exists():
        lines.append("# Enhancement CPU Benchmark Results\n")
        lines.append("CPU-only, no GPU. All times measured with `time.perf_counter()`.\n")
        lines.append(f"Warm-up: {WARMUP_RUNS} runs | Timed: {TIMED_RUNS} runs | ROI fraction: {ROI_FRACTION:.0%}\n")

    lines.append(f"\n## {model.upper()} x{scale} — {timestamp}\n")
    lines.append("| Resolution | Full-frame mean | Full-frame fps | ROI mean | ROI fps |\n")
    lines.append("|---|---|---|---|---|\n")
    for r in results:
        lines.append(
            f"| {r['resolution']} "
            f"| {r['full_mean_ms']:.1f} ms "
            f"| {r['full_fps']:.1f} fps "
            f"| {r['roi_mean_ms']:.1f} ms "
            f"| {r['roi_fps']:.1f} fps |\n"
        )

    with open(out_path, "a") as f:
        f.writelines(lines)

    print(f"\n  Results appended to {out_path}")


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Benchmark CPU per-frame timing for the Enhancer super-resolution module."
    )
    parser.add_argument(
        "--model",
        default="espcn",
        choices=MODELS_TO_TEST,
        help="SR model to benchmark. Default: espcn.",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=4,
        choices=[2, 4, 8],
        help="Upscale factor. Default: 4.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="run_all",
        help="Run benchmark for all models and both x2/x4 scales.",
    )
    parser.add_argument(
        "--no-md",
        action="store_false",
        dest="output_md",
        help="Skip writing markdown results file.",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=WARMUP_RUNS,
        help=f"Warm-up iterations before timing. Default: {WARMUP_RUNS}.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=TIMED_RUNS,
        help=f"Timed iterations per configuration. Default: {TIMED_RUNS}.",
    )
    args = parser.parse_args()

    WARMUP_RUNS = args.warmup
    TIMED_RUNS  = args.runs

    print("=" * 60)
    print("  Enhancer CPU Benchmark")
    print("  EGN 4950C Capstone — Group 16")
    print("=" * 60)

    if args.run_all:
        for mdl in MODELS_TO_TEST:
            for sc in [2, 4]:
                run_benchmark(mdl, sc, output_md=args.output_md)
    else:
        run_benchmark(args.model, args.scale, output_md=args.output_md)

    print("\nBenchmark complete.")
