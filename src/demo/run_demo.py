"""
run_demo.py

High-level demo orchestration script for the compression pipeline.

This script automates:
1. Running the pipeline across multiple modes (mode0, mode1, mode2, mode3)
2. Rendering annotated demo videos for each mode
3. Generating a split-screen comparison video
4. Producing a manifest of all outputs

------------------------------------------------------------
USAGE:

Basic: runs all modes by default
    python -m src.demo.run_demo \
        --input footage/test_clip.mp4 \
        --output outputs/ \
        --camera-id cam_test

Multiple modes: select which modes to compare
    python -m src.demo.run_demo \
        --input footage/test_clip.mp4 \
        --output outputs/ \
        --camera-id cam_test \
        --modes mode0 mode1 mode2

With ROI-tinted view:
    python -m src.demo.run_demo \
        --input footage/test_clip.mp4 \
        --output outputs/ \
        --camera-id cam_test \
        --view roi_tint

------------------------------------------------------------
OUTPUT STRUCTURE:

outputs/
├── demo_mode0/
├── demo_mode1/
├── demo_mode2/
├── demo_mode3/
├── demo_comp/
│   ├── mode0_demo.mp4
│   ├── mode1_demo.mp4
│   ├── demo_splitscreen.mp4
│   └── manifest.json

------------------------------------------------------------
NOTES:

- Each mode runs independently using the same input.
- Demo videos are rendered from pipeline metadata (NOT reprocessed frames).
- Split-screen is automatically generated for 2–4 modes.
- If only one mode is used, split-screen is skipped.
- File size comparisons for benchmarking should be computed from segment metadata (metadata.db),
  not from stitched demo outputs. Stitched videos include overlays and are not
  representative of compression efficiency.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make src/ importable when this script is run directly (python src/demo/run_demo.py)
# or as a module from the project root (python -m src.demo.run_demo).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from demo.demo import render_demo
    from demo.split_screen import build_split_screen_from_manifest
    from pipeline.pipeline import run_pipeline
    from utils.metrics import build_demo_metrics, measure_cpu_usage
except ModuleNotFoundError:
    from src.demo.demo import render_demo
    from src.demo.split_screen import build_split_screen_from_manifest
    from src.pipeline.pipeline import run_pipeline
    from src.utils.metrics import build_demo_metrics, measure_cpu_usage


ALLOWED_MODES = {"mode0", "mode1", "mode2", "mode3"}
ALLOWED_VIEWS = {"standard", "roi_tint"}


def validate_mode(mode: str) -> str:
    if mode not in ALLOWED_MODES:
        raise ValueError(f"Unsupported mode: {mode}")
    return mode


def validate_view(view: str) -> str:
    if view not in ALLOWED_VIEWS:
        raise ValueError(f"Unsupported view: {view}")
    return view


def get_next_run_suffix(output_root: Path, modes: list[str]) -> str:
    base_names = [f"demo_{mode}" for mode in modes] + ["demo_comp"]

    i = 0
    while True:
        suffix = "" if i == 0 else f"_{i}"
        exists = any((output_root / (name + suffix)).exists() for name in base_names)
        if not exists:
            return suffix
        i += 1


def find_jsonl_file(folder: Path, mode: str) -> Path:
    matches = list(folder.glob(f"*_{mode}_demo_frames.jsonl"))
    if not matches:
        raise RuntimeError(f"No JSONL demo file found in {folder} for mode={mode}")
    if len(matches) > 1:
        raise RuntimeError(f"Multiple JSONL files found in {folder} for mode={mode}")
    return matches[0]


def stitched_name_for_view(mode: str, view: str) -> str:
    if view == "standard":
        return f"{mode}_demo.mp4"
    return f"{mode}_demo_{view}.mp4"


def _aggregate_demo_metadata(mode_output_dirs: dict) -> dict:
    """Pull aggregated metrics from the per-mode metadata.db files.

    The split-screen row used to land in the dashboard with empty
    Color/Scene/Light/Motion columns because we never copied any of
    that data from the underlying mode runs (which DO have it). Here
    we walk one mode's metadata.db (any mode — same source clip, so
    scene/lighting/color are identical) and aggregate the per-segment
    rows into a single set of values for the composite row.

    Returns a dict with keys ready to slot into the segments INSERT.
    Falls back to safe defaults if the per-mode DB can't be read.
    Author: Bloodawn (KheivenD), 2026-05-04 (splitscreen metrics).
    """
    import sqlite3

    out = {
        "target_detected": 0,
        "roi_count":       0,
        "duration":        0.0,
        "object_type":     "demo",
        "avg_sharpness":   None,
        "sharpness_label": None,
        "object_classes":  None,
        "dominant_color":  None,
        "scene_type":      "unknown",
        "time_of_day":     None,
        "vehicle_count":   0,
        "person_count":    0,
    }
    if not mode_output_dirs:
        return out

    # Use the first mode's DB — all modes process the same source clip,
    # so scene_type / time_of_day / dominant_color are equivalent.
    sample_dir = next(iter(mode_output_dirs.values()))
    db_path = Path(sample_dir) / "metadata.db"
    if not db_path.exists():
        return out

    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute(
            """
            SELECT
                MAX(COALESCE(target_detected, 0)),
                SUM(COALESCE(roi_count, 0)),
                SUM(COALESCE(duration, 0.0)),
                COALESCE(object_type, 'unknown'),
                AVG(avg_sharpness),
                sharpness_label,
                dominant_color,
                COALESCE(scene_type, 'unknown'),
                time_of_day,
                SUM(COALESCE(vehicle_count, 0)),
                SUM(COALESCE(person_count, 0))
            FROM segments
            WHERE COALESCE(hidden, 0) = 0
            """
        ).fetchone()
        conn.close()
        if cur:
            out.update({
                "target_detected": int(cur[0] or 0),
                "roi_count":       int(cur[1] or 0),
                "duration":        float(cur[2] or 0.0),
                "object_type":     cur[3] or "demo",
                "avg_sharpness":   float(cur[4]) if cur[4] is not None else None,
                "sharpness_label": cur[5],
                "dominant_color":  cur[6],
                "scene_type":      cur[7] or "unknown",
                "time_of_day":     cur[8],
                "vehicle_count":   int(cur[9] or 0),
                "person_count":    int(cur[10] or 0),
            })
    except Exception:
        pass

    return out


def _index_demo_outputs(
    *,
    stitched_dir: Path,
    input_path: str,
    camera_id: str,
    modes: list[str],
    views: list[str],
    stitched_outputs: dict,
    split_screen_path: "Path | None",
    mode_output_dirs: dict | None = None,
) -> None:
    """Write a single ``metadata.db`` row for the split-screen composite.

    Behavior change 2026-05-04 (Bloodawn / KheivenD): was writing one
    row per per-mode rendered demo video PLUS one row for the composite
    — that flooded the metrics tab with 5 rows per demo run. The user
    wants only the actual stitched output (the one video that contains
    all selected modes side-by-side). The per-mode renders are still
    on disk in this folder (you can play them by opening the file), but
    they're no longer indexed.

    Metadata for the row is aggregated from one of the underlying mode
    dirs so the Color/Scene/Light/Motion columns aren't empty — every
    mode processes the same source so the per-clip metadata is shared.
    """
    import sqlite3
    from datetime import datetime, timezone

    if split_screen_path is None or not Path(split_screen_path).exists():
        # Single-mode demo (no composite to index). The pipeline already
        # wrote rows for each mode's own metadata.db, so there's nothing
        # extra to do here — bailing out is correct.
        return

    db_path = stitched_dir / "metadata.db"
    src_stem = Path(input_path).stem
    cam_short = camera_id if camera_id and camera_id != "cam_00" else src_stem

    # Aggregated metadata pulled from one of the per-mode runs
    meta = _aggregate_demo_metadata(mode_output_dirs or {})

    size = Path(split_screen_path).stat().st_size
    mode_tag = "+".join(m.replace("mode", "M") for m in modes)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS segments (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TEXT    NOT NULL,
                camera_id       TEXT    NOT NULL,
                target_detected INTEGER NOT NULL DEFAULT 0,
                roi_count       INTEGER NOT NULL DEFAULT 0,
                file_size       INTEGER NOT NULL DEFAULT 0,
                duration        REAL    NOT NULL DEFAULT 0.0,
                file_path       TEXT    NOT NULL,
                object_type     TEXT    NOT NULL DEFAULT 'unknown',
                avg_sharpness   REAL,
                sharpness_label TEXT,
                hidden          INTEGER DEFAULT 0,
                object_classes  TEXT,
                dominant_color  TEXT,
                scene_type      TEXT    DEFAULT 'unknown',
                time_of_day     TEXT,
                vehicle_count   INTEGER DEFAULT 0,
                person_count    INTEGER DEFAULT 0
            )
        """)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        # Hide any leftover per-mode demo rows from old indexing runs in
        # this same db (pre-2026-05-04). The user requested that only
        # the composite show up, so we mark anything but the new
        # split-screen row as hidden.
        try:
            conn.execute(
                "UPDATE segments SET hidden = 1 "
                "WHERE COALESCE(hidden, 0) = 0 AND file_path != ?",
                (str(split_screen_path),),
            )
        except Exception:
            pass

        conn.execute(
            "INSERT INTO segments "
            "(timestamp, camera_id, target_detected, roi_count, file_size, "
            " duration, file_path, object_type, avg_sharpness, sharpness_label, "
            " dominant_color, scene_type, time_of_day, vehicle_count, person_count) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ts,
                f"{cam_short}_split_{mode_tag}",
                meta["target_detected"],
                meta["roi_count"],
                size,
                meta["duration"],
                str(split_screen_path),
                meta["object_type"],
                meta["avg_sharpness"],
                meta["sharpness_label"],
                meta["dominant_color"],
                meta["scene_type"],
                meta["time_of_day"],
                meta["vehicle_count"],
                meta["person_count"],
            ),
        )
        conn.commit()
    finally:
        conn.close()


