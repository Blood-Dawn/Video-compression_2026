from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np

try:
    from demo.video_writer import H264Writer
except ImportError:
    from src.demo.video_writer import H264Writer


def load_manifest(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_mode_videos(manifest: dict) -> list[tuple[str, Path]]:
    """Resolve one video per mode for split-screen compositing.

    When multiple views exist for a mode (e.g. "standard" and "roi_tint"),
    prefer "standard"; fall back to the first available view.
    This avoids crashing when run_all_demos() renders more than one view.
    """
    outputs = manifest.get("outputs", {})
    if not outputs:
        raise RuntimeError("Manifest contains no outputs")

    resolved: list[tuple[str, Path]] = []

    for mode, mode_outputs in outputs.items():
        if not isinstance(mode_outputs, dict) or not mode_outputs:
            raise RuntimeError(f"No rendered outputs found for mode '{mode}'")

        # Prefer "standard" view for the split screen; fall back to first available
        if "standard" in mode_outputs:
            chosen_path = mode_outputs["standard"]
        else:
            chosen_path = next(iter(mode_outputs.values()))

        resolved.append((mode, Path(chosen_path)))

    return resolved


def open_video(path: Path) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video: {path}")
    return cap


def get_video_info(cap: cv2.VideoCapture) -> dict:
    return {
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": float(cap.get(cv2.CAP_PROP_FPS) or 30.0),
        "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
    }


def choose_layout(n: int) -> tuple[int, int] | None:
    if n <= 0:
        raise RuntimeError("No videos to composite")
    if n == 1:
        return None
    if n == 2:
        return (1, 2)
    if n in (3, 4):
        return (2, 2)
    raise RuntimeError(f"split_screen.py supports at most 4 modes, got {n}")


def fit_frame(frame: np.ndarray, cell_w: int, cell_h: int) -> np.ndarray:
    h, w = frame.shape[:2]
    scale = min(cell_w / w, cell_h / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))

    resized = cv2.resize(frame, (new_w, new_h))
    canvas = np.zeros((cell_h, cell_w, 3), dtype=np.uint8)

    x = (cell_w - new_w) // 2
    y = (cell_h - new_h) // 2
    canvas[y:y + new_h, x:x + new_w] = resized
    return canvas


def draw_label(frame: np.ndarray, text: str) -> None:
    """Tiny top-left mode tag for each quadrant.

    Was a big chunky label (scale 0.8, thickness 2, padded 8px) that
    chewed up ~10% of every quadrant. Shrunk to a discreet badge so
    the underlying video is actually visible.
    Author: Bloodawn (KheivenD), 2026-05-04 (corner overlays).
    """
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.45
    thickness = 1
    pad_x, pad_y = 6, 4
    x = 8
    y_baseline = 18

    # Normalize "mode0" → "M0" so all four labels fit in tight quadrants.
    short = text
    low = text.lower()
    if low.startswith("mode") and len(text) > 4:
        short = "M" + text[4:]

    (tw, th), baseline = cv2.getTextSize(short, font, scale, thickness)

    # Translucent dark pad
    overlay = frame.copy()
    cv2.rectangle(
        overlay,
        (x - pad_x, y_baseline - th - pad_y),
        (x + tw + pad_x, y_baseline + baseline + pad_y - 2),
        (0, 0, 0),
        -1,
    )
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, dst=frame)

    cv2.putText(frame, short, (x, y_baseline), font, scale,
                (255, 255, 255), thickness, cv2.LINE_AA)


def build_composite_frame(
    labeled_frames: list[tuple[str, np.ndarray]],
    rows: int,
    cols: int,
    cell_w: int,
    cell_h: int,
) -> np.ndarray:
    total_cells = rows * cols
    blank = np.zeros((cell_h, cell_w, 3), dtype=np.uint8)

    # Each per-mode demo video is rendered with corner labels already
    # stamped by add_bottom_right_labels() in src/demo/demo.py
    # (top-left "MODE N · SEG N", top-right "TIME"). If we call
    # draw_label() again here we get a second small "M0" badge stacked
    # on top of the existing "MODE 0 · SEG 1" label, which is the
    # "modes on top of each other" defect Riley flagged 2026-05-04.
    # Skip the second draw and just stitch the already-labeled cells.
    # Author: Bloodawn (KheivenD), 2026-05-04 (split-screen label fix).
    prepared: list[np.ndarray] = []
    for _mode, frame in labeled_frames:
        prepared.append(fit_frame(frame, cell_w, cell_h))

    while len(prepared) < total_cells:
        prepared.append(blank.copy())

    row_imgs = []
    idx = 0
    for _ in range(rows):
        row_imgs.append(cv2.hconcat(prepared[idx:idx + cols]))
        idx += cols

    return cv2.vconcat(row_imgs)


def build_split_screen_from_manifest(manifest_path: Path) -> Path | None:
    manifest = load_manifest(manifest_path)
    stitched_dir = Path(manifest["stitched_dir"])
    videos = resolve_mode_videos(manifest)

    caps: list[tuple[str, cv2.VideoCapture]] = []
    try:
        for mode, path in videos:
            caps.append((mode, open_video(path)))

        infos = [get_video_info(cap) for _, cap in caps]
        fps = min(info["fps"] for info in infos)
        if fps <= 0:
            fps = 30.0

        rows_cols = choose_layout(len(caps))
        if rows_cols is None:
            print("Only one mode present in manifest; skipping split-screen generation.")
            return None

        rows, cols = rows_cols

        cell_w = max(info["width"] for info in infos)
        cell_h = max(info["height"] for info in infos)

        first_frames: list[tuple[str, np.ndarray]] = []
        for mode, cap in caps:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError(f"Could not read first frame for mode '{mode}'")
            first_frames.append((mode, frame))

        first_composite = build_composite_frame(first_frames, rows, cols, cell_w, cell_h)

        output_path = stitched_dir / "demo_splitscreen.mp4"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        writer = H264Writer(
            str(output_path),
            fps,
            first_composite.shape[1],
            first_composite.shape[0],
        )
        if not writer.isOpened():
            raise RuntimeError(f"Failed to open H264Writer for: {output_path}")

        try:
            current_frames = first_frames
            while True:
                composite = build_composite_frame(current_frames, rows, cols, cell_w, cell_h)
                writer.write(composite)

                next_frames: list[tuple[str, np.ndarray]] = []
                for mode, cap in caps:
                    ok, frame = cap.read()
                    if not ok:
                        return output_path
                    next_frames.append((mode, frame))

                current_frames = next_frames
        finally:
            writer.release()

    finally:
        for _, cap in caps:
            cap.release()


def main() -> None:
    parser = argparse.ArgumentParser(description="Automatically build a demo split-screen from manifest outputs")
    parser.add_argument("--manifest", required=True, help="Path to manifest.json")
    args = parser.parse_args()

    output_path = build_split_screen_from_manifest(Path(args.manifest))
    if output_path is not None:
        print(f"Saved split-screen video: {output_path}")


if __name__ == "__main__":
    main()