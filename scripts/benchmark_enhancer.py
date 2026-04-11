"""
benchmark_enhancer.py

Measures per-frame CPU inference time for the Enhancer module.

Benchmarks both:
  - upscale_frame: full-frame upscaling (Real-ESRGAN or bicubic fallback)
  - upscale_roi:   bounding-box region enhancement

Tests run at multiple resolutions and ROI sizes to give a realistic picture
of the CPU cost of enabling --enhance in the pipeline.

Author: Victor Teixeira

Usage:
    python scripts/benchmark_enhancer.py
    python scripts/benchmark_enhancer.py --frames 30
    python scripts/benchmark_enhancer.py --scale 2
    python scripts/benchmark_enhancer.py --csv outputs/enhancer_benchmark.csv
"""

import argparse
import csv
import logging
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from enhancement.enhancer import Enhancer

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# Resolutions to test  (label, width, height)
RESOLUTIONS = [
    ("240p",  426,  240),
    ("480p",  854,  480),
    ("720p", 1280,  720),
]

# ROI sizes as a fraction of the frame  (label, fraction)
ROI_SIZES = [
    ("small  (5%)",  0.05),
    ("medium (15%)", 0.15),
    ("large  (30%)", 0.30),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_frame(width: int, height: int) -> np.ndarray:
    """Create a synthetic BGR frame (random noise, uint8)."""
    rng = np.random.default_rng(42)
    return rng.integers(0, 256, (height, width, 3), dtype=np.uint8)


def _bbox_for_fraction(width: int, height: int, fraction: float):
    """Return a centred (x, y, w, h) bbox covering `fraction` of frame area."""
    side = int((width * height * fraction) ** 0.5)
    side = max(side, 4)
    x = (width - side) // 2
    y = (height - side) // 2
    return (x, y, side, side)


def _time_calls(fn, n: int) -> dict:
    """
    Call `fn()` n times and return timing statistics in milliseconds.

    Discards the first call (warm-up) before recording times.
    """
    # warm-up
    fn()

    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)

    arr = np.array(times)
    return {
        "n": n,
        "mean_ms": round(float(arr.mean()), 1),
        "min_ms":  round(float(arr.min()),  1),
        "max_ms":  round(float(arr.max()),  1),
        "std_ms":  round(float(arr.std()),  1),
    }


# ---------------------------------------------------------------------------
# Benchmark functions
# ---------------------------------------------------------------------------

def benchmark_upscale_frame(enhancer: Enhancer, n_frames: int) -> list:
    """
    Time upscale_frame at each resolution.

    Returns a list of result dicts, one per resolution.
    """
    results = []
    for label, w, h in RESOLUTIONS:
        frame = _make_frame(w, h)
        log.info(f"  upscale_frame  {label} ({w}x{h})  n={n_frames}")

        stats = _time_calls(lambda f=frame: enhancer.upscale_frame(f), n_frames)
        results.append({
            "benchmark": "upscale_frame",
            "backend": enhancer.backend,
            "resolution": label,
            "frame_size": f"{w}x{h}",
            "scale": enhancer.scale,
            **stats,
        })
    return results


def benchmark_upscale_roi(enhancer: Enhancer, n_frames: int) -> list:
    """
    Time upscale_roi at each (resolution × ROI size) combination.

    Returns a list of result dicts.
    """
    results = []
    for res_label, w, h in RESOLUTIONS:
        frame = _make_frame(w, h)
        for roi_label, frac in ROI_SIZES:
            bbox = _bbox_for_fraction(w, h, frac)
            log.info(
                f"  upscale_roi    {res_label} ({w}x{h})  roi={roi_label}  n={n_frames}"
            )
            stats = _time_calls(
                lambda f=frame, b=bbox: enhancer.upscale_roi(f, b), n_frames
            )
            results.append({
                "benchmark": "upscale_roi",
                "backend": enhancer.backend,
                "resolution": res_label,
                "frame_size": f"{w}x{h}",
                "roi_size": roi_label,
                "scale": enhancer.scale,
                **stats,
            })
    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_frame_table(results: list):
    print("\n" + "=" * 72)
    print("  ENHANCER BENCHMARK — upscale_frame")
    print("  Author: Victor Teixeira")
    print("=" * 72)
    header = f"{'Backend':<12} {'Resolution':<8} {'Scale':>5}  {'Mean ms':>8} {'Min ms':>7} {'Max ms':>7} {'Std ms':>7}"
    print(header)
    print("-" * 72)
    for r in results:
        print(
            f"{r['backend']:<12} {r['resolution']:<8} {r['scale']:>5}x "
            f"{r['mean_ms']:>8.1f} {r['min_ms']:>7.1f} {r['max_ms']:>7.1f} {r['std_ms']:>7.1f}"
        )
    print("=" * 72)


def print_roi_table(results: list):
    print("\n" + "=" * 84)
    print("  ENHANCER BENCHMARK — upscale_roi")
    print("  Author: Victor Teixeira")
    print("=" * 84)
    header = (
        f"{'Backend':<12} {'Resolution':<8} {'ROI size':<16} {'Scale':>5}  "
        f"{'Mean ms':>8} {'Min ms':>7} {'Max ms':>7}"
    )
    print(header)
    print("-" * 84)
    for r in results:
        print(
            f"{r['backend']:<12} {r['resolution']:<8} {r['roi_size']:<16} {r['scale']:>5}x "
            f"{r['mean_ms']:>8.1f} {r['min_ms']:>7.1f} {r['max_ms']:>7.1f}"
        )
    print("=" * 84 + "\n")


def save_csv(results: list, path: str):
    if not results:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    log.info(f"CSV saved: {path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark Enhancer CPU inference time")
    parser.add_argument(
        "--frames",
        type=int,
        default=20,
        help="Number of timed calls per configuration. Default 20."
    )
    parser.add_argument(
        "--scale",
        type=int,
        choices=[2, 4],
        default=4,
        help="Upscale factor passed to Enhancer. Default 4."
    )
    parser.add_argument(
        "--model-path",
        default=None,
        help="Path to RealESRGAN .pth weights. Omit to use default models/ location."
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Save results to this CSV path."
    )
    args = parser.parse_args()

    log.info(f"Initialising Enhancer (scale={args.scale}) ...")
    enhancer = Enhancer(model_path=args.model_path, scale=args.scale)
    log.info(f"Backend: {enhancer.backend}")

    log.info("Benchmarking upscale_frame ...")
    frame_results = benchmark_upscale_frame(enhancer, args.frames)

    log.info("Benchmarking upscale_roi ...")
    roi_results = benchmark_upscale_roi(enhancer, args.frames)

    print_frame_table(frame_results)
    print_roi_table(roi_results)

    if args.csv:
        save_csv(frame_results + roi_results, args.csv)
