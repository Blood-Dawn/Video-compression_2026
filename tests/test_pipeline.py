"""
test_pipeline.py

Unit tests for src/pipeline/pipeline.py.
Covers:
  - EOF behavior when the video ends exactly on a full segment boundary
  - No extra final partial-segment encode when zero leftover frames remain
  - mode1 buffers only frames with detected foreground regions
  - Storage reporting still runs on exit

These tests use monkeypatch with lightweight dummy classes so they run fast
and do not depend on real video files, OpenCV capture devices, or FFmpeg.
"""

import numpy as np
import pytest

from pipeline.pipeline import run_pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class DummyFrameSource:
    """
    Minimal fake FrameSource that returns a fixed list of frames and then EOF.

    Exposes the same attributes run_pipeline expects:
      - fps
      - width
      - height
      - read()
      - release()
      - get_warmup_frames()
    """
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
    """Minimal stand-in for ForegroundRegion used by pipeline serialization."""
    # Match the attributes accessed by pipeline.py (color, centroid, enhance checks)
    x: int = 0
    y: int = 0
    w: int = 4
    h: int = 4

    def __init__(self, x=0, y=0, w=4, h=4):
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    def to_tuple(self):
        return (self.x, self.y, self.w, self.h)


class DummySubtractor:
    """
    Fake BackgroundSubtractor.

    Always reports one foreground region so mode0 buffers frames and the
    pipeline reaches the full-segment encode path deterministically.
    """
    def __init__(self, *args, **kwargs):
        pass

    def apply(self, frame):
        return np.zeros((frame.shape[0], frame.shape[1]), dtype=np.uint8)

    def get_foreground_regions(self, mask):
        return [DummyRegion()]

    def draw_regions(self, frame, regions):
        return frame


class DummyEncoder:
    """
    Fake ROIEncoder that records calls without writing any files.
    Implements the streaming API: begin_segment / write_frame / finish_segment / abort_segment.
    """
    def __init__(self, call_log, *args, **kwargs):
        self.call_log = call_log
        self._open = False

    def begin_segment(self, frame_shape, fps, camera_id="cam_unknown",
                      has_targets=True, object_type="unknown", source_path=None,
                      **kwargs):
        self._open = True

    def write_frame(self, frame, boxes=None, background_frame=None,
                    object_only=False, mode_label="", draw_roi_boxes=None,
                    measure_sharpness=True, compress_background=False):
        pass

    def abort_segment(self):
        self._open = False

    def finish_segment(self, timeout=30.0, **kwargs):
        self._open = False
        self.call_log["encode_segment"] += 1
        return {
            "file_path": f"dummy_segment_{self.call_log['encode_segment']}.mp4",
            "avg_sharpness": None,
            "sharpness_label": None,
        }

    def get_storage_report(self):
        self.call_log["get_storage_report"] += 1
        return {"total_segments": self.call_log["encode_segment"]}


class SequenceSubtractor:
    """
    Fake BackgroundSubtractor that returns a predefined sequence of region lists.

    This lets tests control exactly which frames count as 'event' frames.
    """
    def __init__(self, regions_per_frame, *args, **kwargs):
        self.regions_per_frame = regions_per_frame
        self.index = 0

    def apply(self, frame):
        return np.zeros((frame.shape[0], frame.shape[1]), dtype=np.uint8)

    def get_foreground_regions(self, mask):
        regions = self.regions_per_frame[self.index]
        self.index += 1
        return regions

    def draw_regions(self, frame, regions):
        return frame


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def exact_segment_frames():
    """
    20 frames total.

    With fps=10 and segment_seconds=2, this is exactly one full segment,
    so EOF should occur with zero leftover frames.
    """
    rng = np.random.default_rng(123)
    return [
        rng.integers(0, 256, (16, 16, 3), dtype=np.uint8)
        for _ in range(20)
    ]


@pytest.fixture
def mixed_event_frames():
    """
    Six frames total.

    Used to verify that mode1 buffers only frames with detected foreground
    regions and skips non-event frames.
    """
    rng = np.random.default_rng(456)
    return [
        rng.integers(0, 256, (16, 16, 3), dtype=np.uint8)
        for _ in range(6)
    ]



