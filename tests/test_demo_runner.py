"""
tests/test_demo_runner.py

Covers gui.services.demo_runner — the background demo worker and the
manifest -> result payload builder it feeds into _demo_state (read verbatim
by /api/demo/status and static/js/demo.js::_demoNotifyDone).

The _build_demo_result_from_manifest helper was undefined in the source tree
for a stretch (dropped in an earlier refactor), so any full demo run that
reached manifest-building raised NameError and reported
"Could not read manifest: name '_build_demo_result_from_manifest' is not
defined". These tests exercise that path against a synthetic manifest fixture
so the regression can't return silently.
"""

import json
from pathlib import Path

import demo.run_demo as run_demo_mod
from gui.services.demo_runner import (
    _build_demo_result_from_manifest,
    _run_demo_thread,
)
from gui.state import _demo_lock, _demo_state


def _make_manifest_run(output_root: Path) -> Path:
    """Create a synthetic demo_comp run folder + manifest.json under output_root.

    Mirrors the shape run_all_demos() writes: a stitched_dir containing the
    per-mode/per-view output videos and a demo_splitscreen*.mp4, plus a
    manifest.json describing them. Returns the manifest path.
    """
    run_dir = output_root / "demo_comp1"
    run_dir.mkdir(parents=True)

    # Real files on disk so the builder resolves them to playable URLs.
    mode0_video = run_dir / "demo_mode0_standard.mp4"
    mode2_video = run_dir / "demo_mode2_standard.mp4"
    splitscreen = run_dir / "demo_splitscreen_1.mp4"
    for f in (mode0_video, mode2_video, splitscreen):
        f.write_bytes(b"\x00\x00\x00\x18ftypmp42")  # token mp4 header bytes

    manifest = {
        "input": "input.mp4",
        "camera_id": "cam_00",
        "run_suffix": "1",
        "modes": ["mode0", "mode2"],
        "stitched_dir": str(run_dir),
        "outputs": {
            "mode0": {"standard": str(mode0_video)},
            # A view whose file does not exist -> must map to None, not crash.
            "mode2": {"standard": str(mode2_video), "roi_tint": str(run_dir / "missing.mp4")},
        },
        "metrics": {
            "mode0": {"compression_ratio": 1.0, "space_saved_pct": 0.0},
            "mode2": {"compression_ratio": 5.0, "space_saved_pct": 80.0},
        },
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def test_build_demo_result_shape(tmp_path):
    """The builder returns the dict shape the status route + demo.js expect."""
    manifest_path = _make_manifest_run(tmp_path)

    result = _build_demo_result_from_manifest(manifest_path)

    # Keys consumed by static/js/demo.js::_demoNotifyDone / _demoCollectPlayables.
    assert set(result) >= {"modes", "videos", "split_screen", "dir"}
    assert result["modes"] == ["mode0", "mode2"]
    assert result["dir"] == "demo_comp1"
    assert result["manifest_path"] == str(manifest_path)

    # videos: {mode: {view: url|None}}
    videos = result["videos"]
    assert set(videos) == {"mode0", "mode2"}
    assert videos["mode0"]["standard"].startswith("/api/media?path=")
    assert videos["mode2"]["standard"].startswith("/api/media?path=")
    # Missing file -> None rather than a dangling URL or KeyError.
    assert videos["mode2"]["roi_tint"] is None

    # split_screen discovered by globbing the stitched dir.
    assert result["split_screen"] is not None
    assert result["split_screen"].startswith("/api/media?path=")

    # metrics passed through verbatim for the dashboard demo viewer.
    assert result["metrics"]["mode2"]["space_saved_pct"] == 80.0


def test_build_demo_result_missing_splitscreen_is_none(tmp_path):
    """Single-mode runs have no split-screen file; the key must be None."""
    run_dir = tmp_path / "demo_comp1"
    run_dir.mkdir(parents=True)
    video = run_dir / "demo_mode0_standard.mp4"
    video.write_bytes(b"\x00")
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "modes": ["mode0"],
                "stitched_dir": str(run_dir),
                "outputs": {"mode0": {"standard": str(video)}},
                "metrics": {},
            }
        ),
        encoding="utf-8",
    )

    result = _build_demo_result_from_manifest(manifest_path)

    assert result["split_screen"] is None
    assert result["videos"]["mode0"]["standard"].startswith("/api/media?path=")


def test_run_demo_thread_builds_result_from_manifest(tmp_path, monkeypatch):
    """A full _run_demo_thread run reaches manifest-building without NameError.

    Replaces run_all_demos with a no-op (it would otherwise spawn ffmpeg and
    render real videos) and points output_root at a folder already containing
    a synthetic demo_comp manifest, exercising the locate-manifest -> build
    -> _demo_state["result"] tail end-to-end.
    """
    _make_manifest_run(tmp_path)

    def _fake_run_all_demos(**kwargs):  # noqa: ANN003 - test stub
        # run_all_demos normally renders + writes the manifest; the fixture
        # already provides one, so this is a no-op that just succeeds.
        return None

    monkeypatch.setattr(run_demo_mod, "run_all_demos", _fake_run_all_demos)

    config = {
        "input_path": "input.mp4",
        "output_root": str(tmp_path),
        "camera_id": "cam_00",
        "modes": ["mode0", "mode2"],
        "views": ["standard"],
    }

    _run_demo_thread(config)

    with _demo_lock:
        state = dict(_demo_state)

    assert state["status"] == "done"
    assert state["error"] is None
    result = state["result"]
    assert result is not None
    assert result["modes"] == ["mode0", "mode2"]
    assert result["dir"] == "demo_comp1"
    assert result["videos"]["mode0"]["standard"].startswith("/api/media?path=")
    assert result["split_screen"].startswith("/api/media?path=")
