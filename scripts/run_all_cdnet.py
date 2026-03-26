"""
scripts/run_all_cdnet.py

Batch runner for all CDnet 2014 categories.

Runs MOG2 + KNN on every scene across all categories using demo_detection.py's
compare_all_methods() directly (no subprocess overhead). Prints the live coverage
report after each scene exactly as the interactive demo does, then prints a
consolidated summary table of every result at the end.

All terminal output (logging + print) is simultaneously written to a log file
so nothing is lost to scroll-buffer truncation.  Default log path:
    outputs/cdnet_batch_results.log

Categories covered:
    baseline, badWeather, shadow, dynamicBackground, intermittentObjectMotion,
    lowFramerate, cameraJitter, turbulence, nightVideos, thermal

Skipped:
    PTZ  -- pan/tilt/zoom cameras are incompatible with static-camera background
            subtraction; the whole frame shifts every frame, giving ~100% FG.

Usage (from project root, with venv activated):
    python scripts/run_all_cdnet.py

    # Skip categories you've already run:
    python scripts/run_all_cdnet.py --skip baseline nightVideos thermal

    # Override sample rate (default 20):
    python scripts/run_all_cdnet.py --sample-rate 30

    # Point at a different dataset root:
    python scripts/run_all_cdnet.py --dataset-root data/dataset

    # Custom log file location:
    python scripts/run_all_cdnet.py --log-file outputs/my_run.log

Author: Bloodawn (KheivenD)
"""

import argparse
import logging
import os
import sys
import time
import traceback
from pathlib import Path


# ---------------------------------------------------------------------------
# Tee: mirror everything written to stdout/stderr into a log file as well.
# This captures BOTH logging output and print() calls in one place.
# ---------------------------------------------------------------------------

class _Tee:
    """Write to both the original stream and a file simultaneously."""

    def __init__(self, original_stream, file_path: Path):
        self._orig = original_stream
        self._file = open(file_path, "w", encoding="utf-8", buffering=1)  # line-buffered

    def write(self, data):
        self._orig.write(data)
        self._orig.flush()
        self._file.write(data)
        self._file.flush()

    def flush(self):
        self._orig.flush()
        self._file.flush()

    def close(self):
        self._file.close()

    # Proxy everything else so logging / readline don't break
    def __getattr__(self, name):
        return getattr(self._orig, name)


