"""
src/compression/vmaf_target.py

VMAF-targeted rate control (R5 TASK 5.1). Design: docs/RESEARCH-VMAF-TARGET.md.

A fixed CRF spends fixed EFFORT, not fixed perceived QUALITY, so every clip is
either over-spent (wasted bytes) or under-spent. This module finds the smallest
file that still clears a perceptual quality floor: it sample-encodes a few short
segments of the source at candidate CRFs, measures VMAF with the existing
harness, interpolates, and returns the LARGEST CRF (smallest file) whose VMAF
still meets the target. Measured locally, holding VMAF ~91 instead of ~95.6 on
real footage costs 4.5 VMAF points and saves 2.8x the bytes.

This is the ab-av1 method (CRF search to a --min-vmaf over short samples).

Guarantees:
  * NEVER raises into the encode path and never hangs. If libvmaf/ffmpeg is
    missing, sampling fails, or the search cannot converge, it returns the
    caller's fixed CRF with a ``fallback_reason`` and the pipeline logs it.
  * The chosen CRF is cached by source signature + codec + preset + target, so
    a re-run of the same clip is instant.

Author: Bloodawn (KheivenD), 2026-07-16 (R5 TASK 5.1 - VMAF-targeted CRF).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from utils.ffmpeg import ffmpeg_path, ffmpeg_available
    from utils.metrics import compute_vmaf
    from utils import paths as _paths
    from utils.compressed_index import signature as _source_signature
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils.ffmpeg import ffmpeg_path, ffmpeg_available
    from src.utils.metrics import compute_vmaf
    from src.utils import paths as _paths
    from src.utils.compressed_index import signature as _source_signature

log = logging.getLogger(__name__)

# Target VMAF band. Below 85 artifacts become visible on the steep part of the
# curve; above 97 the bitrate cost explodes for no perceived gain.
TARGET_VMAF_MIN = 85.0
TARGET_VMAF_MAX = 97.0
DEFAULT_TARGET_VMAF = 93.0

# Codec CRF scales. AV1 encoders use 0-63, H.264/H.265 use 0-51.
_AV1_CODECS = {"libaom-av1", "libsvtav1", "av1", "av1_nvenc"}

# Search window: never probe absurd extremes even if the codec allows them.
_SEARCH_CRF_MIN = 14
_SEARCH_CRF_MAX_H264 = 46
_SEARCH_CRF_MAX_AV1 = 56

# Cost guards. Sampling scheme tuned against measurement, not guessed: sample
# VMAF reads slightly LOW versus the full clip, which makes the search reject a
# CRF the full clip would actually pass. Measured on parking_input.mp4 at CRF 22
# (full-clip VMAF 93.31):
#     3 x 2s -> sample 92.91 (bias -0.40), rejects the better CRF
#     4 x 3s -> sample 93.03 (bias -0.28), accepts it
#     5 x 4s -> sample 93.04 (bias -0.27), no gain for 67% more sampling
# So 4 x 3s: it halves the bias and recovers a CRF step worth ~20% file size,
# and more sampling buys nothing. The residual bias is CONSERVATIVE (samples
# under-read, so the search errs toward more quality, never less).
DEFAULT_SAMPLES = 4
DEFAULT_SAMPLE_SECONDS = 3.0
MAX_PROBES = 6

_CACHE_FILENAME = "vmaf_target_cache.json"
_MAX_CACHE_ENTRIES = 200
_cache_lock = threading.Lock()


@dataclass
class CrfSearchResult:
    """Outcome of a target-VMAF CRF search."""

    crf: int                              # the CRF to encode the full clip at
    target_vmaf: float
    measured_vmaf: Optional[float] = None  # VMAF of the samples at ``crf``
    probes: int = 0                        # sample encodes actually run
    cached: bool = False
    fallback_reason: Optional[str] = None  # set when the fixed CRF was kept
    measurements: List[Tuple[int, float]] = field(default_factory=list)

    @property
    def used_target(self) -> bool:
        """True when the search produced the CRF (not a fixed-CRF fallback)."""
        return self.fallback_reason is None


# ── helpers ───────────────────────────────────────────────────────────────────

def clamp_target(target: Optional[float]) -> float:
    """Clamp a requested VMAF target into the supported band."""
    try:
        t = float(target) if target is not None else DEFAULT_TARGET_VMAF
    except (TypeError, ValueError):
        return DEFAULT_TARGET_VMAF
    if t != t:  # NaN
        return DEFAULT_TARGET_VMAF
    return max(TARGET_VMAF_MIN, min(TARGET_VMAF_MAX, t))


def crf_bounds(codec: str) -> Tuple[int, int]:
    """The CRF search window for ``codec`` (AV1 uses a wider 0-63 scale)."""
    if (codec or "").lower() in _AV1_CODECS:
        return _SEARCH_CRF_MIN, _SEARCH_CRF_MAX_AV1
    return _SEARCH_CRF_MIN, _SEARCH_CRF_MAX_H264


def _cache_file() -> Path:
    # Resolved lazily so tests that patch utils.paths.state_file isolate it.
    return _paths.state_file(_CACHE_FILENAME)


def _cache_key(source, codec: str, preset: str, target: float,
               samples: int = DEFAULT_SAMPLES,
               sample_seconds: float = DEFAULT_SAMPLE_SECONDS) -> str:
    """Cache key for a search result.

    The SAMPLING SCHEME is part of the key on purpose: a different scheme
    measures a different VMAF and so can pick a different CRF. Without it, a
    tuning change to the defaults would keep silently serving CRFs found under
    the old scheme (observed during development: the 3x2s answer survived the
    move to 4x3s and masked the improvement).
    """
    return (f"{_source_signature(source)}|{codec}|{preset}|{target:.1f}"
            f"|{int(samples)}x{float(sample_seconds):.1f}")


def _cache_load() -> Dict[str, dict]:
    try:
        f = _cache_file()
        if not f.exists():
            return {}
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - an unreadable cache is just a miss
        return {}


def cache_get(source, codec: str, preset: str, target: float,
              samples: int = DEFAULT_SAMPLES,
              sample_seconds: float = DEFAULT_SAMPLE_SECONDS) -> Optional[dict]:
    with _cache_lock:
        return _cache_load().get(
            _cache_key(source, codec, preset, target, samples, sample_seconds))


def cache_put(source, codec: str, preset: str, target: float,
              crf: int, vmaf: Optional[float],
              samples: int = DEFAULT_SAMPLES,
              sample_seconds: float = DEFAULT_SAMPLE_SECONDS) -> None:
    try:
        with _cache_lock:
            data = _cache_load()
            data[_cache_key(source, codec, preset, target,
                            samples, sample_seconds)] = {
                "crf": int(crf), "vmaf": vmaf,
            }
            # Bound the file; drop arbitrary old entries once oversized.
            if len(data) > _MAX_CACHE_ENTRIES:
                for k in list(data)[: len(data) - _MAX_CACHE_ENTRIES]:
                    data.pop(k, None)
            f = _cache_file()
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001 - caching is best effort
        pass


def _probe_duration(source) -> Optional[float]:
    """Source duration in seconds via ffprobe, or None."""
    try:
        from utils.ffmpeg import ffprobe_path
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.utils.ffmpeg import ffprobe_path
    try:
        proc = subprocess.run(
            [ffprobe_path(), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(source)],
            capture_output=True, text=True, timeout=30,
        )
        d = float((proc.stdout or "").strip())
        return d if d > 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def sample_offsets(duration: float, samples: int, sample_seconds: float) -> List[float]:
    """Start offsets spread across the clip (not just the head).

    For 3 samples that is roughly 20%/50%/80% of the duration, pulled back so a
    sample never runs off the end. A clip shorter than one sample yields a single
    sample at 0.
    """
    if duration <= 0 or samples <= 0:
        return [0.0]
    usable = max(0.0, duration - sample_seconds)
    if usable <= 0:
        return [0.0]
    if samples == 1:
        return [usable / 2.0]
    # Evenly spaced interior points: i/(n+1) for i in 1..n.
    return [round(usable * (i + 1) / (samples + 1), 3) for i in range(samples)]


def _extract_sample(source, start: float, seconds: float, dest: Path) -> bool:
    """Cut one sample out of ``source``. Stream-copy first (exact source bits),
    fall back to a near-transparent re-encode for containers copy cannot cut."""
    base = [ffmpeg_path(), "-v", "error", "-nostdin", "-ss", str(start),
            "-t", str(seconds), "-i", str(source)]
    for tail in (["-c:v", "copy", "-an"],
                 ["-c:v", "libx264", "-crf", "10", "-preset", "veryfast", "-an"]):
        try:
            proc = subprocess.run(base + tail + [str(dest), "-y"],
                                  capture_output=True, timeout=120)
            if proc.returncode == 0 and dest.is_file() and dest.stat().st_size > 0:
                return True
        except (OSError, subprocess.SubprocessError):
            continue
        try:
            dest.unlink()
        except OSError:
            pass
    return False


def _encode_sample(sample: Path, crf: int, codec: str, preset: str, dest: Path) -> bool:
    """Encode one sample at ``crf`` with the codec/preset the real encode uses."""
    args = [ffmpeg_path(), "-v", "error", "-nostdin", "-i", str(sample),
            "-c:v", codec, "-crf", str(crf), "-an"]
    if (codec or "").lower() == "libsvtav1":
        args += ["-preset", "10"]
    elif (codec or "").lower() in ("libaom-av1", "av1"):
        args += ["-cpu-used", "8", "-row-mt", "1"]
    else:
        args += ["-preset", preset or "veryfast"]
    try:
        proc = subprocess.run(args + [str(dest), "-y"], capture_output=True, timeout=300)
        return proc.returncode == 0 and dest.is_file() and dest.stat().st_size > 0
    except (OSError, subprocess.SubprocessError):
        return False


def _measure_crf(samples: List[Path], crf: int, codec: str, preset: str,
                 workdir: Path) -> Optional[float]:
    """Mean VMAF across the samples encoded at ``crf``, or None on failure."""
    scores: List[float] = []
    for i, sample in enumerate(samples):
        dist = workdir / f"d_{crf}_{i}.mp4"
        if not _encode_sample(sample, crf, codec, preset, dist):
            return None
        score = compute_vmaf(str(sample), str(dist))
        try:
            dist.unlink()
        except OSError:
            pass
        if score is None:
            return None
        scores.append(float(score))
    return (sum(scores) / len(scores)) if scores else None


def interpolate_crf(measurements: List[Tuple[int, float]], target: float,
                    lo: int, hi: int) -> int:
    """Next CRF to probe: linear interpolation on the bracketing pair, else bisect.

    ``measurements`` are (crf, vmaf) pairs. Because VMAF decreases as CRF rises,
    the bracket is the highest-CRF point still above target and the lowest-CRF
    point below it. Pure function so the search logic is unit-testable without
    running any encodes.
    """
    above = [m for m in measurements if m[1] >= target]   # crf low side
    below = [m for m in measurements if m[1] < target]    # crf high side
    if above and below:
        c_lo, v_lo = max(above, key=lambda m: m[0])   # closest above target
        c_hi, v_hi = min(below, key=lambda m: m[0])   # closest below target
        if c_hi - c_lo <= 1:
            return c_lo                                # converged to adjacent
        # A bracket means v_lo >= target > v_hi, so (v_lo - v_hi) is strictly
        # positive and the interpolation cannot divide by zero.
        guess = c_lo + (v_lo - target) * (c_hi - c_lo) / (v_lo - v_hi)
        nxt = int(round(guess))
        # Keep the probe strictly inside the open bracket.
        return max(c_lo + 1, min(c_hi - 1, nxt))
    return (lo + hi) // 2


def find_crf_for_target(
    source,
    codec: str,
    fixed_crf: int,
    target_vmaf: Optional[float] = None,
    preset: str = "veryfast",
    samples: int = DEFAULT_SAMPLES,
    sample_seconds: float = DEFAULT_SAMPLE_SECONDS,
    max_probes: int = MAX_PROBES,
    use_cache: bool = True,
) -> CrfSearchResult:
    """Find the largest CRF (smallest file) whose sampled VMAF meets the target.

    Falls back to ``fixed_crf`` (with a reason) whenever the search cannot run.
    Never raises.
    """
    target = clamp_target(target_vmaf)
    lo, hi = crf_bounds(codec)
    result = CrfSearchResult(crf=int(fixed_crf), target_vmaf=target)

    try:
        src = Path(str(source))
        if not src.is_file():
            result.fallback_reason = "source is not a file"
            return result
        if not ffmpeg_available():
            result.fallback_reason = "ffmpeg unavailable"
            return result

        if use_cache:
            hit = cache_get(src, codec, preset, target, samples, sample_seconds)
            if hit and isinstance(hit.get("crf"), int):
                result.crf = int(hit["crf"])
                result.measured_vmaf = hit.get("vmaf")
                result.cached = True
                return result

        duration = _probe_duration(src) or 0.0
        offsets = sample_offsets(duration, samples, sample_seconds)

        workdir = Path(tempfile.mkdtemp(prefix="svcs_vmaf_target_"))
        try:
            cut: List[Path] = []
            for i, off in enumerate(offsets):
                dest = workdir / f"s{i}.mp4"
                if _extract_sample(src, off, sample_seconds, dest):
                    cut.append(dest)
            if not cut:
                result.fallback_reason = "could not extract samples"
                return result

            measurements: List[Tuple[int, float]] = []
            best: Optional[Tuple[int, float]] = None   # largest CRF meeting target
            probe_lo, probe_hi = lo, hi

            for _ in range(max(1, int(max_probes))):
                crf = interpolate_crf(measurements, target, probe_lo, probe_hi)
                crf = max(lo, min(hi, int(crf)))
                if any(m[0] == crf for m in measurements):
                    break                                   # already probed; converged
                vmaf = _measure_crf(cut, crf, codec, preset, workdir)
                if vmaf is None:
                    if not measurements:
                        result.fallback_reason = "VMAF measurement unavailable"
                        return result
                    break                                   # keep what we have
                measurements.append((crf, vmaf))
                result.probes += 1
                if vmaf >= target:
                    if best is None or crf > best[0]:
                        best = (crf, vmaf)
                    probe_lo = crf                          # can afford more CRF
                else:
                    probe_hi = crf                          # too far
                if probe_hi - probe_lo <= 1:
                    break

            result.measurements = measurements
            if best is not None:
                result.crf, result.measured_vmaf = best[0], best[1]
                if use_cache:
                    cache_put(src, codec, preset, target, best[0], best[1],
                              samples, sample_seconds)
                return result

            # Nothing met the target: fall back to the fixed CRF rather than
            # silently shipping a clip below the quality floor.
            result.fallback_reason = "no probed CRF met the target"
            return result
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001 - target mode must never break an encode
        log.warning("VMAF target search failed (%s); using fixed CRF %s.", exc, fixed_crf)
        result.crf = int(fixed_crf)
        result.fallback_reason = f"search error: {exc}"
        return result
