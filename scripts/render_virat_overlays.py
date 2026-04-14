#!/usr/bin/env python3
"""Render VIRAT KPF overlays as preview videos.

This script can draw overlays on top of an existing video, or generate
annotation-only preview videos on a blank canvas when source media is absent.
"""

from __future__ import annotations

import argparse
import glob
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import yaml


@dataclass
class Detection:
    track_id: int
    frame_idx: int
    bbox: Tuple[int, int, int, int]


@dataclass
class Activity:
    label: str
    frame_start: int
    frame_end: int
    actor_ids: List[int]


def parse_bbox_g0(g0: str) -> Optional[Tuple[int, int, int, int]]:
    parts = [p for p in g0.strip().split() if p]
    if len(parts) < 4:
        return None
    try:
        x1, y1, x2, y2 = [int(float(v)) for v in parts[:4]]
    except ValueError:
        return None
    return x1, y1, x2, y2


def load_kpf_yaml(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, list) else []


def load_types(types_path: str) -> Dict[int, str]:
    rows = load_kpf_yaml(types_path)
    out: Dict[int, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload = row.get("types")
        if not isinstance(payload, dict):
            continue
        tid = payload.get("id1")
        cset3 = payload.get("cset3")
        if not isinstance(tid, int) or not isinstance(cset3, dict) or not cset3:
            continue
        label = max(cset3.items(), key=lambda kv: kv[1])[0]
        out[tid] = str(label)
    return out


def load_geometry(geom_path: str) -> Tuple[Dict[int, List[Detection]], int, Tuple[int, int]]:
    rows = load_kpf_yaml(geom_path)
    tracks: Dict[int, List[Detection]] = {}
    max_frame = 0
    width = 1920
    height = 1080

    for row in rows:
        if not isinstance(row, dict):
            continue

        # Read dimensions from metadata if available.
        meta = row.get("meta")
        if isinstance(meta, str) and "(" in meta and "x" in meta and "+" in meta:
            # Example: (... 1920x1080+0+0 )
            token = meta.split("(")[-1].split(")")[0].strip()
            wh = token.split("+")[0]
            if "x" in wh:
                try:
                    w_s, h_s = wh.split("x", 1)
                    width = int(w_s)
                    height = int(h_s)
                except ValueError:
                    pass

        payload = row.get("geom")
        if not isinstance(payload, dict):
            continue

        tid = payload.get("id1")
        frame_idx = payload.get("ts0")
        g0 = payload.get("g0")
        if not isinstance(tid, int) or not isinstance(frame_idx, int) or not isinstance(g0, str):
            continue

        bbox = parse_bbox_g0(g0)
        if bbox is None:
            continue

        max_frame = max(max_frame, frame_idx)
        tracks.setdefault(tid, []).append(Detection(track_id=tid, frame_idx=frame_idx, bbox=bbox))

    for tid in tracks:
        tracks[tid].sort(key=lambda d: d.frame_idx)

    return tracks, max_frame, (width, height)


def load_activities(activity_path: str) -> List[Activity]:
    rows = load_kpf_yaml(activity_path)
    activities: List[Activity] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload = row.get("act")
        if not isinstance(payload, dict):
            continue

        act2 = payload.get("act2")
        timespan = payload.get("timespan")
        actors = payload.get("actors", [])
        if not isinstance(act2, dict) or not isinstance(timespan, list) or not timespan:
            continue

        label = max(act2.items(), key=lambda kv: kv[1])[0]

        first_span = timespan[0].get("tsr0") if isinstance(timespan[0], dict) else None
        if not isinstance(first_span, list) or len(first_span) < 2:
            continue

        try:
            frame_start = int(first_span[0])
            frame_end = int(first_span[1])
        except (TypeError, ValueError):
            continue

        actor_ids: List[int] = []
        if isinstance(actors, list):
            for actor in actors:
                if not isinstance(actor, dict):
                    continue
                aid = actor.get("id1")
                if isinstance(aid, int):
                    actor_ids.append(aid)

        activities.append(
            Activity(
                label=str(label),
                frame_start=frame_start,
                frame_end=frame_end,
                actor_ids=actor_ids,
            )
        )

    return activities


def color_for_track(track_id: int) -> Tuple[int, int, int]:
    rng = np.random.default_rng(track_id)
    vals = rng.integers(64, 255, size=3)
    return int(vals[0]), int(vals[1]), int(vals[2])


def find_or_interpolate(det_list: List[Detection], frame_idx: int) -> Optional[Tuple[int, int, int, int]]:
    if not det_list:
        return None

    frames = [d.frame_idx for d in det_list]
    pos = np.searchsorted(frames, frame_idx)

    if pos < len(det_list) and det_list[pos].frame_idx == frame_idx:
        return det_list[pos].bbox

    if pos == 0 or pos >= len(det_list):
        return None

    d0 = det_list[pos - 1]
    d1 = det_list[pos]
    if d1.frame_idx == d0.frame_idx:
        return d0.bbox

    t = (frame_idx - d0.frame_idx) / float(d1.frame_idx - d0.frame_idx)
    x1 = int(round(d0.bbox[0] + t * (d1.bbox[0] - d0.bbox[0])))
    y1 = int(round(d0.bbox[1] + t * (d1.bbox[1] - d0.bbox[1])))
    x2 = int(round(d0.bbox[2] + t * (d1.bbox[2] - d0.bbox[2])))
    y2 = int(round(d0.bbox[3] + t * (d1.bbox[3] - d0.bbox[3])))
    return x1, y1, x2, y2


def parse_video_map(items: List[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for item in items:
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k and v:
            mapping[k] = v
    return mapping


def render_preview(
    clip_id: str,
    tracks: Dict[int, List[Detection]],
    type_map: Dict[int, str],
    activities: List[Activity],
    max_frame: int,
    base_size: Tuple[int, int],
    output_path: str,
    fps: int,
    frame_step: int,
    source_video: Optional[str],
) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    width, height = base_size
    cap = None
    use_video = False
    if source_video and os.path.exists(source_video):
        cap = cv2.VideoCapture(source_video)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if w > 0 and h > 0:
                width, height = w, h
            use_video = True
        else:
            cap = None

    fourcc = cv2.VideoWriter.fourcc(*"mp4v")
    writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    active_max = max_frame if max_frame > 0 else 1

    for frame_idx in range(0, active_max + 1, max(1, frame_step)):
        if use_video and cap is not None:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, frame = cap.read()
            if not ok or frame is None:
                frame = np.zeros((height, width, 3), dtype=np.uint8)
        else:
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            cv2.putText(
                frame,
                "Annotation-Only Preview (No Source Video)",
                (24, 38),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (180, 180, 180),
                2,
                cv2.LINE_AA,
            )

        active_labels: List[str] = []
        for activity in activities:
            if activity.frame_start <= frame_idx <= activity.frame_end:
                active_labels.append(activity.label)

        active_labels = list(dict.fromkeys(active_labels))
        label_text = ", ".join(active_labels[:3])
        if len(active_labels) > 3:
            label_text += f" (+{len(active_labels)-3})"

        cv2.rectangle(frame, (0, height - 70), (width, height), (16, 16, 16), -1)
        cv2.putText(
            frame,
            f"{clip_id} | frame={frame_idx} | active_acts={len(active_labels)}",
            (14, height - 44),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        if label_text:
            cv2.putText(
                frame,
                label_text,
                (14, height - 18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (180, 230, 255),
                1,
                cv2.LINE_AA,
            )

        for tid, det_list in tracks.items():
            bbox = find_or_interpolate(det_list, frame_idx)
            if bbox is None:
                continue

            x1, y1, x2, y2 = bbox
            x1 = max(0, min(width - 1, x1))
            y1 = max(0, min(height - 1, y1))
            x2 = max(0, min(width - 1, x2))
            y2 = max(0, min(height - 1, y2))
            if x2 <= x1 or y2 <= y1:
                continue

            color = color_for_track(tid)
            cls_name = type_map.get(tid, "Unknown")
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame,
                f"id:{tid} {cls_name}",
                (x1, max(16, y1 - 7)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                color,
                1,
                cv2.LINE_AA,
            )

        writer.write(frame)

    writer.release()
    if cap is not None:
        cap.release()


def main() -> None:
    parser = argparse.ArgumentParser(description="Render VIRAT KPF overlay preview videos")
    parser.add_argument(
        "--annotation-root",
        default="data/viratannotations-master",
        help="Root directory for VIRAT annotation files",
    )
    parser.add_argument(
        "--split",
        choices=["train", "validate", "all"],
        default="train",
        help="Which split to process",
    )
    parser.add_argument(
        "--out-dir",
        default="data/samples/virat_overlay_previews",
        help="Output folder for preview videos",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Max number of clips to render per run",
    )
    parser.add_argument("--fps", type=int, default=15, help="Output video fps")
    parser.add_argument(
        "--frame-step",
        type=int,
        default=10,
        help="Stride over frame numbers to keep render time manageable",
    )
    parser.add_argument(
        "--video-map",
        action="append",
        default=[],
        help="Optional clip mapping, e.g. VIRAT_S_000000=path/to/video.mp4",
    )
    args = parser.parse_args()

    splits = [args.split] if args.split != "all" else ["train", "validate"]
    clip_to_video = parse_video_map(args.video_map)

    rendered = 0
    for split in splits:
        split_dir = os.path.join(args.annotation_root, split)
        geom_files = sorted(glob.glob(os.path.join(split_dir, "*.geom.yml")))
        if not geom_files:
            print(f"No geometry files found in {split_dir}")
            continue

        for geom_file in geom_files:
            if args.limit > 0 and rendered >= args.limit:
                break

            clip_id = os.path.basename(geom_file).replace(".geom.yml", "")
            types_file = geom_file.replace(".geom.yml", ".types.yml")
            acts_file = geom_file.replace(".geom.yml", ".activities.yml")
            if not os.path.exists(types_file) or not os.path.exists(acts_file):
                continue

            tracks, max_frame, base_size = load_geometry(geom_file)
            if not tracks:
                continue

            type_map = load_types(types_file)
            activities = load_activities(acts_file)

            out_name = f"{split}_{clip_id}_overlay_preview.mp4"
            out_path = os.path.join(args.out_dir, out_name)
            src_video = clip_to_video.get(clip_id)

            render_preview(
                clip_id=clip_id,
                tracks=tracks,
                type_map=type_map,
                activities=activities,
                max_frame=max_frame,
                base_size=base_size,
                output_path=out_path,
                fps=args.fps,
                frame_step=args.frame_step,
                source_video=src_video,
            )

            rendered += 1
            src_note = src_video if src_video else "<annotation-only>"
            print(f"Rendered {out_path} from {clip_id} source={src_note}")

        if args.limit > 0 and rendered >= args.limit:
            break

    print(f"Done. Rendered {rendered} preview videos.")


if __name__ == "__main__":
    main()
