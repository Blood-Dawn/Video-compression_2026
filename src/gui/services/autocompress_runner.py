"""
src/gui/services/autocompress_runner.py

Auto-compress background daemon (R3.1b).

An opt-in service that watches a folder and compresses any video that lands in
it (the live-surveillance "save -> compress" use case), plus a one-shot batch
pass over a folder of existing clips. It is the live-save engine for the
AUTO-COMPRESS tab and NEVER starts on app launch - the user toggles it on.

It deliberately REUSES the hardened watch-folder engine in
``utils.watchfolder`` for the hard parts (candidate discovery, partial-write
stability, the ``.ingested`` / ``.processing`` sentinels and crash-resume,
the export-layout profiles, camera-id derivation, preset resolution). It does
NOT reimplement file watching. On top of that it adds the auto-compress
behaviour the watch-folder CLI does not have:

  * skip anything already compressed (``compressed_index.is_compressed``) or
    that is itself a compressed output (``compressed_index.classify``), so it
    never recompresses a clip twice and never recompresses its own outputs;
  * write outputs into ``<output_dir>/compressed/`` (kept out of the watched
    source set) and record the source -> output mapping in the index so the
    Library "Compressed" view can find them;
  * verify each output is a valid container (ffprobe) before trusting it;
  * an OPT-IN ``delete_original_after_compress`` flag (default OFF) that deletes
    the source ONLY AFTER a verified, recorded output exists - never before,
    never if the output is missing/zero-bytes, never anything outside the
    watched source folder, and never anything inside ``compressed/``.

Threading mirrors ``pipeline_runner``: a single daemon thread plus a stop
event, both rebindable module globals.

Author: Bloodawn (KheivenD), 2026-06-06 (R3.1b - auto-compress service).
"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import List, Optional

try:
    from gui.logging_setup import log
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.logging_setup import log

try:
    from utils import watchfolder as wf
    from utils import compressed_index as cidx
    from utils.ffmpeg import ffprobe_path
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils import watchfolder as wf
    from src.utils import compressed_index as cidx
    from src.utils.ffmpeg import ffprobe_path

try:
    from pipeline.pipeline import run_pipeline
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.pipeline.pipeline import run_pipeline


# The default mode auto-compress uses when no preset is chosen (owner decision:
# mode0 = record every frame, the safest default for surveillance footage).
DEFAULT_MODE = "mode0"
# One output per source file: a large segment window means a normal clip lands
# as a single compressed file rather than being split.
_SEGMENT_SECONDS = 3600
# Keep the whole clip - do not drop a warm-up window from a saved recording.
_WARMUP_FRAMES = 0
# How many recent compressions to surface in the status panel.
_RECENT_CAP = 25

# ── Rebindable handles (mirror pipeline_runner) ───────────────────────────────
_ac_thread: Optional[threading.Thread] = None
_ac_stop: Optional[threading.Event] = None

# Live status, guarded by its own lock so /status never blocks the scan loop.
_ac_lock = threading.Lock()
_ac_status = {
    "running": False,
    "folder": "",
    "output_dir": "",
    "mode": DEFAULT_MODE,
    "preset": None,
    "profile": None,
    "delete_original": False,
    "queue": 0,
    "recent": [],          # list of {source, output, when, preset, mode}
    "last_error": None,
    "scans": 0,
    "compressed_total": 0,
    # Batch progress for the current scan pass (R4 Phase 1 - "file N of M").
    # NN/g: waits >= 10s need determinate progress; a batch pass is exactly
    # that, so the UI shows "file <batch_done+1> of <batch_total>: <name>".
    "batch_total": 0,
    "batch_done": 0,
    "current_file": "",
}


# ── small helpers ─────────────────────────────────────────────────────────────

def _is_within(child: Path, parent: Path) -> bool:
    """True if ``child`` is the same as or nested under ``parent`` (resolved)."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def _verify_output(path: Path) -> bool:
    """True only if ``path`` is a non-empty file with a decodable video stream.

    Used as the safety gate before recording an output (and before any optional
    delete of the original). A best-effort ffprobe failure means "not verified".
    """
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return False
    except OSError:
        return False
    try:
        proc = subprocess.run(
            [ffprobe_path(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return proc.returncode == 0 and "video" in (proc.stdout or "")
    except (OSError, subprocess.SubprocessError):
        return False


def _record_recent(entry: dict) -> None:
    with _ac_lock:
        _ac_status["recent"].insert(0, entry)
        del _ac_status["recent"][_RECENT_CAP:]
        _ac_status["compressed_total"] += 1


def _encode_kwargs_for(video_path: Path, mode: str, preset: Optional[str]) -> dict:
    """Resolve the run_pipeline encode kwargs for one file.

    An explicit preset wins (resolved via the watch-folder helper, which returns
    mode/crf/background_crf/codec/object_filter). Otherwise we pass the chosen
    default mode and let the pipeline pick that mode's default codec.
    """
    if preset:
        kwargs, chosen = wf._resolve_encode_config(video_path, auto_preset=False, preset=preset)
        if chosen:
            return kwargs
    return {"mode": mode or DEFAULT_MODE}


# ── per-file processing ───────────────────────────────────────────────────────

def _process_one(
    src: Path,
    output_dir: str,
    mode: str,
    preset: Optional[str],
    delete_original: bool,
    watch_root: Path,
    stop_event: Optional[threading.Event] = None,
) -> Optional[dict]:
    """Compress one already-stable source file. Returns the recorded entry or None.

    Skips (returns None) if the file is already compressed or is itself a
    compressed output. On a successful, ffprobe-verified output it records the
    source -> output mapping and, only then and only if opted in, safely deletes
    the original.
    """
    src = src.resolve()
    comp_dir = cidx.compressed_subdir(output_dir)

    # Never recompress our own outputs or a clip we already did.
    if _is_within(src, comp_dir) or cidx.classify(src) == "compressed":
        return None
    if cidx.is_compressed(src):
        return None

    encode_kwargs = _encode_kwargs_for(src, mode, preset)
    camera_id = wf._build_camera_id(src, "auto")

    # Source size before anything happens (the original may be deleted later),
    # so the batch job-history entry can report real space savings.
    try:
        src_bytes = src.stat().st_size
    except OSError:
        src_bytes = 0

    # Snapshot the output folder so we can identify exactly what this run wrote.
    before = {p.resolve() for p in comp_dir.glob("*") if p.is_file()}

    wf._mark_processing(src)
    try:
        run_pipeline(
            input_source=str(src),
            camera_id=camera_id,
            output_dir=str(comp_dir),
            segment_seconds=_SEGMENT_SECONDS,
            bg_method="MOG2",
            warmup_frames=_WARMUP_FRAMES,
            stop_event=stop_event,
            **encode_kwargs,
        )
    except Exception as exc:  # noqa: BLE001
        # Leave the .processing marker so the next scan retries (crash-resume).
        log.error("Auto-compress failed for %s: %s", src.name, exc)
        with _ac_lock:
            _ac_status["last_error"] = f"{src.name}: {exc}"
        return None

    # SEC-011: if the run was interrupted (daemon stop / shutdown), the output
    # may be a partial-but-still-decodable clip. NEVER record it or delete the
    # original on an interrupted run - leave the .processing marker so a later
    # scan re-encodes the full clip. This is the footage-loss guard.
    if stop_event is not None and stop_event.is_set():
        log.info("Auto-compress interrupted mid-encode for %s; not recording or "
                 "deleting (will retry).", src.name)
        return None

    # Identify the produced output. SEC-012: only count NEW files this run wrote
    # whose name carries THIS source's camera_id, so a concurrent/leftover file
    # in compressed/ can never be mis-attributed as this source's output (and
    # then gate its deletion).
    after = {p.resolve() for p in comp_dir.glob("*") if p.is_file()}
    new_files = [
        p for p in (after - before)
        if p.suffix.lower() in wf.SUPPORTED_EXTENSIONS and p.name.startswith(camera_id)
    ]
    new_files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

    # This file has now been attempted; mark it ingested so it is not retried in
    # a loop regardless of whether it produced output (e.g. an ROI mode on a
    # motionless clip can legitimately produce nothing).
    wf._mark_ingested(src)
    wf._clear_processing(src)

    if not new_files:
        log.info("Auto-compress produced no output for %s (nothing to compress).", src.name)
        return None

    output = new_files[0]
    if not _verify_output(output):
        log.warning("Auto-compress output failed verification: %s", output.name)
        with _ac_lock:
            _ac_status["last_error"] = f"unverified output for {src.name}"
        return None

    entry = cidx.record(src, output, preset=preset, mode=encode_kwargs.get("mode", mode))
    log.info("Auto-compressed %s -> %s", src.name, output.name)

    if delete_original:
        _safe_delete_original(src, output, comp_dir, watch_root)

    try:
        out_bytes = output.stat().st_size
    except OSError:
        out_bytes = 0
    record = {
        "source": str(src), "output": str(output.resolve()),
        "when": entry.get("when"), "preset": preset,
        "mode": encode_kwargs.get("mode", mode),
        "src_bytes": src_bytes, "out_bytes": out_bytes,
    }
    _record_recent(record)
    return record


def _safe_delete_original(src: Path, output: Path, comp_dir: Path, watch_root: Path) -> bool:
    """Delete the source ONLY when every safety condition holds. Returns success.

    Guards (all must pass): a verified, non-empty output exists; the source is
    under the watched folder; the source is NOT inside ``compressed/``. This is
    the last line before an irreversible delete - it re-checks the output on disk
    rather than trusting the caller.
    """
    try:
        if not output.is_file() or output.stat().st_size == 0:
            return False
        if _is_within(src, comp_dir):
            return False
        if not _is_within(src, watch_root):
            return False
        src.unlink()
        # Tidy the sentinels the now-deleted original left behind.
        for suffix in (wf.INGESTED_SUFFIX, wf.PROCESSING_SUFFIX):
            try:
                src.with_suffix(src.suffix + suffix).unlink()
            except OSError:
                pass
        log.info("Deleted original after verified compress: %s", src.name)
        return True
    except OSError as exc:
        log.warning("Could not delete original %s: %s", src.name, exc)
        return False


# ── one scan pass ─────────────────────────────────────────────────────────────

def scan_once(
    folder: str,
    output_dir: str,
    mode: str = DEFAULT_MODE,
    preset: Optional[str] = None,
    profile: Optional[str] = None,
    delete_original: bool = False,
    settle_seconds: Optional[float] = None,
    stable_checks: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
) -> List[dict]:
    """Scan ``folder`` once and compress every new, stable, uncompressed clip.

    Returns the list of entries compressed in this pass. Reuses the watch-folder
    engine for discovery + stability; layout (recursive scan, stability tuning)
    comes from the named ``profile`` when given.
    """
    watch_root = Path(folder).resolve()
    if not watch_root.is_dir():
        return []

    prof = wf.WATCHFOLDER_PROFILES.get(profile) if profile else None
    recursive = prof.recursive if prof else False
    if settle_seconds is None:
        settle_seconds = prof.settle_seconds if prof else 1.0
    if stable_checks is None:
        stable_checks = prof.stable_checks if prof else 2

    comp_dir = cidx.compressed_subdir(output_dir)
    walker = watch_root.rglob("*") if recursive else watch_root.iterdir()
    candidates = []
    for f in walker:
        try:
            if not (f.is_file() and f.suffix.lower() in wf.SUPPORTED_EXTENSIONS):
                continue
        except OSError:
            continue
        if wf._already_ingested(f):
            continue
        if _is_within(f, comp_dir) or cidx.classify(f) == "compressed":
            continue
        if cidx.is_compressed(f):
            continue
        candidates.append(f)

    with _ac_lock:
        _ac_status["queue"] = len(candidates)
        _ac_status["scans"] += 1
        _ac_status["batch_total"] = len(candidates)
        _ac_status["batch_done"] = 0
        _ac_status["current_file"] = ""
        # Snapshot so only an error raised DURING this pass is attributed to it.
        _err_before = _ac_status.get("last_error")

    pass_started = time.time()
    attempted = 0
    done: List[dict] = []
    for f in candidates:
        if stop_event is not None and stop_event.is_set():
            break
        if not wf._is_fully_written(f, settle_seconds, stable_checks):
            log.info("Auto-compress skipping (still writing): %s", f.name)
            with _ac_lock:
                _ac_status["batch_done"] += 1
            continue
        with _ac_lock:
            _ac_status["current_file"] = f.name
        attempted += 1
        entry = _process_one(f, output_dir, mode, preset, delete_original,
                             watch_root, stop_event=stop_event)
        if entry:
            done.append(entry)
        with _ac_lock:
            _ac_status["queue"] = max(0, _ac_status["queue"] - 1)
            _ac_status["batch_done"] += 1
    with _ac_lock:
        _ac_status["queue"] = 0
        _ac_status["batch_total"] = 0
        _ac_status["batch_done"] = 0
        _ac_status["current_file"] = ""
        _err_after = _ac_status.get("last_error")
    pass_error = _err_after if _err_after != _err_before else None

    # One job-history entry per pass that actually attempted work (idle polls
    # of an empty/settled folder do not spam the history). R4 Phase 1.
    if attempted > 0:
        _record_batch_job(watch_root, pass_started, attempted, done,
                          stop_event, pass_error)
    return done


def _record_batch_job(watch_root, pass_started, attempted, done,
                      stop_event, pass_error) -> None:
    """Persist one batch pass to the job history. Best effort, never raises."""
    try:
        try:
            from gui.services import job_history
        except ModuleNotFoundError:  # pragma: no cover - import path shim
            from src.gui.services import job_history
        stopped = stop_event is not None and stop_event.is_set()
        failed = attempted - len(done)
        job_history.record_job(
            "autocompress",
            label=str(watch_root),
            started_at=pass_started,
            ended_at=time.time(),
            status="stopped" if stopped else "completed",
            counts={"files": attempted, "compressed": len(done),
                    "skipped": failed},
            bytes_in=sum(int(e.get("src_bytes", 0) or 0) for e in done),
            bytes_out=sum(int(e.get("out_bytes", 0) or 0) for e in done),
            error=pass_error if failed else None,
        )
    except Exception:  # noqa: BLE001 - history must never break the daemon
        pass


# ── daemon thread ─────────────────────────────────────────────────────────────

def _run_autocompress_thread(config: dict, stop_event: threading.Event) -> None:
    """Daemon target: scan the watched folder on a poll loop until stopped."""
    folder = config.get("folder", "")
    output_dir = config.get("output_dir", "")
    mode = config.get("mode", DEFAULT_MODE)
    preset = config.get("preset")
    profile = config.get("profile")
    delete_original = bool(config.get("delete_original", False))
    poll_interval = max(2, int(config.get("poll_interval", 10)))

    with _ac_lock:
        _ac_status.update({
            "running": True, "folder": folder, "output_dir": output_dir,
            "mode": mode, "preset": preset, "profile": profile,
            "delete_original": delete_original, "last_error": None,
        })

    log.info("Auto-compress started. Watching %s -> %s/compressed (mode=%s, delete_original=%s)",
             folder, output_dir, mode, delete_original)
    try:
        while not stop_event.is_set():
            try:
                scan_once(folder, output_dir, mode=mode, preset=preset,
                          profile=profile, delete_original=delete_original,
                          stop_event=stop_event)
            except Exception as exc:  # noqa: BLE001 - a bad scan must not kill the daemon
                log.error("Auto-compress scan error: %s", exc, exc_info=True)
                with _ac_lock:
                    _ac_status["last_error"] = str(exc)
            # Sleep in short slices so a stop is honoured promptly.
            for _ in range(poll_interval * 2):
                if stop_event.is_set():
                    break
                time.sleep(0.5)
    finally:
        with _ac_lock:
            _ac_status["running"] = False
            _ac_status["queue"] = 0
        log.info("Auto-compress stopped.")


# ── public start/stop/status ──────────────────────────────────────────────────

def is_running() -> bool:
    return bool(_ac_thread and _ac_thread.is_alive())


def start_autocompress(config: dict) -> bool:
    """Start the daemon with ``config``. Returns False if already running.

    Persists the auto-compress config (folder/mode/on-intent/delete flag) via
    gui_state_persist so it survives a restart - but the daemon is only ever
    started here, on an explicit user toggle, never on app launch.
    """
    global _ac_thread, _ac_stop
    if is_running():
        return False

    _persist_config(config, enabled=True)

    _ac_stop = threading.Event()
    _ac_thread = threading.Thread(
        target=_run_autocompress_thread, args=(config, _ac_stop),
        name="autocompress", daemon=True,
    )
    _ac_thread.start()
    return True


def stop_autocompress() -> bool:
    """Signal the daemon to stop. Returns False if it was not running."""
    global _ac_thread, _ac_stop
    if not is_running():
        return False
    if _ac_stop is not None:
        _ac_stop.set()
    _persist_config(get_status(), enabled=False)
    return True


def get_status() -> dict:
    """Return a snapshot of the current auto-compress status.

    Includes ``saved`` - the persisted config (folder / mode / preset / profile /
    delete-original / enabled intent) - so the UI can restore the form on load
    without a separate endpoint, even when the daemon is not running.
    """
    with _ac_lock:
        snap = dict(_ac_status)
        snap["recent"] = list(_ac_status["recent"])
        snap["running"] = is_running()
    try:
        try:
            from gui.services.gui_state_persist import get_autocompress_config
        except ModuleNotFoundError:  # pragma: no cover - import path shim
            from src.gui.services.gui_state_persist import get_autocompress_config
        snap["saved"] = get_autocompress_config()
    except Exception:  # noqa: BLE001
        snap["saved"] = {}
    return snap


def _persist_config(config: dict, enabled: bool) -> None:
    """Best-effort persist of the auto-compress config (never raises)."""
    try:
        try:
            from gui.services.gui_state_persist import set_autocompress_config
        except ModuleNotFoundError:  # pragma: no cover - import path shim
            from src.gui.services.gui_state_persist import set_autocompress_config
        set_autocompress_config({
            "folder": config.get("folder", ""),
            "output_dir": config.get("output_dir", ""),
            "mode": config.get("mode", DEFAULT_MODE),
            "preset": config.get("preset"),
            "profile": config.get("profile"),
            "delete_original": bool(config.get("delete_original", False)),
            "enabled": bool(enabled),
        })
    except Exception:  # noqa: BLE001 - persistence is best effort
        pass
