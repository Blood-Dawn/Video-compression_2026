"""Result numbers and segment length planning for the SVCS Home page.

Two small pure functions with no I/O in the core, so they can be tested alone.

summarize_result: one set of "Saved" numbers, measured from real file sizes.
  The dashboard used to compare the output with an estimate of the uncompressed
  frames (width * height * 3 * fps * seconds). That is not the file the user
  sent in, so "Saved" read much higher than what Windows Explorer shows. It also
  mixed decimal megabytes (/1e6) with binary megabytes (/1024) in one ratio.

plan_segments: default, recommended and preset segment lengths for a video.

Author: Bloodawn (KheivenD), 2026-11-23 (demo branch, task 13.3 and 13.4).
"""
from __future__ import annotations

import math
import os
from typing import Iterable, Sequence

MIB = 1024 * 1024  # Windows Explorer shows MB this way, so numbers match what the user sees
SLIDER_MIN_S = 10
SLIDER_MAX_S = 1800
LIVE_DEFAULT_S = 600  # live sources default to 10 minutes (task 5.17)
PRESET_CANDIDATES_S = (30, 60, 120, 300, 600, 900, 1800)
LIVE_PRESETS_S = (60, 300, 600, 900, 1800)


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def summarize_result(pairs: Iterable[Sequence[int]]) -> dict:
    """pairs: (source_bytes, output_bytes) for every file or segment of one job.

    Percentages come from the summed bytes, never from averaging per file
    percentages. The megabyte figures are rounded once and the saved figure is
    taken from the rounded ones, so the numbers on screen always add up.
    """
    src = out = 0
    for s, o in pairs:
        if s < 0 or o < 0:
            raise ValueError("file sizes cannot be negative")
        src += int(s)
        out += int(o)
    if src == 0:
        return {"verdict": "unknown", "source_bytes": 0, "output_bytes": out}

    before_mb = round(src / MIB, 1)
    after_mb = round(out / MIB, 1)
    if out >= src:
        return {
            "verdict": "no_saving", "source_bytes": src, "output_bytes": out,
            "saved_bytes": 0, "saved_pct": 0, "ratio": round(src / out, 1) if out else None,
            "before_mb": before_mb, "after_mb": after_mb, "saved_mb": 0.0,
        }
    pct = _round_half_up(100.0 * (src - out) / src)
    if out > 0 and pct >= 100:
        pct = 99  # never claim 100% while a file still exists
    return {
        "verdict": "saved", "source_bytes": src, "output_bytes": out,
        "saved_bytes": src - out, "saved_pct": pct,
        "ratio": round(src / out, 1) if out else None,
        "before_mb": before_mb, "after_mb": after_mb,
        "saved_mb": round(before_mb - after_mb, 1),
    }


def summarize_paths(source_path: str, output_paths: Iterable[str]) -> dict:
    """Measure real files on disk. Missing outputs are skipped, a missing source is an error."""
    outs = sum(os.path.getsize(p) for p in output_paths if os.path.exists(p))
    return summarize_result([(os.path.getsize(source_path), outs)])


def format_result(r: dict) -> dict:
    """Strings for the Last result card, built only from the numbers in r."""
    if r["verdict"] == "unknown":
        return {"headline": "Size not available", "detail": "The source file size could not be read."}
    if r["verdict"] == "no_saving":
        return {"headline": "No space saved",
                "detail": f"{r['before_mb']:.1f} MB became {r['after_mb']:.1f} MB. The original was kept."}
    ratio = f", {r['ratio']:.1f} times smaller" if r.get("ratio") else ""
    return {"headline": f"Saved {r['saved_pct']}%",
            "detail": f"{r['before_mb']:.1f} MB to {r['after_mb']:.1f} MB, {r['saved_mb']:.1f} MB freed{ratio}"}


def fmt_length(seconds: int) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} h")
    if m:
        parts.append(f"{m} min")
    if s:
        parts.append(f"{s} s")
    return " ".join(parts)


def clip_count(duration_s: float, segment_seconds: int) -> int:
    return max(1, int(math.ceil(duration_s / max(1, segment_seconds))))


def plan_segments(duration_s: float | None) -> dict:
    """Segment length choices for one video, or for a live source when duration_s is None.

    default:      whole video, one output file. segment_seconds is the length rounded
                  up plus 1 second so a probe that is a hair short never makes a tiny
                  extra clip. It can be longer than the slider maximum, so the UI sends
                  it as a value and shows the "Whole video" button as selected.
    recommended:  half of the video, rounded up to a multiple of 10 seconds. Shown as
                  a suggestion only. Under 20 seconds a half would break the 10 second
                  minimum, so the recommendation is the whole video.
    presets:      fixed lengths that are shorter than the video, plus Half and Whole.
    """
    if duration_s is None or duration_s <= 0:
        presets = [{"label": fmt_length(s), "seconds": s} for s in LIVE_PRESETS_S]
        return {"kind": "live", "default_seconds": LIVE_DEFAULT_S, "recommended_seconds": LIVE_DEFAULT_S,
                "whole_seconds": None, "presets": presets}

    dur = float(duration_s)
    whole = int(math.ceil(dur)) + 1
    if dur < 2 * SLIDER_MIN_S:
        rec = whole
    else:
        rec = max(SLIDER_MIN_S, int(math.ceil((dur / 2) / 10.0)) * 10)
        rec = min(rec, whole)
    presets = [{"label": fmt_length(s), "seconds": s} for s in PRESET_CANDIDATES_S if s < dur]
    return {"kind": "file", "default_seconds": whole, "recommended_seconds": rec,
            "whole_seconds": whole, "presets": presets,
            "clips_at_recommended": clip_count(dur, rec),
            "fits_slider": SLIDER_MIN_S <= rec <= SLIDER_MAX_S}
