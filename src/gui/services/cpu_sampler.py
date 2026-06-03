"""
src/gui/services/cpu_sampler.py

CPU / RAM / battery sampling threads, extracted from gui/app.py (TASK 1.2).

Two samplers share gui.state._power_state (under _power_lock):
  * the always-on background sampler (start_hw_sampler) keeps the dashboard
    hardware strip live even when idle;
  * the per-pipeline sampler (_start_cpu_sampler/_stop_cpu_sampler) runs only
    during an encode, labels samples by mode, and stamps a per-clip
    cpu_stats.json next to that run's segments.

The always-on sampler used to start at *import* time, which spawned a thread
merely by importing the module (bad for tests and PyInstaller). It is now an
explicit start_hw_sampler() invoked from gui.app.create_app().

Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — cpu-sampler extraction,
explicit hw-sampler start).
"""

import json
import threading
import time
from pathlib import Path

try:
    import psutil as _psutil
    _PSUTIL_OK = True
except ImportError:
    _psutil = None       # type: ignore
    _PSUTIL_OK = False

try:
    from gui.state import _power_lock, _power_state
    from gui.logging_setup import log
except ModuleNotFoundError:                # pragma: no cover - import path shim
    from src.gui.state import _power_lock, _power_state
    from src.gui.logging_setup import log

try:
    from utils import paths as _paths
except ModuleNotFoundError:                # pragma: no cover - import path shim
    from src.utils import paths as _paths

# ── Per-pipeline sampler state ─────────────────────────────────────────────────
_cpu_sampler_thread: threading.Thread | None = None
_cpu_sampler_stop = threading.Event()

# Always-on hardware sampler handle (started by start_hw_sampler()).
_bg_hw_thread: threading.Thread | None = None

# Per-mode CPU benchmarks live here so they persist across server
# restarts. Now stored under the platform app-data dir alongside the
# Flask secret; was previously in the repo root, which broke any real
# installer because Program Files / /Applications are read-only.
# Author: Bloodawn (KheivenD), 2026-05-14 (installer prep, was 2026-05-03).
_MODE_AVG_FILE = _paths.state_file("mode_cpu_avgs.json")
try:
    if _MODE_AVG_FILE.exists():
        _saved_avgs = json.loads(_MODE_AVG_FILE.read_text())
        if isinstance(_saved_avgs, dict):
            with _power_lock:
                # Sanity-check structure — only accept entries that look
                # like {"cpu_sum": x, "n": y, "avg": z}
                for k, v in _saved_avgs.items():
                    if (isinstance(v, dict)
                        and "cpu_sum" in v and "n" in v and "avg" in v
                        and isinstance(v["n"], int) and v["n"] > 0):
                        _power_state["mode_avgs"][k] = v
except Exception as _exc:  # noqa: BLE001
    # Corrupt file — ignore, will be overwritten on next sampler stop
    pass


def _cpu_sampler_loop(mode_key: str, output_dir: str | None = None) -> None:
    """Background thread: sample CPU/RAM/battery every 2 s while pipeline runs.

    On stop, writes a per-clip ``cpu_stats.json`` into ``output_dir`` so
    the metrics tab can show the CPU% for *this specific* recording
    instead of a global rolling average. The global mode_avgs dict is
    still updated (for backward compat / fleet-level view) but the
    detail panel reads the per-clip file.
    Author: Bloodawn (KheivenD), 2026-05-03 (per-clip CPU stats).
    """
    samples: list[float] = []
    started_at = time.time()
    while not _cpu_sampler_stop.is_set():
        try:
            cpu = _psutil.cpu_percent(interval=1.0)   # 1-s blocking measurement
            mem = _psutil.virtual_memory()
            bat = _psutil.sensors_battery() if hasattr(_psutil, "sensors_battery") else None

            with _power_lock:
                _power_state["cpu_pct"]      = cpu
                _power_state["ram_pct"]      = mem.percent
                _power_state["ram_used_mb"]  = mem.used // (1024 * 1024)
                _power_state["ram_total_mb"] = mem.total // (1024 * 1024)

                if bat is not None:
                    _power_state["battery_pct"]     = round(bat.percent, 1)
                    _power_state["battery_plugged"] = bat.power_plugged
                    # secsleft: -1 = unknown, -2 = plugged in
                    sl = getattr(bat, "secsleft", -1)
                    _power_state["battery_mins_left"] = round(sl / 60, 1) if sl > 0 else None
                else:
                    _power_state["battery_pct"]     = None
                    _power_state["battery_plugged"] = None
                    _power_state["battery_mins_left"] = None

            samples.append(cpu)

        except Exception:
            pass
        # Non-blocking 1-s wait so we can stop promptly
        _cpu_sampler_stop.wait(timeout=1.0)

    # Session ended — update per-mode running average and persist it so
    # the benchmark survives server restarts (was previously lost every
    # time the user closed the app).
    # Author: Bloodawn (KheivenD), 2026-05-03 (cpu-by-mode persistence).
    if samples:
        ended_at = time.time()
        clip_avg = round(sum(samples) / len(samples), 1)
        clip_max = round(max(samples), 1)
        clip_min = round(min(samples), 1)
        with _power_lock:
            avgs = _power_state["mode_avgs"]
            prev = avgs.get(mode_key, {"cpu_sum": 0.0, "n": 0, "avg": 0.0})
            new_n   = prev["n"] + len(samples)
            new_sum = prev["cpu_sum"] + sum(samples)
            avgs[mode_key] = {
                "cpu_sum": new_sum,
                "n":       new_n,
                "avg":     round(new_sum / new_n, 1),
            }
            # Snapshot for write-out below
            snapshot = {k: dict(v) for k, v in avgs.items()}
        # Persist global running avg outside the lock
        try:
            _MODE_AVG_FILE.parent.mkdir(parents=True, exist_ok=True)
            _MODE_AVG_FILE.write_text(json.dumps(snapshot, indent=2))
        except Exception as exc:  # noqa: BLE001
            log.debug("Could not persist mode_avgs: %s", exc)
        # Per-clip stats: this is what the metrics detail panel reads.
        # Author: Bloodawn (KheivenD), 2026-05-03 (per-clip CPU stats).
        if output_dir:
            try:
                stats_path = Path(output_dir) / "cpu_stats.json"
                stats_path.parent.mkdir(parents=True, exist_ok=True)
                stats_path.write_text(json.dumps({
                    "mode":       mode_key,
                    "avg":        clip_avg,
                    "max":        clip_max,
                    "min":        clip_min,
                    "samples":    len(samples),
                    "started_at": started_at,
                    "ended_at":   ended_at,
                    "duration_s": round(ended_at - started_at, 1),
                }, indent=2))
                log.info("CPU stats for %s: avg=%.1f%% max=%.1f%% n=%d → %s",
                         mode_key, clip_avg, clip_max, len(samples), stats_path)
            except Exception as exc:  # noqa: BLE001
                log.debug("Could not write per-clip cpu_stats.json: %s", exc)


