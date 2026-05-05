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
import json
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
    draw_tint: bool = True,
) -> np.ndarray:
    """
    Option A:
      - dim/tint the background
      - keep ROI areas mostly normal with a very light green emphasis

    This keeps the scene readable while making the detected foreground pop.
    """
    if not draw_tint:
        out = frame.copy()
        h, w = out.shape[:2]
        if draw_boxes:
            for bbox in regions:
                if len(bbox) != 4:
                    continue
                clipped = clip_bbox(bbox[0], bbox[1], bbox[2], bbox[3], w, h)
                if clipped is not None:
                    x1, y1, x2, y2 = clipped
                    cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)
        return out

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

        out[y1:y2, x1:x2] = roi

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



def draw_region_boxes(frame: np.ndarray, regions: List[List[int]]) -> np.ndarray:
    """
    Draw ROI boxes from JSONL metadata without applying any tint.
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


def format_metric_value(value: object, suffix: str = "") -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.1f}{suffix}"
    return f"{value}{suffix}"


def format_compression_ratio(value: object) -> str:
    if value is None:
        return "N/A"
    if value == float("inf"):
        return "inf"
    return f"{float(value):.2f}x"


def format_storage_change(space_saved_pct: object) -> str:
    if space_saved_pct is None:
        return "N/A"
    saved = float(space_saved_pct)
    if saved < 0:
        return f"{abs(saved):.1f}% larger"
    return f"{saved:.1f}% saved"


def make_metrics_card(
    width: int,
    height: int,
    *,
    mode: str,
    metrics: dict,
    frame_count: int,
) -> List[np.ndarray]:
    """
    Create repeated end-card frames summarizing per-mode demo metrics.
    """
    if frame_count <= 0:
        return []

    cpu = metrics.get("cpu") or {}
    latency = metrics.get("latency_ms")
    latency_text = "N/A for file demo" if latency is None else format_metric_value(latency, " ms")

    lines = [
        f"{mode.upper()} METRICS",
        f"Compression ratio: {format_compression_ratio(metrics.get('compression_ratio'))}",
        f"Storage change: {format_storage_change(metrics.get('space_saved_pct'))}",
        f"Original size: {format_metric_value(metrics.get('original_mb'), ' MB')}",
        f"Compressed size: {format_metric_value(metrics.get('compressed_mb'), ' MB')}",
        f"CPU cores used: {format_metric_value(cpu.get('cpu_core_equivalent'), '')} avg",
        f"CPU time: {format_metric_value(cpu.get('cpu_seconds'), 's')}",
        f"Pipeline wall time: {format_metric_value(cpu.get('wall_seconds'), 's')}",
        f"Latency: {latency_text}",
    ]

    frames: List[np.ndarray] = []
    font = cv2.FONT_HERSHEY_SIMPLEX
    title_scale = max(0.85, min(width, height) / 520)
    body_scale = max(0.52, min(width, height) / 820)
    title_thickness = 2
    body_thickness = 1 if min(width, height) < 520 else 2
    start_y = max(46, int(height * 0.18))
    available_h = max(24, height - start_y - 24)
    spacing = max(20, min(max(28, int(height * 0.07)), available_h // max(1, len(lines) - 1)))

    for _ in range(frame_count):
        img = np.zeros((height, width, 3), dtype=np.uint8)
        cv2.rectangle(img, (0, 0), (width, height), (18, 24, 21), -1)
        cv2.rectangle(img, (0, 0), (width, max(8, height // 44)), (0, 180, 90), -1)

        for idx, line in enumerate(lines):
            is_title = idx == 0
            scale = title_scale if is_title else body_scale
            thickness = title_thickness if is_title else body_thickness
            color = (120, 255, 175) if is_title else (238, 246, 240)
            (tw, th), _ = cv2.getTextSize(line, font, scale, thickness)
            x = max(18, (width - tw) // 2 if is_title else int(width * 0.12))
            y = start_y + idx * spacing
            cv2.putText(img, line, (x, y), font, scale, color, thickness, cv2.LINE_AA)

        frames.append(img)

    return frames



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


def load_sparse_mode3_metadata(path: str | Path) -> tuple[Path, dict] | None:
    """
    Load a mode3 sparse artifact metadata file.

    New mode3 segments store metadata.json directly in the DB. Older sparse
    artifacts may point at preview.mp4, with metadata.json beside it.
    """
    p = Path(path)
    metadata_path = p if p.name == "metadata.json" else p.parent / "metadata.json"
    if not metadata_path.exists():
        return None

    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    if metadata.get("mode") != "mode3":
        return None
    return metadata_path.parent, metadata


def build_sparse_frame_lookup(metadata: dict) -> dict[int, dict]:
    return {
        int(frame_record["source_frame_index"]): frame_record
        for frame_record in metadata.get("frames", [])
    }


def render_sparse_mode3_frame(
    artifact_dir: Path,
    metadata: dict,
    frame_record: dict | None,
    image_cache: dict[Path, np.ndarray] | None = None,
) -> np.ndarray:
    """
    Reconstruct a visual frame from mode3 sparse crops for demo playback.
    """
    width = int(metadata["frame_width"])
    height = int(metadata["frame_height"])
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    if not frame_record:
        return canvas

    for obj in frame_record.get("objects", []):
        bbox = obj.get("bbox", [])
        if len(bbox) != 4:
            continue
        x, y, w, h = [int(v) for v in bbox]
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(width, x + max(0, w))
        y2 = min(height, y + max(0, h))
        if x2 <= x1 or y2 <= y1:
            continue

        crop_path = (artifact_dir / obj["crop_path"]).resolve()
        if image_cache is not None and crop_path in image_cache:
            crop = image_cache[crop_path]
        else:
            crop = cv2.imread(str(crop_path), cv2.IMREAD_COLOR)
            if image_cache is not None and crop is not None:
                image_cache[crop_path] = crop
        if crop is None:
            continue
        if crop.shape[1] != (x2 - x1) or crop.shape[0] != (y2 - y1):
            crop = cv2.resize(crop, (x2 - x1, y2 - y1))

        mask_path = obj.get("mask_path")
        if mask_path:
            resolved_mask_path = (artifact_dir / mask_path).resolve()
            if image_cache is not None and resolved_mask_path in image_cache:
                mask = image_cache[resolved_mask_path]
            else:
                mask = cv2.imread(str(resolved_mask_path), cv2.IMREAD_GRAYSCALE)
                if image_cache is not None and mask is not None:
                    image_cache[resolved_mask_path] = mask
            if mask is not None:
                if mask.shape[1] != (x2 - x1) or mask.shape[0] != (y2 - y1):
                    mask = cv2.resize(mask, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)
                roi = canvas[y1:y2, x1:x2]
                roi[mask > 0] = crop[mask > 0]
                continue

        canvas[y1:y2, x1:x2] = crop

    return canvas



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
    draw_tint: bool,
) -> np.ndarray:
    if view == "roi_tint" or draw_tint:
        return build_roi_focus_frame(
            frame,
            regions,
            draw_boxes=draw_boxes,
            draw_tint=draw_tint,
        )

    if draw_boxes:
        return draw_region_boxes(frame, regions)

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
    draw_tint: bool = True,
    metrics: dict | None = None,
    metrics_screen_seconds: float = 4.0,
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
    first_sparse = load_sparse_mode3_metadata(first_path)
    if first_sparse is not None:
        _, first_sparse_metadata = first_sparse
        width = int(first_sparse_metadata["frame_width"])
        height = int(first_sparse_metadata["frame_height"])
        fps = fps_override or float(first_sparse_metadata.get("fps") or 30.0)
    else:
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

            sparse = load_sparse_mode3_metadata(segment_path)
            cap = None
            sparse_artifact_dir = None
            sparse_metadata = None
            sparse_frames = None
            sparse_image_cache = None
            if sparse is not None:
                sparse_artifact_dir, sparse_metadata = sparse
                sparse_frames = build_sparse_frame_lookup(sparse_metadata)
                sparse_image_cache = {}
            else:
                cap = cv2.VideoCapture(segment_path)
                if not cap.isOpened():
                    raise RuntimeError(f"Could not open segment video: {segment_path}")

            try:
                for record in segment_records:
                    if sparse_metadata is not None:
                        frame = render_sparse_mode3_frame(
                            sparse_artifact_dir,
                            sparse_metadata,
                            sparse_frames.get(int(record["source_frame_index"])) if sparse_frames else None,
                            sparse_image_cache,
                        )
                    else:
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
                        draw_tint=draw_tint,
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
                if cap is not None:
                    cap.release()

        if metrics is not None and metrics_screen_seconds > 0:
            metric_frames = make_metrics_card(
                width,
                height,
                mode=str(metrics.get("mode") or records[0].get("mode") or "mode"),
                metrics=metrics,
                frame_count=max(1, int(round(metrics_screen_seconds * fps))),
            )
            for metric_frame in metric_frames:
                writer.write(metric_frame)

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
    parser.add_argument(
        "--no-tint",
        action="store_true",
        help="Disable ROI tinting in the rendered view.",
    )
    parser.add_argument(
        "--metrics-json",
        default=None,
        help="Optional JSON file containing metrics to append as an end card.",
    )
    parser.add_argument(
        "--metrics-screen-seconds",
        type=float,
        default=4.0,
        help="Duration of the metrics end card when --metrics-json is provided.",
    )

    args = parser.parse_args()
    metrics = None
    if args.metrics_json:
        import json

        with open(args.metrics_json, "r", encoding="utf-8") as f:
            metrics = json.load(f)

    out = render_demo(
        db_path=args.db,
        metadata_path=args.metadata,
        output_path=args.output,
        fps_override=args.fps,
        min_black_skip_seconds=args.min_black_skip,
        view=args.view,
        draw_boxes=not args.no_boxes,
        draw_tint=not args.no_tint,
        metrics=metrics,
        metrics_screen_seconds=args.metrics_screen_seconds,
    )
    print(f"Saved demo video: {out}")
