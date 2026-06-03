"""
src/gui/services/demo_runner.py

Split-screen / multi-mode demo worker, extracted from gui/app.py (TASK 1.2).

`_run_demo_thread` runs run_all_demos() in a background thread, pushes progress
into gui.state._demo_state, and drives the per-mode CPU sampler so the metrics
tab's "CPU Usage by Mode" card populates from demo runs. The /api/demo* routes
(still in app.py until TASK 1.3) spawn and read this.

Imports gui.state (the shared demo dict + lock), gui.services.cpu_sampler (the
per-mode sampler hooks - an acyclic service->service dependency), and
gui.logging_setup.

Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - demo-runner extraction).
"""

import json
from pathlib import Path
from urllib.parse import quote

try:
    from gui.state import _demo_lock, _demo_state
    from gui.logging_setup import log
    from gui.services.cpu_sampler import _start_cpu_sampler, _stop_cpu_sampler
except ModuleNotFoundError:                # pragma: no cover - import path shim
    from src.gui.state import _demo_lock, _demo_state
    from src.gui.logging_setup import log
    from src.gui.services.cpu_sampler import _start_cpu_sampler, _stop_cpu_sampler


def _build_demo_result_from_manifest(manifest_path: Path) -> dict:
    """Build the GUI demo result payload from a stitched demo manifest.

    Reads the manifest.json written by run_all_demos() and assembles the dict
    that /api/demo/status returns (verbatim, via the shared _demo_state) and
    that static/js/demo.js's _demoNotifyDone() consumes. Required keys read by
    the frontend: ``modes``, ``videos`` ({mode: {view: url|None}}),
    ``split_screen`` (url|None) and ``dir`` (run folder name). ``metrics`` and
    ``manifest_path`` are passed through for the dashboard demo viewer.

    Mirrors the per-run shaping in routes/demo_bp.py::api_demo_history so a
    just-finished run and a historical run present an identical structure.

    Originally defined in gui/app.py; dropped during an earlier refactor, which
    left _run_demo_thread calling an undefined name (NameError on any full demo
    run). Restored here. -- 2026-06-02.
    """
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    videos: dict = {}
    for mode, view_map in manifest.get("outputs", {}).items():
        videos[mode] = {}
        for view, file_path in view_map.items():
            p = Path(file_path).resolve()
            videos[mode][view] = f"/api/media?path={quote(str(p))}" if p.exists() else None

    split_screen_url = None
    stitched_dir = Path(manifest.get("stitched_dir", ""))
    if stitched_dir.exists():
        for candidate in stitched_dir.glob("demo_splitscreen*.mp4"):
            split_screen_url = f"/api/media?path={quote(str(candidate.resolve()))}"
            break

    return {
        "manifest_path": str(manifest_path),
        "modes": manifest.get("modes", []),
        "videos": videos,
        "split_screen": split_screen_url,
        "metrics": manifest.get("metrics", {}),
        "dir": manifest_path.parent.name,
    }


def _run_demo_thread(config: dict) -> None:
    """Background thread: run multi-mode pipeline + render demo videos."""
    try:
        from demo.run_demo import run_all_demos          # noqa: E402
    except ModuleNotFoundError:
        from src.demo.run_demo import run_all_demos      # noqa: E402

    def _update(**kw):
        with _demo_lock:
            _demo_state.update(kw)

    def _progress_cb(message: str, detail: dict):
        """Receive step updates from run_all_demos and push to demo state.

        Also drives the per-mode CPU sampler so the "CPU Usage by Mode"
        card on the metrics tab actually populates from demo runs (was
        only hooked into /api/start, which the user rarely invokes).
        Author: Bloodawn (KheivenD), 2026-05-03 (cpu-by-mode demo wire-up).
        """
        phase = detail.get("phase", "")
        mode = detail.get("mode", "")
        mode_dir = detail.get("mode_dir", "")  # populated by run_demo as of 2026-05-03
        mode_index = detail.get("mode_index")
        mode_total = detail.get("mode_total")
        done       = detail.get("done", None)

        # Start sampler when entering a new mode's pipeline, stop when
        # the pipeline phase reports done. Ignore phase=="render"/"stitch"
        # - those are post-processing and shouldn't pollute the average.
        # Pass mode_dir so cpu_stats.json lands in THIS run's output folder.
        try:
            if phase == "pipeline" and mode and done is False:
                _start_cpu_sampler(mode, output_dir=mode_dir or None)
            elif phase == "pipeline" and mode and done is True:
                _stop_cpu_sampler()
            elif phase == "done":
                # Safety net in case the last "done=True" was missed
                _stop_cpu_sampler()
        except Exception as exc:  # noqa: BLE001
            log.debug("cpu sampler hook failed: %s", exc)

        # Build a concise progress string for the UI
        if mode_total and mode_index is not None:
            step_label = f"({mode_index + 1}/{mode_total})"
        else:
            step_label = ""

        _update(
            progress=message,
            demo_phase=phase,
            demo_mode=mode,
            demo_step=step_label,
        )
        log.debug("Demo progress [%s]: %s", phase, message)

    _update(
        status="running",
        progress="Starting demo…",
        demo_phase="start",
        demo_mode="",
        demo_step="",
        error=None,
        result=None,
    )

    try:
        run_all_demos(
            input_path=config["input_path"],
            output_root=config["output_root"],
            camera_id=config.get("camera_id", "cam_00"),
            modes=config["modes"],
            views=config.get("views", ["standard"]),
            no_boxes=config.get("no_boxes", False),
            no_tint=config.get("no_tint", False),
            progress_callback=_progress_cb,
        )
    except Exception as exc:
        log.error(f"Demo run failed: {exc}", exc_info=True)
        _update(running=False, status="error", error=str(exc))
        return

    _update(progress="Locating manifest…")

    # Find the manifest written by run_all_demos(). It picks a suffix to avoid
    # overwriting previous runs, so we glob for the newest one.
    output_root = Path(config["output_root"]).resolve()
    manifests = sorted(
        output_root.glob("demo_comp*/manifest.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not manifests:
        _update(running=False, status="error", error="manifest.json not found after demo run")
        return

    try:
        manifest_path = manifests[0]
        result = _build_demo_result_from_manifest(manifest_path)
    except Exception as exc:
        _update(running=False, status="error", error=f"Could not read manifest: {exc}")
        return
    _update(running=False, status="done", progress="Complete.", result=result)
    log.info(f"Demo run complete. Manifest: {manifest_path}")