def _start_cpu_sampler(mode_key: str, output_dir: str | None = None) -> None:
    """Spawn the background CPU sampler.

    ``output_dir`` is the folder where the pipeline is writing this run's
    segments — the sampler stamps a ``cpu_stats.json`` there on stop so
    the metrics tab can show CPU% for THIS clip rather than a global
    rolling average.
    Author: Bloodawn (KheivenD), 2026-05-03 (per-clip CPU stats).
    """
    global _cpu_sampler_thread
    if not _PSUTIL_OK:
        return
    _cpu_sampler_stop.clear()
    _cpu_sampler_thread = threading.Thread(
        target=_cpu_sampler_loop,
        args=(mode_key, output_dir),
        daemon=True,
        name="cpu-sampler",
    )
    _cpu_sampler_thread.start()


def _stop_cpu_sampler() -> None:
    _cpu_sampler_stop.set()
    if _cpu_sampler_thread is not None:
        _cpu_sampler_thread.join(timeout=4)


def _bg_hw_sampler_loop() -> None:
    """Always-on background thread: samples CPU/RAM/battery every 2 s.

    This ensures /api/system_metrics always returns fresh data without doing a
    blocking cpu_percent() call in the request handler.  The per-pipeline
    _cpu_sampler_loop continues to run during pipeline execution and handles
    per-mode averages; this thread simply keeps _power_state current at all
    times so the dashboard strip is live even when idle.
    """
    if not _PSUTIL_OK:
        return
    # Prime psutil so the first sample isn't 0.0
    _psutil.cpu_percent(interval=None)
    while True:
        try:
            cpu = _psutil.cpu_percent(interval=1.0)
            mem = _psutil.virtual_memory()
            bat = _psutil.sensors_battery() if hasattr(_psutil, "sensors_battery") else None
            with _power_lock:
                _power_state["cpu_pct"]      = cpu
                _power_state["ram_pct"]      = mem.percent
                _power_state["ram_used_mb"]  = mem.used // (1024 * 1024)
                _power_state["ram_total_mb"] = mem.total // (1024 * 1024)
                if bat is not None:
                    _power_state["battery_pct"]      = round(bat.percent, 1)
                    _power_state["battery_plugged"]  = bat.power_plugged
                    sl = getattr(bat, "secsleft", -1)
                    _power_state["battery_mins_left"] = round(sl / 60, 1) if sl > 0 else None
                else:
                    _power_state["battery_pct"]      = None
                    _power_state["battery_plugged"]  = None
                    _power_state["battery_mins_left"] = None
        except Exception:
            pass
        # cpu_percent(interval=1.0) already blocks for 1 s; sleep 1 more → 2 s cadence
        import time as _time
        _time.sleep(1.0)


def start_hw_sampler() -> None:
    """Start the always-on hardware sampler (idempotent).

    Called from gui.app.create_app(). Previously this thread was started at
    import time; making it explicit keeps importing gui.app side-effect-free
    (no stray thread during tests / PyInstaller analysis).
    Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — explicit start).
    """
    global _bg_hw_thread
    if not _PSUTIL_OK:
        return
    if _bg_hw_thread is not None and _bg_hw_thread.is_alive():
        return
    _bg_hw_thread = threading.Thread(
        target=_bg_hw_sampler_loop, daemon=True, name="bg-hw-sampler",
    )
    _bg_hw_thread.start()
