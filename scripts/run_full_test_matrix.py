"""
run_full_test_matrix.py

Runs a repeatable benchmark matrix for DoD-style surveillance scenes and
optionally compares current results against an older benchmark CSV.

Why this exists:
  - `run_benchmark.py` benchmarks one input (or one category) at a time.
  - This script runs multiple scenes/methods/warmup values in one pass,
    compiles all output rows into one CSV, and emits a clear "better/worse"
    comparison report versus an old output file.

Usage examples:
  # Default DoD-style matrix (highway, pedestrians, parking, night scenes)
  python scripts/run_full_test_matrix.py

  # Custom scenes + compare against old CSV
  python scripts/run_full_test_matrix.py \
    --scenes data/dataset/baseline/highway data/dataset/nightVideos/fluidHighway \
    --old-csv outputs/benchmark_old.csv

  # Sweep warmups and methods
  python scripts/run_full_test_matrix.py \
    --methods MOG2 KNN \
    --warmups 60 120 180

Outputs:
  - Current matrix rows CSV (default: outputs/test_matrix_current.csv)
  - Optional compare CSV (default: outputs/test_matrix_compare.csv)
  - Console summary with per-scene/method improvement status

Author: Bloodawn (KheivenD)
"""

from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path
from typing import Dict, List, Tuple

from run_benchmark import benchmark_one

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")


DEFAULT_SCENES = [
    "data/dataset/baseline/highway",
    "data/dataset/baseline/pedestrians",
    "data/dataset/intermittentObjectMotion/parking",
    "data/dataset/nightVideos/fluidHighway",
    "data/dataset/nightVideos/streetCornerAtNight",
]


def _write_csv(rows: List[dict], csv_path: Path) -> None:
    if not rows:
        return
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> List[dict]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _best_by_scene_method(rows: List[dict]) -> Dict[Tuple[str, str], dict]:
    """
    If multiple warmups exist for one (scene, method), keep the row with the
    highest selective_ratio. This makes compare output deterministic.
    """
    best: Dict[Tuple[str, str], dict] = {}
    for r in rows:
        k = (r["scene"], r["method"])
        cur = best.get(k)
        if cur is None or float(r["selective_ratio"]) > float(cur["selective_ratio"]):
            best[k] = r
    return best


def _compare(new_rows: List[dict], old_rows: List[dict]) -> List[dict]:
    old_best = _best_by_scene_method(old_rows)
    new_best = _best_by_scene_method(new_rows)

    out = []
    for key, n in sorted(new_best.items()):
        o = old_best.get(key)
        if o is None:
            out.append({
                "scene": n["scene"],
                "method": n["method"],
                "status": "NO_OLD_ROW",
                "old_selective_ratio": "",
                "new_selective_ratio": n["selective_ratio"],
                "delta_selective_ratio": "",
                "old_selective_psnr": "",
                "new_selective_psnr": n["selective_psnr"],
                "delta_selective_psnr": "",
                "old_selective_ssim": "",
                "new_selective_ssim": n["selective_ssim"],
                "delta_selective_ssim": "",
            })
            continue

        old_sel = float(o["selective_ratio"])
        new_sel = float(n["selective_ratio"])
        old_psnr = float(o["selective_psnr"])
        new_psnr = float(n["selective_psnr"])
        old_ssim = float(o["selective_ssim"])
        new_ssim = float(n["selective_ssim"])

        d_sel = round(new_sel - old_sel, 3)
        d_psnr = round(new_psnr - old_psnr, 3)
        d_ssim = round(new_ssim - old_ssim, 5)

        # Improvement rule: better/equal compression, and quality not meaningfully worse.
        improved = (new_sel >= old_sel) and (new_psnr >= old_psnr - 0.3) and (new_ssim >= old_ssim - 0.01)

        out.append({
            "scene": n["scene"],
            "method": n["method"],
            "status": "BETTER_OR_EQUAL" if improved else "CHECK_REGRESSION",
            "old_selective_ratio": old_sel,
            "new_selective_ratio": new_sel,
            "delta_selective_ratio": d_sel,
            "old_selective_psnr": old_psnr,
            "new_selective_psnr": new_psnr,
            "delta_selective_psnr": d_psnr,
            "old_selective_ssim": old_ssim,
            "new_selective_ssim": new_ssim,
            "delta_selective_ssim": d_ssim,
        })
    return out


