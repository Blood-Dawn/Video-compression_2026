from __future__ import annotations

import argparse
import json
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

    When a mode has several views (e.g. "standard" and "roi_tint"), prefer
    "standard" and otherwise take the first one listed, so a run that rendered
    more than one view still composites.
    """
    outputs = manifest.get("outputs", {})
    if not outputs:
        raise RuntimeError("Manifest contains no outputs")

    resolved: list[tuple[str, Path]] = []
    for mode, mode_outputs in outputs.items():
        if not isinstance(mode_outputs, dict) or not mode_outputs:
            raise RuntimeError(f"No rendered outputs found for mode '{mode}'")
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


def _fit_into(frame: np.ndarray, cell: np.ndarray) -> None:
    """Letterbox `frame` into the (zeroed) `cell` view, keeping aspect ratio."""
    cell_h, cell_w = cell.shape[:2]
    h, w = frame.shape[:2]
    scale = min(cell_w / w, cell_h / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))

    resized = cv2.resize(frame, (new_w, new_h))
    x = (cell_w - new_w) // 2
    y = (cell_h - new_h) // 2
    cell[y:y + new_h, x:x + new_w] = resized


def fit_frame(frame: np.ndarray, cell_w: int, cell_h: int) -> np.ndarray:
    canvas = np.zeros((cell_h, cell_w, 3), dtype=np.uint8)
    _fit_into(frame, canvas)
    return canvas


def draw_label(frame: np.ndarray, text: str) -> None:
    """Tiny top-left mode tag ("mode0" -> "M0") drawn in-place.

    No longer used by build_composite_frame (see there); kept for callers that
    want a label on an unlabeled frame.
    Author: Bloodawn (KheivenD), 2026-05-04 (corner overlays).
    """
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.45
    thickness = 1
    pad_x, pad_y = 6, 4
    x = 8
    y_baseline = 18

    # Short tags so all four labels fit in tight quadrants.
    short = text
    if text.lower().startswith("mode") and len(text) > 4:
        short = "M" + text[4:]

    (tw, th), baseline = cv2.getTextSize(short, font, scale, thickness)

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
    # The per-mode videos already carry demo.py's corner labels
    # (add_bottom_right_labels), so draw_label is deliberately NOT called
    # here: a second "M0" badge would stack on top of "MODE 0 · SEG 1", the
    # overlapping-labels defect Riley flagged on 2026-05-04.
    # Author: Bloodawn (KheivenD), 2026-05-04 (split-screen label fix).
    #
    # Each frame is fitted straight into its cell of one preallocated
    # canvas; unused cells stay black.
    out = np.zeros((rows * cell_h, cols * cell_w, 3), dtype=np.uint8)
    for i, (_mode, frame) in enumerate(labeled_frames[:rows * cols]):
        r, c = divmod(i, cols)
        _fit_into(frame, out[r * cell_h:(r + 1) * cell_h, c * cell_w:(c + 1) * cell_w])
    return out


def _read_next(caps: list[tuple[str, cv2.VideoCapture]]) -> list[tuple[str, np.ndarray]] | None:
    """One frame from every capture, or None as soon as any of them runs out."""
    frames: list[tuple[str, np.ndarray]] = []
    for mode, cap in caps:
        ok, frame = cap.read()
        if not ok:
            return None
        frames.append((mode, frame))
    return frames


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

        current_frames: list[tuple[str, np.ndarray]] | None = []
        for mode, cap in caps:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError(f"Could not read first frame for mode '{mode}'")
            current_frames.append((mode, frame))

        output_path = stitched_dir / "demo_splitscreen.mp4"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        writer = H264Writer(str(output_path), fps, cols * cell_w, rows * cell_h)
        if not writer.isOpened():
            raise RuntimeError(f"Failed to open H264Writer for: {output_path}")

        try:
            while current_frames is not None:
                writer.write(build_composite_frame(current_frames, rows, cols, cell_w, cell_h))
                current_frames = _read_next(caps)
            return output_path
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
