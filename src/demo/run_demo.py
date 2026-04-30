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
├── demos_stitched/
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
except ModuleNotFoundError:
    from src.demo.demo import render_demo
    from src.demo.split_screen import build_split_screen_from_manifest
    from src.pipeline.pipeline import run_pipeline


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
    base_names = [f"demo_{mode}" for mode in modes] + ["demos_stitched"]

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


def run_all_demos(
    *,
    input_path: str,
    output_root: str,
    camera_id: str,
    modes: list[str],
    views: list[str],
    no_boxes: bool = False,
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

    for mode_index, mode in enumerate(modes):
        mode_dir = (output_root_path / f"demo_{mode}{suffix}").resolve()
        mode_output_dirs[mode] = mode_dir

        _cb(
            f"Running pipeline: {mode} ({mode_index + 1}/{mode_total})",
            phase="pipeline", mode=mode,
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
            phase="pipeline", mode=mode,
            mode_index=mode_index, mode_total=mode_total, done=True,
        )

    stitched_dir = (output_root_path / f"demos_stitched{suffix}").resolve()
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

    _cb("Demo run complete.", phase="done", done=True)
    print("\n=== Demo Run Complete ===\n")
    print("Generated outputs:\n")

    for mode in modes:
        print(f"demo_{mode}{suffix}/")

    print(f"demos_stitched{suffix}/")
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

    args = parser.parse_args()

    run_all_demos(
        input_path=args.input,
        output_root=args.output,
        camera_id=args.camera_id,
        modes=args.modes,
        views=args.view,
        no_boxes=args.no_boxes,
    )
