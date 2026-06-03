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
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

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

# In-progress marker written just before encoding starts and removed on success.
# If the daemon crashes mid-encode the marker survives; on the next scan we treat
# the file as interrupted (not ingested) and retry it - explicit crash-resume.
# E.g. "clip.mp4" -> "clip.mp4.processing"
PROCESSING_SUFFIX = ".processing"


@dataclass(frozen=True)
class WatchProfile:
    """A watch-folder profile tuned to a common camera export/recording layout.

    Profiles are data-driven (not hard-coded per vendor): they set how the tree
    is scanned (recursive for per-camera/per-day folders), how fast the source
    writes (stable_checks/settle - a microSD dump copies fast, a NAS sync is
    slow and bursty), and how the encode preset is chosen (auto-detected per
    clip, or a fixed preset for a known layout). A specific camera family maps to
    one of these in docs/camera-ingestion.md.
    """
    key: str
    label: str
    description: str
    recursive: bool = False
    auto_preset: bool = True
    preset: Optional[str] = None
    stable_checks: int = 2
    settle_seconds: float = 1.0
    camera_prefix: str = "external"

    def scan_kwargs(self) -> dict:
        """The subset of scan_and_ingest kwargs this profile fixes."""
        return {
            "recursive": self.recursive,
            "auto_preset": self.auto_preset,
            "preset": self.preset,
            "stable_checks": self.stable_checks,
            "settle_seconds": self.settle_seconds,
            "camera_prefix": self.camera_prefix,
        }


# Ordered registry of layouts. Adding a layout is one entry - no code branch.
_PROFILE_LIST: List[WatchProfile] = [
    WatchProfile(
        key="continuous",
        label="Timestamped continuous recordings",
        description="A static camera writing back-to-back time-stamped files "
                    "(hourly CCTV clips, dashcam loops). Fixed Continuous-CCTV "
                    "preset for the biggest storage win.",
        recursive=True, auto_preset=False, preset="continuous_cctv",
        stable_checks=2, camera_prefix="cctv",
    ),
    WatchProfile(
        key="motion_events",
        label="Per-event motion clips",
        description="A folder of short clips, one per motion event (most "
                    "consumer cams). Auto-detect per clip - a porch visit and a "
                    "passing car want different settings.",
        recursive=True, auto_preset=True, camera_prefix="event",
    ),
    WatchProfile(
        key="microsd_dump",
        label="microSD / SD-card dump",
        description="A card pulled from a camera and copied in bulk. Files land "
                    "fast and complete; scan subfolders (DCIM-style trees).",
        recursive=True, auto_preset=True, stable_checks=2, camera_prefix="sdcard",
    ),
    WatchProfile(
        key="nas_sync",
        label="NAS / cloud-sync folder",
        description="Files arriving via a NAS or cloud sync client, which write "
                    "slowly and can pause mid-copy. Extra stability checks avoid "
                    "ingesting a half-synced file.",
        recursive=True, auto_preset=True, stable_checks=4, settle_seconds=2.0,
        camera_prefix="nas",
    ),
    WatchProfile(
        key="nvr_export",
        label="NVR export tree",
        description="An NVR's export, typically nested per-camera/per-day. "
                    "Recursive scan; the per-camera subfolder name becomes part "
                    "of the camera ID. Auto-detect per clip.",
        recursive=True, auto_preset=True, stable_checks=3, camera_prefix="nvr",
    ),
    WatchProfile(
        key="generic",
        label="Generic drop folder",
        description="A flat folder you drop files into. Non-recursive, "
                    "auto-detect per clip.",
        recursive=False, auto_preset=True, camera_prefix="external",
    ),
]

WATCHFOLDER_PROFILES: Dict[str, WatchProfile] = {p.key: p for p in _PROFILE_LIST}
DEFAULT_PROFILE = "generic"


