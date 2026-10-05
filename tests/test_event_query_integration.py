import json

import numpy as np

from pipeline.pipeline import run_pipeline
from utils.db import initialize_database
from utils.event_log import read_recent
from gui.services.nl_query import search


class DummyFrameSource:
    """Small deterministic frame source for the integration test."""

    def __init__(self, frames, fps=10.0, width=16, height=16):
        self.frames = frames
        self.index = 0
        self.fps = fps
        self.width = width
        self.height = height

    def read(self):
        if self.index < len(self.frames):
            frame = self.frames[self.index]
            self.index += 1
            return True, frame
        return False, None

    def release(self):
        pass

    def get_warmup_frames(self, fallback):
        return 0


class DummyRegion:
    """Foreground region whose center moves across the event line."""

    def __init__(self, x, y, w=4, h=4):
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    def to_tuple(self):
        return (self.x, self.y, self.w, self.h)


class CrossingSubtractor:
    """Produces one region that crosses y=0.5 in normalized coordinates."""

    def __init__(self, *args, **kwargs):
        self.index = 0

        self.regions = [
            DummyRegion(6, 4),
            DummyRegion(6, 10),
        ]

    def apply(self, frame):
        return np.zeros(
            (frame.shape[0], frame.shape[1]),
            dtype=np.uint8,
        )

    def get_foreground_regions(self, mask):
        region = self.regions[min(self.index, len(self.regions) - 1)]
        self.index += 1
        return [region]

    def draw_regions(self, frame, regions):
        return frame


class IntegrationEncoder:
    """Minimal encoder that writes the segment metadata to SQLite."""

    def __init__(self, *args, **kwargs):
        self.db_path = kwargs.get("db_path")
        self.camera_id = "cam_event_test"
        self.frames = 0

    def begin_segment(
        self,
        frame_shape,
        fps,
        camera_id="cam_unknown",
        has_targets=True,
        object_type="unknown",
        source_path=None,
        **kwargs,
    ):
        self.camera_id = camera_id

    def write_frame(self, *args, **kwargs):
        self.frames += 1

    def abort_segment(self):
        pass

    def finish_segment(
        self,
        timeout=30.0,
        object_classes=None,
        dominant_color=None,
        scene_type="unknown",
        time_of_day=None,
        vehicle_count=0,
        person_count=0,
        **kwargs,
    ):
        from utils.db import insert_segment

        insert_segment(
            timestamp="20261004T190000Z",
            camera_id=self.camera_id,
            target_detected=True,
            roi_count=self.frames,
            file_size=1234,
            duration=0.2,
            file_path="event_segment.mp4",
            object_classes=json.dumps(["person"]),
            dominant_color=dominant_color or "red",
            scene_type=scene_type or "street",
            time_of_day=time_of_day or "night",
            vehicle_count=vehicle_count,
            person_count=person_count or 1,
            db_path=self.db_path,
        )

        return {
            "file_path": "event_segment.mp4",
            "avg_sharpness": None,
            "sharpness_label": None,
        }

    def get_storage_report(self):
        return {"total_segments": 1}


def test_pipeline_event_is_retrievable_by_query(
    monkeypatch,
    tmp_path,
):
    """A pipeline run produces an event and a query retrieves its segment."""

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    db_path = output_dir / "metadata.db"
    initialize_database(db_path)

    zones_path = tmp_path / "zones_config.json"
    zones_path.write_text(
        json.dumps(
            {
                "cam_event_test": {
                    "exclude": [],
                    "lines": [
                        {
                            "id": "gate",
                            "line": [0.0, 0.5, 1.0, 0.5],
                        }
                    ],
                    "zones": [],
                    "loiter_s": 30.0,
                    "class_filter": [],
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "utils.zones_config.state_file",
        lambda filename: zones_path,
    )

    frames = [
        np.zeros((16, 16, 3), dtype=np.uint8)
        for _ in range(2)
    ]

    monkeypatch.setattr(
        "pipeline.pipeline.FrameSource",
        lambda *_args, **_kwargs: DummyFrameSource(
            frames,
            fps=10.0,
            width=16,
            height=16,
        ),
    )

    monkeypatch.setattr(
        "pipeline.pipeline.BackgroundSubtractor",
        CrossingSubtractor,
    )

    monkeypatch.setattr(
        "pipeline.pipeline.ROIEncoder",
        lambda *args, **kwargs: IntegrationEncoder(
            **kwargs,
        ),
    )

    monkeypatch.setattr(
        "pipeline.pipeline.initialize_database",
        lambda *_args, **_kwargs: initialize_database(db_path),
    )

    run_pipeline(
        input_source="dummy",
        camera_id="cam_event_test",
        output_dir=output_dir,
        segment_seconds=1.0,
        mode="mode0",
        warmup_frames=0,
    )

    events = read_recent(output_dir, limit=10)

    assert len(events) == 1
    assert events[0]["kind"] == "line_crossing"
    assert events[0]["geometry_id"] == "gate"
    assert events[0]["camera_id"] == "cam_event_test"

    results = search(
        "event_segment.mp4",
        db_path=db_path,
    )

    assert results["count"] == 1
    assert results["segments"][0]["camera_id"] == "cam_event_test"
    assert results["segments"][0]["file_path"] == "event_segment.mp4"
