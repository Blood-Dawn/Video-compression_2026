"""
demo_metadata.py

Per-frame demo sidecar metadata for sponsor/demo rendering.

Writes one JSONL record per kept output frame so later demo tools can:
- reconstruct source timeline
- label frames with source time
- show segment membership
- draw ROI overlays from stored bounding boxes

Each line in the output file is one JSON object.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List


def _normalize_regions(regions: Iterable[object]) -> List[list]:
    """
    Convert a list of region objects or tuples into plain JSON-safe bbox lists.

    Supported inputs:
    - objects with .to_tuple() -> (x, y, w, h)
    - tuples/lists already shaped like (x, y, w, h)
    """
    out: List[list] = []

    for region in regions:
        if hasattr(region, "to_tuple"):
            bbox = region.to_tuple()
        else:
            bbox = region

        out.append([int(v) for v in bbox])

    return out


class DemoMetadataWriter:
    """
    Appends one JSONL record per kept frame.

    Example record:
    {
        "source_frame_index": 183,
        "source_time_seconds": 7.32,
        "mode": "mode1",
        "segment_index": 0,
        "frame_index_within_segment": 41,
        "regions": [[x, y, w, h], ...]
    }
    """

    def __init__(self, output_path: str | Path):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.output_path.open("w", encoding="utf-8")

    def write_record(
        self,
        *,
        source_frame_index: int,
        source_time_seconds: float,
        mode: str,
        segment_index: int,
        frame_index_within_segment: int,
        regions: Iterable[object],
    ) -> None:
        record = {
            "source_frame_index": int(source_frame_index),
            "source_time_seconds": float(source_time_seconds),
            "mode": str(mode),
            "segment_index": int(segment_index),
            "frame_index_within_segment": int(frame_index_within_segment),
            "regions": _normalize_regions(regions),
        }
        self._fh.write(json.dumps(record) + "\n")

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> "DemoMetadataWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def load_demo_metadata(path: str | Path) -> list[dict]:
    """
    Load a JSONL sidecar into memory.
    """
    records: list[dict] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records