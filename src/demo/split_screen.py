from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np


def load_manifest(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_mode_videos(manifest: dict) -> list[tuple[str, Path]]:
    outputs = manifest.get("outputs", {})
    if not outputs:
        raise RuntimeError("Manifest contains no outputs")

    resolved: list[tuple[str, Path]] = []

    for mode, mode_outputs in outputs.items():
        if not isinstance(mode_outputs, dict) or not mode_outputs:
            raise RuntimeError(f"No rendered outputs found for mode '{mode}'")

        if len(mode_outputs) > 1:
            available = ", ".join(mode_outputs.keys())
            raise RuntimeError(
                f"Mode '{mode}' has multiple rendered views ({available}). "
                f"For now, split_screen.py expects exactly one rendered file per mode."
            )

        only_path = Path(next(iter(mode_outputs.values())))
        resolved.append((mode, only_path))

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
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.8
    thickness = 2
    pad = 8
    x = 12
    y = 30

    (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)

    cv2.rectangle(
        frame,
        (x - pad, y - th - pad),
        (x + tw + pad, y + pad),
        (0, 0, 0),
        -1,
    )
    cv2.putText(frame, text, (x, y), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)


def build_composite_frame(
    labeled_frames: list[tuple[str, np.ndarray]],
    rows: int,
    cols: int,
    cell_w: int,
    cell_h: int,
) -> np.ndarray:
    total_cells = rows * cols
    blank = np.zeros((cell_h, cell_w, 3), dtype=np.uint8)

    prepared: list[np.ndarray] = []
    for mode, frame in labeled_frames:
        fitted = fit_frame(frame, cell_w, cell_h)
        draw_label(fitted, mode)
        prepared.append(fitted)

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

        writer = cv2.VideoWriter(
            str(output_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (first_composite.shape[1], first_composite.shape[0]),
        )
        if not writer.isOpened():
            raise RuntimeError(f"Failed to open output writer: {output_path}")

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