def list_profiles() -> List[dict]:
    """Catalog of profiles (key/label/description) for docs and the CLI."""
    return [
        {"key": p.key, "label": p.label, "description": p.description,
         "recursive": p.recursive, "auto_preset": p.auto_preset, "preset": p.preset}
        for p in _PROFILE_LIST
    ]


def get_profile(key: str) -> WatchProfile:
    """Return the WatchProfile for ``key`` or raise KeyError."""
    try:
        return WATCHFOLDER_PROFILES[key]
    except KeyError:
        raise KeyError(f"unknown watch-folder profile: {key!r}") from None


def _sanitize_camera_id(name: str) -> str:
    """Strip unsafe characters from a camera ID (alphanumeric, _ and - only)."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


def _is_fully_written(
    path: Path,
    settle_seconds: float = 1.0,
    stable_checks: int = 2,
) -> bool:
    """
    Return True only if the file size is non-zero and has stopped growing.

    Cameras, NAS sync clients and network copies write files incrementally and
    can even pause mid-copy. A single before/after comparison can be fooled by a
    copy that happens to pause across one poll. We instead require the size to be
    identical across ``stable_checks`` consecutive polls spaced ``settle_seconds``
    apart; any change (or a zero size) means "still writing" and we return False,
    so the caller retries on the next scan cycle.

    Args:
        path: Path to the video file.
        settle_seconds: Seconds to wait between size checks.
        stable_checks: Number of consecutive unchanged reads required (>=1).

    Returns:
        True if the file size is non-zero and stable across every check.
    """
    try:
        size = path.stat().st_size
        if size == 0:
            return False
        for _ in range(max(1, stable_checks)):
            time.sleep(settle_seconds)
            new_size = path.stat().st_size
            if new_size != size or new_size == 0:
                return False
            size = new_size
        return True
    except OSError:
        return False


def _already_ingested(video_path: Path) -> bool:
    """Return True if a sentinel file exists for this video."""
    return video_path.with_suffix(video_path.suffix + INGESTED_SUFFIX).exists()


def _mark_ingested(video_path: Path) -> None:
    """Write a sentinel file next to the video so it is never processed again."""
    sentinel = video_path.with_suffix(video_path.suffix + INGESTED_SUFFIX)
    sentinel.touch()


def _processing_path(video_path: Path) -> Path:
    """Path of the in-progress marker for a video."""
    return video_path.with_suffix(video_path.suffix + PROCESSING_SUFFIX)


def _mark_processing(video_path: Path) -> None:
    """Write the in-progress marker (encode about to start)."""
    _processing_path(video_path).touch()


def _clear_processing(video_path: Path) -> None:
    """Remove the in-progress marker (encode finished or being retried)."""
    try:
        _processing_path(video_path).unlink()
    except OSError:
        pass


def _was_interrupted(video_path: Path) -> bool:
    """True if a prior encode of this (not-yet-ingested) file was interrupted."""
    return _processing_path(video_path).exists() and not _already_ingested(video_path)


def _resolve_encode_config(video_path: Path, auto_preset: bool, preset):
    """Resolve the per-file encode parameters for run_pipeline.

    If an explicit ``preset`` key is given, use it. Else if ``auto_preset`` is
    set, run rule-based content detection (TASK 3.2) on the clip and use the
    recommended preset. Detection failures degrade to the pipeline defaults (an
    empty dict) so ingestion never blocks on a flaky probe.

    Returns:
        (kwargs dict for run_pipeline, chosen preset key or None)
    """
    key = preset
    if auto_preset and not key:
        try:
            from pipeline.content_detect import detect_content
            key = detect_content(str(video_path)).preset
        except Exception as exc:  # detection is best-effort
            log.warning("Preset auto-detect failed for %s: %s", video_path.name, exc)
            key = None
    if not key:
        return {}, None
    try:
        from pipeline.presets import resolve_preset
        cfg = resolve_preset(key)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("Could not resolve preset %r: %s", key, exc)
        return {}, None
    return {
        "mode": cfg["mode"],
        "crf": cfg["crf"],
        "background_crf": cfg["background_crf"],
        "codec": cfg["codec"],
        "object_filter": cfg["object_filter"],
    }, key


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
    settle_seconds: float = 1.0,
    stable_checks: int = 2,
    auto_preset: bool = False,
    preset=None,
    recursive: bool = False,
) -> int:
    """
    Scan watch_dir once for new video files and ingest any that are found.

    Skips files that:
      - Have already been ingested (``.ingested`` sentinel exists) - dedupe.
      - Are still being written (size not stable across ``stable_checks`` polls).
      - Have unsupported extensions.

    Crash-resume: a ``.processing`` marker is written immediately before encoding
    and removed on success. A file that still carries that marker (without an
    ``.ingested`` sentinel) was interrupted by a crash and is retried.

    Preset auto-detection: when ``auto_preset`` is set (and no explicit
    ``preset``), each clip is analyzed (TASK 3.2) and encoded with the
    recommended surveillance preset.

    Args:
        watch_dir: Directory to scan for new video files.
        output_dir: Where compressed output segments are written.
        camera_prefix: Prefix added to the camera ID for each ingested file.
        bg_method: Background subtraction algorithm passed to the pipeline.
        segment_seconds: Segment duration passed to the pipeline.
        warmup_frames: Warmup frames passed to the pipeline.
        dry_run: If True, detect files but skip encoding (for testing).
        settle_seconds: Seconds between size-stability checks.
        stable_checks: Consecutive unchanged size reads required before ingest.
        auto_preset: Auto-detect a preset per file (TASK 3.2).
        preset: Explicit preset key to use for every file (overrides auto_preset).
        recursive: Scan subfolders too (NVR/microSD/NAS trees). The immediate
            parent folder name is folded into the camera ID so per-camera
            subfolders stay distinguishable.

    Returns:
        Number of files ingested in this scan.
    """
    ingested_count = 0

    walker = watch_dir.rglob("*") if recursive else watch_dir.iterdir()
    candidates = [
        f for f in walker
        if f.is_file()
        and f.suffix.lower() in SUPPORTED_EXTENSIONS
        and not _already_ingested(f)
    ]

    if not candidates:
        return 0

    log.info(f"Found {len(candidates)} new file(s) in {watch_dir}")

    for video_path in candidates:
        if _was_interrupted(video_path):
            log.info(f"Resuming after interrupted encode: {video_path.name}")

        if not _is_fully_written(video_path, settle_seconds, stable_checks):
            log.info(f"Skipping (still writing): {video_path.name}")
            continue

        # For nested trees, fold the immediate parent folder into the camera ID
        # so two clips named the same under different camera folders stay apart.
        file_prefix = camera_prefix
        if recursive and video_path.parent != watch_dir:
            sub = _sanitize_camera_id(video_path.parent.name)
            file_prefix = f"{camera_prefix}_{sub}" if camera_prefix else sub
        camera_id = _build_camera_id(video_path, file_prefix)
        log.info(f"Ingesting: {video_path.name} -> camera_id={camera_id!r}")

        if dry_run:
            log.info(f"[DRY RUN] Would encode {video_path.name} as {camera_id}")
            _mark_ingested(video_path)
            ingested_count += 1
            continue

        encode_kwargs, chosen = _resolve_encode_config(video_path, auto_preset, preset)
        if chosen:
            log.info(f"  preset: {chosen} ({encode_kwargs.get('mode')})")

        _mark_processing(video_path)
        try:
            from pipeline.pipeline import run_pipeline
            run_pipeline(
                input_source=str(video_path),
                camera_id=camera_id,
                output_dir=output_dir,
                segment_seconds=segment_seconds,
                bg_method=bg_method,
                warmup_frames=warmup_frames,
                **encode_kwargs,
            )
            _mark_ingested(video_path)
            _clear_processing(video_path)
            ingested_count += 1
            log.info(f"Done: {video_path.name}")
        except Exception as exc:
            # Leave the .processing marker in place: the next scan logs a resume
            # and retries this file rather than silently dropping it.
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
    settle_seconds: float = 1.0,
    stable_checks: int = 2,
    auto_preset: bool = False,
    preset=None,
    recursive: bool = False,
    profile: Optional[str] = None,
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
        settle_seconds / stable_checks: Partial-write stability tuning.
        auto_preset / preset: Per-file or fixed preset selection.
        recursive: Scan subfolders (NVR/microSD/NAS trees).
        profile: A named export-layout profile (see WATCHFOLDER_PROFILES) that
            sets recursive/auto_preset/preset/stability/camera_prefix defaults.
            Explicitly passed args still take precedence over the profile.
    """
    # A profile supplies layout-appropriate defaults; an explicitly-passed value
    # (different from this function's own default) wins over the profile.
    if profile:
        prof = get_profile(profile)
        pk = prof.scan_kwargs()
        if recursive is False:
            recursive = pk["recursive"]
        if auto_preset is False:
            auto_preset = pk["auto_preset"]
        if preset is None:
            preset = pk["preset"]
        if stable_checks == 2:
            stable_checks = pk["stable_checks"]
        if settle_seconds == 1.0:
            settle_seconds = pk["settle_seconds"]
        if camera_prefix == "external":
            camera_prefix = pk["camera_prefix"]

    watch_path = Path(watch_dir)
    watch_path.mkdir(parents=True, exist_ok=True)

    log.info(f"Watchfolder daemon started.")
    log.info(f"Watching : {watch_path.resolve()}")
    log.info(f"Output   : {output_dir}")
    log.info(f"Interval : {poll_interval}s")
    log.info(f"Formats  : {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
    if profile:
        log.info(f"Profile  : {profile} ({get_profile(profile).label})")
    if recursive:
        log.info("Recursive: scanning subfolders.")
    if dry_run:
        log.info("DRY RUN mode. No encoding will occur.")
    if auto_preset:
        log.info("Auto-preset: content detection chooses a preset per file.")
    elif preset:
        log.info(f"Preset    : {preset} (applied to every file)")

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
                settle_seconds=settle_seconds,
                stable_checks=stable_checks,
                auto_preset=auto_preset,
                preset=preset,
                recursive=recursive,
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
            " -  if you want the same behaviour, point --output explicitly at "
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
            "Set to <OneDrive>/SVCS/ for cloud-synced output - see the "
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
    parser.add_argument(
        "--stable-checks",
        type=int,
        default=2,
        help=(
            "Consecutive unchanged size reads required before a file is "
            "considered fully written (default: 2). Raise for slow NAS sync."
        ),
    )
    parser.add_argument(
        "--settle",
        type=float,
        default=1.0,
        help="Seconds between size-stability checks (default: 1.0)",
    )
    parser.add_argument(
        "--auto-preset",
        action="store_true",
        help="Auto-detect a surveillance preset per file (content analysis).",
    )
    parser.add_argument(
        "--preset",
        default=None,
        help="Apply a named preset to every file (overrides --auto-preset).",
    )
    parser.add_argument(
        "--profile",
        default=None,
        choices=sorted(WATCHFOLDER_PROFILES),
        help=(
            "Export-layout profile that sets sensible defaults for a camera "
            "family (recursive scan, stability, preset). See "
            "docs/camera-ingestion.md. One of: " + ", ".join(sorted(WATCHFOLDER_PROFILES))
        ),
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Scan subfolders too (NVR/microSD/NAS export trees).",
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
        settle_seconds=args.settle,
        stable_checks=args.stable_checks,
        auto_preset=args.auto_preset,
        preset=args.preset,
        recursive=args.recursive,
        profile=args.profile,
    )