def run_all_demos(
    *,
    input_path: str,
    output_root: str,
    camera_id: str,
    modes: list[str],
    views: list[str],
    no_boxes: bool = False,
    no_tint: bool = False,
    progress_callback=None,
):
    """Run pipelines for each mode then render annotated demo videos.

    Args:
        progress_callback: Optional callable(message: str, detail: dict) called
            at each significant step so the caller can surface live updates.
            detail keys: phase ("pipeline"|"render"|"stitch"), mode, mode_index,
            mode_total, done (bool).
    """
    def _cb(msg, **kw):
        if progress_callback is not None:
            try:
                progress_callback(msg, kw)
            except Exception:
                pass
        print(msg)

    input_path = str(Path(input_path).resolve())
    output_root_path = Path(output_root).resolve()
    output_root_path.mkdir(parents=True, exist_ok=True)

    modes = [validate_mode(mode) for mode in modes]
    views = [validate_view(view) for view in views]

    suffix = get_next_run_suffix(output_root_path, modes)
    mode_total = len(modes)

    _cb(f"Starting demo run: {mode_total} mode(s)", phase="start", mode_total=mode_total)

    mode_output_dirs: dict[str, Path] = {}
    mode_metrics: dict[str, dict] = {}

    for mode_index, mode in enumerate(modes):
        mode_dir = (output_root_path / f"demo_{mode}{suffix}").resolve()
        mode_output_dirs[mode] = mode_dir

        # Pass mode_dir on the progress events so the GUI's CPU sampler
        # can attribute samples to this specific output folder rather
        # than aggregating across every demo run.
        # Author: Bloodawn (KheivenD), 2026-05-03 (per-clip CPU stats).
        _cb(
            f"Running pipeline: {mode} ({mode_index + 1}/{mode_total})",
            phase="pipeline", mode=mode, mode_dir=str(mode_dir),
            mode_index=mode_index, mode_total=mode_total, done=False,
        )

        run_pipeline(
            input_source=input_path,
            camera_id=camera_id,
            output_dir=str(mode_dir),
            mode=mode,
            demo=True,
        )

        _cb(
            f"Pipeline done: {mode}. Rendering annotated video…",
            phase="pipeline", mode=mode, mode_dir=str(mode_dir),
            mode_index=mode_index, mode_total=mode_total, done=True,
        )

    stitched_dir = (output_root_path / f"demo_comp{suffix}").resolve()
    stitched_dir.mkdir(parents=True, exist_ok=True)

    stitched_outputs: dict[tuple[str, str], Path] = {}

    for mode_index, mode in enumerate(modes):
        mode_dir = mode_output_dirs[mode]

        db_path = (mode_dir / "metadata.db").resolve()
        if not db_path.exists():
            raise RuntimeError(f"Missing metadata.db in {mode_dir}")

        jsonl_path = find_jsonl_file(mode_dir, mode).resolve()

        for view in views:
            output_video = (stitched_dir / stitched_name_for_view(mode, view)).resolve()

            _cb(
                f"Rendering demo video: {mode} [{view}] ({mode_index + 1}/{mode_total})",
                phase="render", mode=mode, view=view,
                mode_index=mode_index, mode_total=mode_total, done=False,
            )

            render_demo(
                db_path=str(db_path),
                metadata_path=str(jsonl_path),
                output_path=str(output_video),
                view=view,
                draw_boxes=not no_boxes,
                draw_tint=not no_tint,
                metrics=mode_metrics.get(mode),
            )

            _cb(
                f"Rendered: {output_video.name}",
                phase="render", mode=mode, view=view,
                mode_index=mode_index, mode_total=mode_total, done=True,
            )
            stitched_outputs[(mode, view)] = output_video

    manifest = {
        "input": input_path,
        "camera_id": camera_id,
        "run_suffix": suffix,
        "modes": modes,
        "stitched_dir": str(stitched_dir),
        "outputs": {},
        "metrics": mode_metrics,
    }

    for mode in modes:
        manifest["outputs"][mode] = {}
        for view in views:
            manifest["outputs"][mode][view] = str(stitched_outputs[(mode, view)])

    manifest_path = (stitched_dir / "manifest.json").resolve()
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n[INFO] Manifest written to: {manifest_path}")

    split_screen_path: Path | None = None
    if len(modes) > 1:
        _cb("Building split-screen comparison…", phase="stitch", done=False)
        split_screen_path = build_split_screen_from_manifest(manifest_path)
        _cb("Split-screen ready.", phase="stitch", done=True)

    # ── Index demo outputs into a metadata.db for /api/segments ───────────
    # Without this the rendered demo videos (per-mode + split-screen)
    # never appear in the dashboard. Was filed by the user 2026-05-04
    # ("the vid I just outputed is not showing in search/metrics/recent").
    # We write one row per output file into <stitched_dir>/metadata.db.
    # Author: Bloodawn (KheivenD), 2026-05-04.
    try:
        _index_demo_outputs(
            stitched_dir=stitched_dir,
            input_path=input_path,
            camera_id=camera_id,
            modes=modes,
            views=views,
            stitched_outputs=stitched_outputs,
            split_screen_path=split_screen_path,
            mode_output_dirs=mode_output_dirs,
        )
    except Exception as exc:  # noqa: BLE001
        # Indexing failures shouldn't fail the demo — files are still on
        # disk, only the dashboard table won't show them.
        print(f"[WARN] Demo indexing failed: {exc}")

    _cb("Demo run complete.", phase="done", done=True)
    print("\n=== Demo Run Complete ===\n")
    print("Generated outputs:\n")

    for mode in modes:
        print(f"demo_{mode}{suffix}/")

    print(f"demo_comp{suffix}/")
    for mode in modes:
        for view in views:
            path = stitched_outputs[(mode, view)]
            print(f"  {path.name}")

    if split_screen_path is not None:
        print(f"  {split_screen_path.name}")

    print("  manifest.json")
    print("\n=========================\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run all demo modes and stitch outputs")

    parser.add_argument("--input", required=True, help="Input video path")
    parser.add_argument("--output", required=True, help="Root output directory")
    parser.add_argument("--camera-id", required=True, help="Camera ID")

    parser.add_argument(
        "--modes",
        nargs="+",
        default=["mode0", "mode1", "mode2", "mode3"],
        help="List of modes to run (default: mode0 mode1 mode2 mode3)",
    )

    parser.add_argument(
        "--view",
        nargs="+",
        choices=["standard", "roi_tint"],
        default=["standard"],
        help="Which stitched demo views to render",
    )

    parser.add_argument(
        "--no-boxes",
        action="store_true",
        help="Disable ROI boxes in stitched demo renders",
    )
    parser.add_argument(
        "--no-tint",
        action="store_true",
        help="Disable ROI tinting in stitched demo renders",
    )

    args = parser.parse_args()

    run_all_demos(
        input_path=args.input,
        output_root=args.output,
        camera_id=args.camera_id,
        modes=args.modes,
        views=args.view,
        no_boxes=args.no_boxes,
        no_tint=args.no_tint,
    )