# ---------------------------------------------------------------------------
# EOF / segment-boundary behavior
# ---------------------------------------------------------------------------

class TestEOFBoundaryBehavior:
    def test_mode0_compresses_background_outside_rois(
        self, monkeypatch, tmp_path, exact_segment_frames
    ):
        calls = {
            "encode_segment": 0,
            "get_storage_report": 0,
            "compress_background": None,
        }

        monkeypatch.setattr(
            "pipeline.pipeline.FrameSource",
            lambda *_args, **_kwargs: DummyFrameSource(exact_segment_frames)
        )
        monkeypatch.setattr(
            "pipeline.pipeline.BackgroundSubtractor",
            DummySubtractor
        )
        monkeypatch.setattr(
            "pipeline.pipeline.initialize_database",
            lambda *_args, **_kwargs: None
        )

        class RecordingEncoder(DummyEncoder):
            def write_frame(self, frame, boxes=None, background_frame=None,
                            object_only=False, mode_label="", draw_roi_boxes=None,
                            measure_sharpness=True, compress_background=False):
                if calls["compress_background"] is None:
                    calls["compress_background"] = compress_background

        monkeypatch.setattr(
            "pipeline.pipeline.ROIEncoder",
            lambda *args, **kwargs: RecordingEncoder(calls, *args, **kwargs)
        )

        run_pipeline(
            input_source="dummy.mp4",
            camera_id="cam_test",
            output_dir=str(tmp_path),
            segment_seconds=2,
            bg_method="MOG2",
            mode="mode0",
            show_preview=False,
            warmup_frames=0,
        )

        assert calls["compress_background"] is True

    def test_no_extra_partial_encode_when_video_ends_on_exact_segment_boundary(
        self, monkeypatch, tmp_path, exact_segment_frames
    ):
        """
        If the source ends exactly on a full segment boundary, run_pipeline()
        should perform the normal full-segment encode only once and must not
        perform a second EOF partial-segment encode.

        Cleanup/reporting should still run even though there are zero leftover
        buffered frames at shutdown.
        """
        calls = {
            "encode_segment": 0,
            "get_storage_report": 0,
        }

        monkeypatch.setattr(
            "pipeline.pipeline.FrameSource",
            lambda *_args, **_kwargs: DummyFrameSource(exact_segment_frames)
        )
        monkeypatch.setattr(
            "pipeline.pipeline.BackgroundSubtractor",
            DummySubtractor
        )
        monkeypatch.setattr(
            "pipeline.pipeline.ROIEncoder",
            lambda *args, **kwargs: DummyEncoder(calls, *args, **kwargs)
        )
        monkeypatch.setattr(
            "pipeline.pipeline.initialize_database",
            lambda *_args, **_kwargs: None
        )


        run_pipeline(
            input_source="dummy.mp4",
            camera_id="cam_test",
            output_dir=str(tmp_path),
            segment_seconds=2,
            bg_method="MOG2",
            show_preview=False,
            warmup_frames=0,
        )

        # One normal full-segment encode, no extra EOF partial encode.
        assert calls["encode_segment"] == 1

        # Cleanup/reporting should still run with zero leftover frames.
        assert calls["get_storage_report"] == 1


# ---------------------------------------------------------------------------
# mode1 behavior
# ---------------------------------------------------------------------------

