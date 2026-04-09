"""
demo.py

Renders annotated demo videos from pipeline outputs.

This script takes:
- metadata.db (segment index + file paths)
- JSONL metadata (frame-level ROI + timestamps)

and reconstructs a clean, human-readable video showing:
- ROI bounding boxes
- Optional ROI tinting
- Time, mode, and segment labels
- Frame skipping visualization (for sparse modes like mode1)

------------------------------------------------------------
WHAT THIS DOES:

- Replays compressed segments in chronological order
- Aligns frames using source timestamps
- Handles missing frames (mode1) by:
    - Holding previous frames (small gaps)
    - Rendering skip cards (large gaps)
- Overlays useful debug/demo information

------------------------------------------------------------
USAGE:

Basic:
    python -m src.demo.demo \
        --db outputs/demo_mode0/metadata.db \
        --metadata outputs/demo_mode0/cam_test_mode0_demo_frames.jsonl \
        --output outputs/demos_stitched/mode0_demo.mp4

ROI-tinted view:
    python -m src.demo.demo \
        --db outputs/demo_mode0/metadata.db \
        --metadata outputs/demo_mode0/cam_test_mode0_demo_frames.jsonl \
        --output outputs/demos_stitched/mode0_demo_roi.mp4 \
        --view roi_tint

Disable bounding boxes:
    python -m src.demo.demo \
        --db ... \
        --metadata ... \
        --output ... \
        --no-boxes

------------------------------------------------------------
NOTES:

- This does NOT recompress video — it only reads existing segments.
- Frame timing is reconstructed from source timestamps.
- Designed for demo/visualization, not benchmarking.
- Benchmarking should use raw segment sizes from metadata.db instead.
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import cv2
import numpy as np

from src.demo.demo_metadata import load_demo_metadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def format_time_hhmmss(seconds: float) -> str:
    """
    Format seconds as HH:MM:SS.mmm
    """
    total_ms = int(round(seconds * 1000))
    hours = total_ms // 3_600_000
    total_ms %= 3_600_000
    minutes = total_ms // 60_000
    total_ms %= 60_000
    secs = total_ms // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"



def add_bottom_right_labels(
    frame: np.ndarray,
    *,
    time_text: str,
    mode: str,
    segment_index: int,
    view: str,
) -> np.ndarray:
    """
    Draw bottom-right stacked labels.
    """
    out = frame.copy()
    h, w = out.shape[:2]

    lines = [
        f"TIME: {time_text}",
        f"MODE: {mode}",
        f"SEGMENT: {segment_index + 1}",
        f"VIEW: {view.upper()}",
    ]

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.65
    thickness = 2
    line_height = 28
    padding = 12

    sizes = [cv2.getTextSize(line, font, font_scale, thickness)[0] for line in lines]
    box_w = max(size[0] for size in sizes) + 2 * padding
    box_h = len(lines) * line_height + 2 * padding

    x1 = w - box_w - 16
    y1 = h - box_h - 16
    x2 = w - 16
    y2 = h - 16

    overlay = out.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 0, 0), -1)
    out = cv2.addWeighted(overlay, 0.55, out, 0.45, 0)

    y = y1 + padding + 18
    for line in lines:
        cv2.putText(out, line, (x1 + padding, y), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
        y += line_height

    return out



def clip_bbox(x: int, y: int, w: int, h: int, frame_w: int, frame_h: int) -> Tuple[int, int, int, int] | None:
    """
    Clip bbox coordinates to frame bounds and return (x1, y1, x2, y2).
    """
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(frame_w, x + max(0, w))
    y2 = min(frame_h, y + max(0, h))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2



def build_roi_focus_frame(
    frame: np.ndarray,
    regions: List[List[int]],
    *,
    background_dim_alpha: float = 0.45,
    background_tint_strength: float = 0.08,
    roi_green_tint_strength: float = 0.12,
    draw_boxes: bool = True,
) -> np.ndarray:
    """
    Option A:
      - dim/tint the background
      - keep ROI areas mostly normal with a very light green emphasis

    This keeps the scene readable while making the detected foreground pop.
    """
    out = frame.copy()
    h, w = out.shape[:2]

    # Inspired by demo_detection.py's easy-to-read green foreground treatment:
    # the background is dimmed globally, then ROI regions are restored and given
    # a subtle green emphasis instead of being heavily stylized.
    darkened = (frame.astype(np.float32) * background_dim_alpha).clip(0, 255).astype(np.uint8)
    bg_tint = np.full_like(frame, (20, 28, 20), dtype=np.uint8)
    out = cv2.addWeighted(darkened, 1.0 - background_tint_strength, bg_tint, background_tint_strength, 0)

    for bbox in regions:
        if len(bbox) != 4:
            continue
        clipped = clip_bbox(bbox[0], bbox[1], bbox[2], bbox[3], w, h)
        if clipped is None:
            continue

        x1, y1, x2, y2 = clipped
        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            continue

        roi_green = np.zeros_like(roi)
        roi_green[:, :] = (0, 55, 0)
        restored_roi = cv2.addWeighted(roi, 1.0 - roi_green_tint_strength, roi_green, roi_green_tint_strength, 0)
        out[y1:y2, x1:x2] = restored_roi

        if draw_boxes:
            cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)

    return out



def draw_regions(frame: np.ndarray, regions: List[List[int]]) -> np.ndarray:
    """
    Draw ROI boxes from JSONL metadata.
    Each region is [x, y, w, h].
    """
    out = frame.copy()
    h, w = out.shape[:2]

    for bbox in regions:
        if len(bbox) != 4:
            continue

        clipped = clip_bbox(bbox[0], bbox[1], bbox[2], bbox[3], w, h)
        if clipped is None:
            continue

        x1, y1, x2, y2 = clipped
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)

        roi = out[y1:y2, x1:x2]
        if roi.size > 0:
            tint = np.zeros_like(roi)
            tint[:, :] = (0, 60, 0)
            out[y1:y2, x1:x2] = cv2.addWeighted(roi, 0.8, tint, 0.2, 0)

    return out



def make_skip_card(
    width: int,
    height: int,
    *,
    mode: str,
    skip_seconds: float,
    next_time_seconds: float,
    frame_count: int,
) -> List[np.ndarray]:
    """
    Create black placeholder frames for a measured number of skipped frames.
    """
    if frame_count <= 0:
        return []

    frames: List[np.ndarray] = []

    text_lines = [
        f"MODE: {mode}",
        f"SKIP -> {skip_seconds:.2f}s",
        f"NEXT TIME: {format_time_hhmmss(next_time_seconds)}",
    ]

    for _ in range(frame_count):
        img = np.zeros((height, width, 3), dtype=np.uint8)

        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.9
        thickness = 2
        spacing = 40

        sizes = [cv2.getTextSize(line, font, font_scale, thickness)[0] for line in text_lines]
        total_h = len(text_lines) * spacing
        start_y = (height // 2) - (total_h // 2)

        for i, line in enumerate(text_lines):
            tw, th = sizes[i]
            x = (width - tw) // 2
            y = start_y + i * spacing
            cv2.putText(img, line, (x, y), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)

        frames.append(img)

    return frames



def make_hold_frames(previous_frame: np.ndarray, frame_count: int) -> List[np.ndarray]:
    """
    Duplicate the previous rendered frame for a measured number of missing frames.
    This preserves timeline alignment without flashing to black.
    """
    if frame_count <= 0:
        return []

    return [previous_frame.copy() for _ in range(frame_count)]



def load_segment_rows(db_path: str | Path, mode_records: List[dict]) -> List[Tuple[int, str]]:
    """
    Load segment file paths from metadata.db in chronological order.

    Returns:
        List of (segment_index, file_path)
    """
    if not mode_records:
        return []

    max_segment_index = max(r["segment_index"] for r in mode_records)

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            """
            SELECT timestamp, file_path
            FROM segments
            ORDER BY timestamp ASC
            """
        ).fetchall()
    finally:
        conn.close()

    needed = rows[: max_segment_index + 1]
    return [(i, file_path) for i, (_, file_path) in enumerate(needed)]



def compute_missing_frame_count(
    previous_time: float,
    current_time: float,
    fps: float,
) -> Tuple[int, float]:
    """
    Convert a source-time gap into an integer number of missing frames.
    """
    gap_seconds = current_time - previous_time
    if gap_seconds <= 0:
        return 0, 0.0

    gap_frames = gap_seconds * fps
    missing_frames = max(0, int(round(gap_frames)) - 1)
    skip_seconds = missing_frames / fps if missing_frames > 0 else 0.0
    return missing_frames, skip_seconds



def render_view(
    frame: np.ndarray,
    regions: List[List[int]],
    *,
    view: str,
    draw_boxes: bool,
) -> np.ndarray:
    if view == "roi_tint":
        return build_roi_focus_frame(frame, regions, draw_boxes=draw_boxes)

    if draw_boxes:
        return draw_regions(frame, regions)

    return frame.copy()


# ---------------------------------------------------------------------------
# Core render
# ---------------------------------------------------------------------------


def render_demo(
    *,
    db_path: str,
    metadata_path: str,
    output_path: str,
    fps_override: float | None = None,
    min_black_skip_seconds: float = 0.25,
    view: str = "standard",
    draw_boxes: bool = True,
) -> str:
    """
    Render one stitched annotated demo video from segment DB + JSONL sidecar.
    """
    records = load_demo_metadata(metadata_path)
    if not records:
        raise ValueError(f"No records found in metadata sidecar: {metadata_path}")

    records_by_segment: Dict[int, List[dict]] = defaultdict(list)
    for record in records:
        records_by_segment[record["segment_index"]].append(record)

    for seg_records in records_by_segment.values():
        seg_records.sort(key=lambda r: r["frame_index_within_segment"])

    segment_rows = load_segment_rows(db_path, records)
    if not segment_rows:
        raise ValueError(f"No usable segment rows found in DB: {db_path}")

    first_path = segment_rows[0][1]
    probe = cv2.VideoCapture(first_path)
    if not probe.isOpened():
        raise RuntimeError(f"Could not open segment video: {first_path}")

    width = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = fps_override or probe.get(cv2.CAP_PROP_FPS) or 30.0
    probe.release()

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        output_path,
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"Could not open output writer: {output_path}")

    try:
        previous_time = None
        previous_rendered_frame = None

        for segment_index, segment_path in segment_rows:
            segment_records = records_by_segment.get(segment_index, [])
            if not segment_records:
                continue

            cap = cv2.VideoCapture(segment_path)
            if not cap.isOpened():
                raise RuntimeError(f"Could not open segment video: {segment_path}")

            try:
                for record in segment_records:
                    ok, frame = cap.read()
                    if not ok:
                        raise RuntimeError(
                            f"Segment video ended early while reading {segment_path} "
                            f"for segment_index={segment_index}"
                        )

                    current_time = record["source_time_seconds"]

                    if previous_time is not None:
                        missing_frames, skip_seconds = compute_missing_frame_count(
                            previous_time=previous_time,
                            current_time=current_time,
                            fps=fps,
                        )

                        if missing_frames > 0:
                            if skip_seconds < min_black_skip_seconds and previous_rendered_frame is not None:
                                hold_frames = make_hold_frames(previous_rendered_frame, missing_frames)
                                for hold_frame in hold_frames:
                                    writer.write(hold_frame)
                            else:
                                skip_frames = make_skip_card(
                                    width,
                                    height,
                                    mode=record["mode"],
                                    skip_seconds=skip_seconds,
                                    next_time_seconds=current_time,
                                    frame_count=missing_frames,
                                )
                                for skip_frame in skip_frames:
                                    writer.write(skip_frame)

                    rendered = render_view(
                        frame,
                        record["regions"],
                        view=view,
                        draw_boxes=draw_boxes,
                    )
                    rendered = add_bottom_right_labels(
                        rendered,
                        time_text=format_time_hhmmss(current_time),
                        mode=record["mode"],
                        segment_index=record["segment_index"],
                        view=view,
                    )

                    writer.write(rendered)
                    previous_time = current_time
                    previous_rendered_frame = rendered

            finally:
                cap.release()

    finally:
        writer.release()

    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Render a stitched single-mode demo video")
    parser.add_argument("--db", required=True, help="Path to metadata.db")
    parser.add_argument("--metadata", required=True, help="Path to demo JSONL sidecar")
    parser.add_argument("--output", required=True, help="Path to stitched demo mp4")
    parser.add_argument("--fps", type=float, default=None, help="Optional FPS override for output video")
    parser.add_argument(
        "--min-black-skip",
        type=float,
        default=0.25,
        help="Minimum skip duration in seconds before rendering a black skip card. Smaller gaps are filled by holding the previous frame.",
    )
    parser.add_argument(
        "--view",
        choices=["standard", "roi_tint"],
        default="standard",
        help="Render style for annotated frames.",
    )
    parser.add_argument(
        "--no-boxes",
        action="store_true",
        help="Disable ROI bounding boxes in the rendered view.",
    )

    args = parser.parse_args()

    out = render_demo(
        db_path=args.db,
        metadata_path=args.metadata,
        output_path=args.output,
        fps_override=args.fps,
        min_black_skip_seconds=args.min_black_skip,
        view=args.view,
        draw_boxes=not args.no_boxes,
    )
    print(f"Saved demo video: {out}")
