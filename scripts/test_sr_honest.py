"""
test_sr_honest.py

Honest super-resolution evaluation on real CDnet footage.

This script runs the SVCS pipeline on a test clip with enhance=True, then
compares the enhanced ROI crops against their bicubic-upscaled equivalents
using PSNR and SSIM. The goal is an honest answer to the question: does the
SR enhancement actually improve perceptual quality over a simple bicubic
upscale, and by how much, at what CPU cost?

Usage:
    uv run python scripts/test_sr_honest.py

Requirements:
    - ffmpeg on PATH
    - realesrgan, basicsr, torch installed (or bicubic fallback is used)
    - At least one CDnet clip in data/samples/cdnet_mp4/

Output:
    results/sr_test_<timestamp>.json  -- per-frame PSNR/SSIM measurements
    results/sr_test_<timestamp>.md    -- human-readable summary

The test deliberately uses a CDnet clip so the results are reproducible and
comparable across machines. It does NOT require a real camera.
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from enhancement.enhancer import Enhancer
from background_subtraction.background_subtraction import BackgroundSubtractor

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TEST_CLIP = Path("data/samples/cdnet_mp4/baseline/baseline_highway.mp4")
RESULTS_DIR = Path("results")
WARMUP_FRAMES = 100      # skip first N frames while MOG2 warms up
EVAL_FRAMES = 50         # number of frames to measure after warmup
SCALE = 4                # upscale factor
MIN_ROI_PX = 30          # skip ROI crops smaller than this (no reliable metric)
SR_MODEL = "espcn"       # fastest model; change to "realesrgan" for quality test

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def psnr(a: np.ndarray, b: np.ndarray) -> float:
    """PSNR in dB between two uint8 images of the same size."""
    mse = np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2)
    if mse < 1e-10:
        return 100.0
    return 20 * np.log10(255.0 / np.sqrt(mse))


def ssim_channel(a: np.ndarray, b: np.ndarray) -> float:
    """Single-channel SSIM (Wang et al. 2004).  a, b: float32 [0,255]."""
    k1, k2, L = 0.01, 0.03, 255.0
    c1, c2 = (k1 * L) ** 2, (k2 * L) ** 2
    mu_a = cv2.GaussianBlur(a, (11, 11), 1.5)
    mu_b = cv2.GaussianBlur(b, (11, 11), 1.5)
    mu_a2, mu_b2, mu_ab = mu_a ** 2, mu_b ** 2, mu_a * mu_b
    sig_a2 = cv2.GaussianBlur(a * a, (11, 11), 1.5) - mu_a2
    sig_b2 = cv2.GaussianBlur(b * b, (11, 11), 1.5) - mu_b2
    sig_ab = cv2.GaussianBlur(a * b, (11, 11), 1.5) - mu_ab
    num = (2 * mu_ab + c1) * (2 * sig_ab + c2)
    den = (mu_a2 + mu_b2 + c1) * (sig_a2 + sig_b2 + c2)
    return float(np.mean(num / (den + 1e-10)))


def ssim_color(a: np.ndarray, b: np.ndarray) -> float:
    """Mean SSIM across BGR channels."""
    a, b = a.astype(np.float32), b.astype(np.float32)
    return np.mean([ssim_channel(a[:,:,c], b[:,:,c]) for c in range(3)])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    if not TEST_CLIP.exists():
        print(f"[ERROR] Test clip not found: {TEST_CLIP}")
        print("        Place a CDnet .mp4 clip at that path and re-run.")
        sys.exit(1)

    print(f"Test clip:   {TEST_CLIP}")
    print(f"SR model:    {SR_MODEL}  (scale x{SCALE})")
    print(f"Warmup:      {WARMUP_FRAMES} frames")
    print(f"Eval frames: {EVAL_FRAMES}")
    print()

    # Load enhancer
    try:
        enhancer = Enhancer(scale=SCALE, device="cpu")
        print(f"Enhancer loaded: {enhancer.backend} backend on {enhancer.device}")
    except Exception as e:
        print(f"[WARN] Could not load Enhancer: {e}")
        print("       Bicubic fallback will be used for both paths - SR result will match baseline.")
        enhancer = None

    cap = cv2.VideoCapture(str(TEST_CLIP))
    if not cap.isOpened():
        print(f"[ERROR] Cannot open {TEST_CLIP}")
        sys.exit(1)

    sub = BackgroundSubtractor(var_threshold=50)

    frame_results = []
    frame_idx = 0
    eval_count = 0
    t_sr_total = 0.0
    t_bicubic_total = 0.0

    print("Processing frames...")
    while eval_count < EVAL_FRAMES:
        ok, frame = cap.read()
        if not ok:
            break

        mask = sub.apply(frame)
        frame_idx += 1

        if frame_idx <= WARMUP_FRAMES:
            continue

        # Get ROI regions from MOG2
        regions = sub.get_foreground_regions(mask)
        if not regions:
            continue

        for region in regions:
            x1 = max(0, region.x)
            y1 = max(0, region.y)
            x2 = min(frame.shape[1], region.x + region.w)
            y2 = min(frame.shape[0], region.y + region.h)
            if x2 - x1 < MIN_ROI_PX or y2 - y1 < MIN_ROI_PX:
                continue

            crop = frame[y1:y2, x1:x2]
            h, w = crop.shape[:2]

            # Ground truth: the original crop
            ground_truth = crop.copy()

            # Downscale then upscale (simulate what SR sees)
            small = cv2.resize(crop, (max(1, w // SCALE), max(1, h // SCALE)),
                               interpolation=cv2.INTER_AREA)

            # Bicubic upscale (baseline)
            t0 = time.perf_counter()
            bicubic_up = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
            t_bicubic_total += time.perf_counter() - t0

            # SR upscale
            if enhancer is not None:
                t0 = time.perf_counter()
                sr_up = enhancer.upscale_frame(small)
                t_sr_total += time.perf_counter() - t0
                # Resize SR output to match ground truth dimensions (scale may differ)
                if sr_up.shape[:2] != (h, w):
                    sr_up = cv2.resize(sr_up, (w, h), interpolation=cv2.INTER_AREA)
            else:
                sr_up = bicubic_up.copy()
                t_sr_total += 0.0

            psnr_bicubic = psnr(ground_truth, bicubic_up)
            psnr_sr = psnr(ground_truth, sr_up)
            ssim_bicubic = ssim_color(ground_truth, bicubic_up)
            ssim_sr = ssim_color(ground_truth, sr_up)

            frame_results.append({
                "frame": frame_idx,
                "roi_wh": [w, h],
                "psnr_bicubic": round(psnr_bicubic, 2),
                "psnr_sr": round(psnr_sr, 2),
                "ssim_bicubic": round(ssim_bicubic, 4),
                "ssim_sr": round(ssim_sr, 4),
            })

        eval_count += 1
        if eval_count % 10 == 0:
            print(f"  {eval_count}/{EVAL_FRAMES} frames evaluated...")

    cap.release()

    if not frame_results:
        print("[WARN] No ROI crops were large enough to measure. Try a busier clip.")
        sys.exit(1)

    # Aggregate
    n = len(frame_results)
    avg_psnr_bicubic = np.mean([r["psnr_bicubic"] for r in frame_results])
    avg_psnr_sr = np.mean([r["psnr_sr"] for r in frame_results])
    avg_ssim_bicubic = np.mean([r["ssim_bicubic"] for r in frame_results])
    avg_ssim_sr = np.mean([r["ssim_sr"] for r in frame_results])
    psnr_gain = avg_psnr_sr - avg_psnr_bicubic
    ssim_gain = avg_ssim_sr - avg_ssim_bicubic
    sr_ms_per_crop = (t_sr_total / n * 1000) if n > 0 else 0
    bicubic_ms_per_crop = (t_bicubic_total / n * 1000) if n > 0 else 0

    summary = {
        "timestamp": ts,
        "clip": str(TEST_CLIP),
        "model": SR_MODEL,
        "scale": SCALE,
        "n_crops": n,
        "avg_psnr_bicubic_dB": round(float(avg_psnr_bicubic), 2),
        "avg_psnr_sr_dB": round(float(avg_psnr_sr), 2),
        "psnr_gain_dB": round(float(psnr_gain), 2),
        "avg_ssim_bicubic": round(float(avg_ssim_bicubic), 4),
        "avg_ssim_sr": round(float(avg_ssim_sr), 4),
        "ssim_gain": round(float(ssim_gain), 4),
        "sr_ms_per_crop": round(sr_ms_per_crop, 1),
        "bicubic_ms_per_crop": round(bicubic_ms_per_crop, 2),
        "sr_speedup_factor": round(sr_ms_per_crop / max(bicubic_ms_per_crop, 0.001), 1),
        "frame_results": frame_results,
    }

    def _json_safe(obj):
        """Convert numpy scalars to native Python types for JSON serialization."""
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        raise TypeError(f"Not JSON serializable: {type(obj)}")

    json_out = RESULTS_DIR / f"sr_test_{ts}.json"
    json_out.write_text(json.dumps(summary, indent=2, default=_json_safe))

    # Human-readable summary
    md_lines = [
        f"# SR Honest Test Results",
        f"",
        f"**Clip:** `{TEST_CLIP}`",
        f"**SR model:** {SR_MODEL} (x{SCALE})",
        f"**Crops evaluated:** {n}",
        f"**Timestamp:** {ts}",
        f"",
        f"## Metrics",
        f"",
        f"| Metric | Bicubic baseline | SR output | Gain |",
        f"|--------|-----------------|-----------|------|",
        f"| PSNR (dB) | {avg_psnr_bicubic:.2f} | {avg_psnr_sr:.2f} | {psnr_gain:+.2f} |",
        f"| SSIM | {avg_ssim_bicubic:.4f} | {avg_ssim_sr:.4f} | {ssim_gain:+.4f} |",
        f"",
        f"## Speed",
        f"",
        f"| | ms / crop |",
        f"|---|---|",
        f"| SR ({SR_MODEL}) | {sr_ms_per_crop:.1f} ms |",
        f"| Bicubic | {bicubic_ms_per_crop:.2f} ms |",
        f"| Overhead factor | {summary['sr_speedup_factor']}x slower |",
        f"",
        f"## Interpretation",
        f"",
    ]

    if psnr_gain > 1.0:
        md_lines.append(
            f"SR improves PSNR by {psnr_gain:.2f} dB over bicubic - a meaningful "
            f"perceptual improvement on small ROI crops at x{SCALE}."
        )
    elif psnr_gain > 0.1:
        md_lines.append(
            f"SR shows a modest PSNR improvement of {psnr_gain:.2f} dB. "
            f"Visible on close inspection; may not be significant for operator use."
        )
    else:
        md_lines.append(
            f"SR shows negligible or no PSNR improvement ({psnr_gain:+.2f} dB) "
            f"over bicubic on this footage. Enhancement is {summary['sr_speedup_factor']}x "
            f"slower than bicubic for no measurable benefit on this clip."
        )

    md_out = RESULTS_DIR / f"sr_test_{ts}.md"
    md_out.write_text("\n".join(md_lines))

    # Print to terminal
    print(f"\n{'='*60}")
    print(f"SR honest test complete. {n} ROI crops measured.")
    print(f"  PSNR:  bicubic {avg_psnr_bicubic:.2f} dB  |  SR {avg_psnr_sr:.2f} dB  (gain: {psnr_gain:+.2f} dB)")
    print(f"  SSIM:  bicubic {avg_ssim_bicubic:.4f}     |  SR {avg_ssim_sr:.4f}     (gain: {ssim_gain:+.4f})")
    print(f"  Speed: {sr_ms_per_crop:.1f} ms/crop (SR) vs {bicubic_ms_per_crop:.2f} ms/crop (bicubic)")
    print(f"\nFull results: {json_out}")
    print(f"Summary:      {md_out}")


if __name__ == "__main__":
    main()