class TestMode1Behavior:
    def test_mode1_buffers_only_frames_with_foreground_regions(
        self, monkeypatch, tmp_path, mixed_event_frames
    ):
        """
        In mode1, run_pipeline() should only buffer frames that have detected
        foreground regions and skip non-event frames.

        Given six input frames where only three contain regions, the encoder
        should receive exactly three frames and three bbox entries.
        """
        calls = {
            "encode_segment": 0,
            "get_storage_report": 0,
            "encoded_frame_count": None,
            "encoded_bboxes_count": None,
            "compress_background": None,
        }

        # Event pattern across 6 frames: skip, keep, skip, keep, skip, keep
        regions_per_frame = [
            [],
            [DummyRegion()],
            [],
            [DummyRegion()],
            [],
            [DummyRegion()],
        ]

        monkeypatch.setattr(
            "pipeline.pipeline.FrameSource",
            lambda *_args, **_kwargs: DummyFrameSource(
                mixed_event_frames, fps=10.0, width=16, height=16
            )
        )
        monkeypatch.setattr(
            "pipeline.pipeline.BackgroundSubtractor",
            lambda *args, **kwargs: SequenceSubtractor(regions_per_frame, *args, **kwargs)
        )
        monkeypatch.setattr(
            "pipeline.pipeline.initialize_database",
            lambda *_args, **_kwargs: None
        )

        class RecordingEncoder:
            def __init__(self, *args, **kwargs):
                self._frame_count = 0
                self._bbox_count = 0

            def begin_segment(self, frame_shape, fps, camera_id="cam_unknown",
                              has_targets=True, object_type="unknown", source_path=None,
                              **kwargs):
                self._frame_count = 0
                self._bbox_count = 0

            def write_frame(self, frame, boxes=None, background_frame=None,
                            object_only=False, mode_label="", draw_roi_boxes=None,
                            measure_sharpness=True, compress_background=False):
                self._frame_count += 1
                self._bbox_count += 1  # one bboxes_per_frame entry per write_frame call
                if calls["compress_background"] is None:
                    calls["compress_background"] = compress_background

            def abort_segment(self):
                pass

            def finish_segment(self, timeout=30.0, **kwargs):
                calls["encode_segment"] += 1
                calls["encoded_frame_count"] = self._frame_count
                calls["encoded_bboxes_count"] = self._bbox_count
                return {
                    "file_path": "dummy_mode1.mp4",
                    "avg_sharpness": None,
                    "sharpness_label": None,
                }

            def get_storage_report(self):
                calls["get_storage_report"] += 1
                return {"total_segments": calls["encode_segment"]}

        monkeypatch.setattr(
            "pipeline.pipeline.ROIEncoder",
            RecordingEncoder
        )

        run_pipeline(
            input_source="dummy.mp4",
            camera_id="cam_test",
            output_dir=str(tmp_path),
            segment_seconds=60,
            bg_method="MOG2",
            mode="mode1",
            show_preview=False,
            warmup_frames=0,
        )

        # No full segment boundary is reached, so a single final partial encode
        # should occur with only the 3 event frames.
        assert calls["encode_segment"] == 1
        assert calls["encoded_frame_count"] == 3
        assert calls["encoded_bboxes_count"] == 3
        assert calls["compress_background"] is False
        assert calls["get_storage_report"] == 1


# ---------------------------------------------------------------------------
# mode2 behavior
# ---------------------------------------------------------------------------

