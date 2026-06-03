"""
src/pipeline/presets.py

Surveillance-first named presets (M3 TASK 3.1).

Operators shouldn't have to reason about "Mode 0–3" — they think in terms of
*what the camera is watching*. Each preset maps a human name to a concrete
encode config tuple (mode, foreground-CRF, background-CRF, codec, ...) built on
the settled decisions:

  * progressive foreground CRF: mode0=18, mode1=18, mode2=23, mode3=38;
  * per-mode default codec ("auto" -> H.264 for mode0/1, AV1 for mode2/3);
  * object detection (ONNX) gates the foreground so leaves/shadows aren't kept.

The raw mode picker stays available behind an "Advanced" toggle in the UI; these
presets are the default surface. A resolved preset is a plain dict that the
/api/start config and the pipeline already understand (with an added
``background_crf`` the encoder honors for the dual-CRF background).

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 3.1 — surveillance presets).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

VALID_MODES = {"mode0", "mode1", "mode2", "mode3"}
VALID_CODECS = {"auto", "libsvtav1", "libaom-av1", "libx264"}
VALID_BG_METHODS = {"MOG2", "KNN", "GMG"}
_CRF_MIN, _CRF_MAX = 0, 63


@dataclass(frozen=True)
class Preset:
    """A named encode preset.

    foreground_crf / background_crf are absolute CRF values (lower = higher
    quality). codec "auto" resolves per-mode at encode time
    (config.default_codec_for_mode). ``surveillance`` flags the security-camera
    family vs the couple of general presets.
    """
    key: str
    label: str
    description: str
    mode: str
    foreground_crf: int
    background_crf: int
    codec: str = "auto"
    bg_method: str = "MOG2"
    object_filter: bool = True
    segment_seconds: int = 60
    surveillance: bool = True

    def to_config(self) -> Dict:
        """Resolve to the encode-config dict consumed by /api/start + pipeline."""
        return {
            "preset": self.key,
            "mode": self.mode,
            "crf": self.foreground_crf,          # foreground CRF
            "background_crf": self.background_crf,
            "codec": self.codec,                 # "auto" -> per-mode default
            "bg_method": self.bg_method,
            "object_filter": self.object_filter,
            "segment_seconds": self.segment_seconds,
        }


# Ordered registry — surveillance family first, then a couple of general ones.
# Rationale per preset is in the description + comments. CRF choices follow the
# progressive scheme and keep foreground <= background (foreground is always the
# higher-quality stream).
_PRESET_LIST: List[Preset] = [
    Preset(
        key="continuous_cctv",
        label="Continuous CCTV (max savings)",
        description="24/7 static camera. Records only when targets are present and "
                    "drops idle background entirely — the biggest storage win.",
        mode="mode2", foreground_crf=23, background_crf=51, codec="auto",
    ),
    Preset(
        key="motion_event",
        label="Motion-event cam",
        description="Mostly-idle camera with occasional motion. Keeps every frame but "
                    "encodes the background hard and the moving foreground sharp (dual-CRF).",
        mode="mode1", foreground_crf=18, background_crf=45, codec="auto",
    ),
    Preset(
        key="doorbell",
        label="Doorbell / entry",
        description="Sparse, close-range events (a person at the door). Object-only clips "
                    "with the background blacked out for the smallest files.",
        mode="mode3", foreground_crf=38, background_crf=51, codec="auto",
    ),
    Preset(
        key="multi_camera_nvr",
        label="Multi-camera / NVR",
        description="Many static feeds into one box. Event-recording per camera keeps the "
                    "aggregate storage and CPU manageable.",
        mode="mode2", foreground_crf=23, background_crf=50, codec="auto",
    ),
    Preset(
        key="active_scene",
        label="Active scene",
        description="Busy view (street, lobby, parking) with near-constant motion. Dual-CRF "
                    "keeps moving subjects sharp without exploding size on the steady background.",
        mode="mode1", foreground_crf=18, background_crf=40, codec="auto",
    ),
    Preset(
        key="archive",
        label="Archive (visually lossless)",
        description="Evidence / long-term retention where quality matters more than size. "
                    "Every frame at high quality, single-pass.",
        mode="mode0", foreground_crf=16, background_crf=22, codec="auto",
    ),
    # ── Consumer cameras (M-CAM TASK 4) ─────────────────────────────────────
    # Tuned for consumer footage: lower-res, noisier sensors, mostly-static
    # scenes with sparse events. CRFs are deliberately CONSERVATIVE — consumer
    # cameras already soften detail, so we don't compress the foreground hard.
    Preset(
        key="indoor_cam",
        label="Indoor cam (pets / home)",
        description="An indoor room camera — pets, kids, general home monitoring. "
                    "Keeps every frame (dual-CRF) with a conservative foreground so "
                    "faces and pets stay legible on a noisy indoor sensor.",
        mode="mode1", foreground_crf=20, background_crf=44, codec="auto",
    ),
    Preset(
        key="outdoor_yard",
        label="Outdoor yard cam",
        description="A yard / driveway camera with sparse events (a person, a car, "
                    "a delivery). Event-recording for big idle savings, conservative "
                    "foreground so plates and faces survive at distance.",
        mode="mode2", foreground_crf=23, background_crf=48, codec="auto",
    ),
    Preset(
        key="baby_monitor",
        label="Baby / pet monitor (long idle)",
        description="Long stretches of stillness with rare movement. Keeps every "
                    "frame and does NOT gate on object detection, so a still baby or "
                    "a curled-up pet is never dropped as 'background'.",
        mode="mode1", foreground_crf=20, background_crf=42, codec="auto",
        object_filter=False,
    ),
    # ── General (non-surveillance) ──────────────────────────────────────────
    Preset(
        key="screen_recording",
        label="Screen recording",
        description="Screen capture / tutorials. Single-pass, no object gating (the whole "
                    "frame is the subject).",
        mode="mode0", foreground_crf=18, background_crf=28,
        object_filter=False, surveillance=False,
    ),
    Preset(
        key="generic",
        label="Generic",
        description="Balanced default when you're not sure — dual-CRF with standard settings.",
        mode="mode1", foreground_crf=18, background_crf=45, surveillance=False,
    ),
]

PRESETS: Dict[str, Preset] = {p.key: p for p in _PRESET_LIST}

# The default preset selected in the UI on first run.
DEFAULT_PRESET = "continuous_cctv"


def list_presets() -> List[Dict]:
    """Catalog for the UI: key/label/description/mode/surveillance, in order."""
    return [
        {
            "key": p.key,
            "label": p.label,
            "description": p.description,
            "mode": p.mode,
            "surveillance": p.surveillance,
        }
        for p in _PRESET_LIST
    ]


def get_preset(key: str) -> Preset:
    """Return the Preset for ``key`` or raise KeyError."""
    try:
        return PRESETS[key]
    except KeyError:
        raise KeyError(f"unknown preset: {key!r}") from None


def resolve_preset(key: str) -> Dict:
    """Resolve a preset key to its encode-config dict."""
    return get_preset(key).to_config()


def validate_encode_config(cfg: Dict) -> None:
    """Raise ValueError if a resolved encode config is invalid.

    Checks the mode, codec, bg method, CRF ranges, and the foreground<=background
    invariant. Used by the round-trip / preset tests and safe to call on any
    imported config before handing it to the pipeline.
    """
    mode = cfg.get("mode")
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode: {mode!r}")
    codec = cfg.get("codec", "auto")
    if codec not in VALID_CODECS:
        raise ValueError(f"invalid codec: {codec!r}")
    bgm = cfg.get("bg_method", "MOG2")
    if bgm not in VALID_BG_METHODS:
        raise ValueError(f"invalid bg_method: {bgm!r}")
    fg = cfg.get("crf")
    bg = cfg.get("background_crf")
    for name, v in (("crf", fg), ("background_crf", bg)):
        if not isinstance(v, int) or not (_CRF_MIN <= v <= _CRF_MAX):
            raise ValueError(f"{name} must be an int in [{_CRF_MIN},{_CRF_MAX}], got {v!r}")
    if fg > bg:
        raise ValueError(f"foreground CRF ({fg}) must be <= background CRF ({bg})")
    ss = cfg.get("segment_seconds", 60)
    if not isinstance(ss, int) or ss <= 0:
        raise ValueError(f"segment_seconds must be a positive int, got {ss!r}")