def _setup_tee_logging(log_path: Path):
    """
    Redirect stdout and stderr through _Tee so every byte going to the
    terminal also lands in log_path.  Must be called before basicConfig.

    Two layers of capture:
      1. Python-level: sys.stdout and sys.stderr are replaced with Tee objects
         so all Python print() and logging output goes to both terminal and file.
      2. OS-level fd 2: OpenCV (a C library) writes error messages directly to
         file descriptor 2, bypassing Python's sys.stderr entirely.  We dup2()
         fd 2 to also point at the log file so those raw C error dumps are caught.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    tee = _Tee(sys.stdout, log_path)
    sys.stdout = tee
    sys.stderr = tee  # captures Python logging output (goes to stderr by default)

    # Also redirect the OS-level file descriptor 2 so C-library output (OpenCV
    # error messages, assertion failures) lands in the log file as well.
    try:
        log_fd = os.open(str(log_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        os.dup2(log_fd, 2)   # fd 2 = stderr at the OS level
        os.close(log_fd)
    except OSError:
        pass  # non-fatal: Python-level capture still works if this fails

    return tee


# ---------------------------------------------------------------------------
# Path setup -- make sure src/ and project root are importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from demo_detection import compare_all_methods, print_coverage_report  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scene manifest
# Each entry: (category, scene_name, use_night_mode, sample_rate_override)
# sample_rate_override=None means use the CLI default.
# lowFramerate clips have very few frames so we use sample_rate 5.
# ---------------------------------------------------------------------------
ALL_SCENES = [
    # category               scene                    night   sr_override
    ("baseline",             "highway",               False,  None),

    ("badWeather",           "blizzard",              False,  None),
    ("badWeather",           "skating",               False,  None),
    ("badWeather",           "snowFall",              False,  None),
    ("badWeather",           "wetSnow",               False,  None),

    ("shadow",               "backdoor",              False,  None),
    ("shadow",               "bungalows",             False,  None),
    ("shadow",               "busStation",            False,  None),
    ("shadow",               "copyMachine",           False,  None),
    ("shadow",               "cubicle",               False,  None),
    ("shadow",               "peopleInShade",         False,  None),

    ("dynamicBackground",    "boats",                 False,  None),
    ("dynamicBackground",    "canoe",                 False,  None),
    ("dynamicBackground",    "fall",                  False,  None),
    ("dynamicBackground",    "fountain01",            False,  None),
    ("dynamicBackground",    "fountain02",            False,  None),
    ("dynamicBackground",    "overpass",              False,  None),

    ("intermittentObjectMotion", "abandonedBox",      False,  None),
    ("intermittentObjectMotion", "parking",           False,  None),
    ("intermittentObjectMotion", "sofa",              False,  None),
    ("intermittentObjectMotion", "streetLight",       False,  None),
    ("intermittentObjectMotion", "tramstop",          False,  None),
    ("intermittentObjectMotion", "winterDriveway",    False,  None),

    # Very few frames per clip -- use sample_rate 5
    ("lowFramerate",         "port_0_17fps",          False,  5),
    ("lowFramerate",         "tramCrossroad_1fps",    False,  5),
    ("lowFramerate",         "tunnelExit_0_35fps",    False,  5),
    ("lowFramerate",         "turnpike_0_5fps",       False,  5),

    ("cameraJitter",         "badminton",             False,  None),
    ("cameraJitter",         "boulevard",             False,  None),
    ("cameraJitter",         "sidewalk",              False,  None),
    ("cameraJitter",         "traffic",               False,  None),

    ("turbulence",           "turbulence0",           False,  None),
    ("turbulence",           "turbulence1",           False,  None),
    ("turbulence",           "turbulence2",           False,  None),
    ("turbulence",           "turbulence3",           False,  None),

    # Night scenes -- CLAHE + higher varThreshold
    ("nightVideos",          "bridgeEntry",           True,   None),
    ("nightVideos",          "busyBoulvard",          True,   None),
    ("nightVideos",          "fluidHighway",          True,   None),
    ("nightVideos",          "streetCornerAtNight",   True,   None),
    ("nightVideos",          "tramStation",           True,   None),
    ("nightVideos",          "winterStreet",          True,   None),

    # Thermal -- no night_mode needed (already high-contrast IR)
    ("thermal",              "corridor",              False,  None),
    ("thermal",              "diningRoom",            False,  None),
    ("thermal",              "lakeSide",              False,  None),
    ("thermal",              "library",               False,  None),
    ("thermal",              "park",                  False,  None),
]


# ---------------------------------------------------------------------------
# Summary table helpers
# ---------------------------------------------------------------------------

def _pad(s: str, width: int) -> str:
    return s[:width].ljust(width)


def print_summary_table(all_results: list):
    """
    Prints a consolidated summary of every scene/method result at the end.

    Columns: Category | Scene | Method | Avg FG% | Max FG% | Activity% | Frames
    """
    SEP = "=" * 105
    HDR = (
        f"  {'Category':<26} {'Scene':<24} {'Method':<6}  "
        f"{'Avg FG%':>7}  {'Max FG%':>7}  {'Activity%':>9}  {'Frames':>8}"
    )

    print("\n\n" + SEP)
    print("  FULL CDnet BATCH RESULTS -- ALL SCENES")
    print("  Author: Bloodawn (KheivenD)")
    print(SEP)
    print(HDR)
    print("-" * 105)

    last_category = None
    for entry in all_results:
        cat = entry["category"]
        r   = entry["result"]

        # Blank separator line between categories
        if last_category and cat != last_category:
            print()
        last_category = cat

        night_flag = "  [night]" if entry.get("night_mode") else ""
        print(
            f"  {_pad(cat, 26)} {_pad(r['scene'], 24)} {_pad(r['method'], 6)}  "
            f"  {r['avg_coverage_pct']:5.2f}%    {r['max_coverage_pct']:5.2f}%"
            f"    {r['activity_rate_pct']:5.1f}%   {r['analyzed_frames']:>7}"
            f"{night_flag}"
        )

    print(SEP)

    # Per-category averages (MOG2 + KNN combined)
    print("\n  PER-CATEGORY AVERAGE FG% (both methods)")
    print("-" * 60)
    by_cat: dict = {}
    for entry in all_results:
        cat = entry["category"]
        by_cat.setdefault(cat, []).append(entry["result"]["avg_coverage_pct"])

    for cat, vals in by_cat.items():
        avg = sum(vals) / len(vals)
        print(f"  {cat:<30}  avg FG: {avg:5.2f}%  ({len(vals)//2} scenes)")

    print(SEP + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run all CDnet 2014 scenes through MOG2 + KNN and collect coverage stats."
    )
    parser.add_argument(
        "--dataset-root",
        default="data/dataset",
        help="Root folder containing the CDnet category subdirectories. Default: data/dataset"
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=20,
        help="Save a comparison image every N frames (default: 20). "
             "lowFramerate scenes use 5 regardless."
    )
    parser.add_argument(
        "--output",
        default="outputs/demo_frames",
        help="Directory to save comparison images. Default: outputs/demo_frames"
    )
    parser.add_argument(
        "--skip",
        nargs="*",
        default=[],
        metavar="CATEGORY",
        help="Categories to skip entirely, e.g. --skip baseline nightVideos"
    )
    parser.add_argument(
        "--log-file",
        default="outputs/cdnet_batch_results.log",
        help="Path to save a full copy of all terminal output. "
             "Default: outputs/cdnet_batch_results.log"
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Tee stdout + stderr → log file so nothing is lost to scroll buffer
    # ------------------------------------------------------------------
    log_path = Path(args.log_file)
    tee = _setup_tee_logging(log_path)
    # Re-configure logging NOW so the new stderr (the tee) is used
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)s  %(message)s",
        stream=sys.stderr,
        force=True,  # override the basicConfig called at module level
    )

    dataset_root = Path(args.dataset_root)
    skipped = set(args.skip or [])

    all_results = []      # flat list of {category, result, night_mode} dicts
    failed_scenes = []    # scenes that errored out, so we can report at the end

    total_scenes = sum(1 for c, s, *_ in ALL_SCENES if c not in skipped)
    done = 0

    log.info(f"Starting CDnet batch run: {total_scenes} scenes across {len(set(c for c,*_ in ALL_SCENES)) - len(skipped)} categories")
    log.info(f"Dataset root : {dataset_root.resolve()}")
    log.info(f"Sample rate  : {args.sample_rate} (lowFramerate: 5)")
    log.info(f"Output dir   : {args.output}")
    if skipped:
        log.info(f"Skipping     : {', '.join(sorted(skipped))}")

    batch_start = time.time()

    for category, scene, night_mode, sr_override in ALL_SCENES:
        if category in skipped:
            continue

        scene_path = dataset_root / category / scene

        if not scene_path.exists():
            log.warning(f"Scene not found, skipping: {scene_path}")
            failed_scenes.append(f"{category}/{scene}  [not found]")
            continue

        effective_sr = sr_override if sr_override is not None else args.sample_rate
        done += 1

        log.info(
            f"\n{'#'*70}\n"
            f"  [{done}/{total_scenes}]  {category}/{scene}"
            + ("  [NIGHT MODE]" if night_mode else "")
            + f"\n{'#'*70}"
        )

        scene_start = time.time()
        try:
            results = compare_all_methods(
                str(scene_path),
                sample_rate=effective_sr,
                warmup_frames=-1,       # auto from temporalROI.txt
                output_dir=args.output,
                night_mode=night_mode,
            )
            print_coverage_report(results)

            elapsed = time.time() - scene_start
            log.info(f"  Scene finished in {elapsed:.1f}s")

            for r in results:
                all_results.append({
                    "category":  category,
                    "result":    r,
                    "night_mode": night_mode,
                })

        except Exception as exc:
            # log.exception() writes the full Python traceback to the log,
            # not just the one-line error message.
            log.exception(f"  FAILED: {category}/{scene} -- {exc}")
            failed_scenes.append(f"{category}/{scene}  [{exc}]")

    # ------------------------------------------------------------------
    # Final output
    # ------------------------------------------------------------------
    total_elapsed = time.time() - batch_start
    log.info(f"\nBatch complete: {done} scenes in {total_elapsed/60:.1f} min")

    if failed_scenes:
        print("\n" + "!" * 70)
        print("  FAILED SCENES:")
        for fs in failed_scenes:
            print(f"    {fs}")
        print("!" * 70)

    if all_results:
        print_summary_table(all_results)
    else:
        log.warning("No results to summarize.")

    # ------------------------------------------------------------------
    # Close the tee and tell the user where the full log landed
    # ------------------------------------------------------------------
    print(f"\nFull output saved to: {log_path.resolve()}")
    tee.close()


if __name__ == "__main__":
    main()
