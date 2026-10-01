"""
src/utils/timelapse.py

Timelapse / quiet-period summary generation (2026-10-01 competitive-gap
review: Reolink/Synology-style "smart summary" that compresses a long,
mostly-static recording into a short fast-forward clip instead of making the
operator scrub the whole thing). SVCS had no equivalent - this closes that
gap with the smallest reasonable piece: a single ffmpeg call that speeds up
an existing segment, callable from the GUI (gui/routes/timelapse_bp.py) or
any script.

This is a standalone post-process over an ALREADY-ENCODED segment, not a new
pipeline mode - it does not touch pipeline.py's streaming loop at all, so it
carries none of the risk of changing the live-record path.

Author: Bloodawn (KheivenD), 2026-10-01.
"""
from pathlib import Path
import subprocess

try:
    from utils.ffmpeg import ffmpeg_path
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils.ffmpeg import ffmpeg_path

# Playback-speed multiplier bounds. MIN keeps this a real timelapse (not a
# no-op copy); MAX keeps a pathological value from collapsing a long clip to
# a handful of unreadable frames or hanging ffmpeg's filter graph.
MIN_SPEED = 2.0
MAX_SPEED = 60.0
DEFAULT_SPEED = 8.0


def clamp_speed(speed) -> float:
    """Coerce ``speed`` to a float within [MIN_SPEED, MAX_SPEED].

    Unparseable/missing input falls back to DEFAULT_SPEED rather than
    raising, so a bad request body degrades to a sane default instead of a
    500 - the same defensive pattern pipeline_bp.py's _clamp_int uses.
    """
    try:
        s = float(speed)
    except (TypeError, ValueError):
        return DEFAULT_SPEED
    if s != s or s in (float("inf"), float("-inf")):  # NaN / inf guard
        return DEFAULT_SPEED
    return max(MIN_SPEED, min(MAX_SPEED, s))


def make_timelapse(input_path, output_path, speed=DEFAULT_SPEED, timeout=600):
    """Create a sped-up, video-only timelapse of ``input_path`` at ``output_path``.

    ``speed`` is the playback multiplier (8.0 = 8x faster / one-eighth the
    runtime), clamped via clamp_speed(). Audio is dropped: surveillance
    clips are routinely silent, and ffmpeg's atempo filter cannot exceed 2x
    per instance anyway, so a sped-up track would need chaining for little
    benefit on a feed nobody listens to.

    Returns (ok: bool, result: str) - result is the output path on success,
    or a human-readable error message on failure. Never raises: a timelapse
    request is a convenience feature and must not crash its caller.
    """
    src = Path(input_path)
    if not src.exists() or not src.is_file():
        return False, f"input not found: {src}"

    speed = clamp_speed(speed)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg_path(), "-y", "-i", str(src),
        "-an",
        "-vf", f"setpts=PTS/{speed}",
        "-c:v", "libx264", "-crf", "28", "-preset", "veryfast",
        str(out),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"ffmpeg timed out after {timeout}s"
    except OSError as exc:
        return False, f"could not run ffmpeg: {exc}"

    if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        stderr_tail = (proc.stderr or "")[-500:]
        return False, f"ffmpeg failed (rc={proc.returncode}): {stderr_tail}"

    return True, str(out)