def _print_compare_table(rows: List[dict]) -> None:
    if not rows:
        return
    print("\n" + "=" * 124)
    print("  CURRENT vs OLD BENCHMARK COMPARISON")
    print("=" * 124)
    print(
        f"{'Scene':<24} {'Method':<6} {'Status':<16} "
        f"{'Old Sel x':>9} {'New Sel x':>9} {'ΔSel x':>8} "
        f"{'Old PSNR':>9} {'New PSNR':>9} {'ΔPSNR':>8} "
        f"{'Old SSIM':>9} {'New SSIM':>9} {'ΔSSIM':>9}"
    )
    print("-" * 124)
    for r in rows:
        print(
            f"{r['scene']:<24} {r['method']:<6} {r['status']:<16} "
            f"{str(r['old_selective_ratio']):>9} {str(r['new_selective_ratio']):>9} {str(r['delta_selective_ratio']):>8} "
            f"{str(r['old_selective_psnr']):>9} {str(r['new_selective_psnr']):>9} {str(r['delta_selective_psnr']):>8} "
            f"{str(r['old_selective_ssim']):>9} {str(r['new_selective_ssim']):>9} {str(r['delta_selective_ssim']):>9}"
        )
    print("=" * 124)
    ok = sum(1 for r in rows if r["status"] == "BETTER_OR_EQUAL")
    print(f"  BETTER_OR_EQUAL rows: {ok}/{len(rows)}")
    print("  CHECK_REGRESSION rows should be reviewed manually.")
    print("=" * 124 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full benchmark matrix and compare to old results.")
    parser.add_argument("--scenes", nargs="*", default=DEFAULT_SCENES,
                        help="Scene paths to benchmark. Defaults to DoD-style local scenes.")
    parser.add_argument("--methods", nargs="*", default=["MOG2", "KNN"], choices=["MOG2", "KNN"],
                        help="Background subtraction methods to test.")
    parser.add_argument("--warmups", nargs="*", type=int, default=[120],
                        help="Warmup frame values to sweep. Example: --warmups 60 120 180")
    parser.add_argument("--out-csv", default="outputs/test_matrix_current.csv",
                        help="CSV path for current matrix output.")
    parser.add_argument("--old-csv", default=None,
                        help="Optional old benchmark CSV to compare against.")
    parser.add_argument("--compare-out", default="outputs/test_matrix_compare.csv",
                        help="CSV path for comparison output when --old-csv is supplied.")
    args = parser.parse_args()

    scene_paths = [Path(s) for s in args.scenes]
    missing = [str(p) for p in scene_paths if not p.exists()]
    if missing:
        for m in missing:
            log.error(f"Missing scene path: {m}")
        raise SystemExit(1)

    results: List[dict] = []
    total = len(scene_paths) * len(args.methods) * len(args.warmups)
    done = 0

    log.info(f"Starting matrix: scenes={len(scene_paths)} methods={args.methods} warmups={args.warmups}")
    for scene in scene_paths:
        for method in args.methods:
            for warmup in args.warmups:
                done += 1
                log.info(f"[{done}/{total}] scene={scene.name} method={method} warmup={warmup}")
                r = benchmark_one(str(scene), method=method, warmup_frames=warmup)
                if not r:
                    continue
                r["warmup_frames"] = warmup
                results.append(r)

    if not results:
        log.error("No benchmark results collected.")
        raise SystemExit(1)

    out_csv = Path(args.out_csv)
    _write_csv(results, out_csv)
    log.info(f"Current matrix CSV saved: {out_csv}")

    # Small summary of current results.
    print("\n" + "=" * 100)
    print("  CURRENT MATRIX SUMMARY")
    print("=" * 100)
    print(
        f"{'Scene':<24} {'Method':<6} {'Warmup':>7} {'Sel x':>8} {'PSNR':>8} {'SSIM':>8} {'FG%':>7} {'CRF':>5}"
    )
    print("-" * 100)
    for r in results:
        print(
            f"{r['scene']:<24} {r['method']:<6} {r['warmup_frames']:>7} "
            f"{r['selective_ratio']:>8} {r['selective_psnr']:>8} {r['selective_ssim']:>8} "
            f"{r['avg_fg_pct']:>7} {str(r['crf_used']):>5}"
        )
    print("=" * 100 + "\n")

    if args.old_csv:
        old_rows = _read_csv(Path(args.old_csv))
        if not old_rows:
            log.warning(f"No old rows loaded from: {args.old_csv}")
            return
        compare_rows = _compare(results, old_rows)
        compare_out = Path(args.compare_out)
        _write_csv(compare_rows, compare_out)
        log.info(f"Comparison CSV saved: {compare_out}")
        _print_compare_table(compare_rows)


if __name__ == "__main__":
    main()
