"""
watchfolder.py

Watchfolder daemon for external video ingestion.

Monitors a drop folder for new video files (body cameras, external sources)
and automatically feeds them into the compression pipeline. Supports all
common surveillance and body camera formats: .mp4, .avi, .mov, .mkv, .ts.

Designed to run as a background process alongside the live pipeline.
Uses polling (no OS-specific file system events) so it works on any platform.

Author: Jorge Sanchez (JS)

Usage:
    # Watch a folder and compress any new videos into outputs/
    python src/utils/watchfolder.py --watch-dir drop/ --output outputs/

    # Custom poll interval and camera prefix
    python src/utils/watchfolder.py --watch-dir drop/ --output outputs/ \
        --interval 5 --camera-prefix bodycam

    # Dry run (detect files but do not encode)
    python src/utils/watchfolder.py --watch-dir drop/ --dry-run
"""

import argparse
import logging
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)

# Supported video file extensions for body cameras and external sources.
SUPPORTED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".ts", ".mts", ".m2ts"}

# Sentinel file written next to each ingested video so we never process it twice.
# E.g. "clip.mp4" -> "clip.mp4.ingested"
INGESTED_SUFFIX = ".ingested"


def _sanitize_camera_id(name: str) -> str:
    """Strip unsafe characters from a camera ID (alphanumeric, _ and - only)."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


def _is_fully_written(path: Path, settle_seconds: float = 1.0) -> bool:
    """
    Return True only if the file size has stopped growing.

    Body cameras sometimes copy files slowly. We wait one poll cycle and
    check that the file size is stable before ingesting, so we never try
    to encode a partially-written file.

    Args:
        path: Path to the video file.
        settle_seconds: How long to wait between size checks.

    Returns:
        True if the file size is non-zero and stable.
    """
    try:
        size_before = path.stat().st_size
        if size_before == 0:
            return False
        time.sleep(settle_seconds)
        size_after = path.stat().st_size
        return size_before == size_after
    except OSError:
        return False


def _already_ingested(video_path: Path) -> bool:
    """Return True if a sentinel file exists for this video."""
    return video_path.with_suffix(video_path.suffix + INGESTED_SUFFIX).exists()


def _mark_ingested(video_path: Path) -> None:
    """Write a sentinel file next to the video so it is never processed again."""
    sentinel = video_path.with_suffix(video_path.suffix + INGESTED_SUFFIX)
    sentinel.touch()


def _build_camera_id(video_path: Path, prefix: str) -> str:
    """
    Build a camera ID from the file name and a prefix.

    Example: prefix='bodycam', file='AXON_2026_04_26_001.mp4'
             -> 'bodycam_AXON_2026_04_26_001'
    """
    stem = _sanitize_camera_id(video_path.stem)
    if prefix:
        safe_prefix = _sanitize_camera_id(prefix)
        return f"{safe_prefix}_{stem}"
    return stem


def scan_and_ingest(
    watch_dir: Path,
    output_dir: str,
    camera_prefix: str = "external",
    bg_method: str = "MOG2",
    segment_seconds: int = 60,
    warmup_frames: int = 120,
    dry_run: bool = False,
) -> int:
    """
    Scan watch_dir once for new video files and ingest any that are found.

    Skips files that:
      - Have already been ingested (sentinel file exists).
      - Are still being written (file size is still growing).
      - Have unsupported extensions.

    Args:
        watch_dir: Directory to scan for new video files.
        output_dir: Where compressed output segments are written.
        camera_prefix: Prefix added to the camera ID for each ingested file.
        bg_method: Background subtraction algorithm passed to the pipeline.
        segment_seconds: Segment duration passed to the pipeline.
        warmup_frames: Warmup frames passed to the pipeline.
        dry_run: If True, detect files but skip encoding (for testing).

    Returns:
        Number of files ingested in this scan.
    """
    ingested_count = 0

    candidates = [
        f for f in watch_dir.iterdir()
        if f.is_file()
        and f.suffix.lower() in SUPPORTED_EXTENSIONS
        and not _already_ingested(f)
    ]

    if not candidates:
        return 0

    log.info(f"Found {len(candidates)} new file(s) in {watch_dir}")

    for video_path in candidates:
        if not _is_fully_written(video_path):
            log.info(f"Skipping (still writing): {video_path.name}")
            continue

        camera_id = _build_camera_id(video_path, camera_prefix)
        log.info(f"Ingesting: {video_path.name} -> camera_id={camera_id!r}")

        if dry_run:
            log.info(f"[DRY RUN] Would encode {video_path.name} as {camera_id}")
            _mark_ingested(video_path)
            ingested_count += 1
            continue

        try:
            from pipeline.pipeline import run_pipeline
            run_pipeline(
                input_source=str(video_path),
                camera_id=camera_id,
                output_dir=output_dir,
                segment_seconds=segment_seconds,
                bg_method=bg_method,
                warmup_frames=warmup_frames,
            )
            _mark_ingested(video_path)
            ingested_count += 1
            log.info(f"Done: {video_path.name}")
        except Exception as exc:
            log.error(f"Failed to ingest {video_path.name}: {exc}")

    return ingested_count


def run_watchfolder(
    watch_dir: str,
    output_dir: str,
    poll_interval: int = 10,
    camera_prefix: str = "external",
    bg_method: str = "MOG2",
    segment_seconds: int = 60,
    warmup_frames: int = 120,
    dry_run: bool = False,
) -> None:
    """
    Run the watchfolder daemon loop indefinitely.

    Polls watch_dir every poll_interval seconds. Any new video file that
    appears in the folder is automatically ingested into the compression
    pipeline. Files are never processed twice (sentinel file mechanism).

    Args:
        watch_dir: Directory to monitor for new video files.
        output_dir: Where compressed output segments are written.
        poll_interval: Seconds between scans (default: 10).
        camera_prefix: Prefix added to camera IDs (e.g. 'bodycam').
        bg_method: Background subtraction algorithm ('MOG2' recommended).
        segment_seconds: Segment duration in seconds.
        warmup_frames: Background model warmup frames.
        dry_run: If True, detect files but skip encoding.
    """
    watch_path = Path(watch_dir)
    watch_path.mkdir(parents=True, exist_ok=True)

    log.info(f"Watchfolder daemon started.")
    log.info(f"Watching : {watch_path.resolve()}")
    log.info(f"Output   : {output_dir}")
    log.info(f"Interval : {poll_interval}s")
    log.info(f"Formats  : {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
    if dry_run:
        log.info("DRY RUN mode. No encoding will occur.")

    total_ingested = 0

    try:
        while True:
            count = scan_and_ingest(
                watch_dir=watch_path,
                output_dir=output_dir,
                camera_prefix=camera_prefix,
                bg_method=bg_method,
                segment_seconds=segment_seconds,
                warmup_frames=warmup_frames,
                dry_run=dry_run,
            )
            total_ingested += count
            if count:
                log.info(f"Total ingested so far: {total_ingested}")
            time.sleep(poll_interval)

    except KeyboardInterrupt:
        log.info(f"Watchfolder stopped. Total files ingested: {total_ingested}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Watchfolder daemon: auto-ingest external video files into the "
            "compression pipeline.\n\n"
            "Tip: the GUI's Save To field auto-detects OneDrive/Google Drive "
            "and writes to <cloud_root>/SVCS/. This CLI does NOT auto-detect "
            "— if you want the same behaviour, point --output explicitly at "
            "your synced folder, e.g. "
            "`--output \"$HOME/OneDrive - Florida Atlantic University/SVCS\"` "
            "(or %USERPROFILE%\\OneDrive - ...\\SVCS on Windows)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--watch-dir",
        default="drop/",
        help="Folder to monitor for new video files (default: drop/)",
    )
    parser.add_argument(
        "--output",
        default="outputs/",
        help=(
            "Output directory for compressed segments (default: outputs/). "
            "Set to <OneDrive>/SVCS/ for cloud-synced output — see the "
            "description above."
        ),
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Poll interval in seconds (default: 10)",
    )
    parser.add_argument(
        "--camera-prefix",
        default="external",
        help="Prefix for auto-generated camera IDs (default: external)",
    )
    parser.add_argument(
        "--method",
        default="MOG2",
        choices=["MOG2", "KNN"],
        help="Background subtraction method (default: MOG2)",
    )
    parser.add_argument(
        "--segment",
        type=int,
        default=60,
        help="Segment duration in seconds (default: 60)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=120,
        help="Warmup frames before encoding starts (default: 120)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect files but do not encode (for testing)",
    )
    args = parser.parse_args()

    run_watchfolder(
        watch_dir=args.watch_dir,
        output_dir=args.output,
        poll_interval=args.interval,
        camera_prefix=args.camera_prefix,
        bg_method=args.method,
        segment_seconds=args.segment,
        warmup_frames=args.warmup,
        dry_run=args.dry_run,
    )