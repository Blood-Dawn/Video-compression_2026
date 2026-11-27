import pytest

from pipeline.modes import get_mode_decision, validate_mode


class DummyRegion:
    pass


def test_mode3_is_valid():
    validate_mode("mode3")


def test_mode2_is_valid():
    validate_mode("mode2")


def test_mode2_buffers_foreground_frames_for_patch_segment():
    decision = get_mode_decision("mode2", [DummyRegion()])

    assert decision.target_detected is True
    assert decision.store_full_frame is True
    assert decision.buffer_frame is True
    assert decision.store_foreground_layer is False


def test_mode2_keeps_empty_background_frames():
    decision = get_mode_decision("mode2", [])

    assert decision.target_detected is False
    assert decision.store_full_frame is True
    assert decision.store_foreground_layer is False


def test_mode3_buffers_foreground_frames_for_object_only_segment():
    decision = get_mode_decision("mode3", [DummyRegion()])

    assert decision.target_detected is True
    assert decision.store_full_frame is True
    assert decision.buffer_frame is True
    assert decision.store_foreground_layer is False


def test_mode3_keeps_empty_background_frames():
    decision = get_mode_decision("mode3", [])

    assert decision.target_detected is False
    assert decision.store_full_frame is True
    assert decision.store_foreground_layer is False


def test_only_mode1_drops_frames_without_activity():
    assert get_mode_decision("mode1", []).buffer_frame is False
    assert get_mode_decision("mode1", [DummyRegion()]).buffer_frame is True
    for m in ("mode0", "mode2", "mode3"):
        assert get_mode_decision(m, []).buffer_frame is True


def test_invalid_mode_still_rejected():
    with pytest.raises(ValueError):
        validate_mode("mode4")
