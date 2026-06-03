"""
tests/test_presets.py

Tests the surveillance preset system (M3 TASK 3.1).

Asserts every named preset resolves to a VALID encode config (mode, CRF ranges,
foreground<=background, codec, bg method) consistent with the settled decisions,
and that a resolved config round-trips losslessly through JSON
(export -> import), which is how presets travel through /api/config/*.

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 3.1).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pipeline import presets as P  # noqa: E402
from config import default_codec_for_mode  # noqa: E402


def test_registry_nonempty_and_includes_surveillance_family():
    keys = set(P.PRESETS)
    assert P.DEFAULT_PRESET in keys
    # The surveillance-first family from the plan.
    for k in ("continuous_cctv", "motion_event", "doorbell",
              "multi_camera_nvr", "active_scene", "archive"):
        assert k in keys, f"missing surveillance preset {k}"
    # Plus a couple of general ones.
    for k in ("screen_recording", "generic"):
        assert k in keys
    # Most presets are surveillance-oriented.
    surveillance = [p for p in P.PRESETS.values() if p.surveillance]
    assert len(surveillance) >= 5


def test_consumer_camera_family_present_and_conservative():
    """M-CAM TASK 4: the consumer-camera family exists and is tuned
    conservatively (consumer sensors are noisy - don't smear detail)."""
    consumer = ("doorbell", "indoor_cam", "outdoor_yard", "baby_monitor")
    for k in consumer:
        assert k in P.PRESETS, f"missing consumer preset {k}"
        p = P.get_preset(k)
        assert p.surveillance  # shown in the security-camera family
        # Conservative foreground: not pushed past the mode3 doorbell value.
        assert p.foreground_crf <= 38
    # Indoor / baby keep every frame (dual-CRF), not object-only clips.
    assert P.get_preset("indoor_cam").mode == "mode1"
    assert P.get_preset("baby_monitor").mode == "mode1"
    # A baby/pet can hold still - must not be gated out by object detection.
    assert P.get_preset("baby_monitor").object_filter is False


@pytest.mark.parametrize("key", list(P.PRESETS))
def test_each_preset_resolves_to_valid_config(key):
    cfg = P.resolve_preset(key)
    # Required keys present.
    for field in ("preset", "mode", "crf", "background_crf", "codec",
                  "bg_method", "object_filter", "segment_seconds"):
        assert field in cfg, f"{key}: missing {field}"
    assert cfg["preset"] == key
    # Validates (raises on any problem).
    P.validate_encode_config(cfg)


@pytest.mark.parametrize("key", list(P.PRESETS))
def test_preset_codec_is_auto_and_resolves_per_mode(key):
    """Presets use the per-mode codec policy; 'auto' resolves to H.264 for
    mode0/1 and AV1 for mode2/3, and is never H.265."""
    cfg = P.resolve_preset(key)
    assert cfg["codec"] in P.VALID_CODECS
    resolved = (default_codec_for_mode(cfg["mode"])
                if cfg["codec"] == "auto" else cfg["codec"])
    assert "265" not in resolved and "hevc" not in resolved.lower()
    if cfg["codec"] == "auto":
        expected = "libx264" if cfg["mode"] in ("mode0", "mode1") else "libsvtav1"
        assert resolved == expected


@pytest.mark.parametrize("key", list(P.PRESETS))
def test_preset_config_round_trips_through_json(key):
    """A resolved config survives export -> import (JSON) unchanged - this is
    how presets travel through /api/config/export + /api/config/import."""
    cfg = P.resolve_preset(key)
    restored = json.loads(json.dumps(cfg))
    assert restored == cfg
    P.validate_encode_config(restored)


def test_foreground_not_worse_than_background_everywhere():
    for p in P.PRESETS.values():
        assert p.foreground_crf <= p.background_crf, p.key


def test_list_presets_is_ordered_catalog():
    cat = P.list_presets()
    assert isinstance(cat, list) and cat
    assert cat[0]["key"] == P.DEFAULT_PRESET
    for entry in cat:
        assert set(entry) >= {"key", "label", "description", "mode", "surveillance"}
        assert entry["mode"] in P.VALID_MODES


def test_unknown_preset_raises():
    with pytest.raises(KeyError):
        P.get_preset("does_not_exist")


def test_invalid_config_rejected():
    bad = P.resolve_preset(P.DEFAULT_PRESET)
    bad = dict(bad, mode="mode9")
    with pytest.raises(ValueError):
        P.validate_encode_config(bad)
    # foreground worse than background must be rejected.
    bad2 = dict(P.resolve_preset("motion_event"), crf=60, background_crf=20)
    with pytest.raises(ValueError):
        P.validate_encode_config(bad2)
