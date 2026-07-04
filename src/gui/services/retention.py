"""
src/gui/services/retention.py

Retention / disk-budget / auto-purge (R4 Phase 3 - docs/RESEARCH-COMPETITORS.md).

The #1 table-stakes gap vs every NVR (ZoneMinder PurgeWhenFull, Frigate per-tier
retain-days): SVCS produced 24/7 compressed footage with NOTHING bounding it on
disk. This adds a retention POLICY over the auto-compressed output and a purge
that enforces it, plus a free-disk/bitrate ESTIMATE of how many days of headroom
remain.

SAFETY FIRST - this deletes footage, so every guard is explicit:
  * operates ONLY inside the resolved ``<output_dir>/compressed`` subdir
    (confined via path_safety.is_within; never the drive root, never originals,
    never the watched source folders);
  * deletes only regular files with a known compressed-media/enc extension;
  * never touches a file modified within ``_FRESH_SECONDS`` (an in-flight or
    just-finished clip a writer may still hold open);
  * no-op when disabled or when both limits are 0 (unlimited);
  * every public function is best-effort and never raises - a retention error
    must never crash the auto-compress daemon or a route.

Author: Bloodawn (KheivenD), 2026-07-04 (R4 Phase 3 - retention).
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import List, Optional

try:
    from gui.logging_setup import log
    from gui.services import path_safety as _ps
    from gui.services import job_history as _jh
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.logging_setup import log
    from src.gui.services import path_safety as _ps
    from src.gui.services import job_history as _jh

try:
    from utils import compressed_index as cidx
    from utils import watchfolder as wf
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils import compressed_index as cidx
    from src.utils import watchfolder as wf

# A file modified within this window is considered possibly-open / just-written
# and is never purged, even if it is over-age. Cheap insurance against deleting
# a clip a writer still holds.
_FRESH_SECONDS = 120

# Extensions the purge is allowed to delete (compressed outputs + their .enc).
_PURGEABLE_EXTS = {ext.lower() for ext in wf.SUPPORTED_EXTENSIONS} | {".enc"}

# Bytes per GB for the size budget (decimal GB, matching disk-vendor sizing and
# the "days = disk / bitrate" math users expect).
_GB = 1_000_000_000

_DEFAULT_POLICY = {
    "enabled": False,
    "max_age_days": 0,      # 0 = no age limit
    "max_total_gb": 0.0,    # 0 = no size limit
}


# ── policy persistence (mirrors autocompress config in gui_state.json) ─────────

def get_policy() -> dict:
    """Return the persisted retention policy, merged over the defaults."""
    pol = dict(_DEFAULT_POLICY)
    try:
        try:
            from gui.services.gui_state_persist import get_retention_config
        except ModuleNotFoundError:  # pragma: no cover - import path shim
            from src.gui.services.gui_state_persist import get_retention_config
        saved = get_retention_config()
        if isinstance(saved, dict):
            pol.update({k: saved[k] for k in _DEFAULT_POLICY if k in saved})
    except Exception:  # noqa: BLE001
        pass
    pol["enabled"] = bool(pol.get("enabled"))
    pol["max_age_days"] = max(0, int(pol.get("max_age_days") or 0))
    try:
        pol["max_total_gb"] = max(0.0, float(pol.get("max_total_gb") or 0.0))
    except (TypeError, ValueError):
        pol["max_total_gb"] = 0.0
    return pol


def set_policy(cfg: dict) -> dict:
    """Validate + persist a retention policy. Returns the stored policy."""
    pol = get_policy()
    if isinstance(cfg, dict):
        if "enabled" in cfg:
            pol["enabled"] = bool(cfg["enabled"])
        if "max_age_days" in cfg:
            try:
                pol["max_age_days"] = max(0, min(3650, int(float(cfg["max_age_days"]))))
            except (TypeError, ValueError):
                pass
        if "max_total_gb" in cfg:
            try:
                pol["max_total_gb"] = max(0.0, min(1_000_000.0, float(cfg["max_total_gb"])))
            except (TypeError, ValueError):
                pass
    try:
        try:
            from gui.services.gui_state_persist import set_retention_config
        except ModuleNotFoundError:  # pragma: no cover - import path shim
            from src.gui.services.gui_state_persist import set_retention_config
        set_retention_config(pol)
    except Exception:  # noqa: BLE001
        pass
    return pol


# ── helpers ────────────────────────────────────────────────────────────────────

def _compressed_dir(output_dir: str) -> Optional[Path]:
    """Resolve ``<output_dir>/compressed`` WITHOUT creating it, with guards.

    Returns None if the path is missing, is a drive root, or somehow escapes the
    output dir - any of which means "refuse to purge".
    """
    try:
        base = Path(output_dir).resolve()
        comp = cidx.compressed_subdir(base, create=False).resolve()
    except (OSError, ValueError):
        return None
    if not comp.is_dir():
        return None
    # Must be strictly nested under the output dir and not a filesystem root.
    if comp == base or not _ps.is_within(comp, base):
        return None
    if comp.parent == comp:  # drive/filesystem root
        return None
    return comp


def _purgeable_files(comp_dir: Path) -> List[Path]:
    """Regular compressed-media files directly in / under comp_dir, resolved."""
    out: List[Path] = []
    try:
        for p in comp_dir.rglob("*"):
            try:
                if not p.is_file():
                    continue
            except OSError:
                continue
            suffix = p.suffix.lower()
            # An encrypted output is "<name>.mp4.enc": accept if either the .enc
            # or the underlying media extension is purgeable.
            media_ok = suffix in _PURGEABLE_EXTS or (
                suffix == ".enc" and p.with_suffix("").suffix.lower() in _PURGEABLE_EXTS)
            if media_ok:
                out.append(p.resolve())
    except OSError:
        pass
    return out


def _delete(path: Path, comp_dir: Path) -> int:
    """Delete one file after re-checking confinement. Returns bytes freed (0 on refusal)."""
    try:
        # Re-assert the file is still inside the compressed dir (TOCTOU guard).
        if not _ps.is_within(path, comp_dir):
            return 0
        size = path.stat().st_size
        path.unlink()
        return size
    except OSError as exc:
        log.warning("Retention: could not delete %s: %s", path.name, exc)
        return 0


# ── purge ──────────────────────────────────────────────────────────────────────

def purge_once(output_dir: str, policy: Optional[dict] = None,
               now: Optional[float] = None) -> dict:
    """Enforce the retention policy over ``<output_dir>/compressed`` once.

    Deletes over-age files first (by mtime), then, if a size budget is set and
    still exceeded, oldest-first until under budget. Prunes index entries whose
    output no longer exists. Returns a summary dict; never raises.
    """
    summary = {"ran": False, "deleted": 0, "freed_bytes": 0,
               "by_age": 0, "by_size": 0, "errors": []}
    try:
        pol = policy if policy is not None else get_policy()
        if not pol.get("enabled"):
            return summary
        max_age_days = int(pol.get("max_age_days") or 0)
        max_total_gb = float(pol.get("max_total_gb") or 0.0)
        if max_age_days <= 0 and max_total_gb <= 0:
            return summary  # nothing to enforce

        comp_dir = _compressed_dir(output_dir)
        if comp_dir is None:
            return summary
        summary["ran"] = True

        now = time.time() if now is None else now
        files = _purgeable_files(comp_dir)
        # (path, size, mtime), skipping too-fresh files entirely.
        stats = []
        for p in files:
            try:
                st = p.stat()
            except OSError:
                continue
            if now - st.st_mtime < _FRESH_SECONDS:
                continue
            stats.append((p, st.st_size, st.st_mtime))
        stats.sort(key=lambda t: t[2])  # oldest first

        deleted_paths = set()

        # 1) Age purge.
        if max_age_days > 0:
            cutoff = now - max_age_days * 86400
            for p, size, mtime in stats:
                if mtime < cutoff:
                    freed = _delete(p, comp_dir)
                    if freed or not p.exists():
                        deleted_paths.add(p)
                        summary["deleted"] += 1
                        summary["by_age"] += 1
                        summary["freed_bytes"] += freed

        # 2) Size purge (oldest-first) on what remains.
        if max_total_gb > 0:
            budget = max_total_gb * _GB
            remaining = [(p, s, m) for (p, s, m) in stats if p not in deleted_paths]
            total = sum(s for _, s, _ in remaining)
            for p, size, mtime in remaining:
                if total <= budget:
                    break
                freed = _delete(p, comp_dir)
                if freed or not p.exists():
                    deleted_paths.add(p)
                    summary["deleted"] += 1
                    summary["by_size"] += 1
                    summary["freed_bytes"] += freed
                    total -= size

        if deleted_paths:
            _prune_index()
            log.info("Retention: purged %d file(s), freed %.1f MB (age=%d, size=%d).",
                     summary["deleted"], summary["freed_bytes"] / 1e6,
                     summary["by_age"], summary["by_size"])
            _notify_purge(summary, output_dir)
    except Exception as exc:  # noqa: BLE001 - retention must never crash a caller
        summary["errors"].append(str(exc))
        log.error("Retention purge error: %s", exc, exc_info=True)
    return summary


def _prune_index() -> None:
    """Drop compressed-index entries whose output file no longer exists."""
    try:
        data = cidx._load()
        entries = data.get("entries", {})
        dead = [sig for sig, e in entries.items()
                if not Path(e.get("output", "")).is_file()]
        if dead:
            for sig in dead:
                entries.pop(sig, None)
            cidx._save(data)
    except Exception:  # noqa: BLE001 - best effort
        pass


def _notify_purge(summary: dict, output_dir: str) -> None:
    """Record the purge as a job-history entry so it shows in Recent Jobs."""
    try:
        _jh.record_job(
            "retention",
            label=str(cidx.compressed_subdir(output_dir, create=False)),
            status="completed",
            counts={"deleted": summary["deleted"],
                    "by_age": summary["by_age"], "by_size": summary["by_size"]},
            bytes_in=summary["freed_bytes"], bytes_out=0,
        )
    except Exception:  # noqa: BLE001
        pass


# ── estimate (days = disk / bitrate) ────────────────────────────────────────────

def estimate(output_dir: str, policy: Optional[dict] = None) -> dict:
    """Estimate retention headroom: free disk, current footage size, and days.

    The daily growth rate is taken from recent auto-compress job history
    (bytes_out over wall-clock span); if history is too thin it falls back to
    the compressed folder's own size spread over its age. Returns a dict with
    everything the UI needs; never raises.
    """
    out = {"available": False, "free_gb": None, "used_gb": None,
           "bytes_per_day": None, "est_days_headroom": None,
           "policy_days": None}
    try:
        base = Path(output_dir).resolve()
        try:
            usage = shutil.disk_usage(str(base if base.exists() else base.anchor or base))
            out["free_gb"] = round(usage.free / _GB, 2)
        except OSError:
            usage = None

        comp_dir = cidx.compressed_subdir(base, create=False)
        used = 0
        oldest = None
        newest = None
        if comp_dir.is_dir():
            for p in _purgeable_files(comp_dir.resolve()):
                try:
                    st = p.stat()
                except OSError:
                    continue
                used += st.st_size
                oldest = st.st_mtime if oldest is None else min(oldest, st.st_mtime)
                newest = st.st_mtime if newest is None else max(newest, st.st_mtime)
        out["used_gb"] = round(used / _GB, 2)

        bpd = _bytes_per_day_from_history()
        if bpd is None and used > 0 and oldest and newest and newest > oldest:
            span_days = max((newest - oldest) / 86400, 1.0 / 24)  # >= 1 hour
            bpd = used / span_days
        out["bytes_per_day"] = int(bpd) if bpd else None

        pol = policy if policy is not None else get_policy()
        if pol.get("enabled") and int(pol.get("max_age_days") or 0) > 0:
            out["policy_days"] = int(pol["max_age_days"])

        # Days of headroom: prefer the tighter of (size budget) and (free disk).
        if bpd and bpd > 0:
            headroom_bytes = None
            max_total_gb = float(pol.get("max_total_gb") or 0.0) if pol.get("enabled") else 0.0
            if max_total_gb > 0:
                headroom_bytes = max(0.0, max_total_gb * _GB - used)
            if usage is not None:
                disk_headroom = float(usage.free)
                headroom_bytes = disk_headroom if headroom_bytes is None else min(headroom_bytes, disk_headroom)
            if headroom_bytes is not None:
                out["est_days_headroom"] = round(headroom_bytes / bpd, 1)

        out["available"] = True
    except Exception as exc:  # noqa: BLE001
        log.debug("Retention estimate failed: %s", exc)
    return out


def _bytes_per_day_from_history() -> Optional[float]:
    """Recent auto-compress output throughput in bytes/day, or None if unknown."""
    try:
        jobs = [j for j in _jh.recent_jobs(limit=50)
                if j.get("kind") == "autocompress" and j.get("bytes_out")]
        if len(jobs) < 2:
            return None
        starts = [j["started_at"] for j in jobs if j.get("started_at")]
        ends = [j["ended_at"] for j in jobs if j.get("ended_at")]
        if not starts or not ends:
            return None
        span = max(ends) - min(starts)
        if span <= 0:
            return None
        total_out = sum(int(j.get("bytes_out") or 0) for j in jobs)
        return total_out / (span / 86400.0)
    except Exception:  # noqa: BLE001
        return None