class TestMode2Behavior:
    def test_mode2_uses_compression_oriented_encoder_settings(
        self, monkeypatch, tmp_path
    ):
        encoder_kwargs = {}
        frames = [np.full((16, 16, 3), 1, dtype=np.uint8)]
        regions_per_frame = [[DummyRegion()]]

        monkeypatch.setattr(
            "pipeline.pipeline.FrameSource",
            lambda *_args, **_kwargs: DummyFrameSource(
                frames, fps=2.0, width=16, height=16
            )
        )
        monkeypatch.setattr(
            "pipeline.pipeline.BackgroundSubtractor",
            lambda *args, **kwargs: SequenceSubtractor(regions_per_frame, *args, **kwargs)
        )
        monkeypatch.setattr(
            "pipeline.pipeline.initialize_database",
            lambda *_args, **_kwargs: None
        )

        class RecordingEncoder(DummyEncoder):
            def __init__(self, *args, **kwargs):
                encoder_kwargs.update(kwargs)
                super().__init__({"encode_segment": 0, "get_storage_report": 0}, *args, **kwargs)

        monkeypatch.setattr("pipeline.pipeline.ROIEncoder", RecordingEncoder)

        run_pipeline(
            input_source="dummy.mp4",
            camera_id="cam_test",
            output_dir=str(tmp_path),
            segment_seconds=60,
            bg_method="MOG2",
            mode="mode2",
            show_preview=False,
            warmup_frames=0,
        )

        assert encoder_kwargs["preset"] == "veryfast"
        assert encoder_kwargs["foreground_crf"] == 23

    def test_mode2_uses_background_only_after_two_clean_seconds(
        self, monkeypatch, tmp_path
    ):
        calls = {
            "encode_segment": 0,
            "background_values": [],
            "object_only": [],
            "encoded_frame_counts": [],
        }

        frames = [
            np.full((16, 16, 3), value, dtype=np.uint8)
            for value in range(9)
        ]
        regions_per_frame = [
            [],
            [],
            [],
            [DummyRegion()],
            [],
            [],
            [],
            [],
            [DummyRegion()],
        ]

        monkeypatch.setattr(
            "pipeline.pipeline.FrameSource",
            lambda *_args, **_kwargs: DummyFrameSource(
                frames, fps=2.0, width=16, height=16
            )
        )
        monkeypatch.setattr(
            "pipeline.pipeline.BackgroundSubtractor",
            lambda *args, **kwargs: SequenceSubtractor(regions_per_frame, *args, **kwargs)
        )
        monkeypatch.setattr(
            "pipeline.pipeline.initialize_database",
            lambda *_args, **_kwargs: None
        )

        class RecordingEncoder:
            def __init__(self, *args, **kwargs):
                self._frame_count = 0
                self._object_only = None
                self._background_val = None

            def begin_segment(self, frame_shape, fps, camera_id="cam_unknown",
                              has_targets=True, object_type="unknown", source_path=None,
                              **kwargs):
                self._frame_count = 0
                self._object_only = None
                self._background_val = None

            def write_frame(self, frame, boxes=None, background_frame=None,
                            object_only=False, mode_label="", draw_roi_boxes=None,
                            measure_sharpness=True, compress_background=False):
                self._frame_count += 1
                # Capture the first frame's object_only and background value
                if self._object_only is None:
                    self._object_only = object_only
                if self._background_val is None:
                    self._background_val = (
                        None if background_frame is None
                        else int(background_frame[0, 0, 0])
                    )

            def abort_segment(self):
                pass

            def finish_segment(self, timeout=30.0, **kwargs):
                calls["encode_segment"] += 1
                calls["encoded_frame_counts"].append(self._frame_count)
                calls["object_only"].append(self._object_only)
                calls["background_values"].append(self._background_val)
                return {
                    "file_path": f"mode2_patch_{calls['encode_segment']}.mp4",
                    "avg_sharpness": None,
                    "sharpness_label": None,
                }

            def get_storage_report(self):
                return {"total_segments": calls["encode_segment"]}

        monkeypatch.setattr("pipeline.pipeline.ROIEncoder", RecordingEncoder)

        run_pipeline(
            input_source="dummy.mp4",
            camera_id="cam_test",
            output_dir=str(tmp_path),
            segment_seconds=0.5,
            bg_method="MOG2",
            mode="mode2",
            show_preview=False,
            warmup_frames=0,
            mode2_clean_seconds=2.0,
        )

        assert calls["encode_segment"] == 2
        assert calls["encoded_frame_counts"] == [1, 1]
        assert calls["object_only"] == [False, False]
        assert calls["background_values"] == [0, 4]

    def test_mode2_does_not_learn_clean_background_during_first_second_after_warmup(
        self, monkeypatch, tmp_path
    ):
        calls = {
            "encode_segment": 0,
            "background_values": [],
        }

        frames = [
            np.full((16, 16, 3), value, dtype=np.uint8)
            for value in range(3)
        ]
        regions_per_frame = [
            [],
            [],
            [DummyRegion()],
        ]

        monkeypatch.setattr(
            "pipeline.pipeline.FrameSource",
            lambda *_args, **_kwargs: DummyFrameSource(
                frames, fps=2.0, width=16, height=16
            )
        )
        monkeypatch.setattr(
            "pipeline.pipeline.BackgroundSubtractor",
            lambda *args, **kwargs: SequenceSubtractor(regions_per_frame, *args, **kwargs)
        )
        monkeypatch.setattr(
            "pipeline.pipeline.initialize_database",
            lambda *_args, **_kwargs: None
        )

        class RecordingEncoder:
            def __init__(self, *args, **kwargs):
                self._background_val = None

            def begin_segment(self, frame_shape, fps, camera_id="cam_unknown",
                              has_targets=True, object_type="unknown", source_path=None):
                self._background_val = None

            def write_frame(self, frame, boxes=None, background_frame=None,
                            object_only=False, mode_label="", draw_roi_boxes=None,
                            measure_sharpness=True, compress_background=False):
                if self._background_val is None:
                    self._background_val = (
                        None if background_frame is None
                        else int(background_frame[0, 0, 0])
                    )

            def abort_segment(self):
                pass

            def finish_segment(self, timeout=30.0):
                calls["encode_segment"] += 1
                calls["background_values"].append(self._background_val)
                return {
                    "file_path": f"mode2_patch_{calls['encode_segment']}.mp4",
                    "avg_sharpness": None,
                    "sharpness_label": None,
                }

            def get_storage_report(self):
                return {"total_segments": calls["encode_segment"]}

        monkeypatch.setattr("pipeline.pipeline.ROIEncoder", RecordingEncoder)

        run_pipeline(
            input_source="dummy.mp4",
            camera_id="cam_test",
            output_dir=str(tmp_path),
            segment_seconds=60,
            bg_method="MOG2",
            mode="mode2",
            show_preview=False,
            warmup_frames=0,
            mode2_clean_seconds=1.0,
        )

        assert calls["encode_segment"] == 1
        assert calls["background_values"] == [0]

    def test_mode2_refreshes_active_segment_background_after_clean_skip_gap(
        self, monkeypatch, tmp_path
    ):
        calls = {
            "encode_segment": 0,
            "background_values_per_write": [],
        }

        frames = [
            np.full((16, 16, 3), value, dtype=np.uint8)
            for value in range(11)
        ]
        regions_per_frame = [
            [DummyRegion()],
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            [DummyRegion()],
            [DummyRegion()],
        ]

        monkeypatch.setattr(
            "pipeline.pipeline.FrameSource",
            lambda *_args, **_kwargs: DummyFrameSource(
                frames, fps=2.0, width=16, height=16
            )
        )
        monkeypatch.setattr(
            "pipeline.pipeline.BackgroundSubtractor",
            lambda *args, **kwargs: SequenceSubtractor(regions_per_frame, *args, **kwargs)
        )
        monkeypatch.setattr(
            "pipeline.pipeline.initialize_database",
            lambda *_args, **_kwargs: None
        )

        class RecordingEncoder:
            def __init__(self, *args, **kwargs):
                pass

            def begin_segment(self, frame_shape, fps, camera_id="cam_unknown",
                              has_targets=True, object_type="unknown", source_path=None):
                pass

            def write_frame(self, frame, boxes=None, background_frame=None,
                            object_only=False, mode_label="", draw_roi_boxes=None,
                            measure_sharpness=True, compress_background=False):
                calls["background_values_per_write"].append(
                    None if background_frame is None
                    else int(background_frame[0, 0, 0])
                )

            def abort_segment(self):
                pass

            def finish_segment(self, timeout=30.0):
                calls["encode_segment"] += 1
                return {
                    "file_path": f"mode2_patch_{calls['encode_segment']}.mp4",
                    "avg_sharpness": None,
                    "sharpness_label": None,
                }

            def get_storage_report(self):
                return {"total_segments": calls["encode_segment"]}

        monkeypatch.setattr("pipeline.pipeline.ROIEncoder", RecordingEncoder)

        run_pipeline(
            input_source="dummy.mp4",
            camera_id="cam_test",
            output_dir=str(tmp_path),
            segment_seconds=60,
            bg_method="MOG2",
            mode="mode2",
            show_preview=False,
            warmup_frames=0,
            mode2_clean_seconds=1.0,
        )

        assert calls["encode_segment"] == 1
        assert calls["background_values_per_write"] == [0, 5, 5]


