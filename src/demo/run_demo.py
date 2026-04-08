from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Sequence


ALLOWED_MODES = {"mode0", "mode1", "mode2", "mode3"}
ALLOWED_VIEWS = {"standard", "roi_tint"}


def run_subprocess(cmd: Sequence[str]) -> None:
    subprocess.run(list(cmd), check=True, shell=False)


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
):
    input_path = str(Path(input_path).resolve())
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    modes = [validate_mode(mode) for mode in modes]
    views = [validate_view(view) for view in views]

    suffix = get_next_run_suffix(output_root, modes)

    print(f"\n=== Starting demo run (suffix='{suffix or 'base'}') ===\n")

    mode_output_dirs: dict[str, Path] = {}

    for mode in modes:
        mode_dir = (output_root / f"demo_{mode}{suffix}").resolve()
        mode_output_dirs[mode] = mode_dir

        print(f"[RUN] Pipeline for {mode}")
        print(f"Output dir: {mode_dir}")

        cmd = [
            sys.executable, "-m", "src.pipeline.pipeline",
            "--input", input_path,
            "--output", str(mode_dir),
            "--camera-id", camera_id,
            "--mode", mode,
            "--demo",
        ]
        run_subprocess(cmd)

    stitched_dir = (output_root / f"demos_stitched{suffix}").resolve()
    stitched_dir.mkdir(parents=True, exist_ok=True)

    stitched_outputs: dict[tuple[str, str], Path] = {}

    for mode in modes:
        mode_dir = mode_output_dirs[mode]

        db_path = (mode_dir / "metadata.db").resolve()
        if not db_path.exists():
            raise RuntimeError(f"Missing metadata.db in {mode_dir}")

        jsonl_path = find_jsonl_file(mode_dir, mode).resolve()

        for view in views:
            output_video = (stitched_dir / stitched_name_for_view(mode, view)).resolve()

            print(f"\n[RUN] demo.py for {mode} [{view}]")
            print(f"DB: {db_path}")
            print(f"JSONL: {jsonl_path}")
            print(f"Output: {output_video}")

            cmd = [
                sys.executable, "-m", "src.demo.demo",
                "--db", str(db_path),
                "--metadata", str(jsonl_path),
                "--output", str(output_video),
                "--view", view,
            ]

            if no_boxes:
                cmd.append("--no-boxes")

            run_subprocess(cmd)
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
        cmd = [
            sys.executable, "-m", "src.demo.split_screen",
            "--manifest", str(manifest_path),
        ]
        run_subprocess(cmd)
        split_screen_path = stitched_dir / "demo_splitscreen.mp4"

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
        default=["mode0", "mode1"],
        help="List of modes to run (default: mode0 mode1)",
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