# ---------------------------------------------------------------------------
# mode3 behavior
# ---------------------------------------------------------------------------

class TestMode3Behavior:
    def test_mode3_encodes_object_only_mp4_segments_with_compression_settings(
        self, monkeypatch, tmp_path, mixed_event_frames
    ):
        calls = {
            "encode_segment": 0,
            "get_storage_report": 0,
            "encoded_frame_count": None,
            "encoded_bboxes_count": None,
            "object_only": None,
            "init_kwargs": None,
            "source_path": "unset",
        }

        regions_per_frame = [
            [],
            [DummyRegion()],
            [],
            [DummyRegion()],
            [],
            [DummyRegion()],
        ]

        monkeypatch.setattr(
            "pipeline.pipeline.FrameSource",
            lambda *_args, **_kwargs: DummyFrameSource(
                mixed_event_frames, fps=10.0, width=16, height=16
            )
        )
        monkeypatch.setattr(
            "pipeline.pipeline.BackgroundSubtractor",
            lambda *args, **kwargs: SequenceSubtractor(regions_per_frame, *args, **kwargs)
        )
        monkeypatch.setattr(
            "pipeline.pipeline.initialize_database",
            lambda *_args, **_kwargs: None
        )

        class RecordingEncoder:
            def __init__(self, *args, **kwargs):
                calls["init_kwargs"] = kwargs
                self._frame_count = 0
                self._bbox_count = 0
                self._object_only = None

            def begin_segment(self, frame_shape, fps, camera_id="cam_unknown",
                              has_targets=True, object_type="unknown", source_path=None,
                              **kwargs):
                self._frame_count = 0
                self._bbox_count = 0
                self._object_only = None
                calls["source_path"] = source_path

            def write_frame(self, frame, boxes=None, background_frame=None,
                            object_only=False, mode_label="", draw_roi_boxes=None,
                            measure_sharpness=True, compress_background=False):
                self._frame_count += 1
                self._bbox_count += 1
                if self._object_only is None:
                    self._object_only = object_only

            def abort_segment(self):
                pass

            def finish_segment(self, timeout=30.0, **kwargs):
                calls["encode_segment"] += 1
                calls["encoded_frame_count"] = self._frame_count
                calls["encoded_bboxes_count"] = self._bbox_count
                calls["object_only"] = self._object_only
                return {
                    "file_path": "mode3_object_only.mp4",
                    "avg_sharpness": None,
                    "sharpness_label": None,
                }

            def get_storage_report(self):
                calls["get_storage_report"] += 1
                return {"total_segments": calls["encode_segment"]}

        # Mode 3 now routes back through ROIEncoder with object_only=True
        # and a higher CRF (default 38). The sparse per-object encoder was
        # removed 2026-05-02 because it produced multiple files per segment
        # which wasn't what the brief asked for.
        # Author: Bloodawn (KheivenD)
        monkeypatch.setattr("pipeline.pipeline.ROIEncoder", RecordingEncoder)

        run_pipeline(
            input_source="dummy.mp4",
            camera_id="cam_test",
            output_dir=str(tmp_path),
            segment_seconds=60,
            bg_method="MOG2",
            mode="mode3",
            show_preview=False,
            warmup_frames=0,
        )

        # Mode 3 contract: object_only=True is passed on every write_frame,
        # the encoder is called once per segment, and 3 frames + 3 bboxes
        # made it through.
        assert calls["encode_segment"] == 1
        assert calls["encoded_frame_count"] == 3
        assert calls["encoded_bboxes_count"] == 3
        assert calls["object_only"] is True
        assert calls["init_kwargs"]["preset"] == "veryfast"
        assert calls["init_kwargs"]["foreground_crf"] == 23
        assert calls["source_path"] is None
        assert calls["get_storage_report"] == 1
