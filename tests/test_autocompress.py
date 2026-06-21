"""
tests/test_autocompress.py

Tests for the auto-compress service (R3.1b runner + blueprint).

These cover the auto-compress LOGIC with the encode step stubbed out (a fake
run_pipeline writes a placeholder output, and ffprobe verification is stubbed
True) so they are fast and need no ffmpeg: the skip/dedup rules, output landing
under ``compressed/`` with an index record, the opt-in delete-original safety
gates, and the HTTP endpoints. The end-to-end LIVE-SAVE behaviour with a real
clip (real run_pipeline + ffprobe) is added in R3.1e.

Author: Bloodawn (KheivenD), 2026-06-06 (R3.1b - auto-compress).
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.services import autocompress_runner as ac  # noqa: E402
from utils import compressed_index as cidx  # noqa: E402
from utils.ffmpeg import ffmpeg_path, ffprobe_path  # noqa: E402

ROOT = Path(__file__).parent.parent


def _mkvid(p: Path, data: bytes = b"v" * 500) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


@pytest.fixture()
def iso(tmp_path, monkeypatch):
    """Isolate the index + persistence, and stub the encode + verify steps.

    The fake run_pipeline writes ``<output_dir>/<camera_id>.mp4`` (a unique name
    per source, since the camera id derives from the file stem) so the runner's
    snapshot-diff sees a brand-new output for each clip.
    """
    # Index and gui-state both isolated to tmp.
    monkeypatch.setattr(cidx._paths, "state_file", lambda name: tmp_path / name)
    try:
        from gui.services import gui_state_persist as gsp
    except ModuleNotFoundError:  # pragma: no cover
        from src.gui.services import gui_state_persist as gsp
    monkeypatch.setattr(gsp, "_GUI_STATE_FILE", tmp_path / "gui_state.json")

    # Stub the encode: drop a placeholder file into the output (compressed) dir.
    def _fake_pipeline(input_source, camera_id, output_dir, **kw):
        out = Path(output_dir) / f"{camera_id}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"compressed-bytes")
        return None

    monkeypatch.setattr(ac, "run_pipeline", _fake_pipeline)
    # Verification is exercised separately; here trust a non-empty file.
    monkeypatch.setattr(ac, "_verify_output", lambda p: Path(p).is_file() and Path(p).stat().st_size > 0)
    return tmp_path


def _scan(folder, out, **kw):
    # Fast stability check (no real settle wait) for the synthetic files.
    kw.setdefault("settle_seconds", 0.0)
    kw.setdefault("stable_checks", 1)
    return ac.scan_once(str(folder), str(out), **kw)


def test_compresses_into_compressed_subdir_and_records(iso):
    watch = iso / "watch"
    out = iso / "out"
    src = _mkvid(watch / "clip.mp4")
    done = _scan(watch, out)
    assert len(done) == 1
    comp_dir = out / "compressed"
    produced = list(comp_dir.glob("*.mp4"))
    assert produced, "an output should land under compressed/"
    # The source -> output mapping is recorded so Library can find it.
    assert cidx.is_compressed(src) is True
    assert done[0]["output"] == str(produced[0].resolve())


def test_dedup_second_scan_compresses_nothing(iso):
    watch = iso / "watch"
    out = iso / "out"
    _mkvid(watch / "clip.mp4")
    assert len(_scan(watch, out)) == 1
    # Second pass: the clip is already compressed -> skipped.
    assert len(_scan(watch, out)) == 0


def test_never_recompresses_its_own_output(iso):
    # When the watched folder IS the output base, the compressed/ subtree must
    # be ignored so outputs are never fed back in.
    base = iso / "base"
    src = _mkvid(base / "clip.mp4")
    first = _scan(base, base)        # output base == watch folder
    assert len(first) == 1
    # A second scan sees the compressed/ output but must not recompress it.
    assert len(_scan(base, base)) == 0


def test_delete_original_off_keeps_source(iso):
    watch = iso / "watch"
    out = iso / "out"
    src = _mkvid(watch / "clip.mp4")
    _scan(watch, out, delete_original=False)
    assert src.exists(), "with delete_original OFF the source is never touched"


def test_delete_original_on_removes_source_after_verified_output(iso):
    watch = iso / "watch"
    out = iso / "out"
    src = _mkvid(watch / "clip.mp4")
    done = _scan(watch, out, delete_original=True)
    assert len(done) == 1
    assert not src.exists(), "with delete_original ON a verified compress removes the source"
    # The output still exists.
    assert Path(done[0]["output"]).is_file()


def test_safe_delete_refuses_outside_watch_root(iso):
    watch = iso / "watch"
    out = iso / "out"
    comp = cidx.compressed_subdir(out)
    outsider = _mkvid(iso / "elsewhere" / "x.mp4")
    valid_output = _mkvid(comp / "x.mp4")
    # Source is NOT under the watch root -> refuse.
    assert ac._safe_delete_original(outsider, valid_output, comp, watch) is False
    assert outsider.exists()


def test_safe_delete_refuses_file_inside_compressed(iso):
    watch = iso / "watch"
    out = iso / "out"
    comp = cidx.compressed_subdir(out)
    inside = _mkvid(comp / "already.mp4")
    other_output = _mkvid(comp / "other.mp4")
    # A file living inside compressed/ must never be deleted as an "original".
    assert ac._safe_delete_original(inside, other_output, comp, watch) is False
    assert inside.exists()


def test_safe_delete_refuses_zero_byte_output(iso):
    watch = iso / "watch"
    out = iso / "out"
    comp = cidx.compressed_subdir(out)
    src = _mkvid(watch / "clip.mp4")
    empty = comp / "clip.mp4"
    empty.parent.mkdir(parents=True, exist_ok=True)
    empty.write_bytes(b"")          # zero-byte output
    assert ac._safe_delete_original(src, empty, comp, watch) is False
    assert src.exists()


# ── HTTP surface ──────────────────────────────────────────────────────────────

@pytest.fixture()
def client(iso, monkeypatch):
    # Point the blueprint's output base at tmp so scan_now never writes to the
    # real default output folder.
    try:
        from gui.routes import autocompress_bp as acbp
    except ModuleNotFoundError:  # pragma: no cover
        from src.gui.routes import autocompress_bp as acbp
    monkeypatch.setattr(acbp, "_default_output_dir", lambda: str(iso / "out"))
    from gui.app import app
    return app.test_client()


def test_status_endpoint_reports_not_running(client):
    body = client.get("/api/autocompress/status").get_json()
    assert body["running"] is False
    assert "recent" in body and "queue" in body


def test_start_requires_existing_folder(client):
    assert client.post("/api/autocompress/start", json={}).status_code == 400
    assert client.post("/api/autocompress/start",
                       json={"folder": "Z:/nope/nope"}).status_code == 400


def test_scan_now_compresses_existing(client, iso):
    watch = iso / "watch"
    _mkvid(watch / "a.mp4")
    _mkvid(watch / "b.mp4")
    resp = client.post("/api/autocompress/scan_now", json={"folder": str(watch)})
    body = resp.get_json()
    assert resp.status_code == 200 and body["ok"] is True
    assert body["compressed"] == 2


# ── R3.1e: simulated live recorder + partial write + failure safety ───────────

def test_partial_write_waits_for_stability(iso):
    """A clip still being written (size growing) must NOT be grabbed mid-write.

    Mimics a recorder saving a live segment: a background thread keeps appending
    to the file. A scan whose stability window spans that writing must skip it;
    once writing stops, the next scan compresses it exactly once.
    """
    watch = iso / "watch"
    watch.mkdir(parents=True, exist_ok=True)
    p = watch / "growing.mp4"
    p.write_bytes(b"x" * 1000)

    stop = threading.Event()

    def _writer():
        for _ in range(14):
            if stop.is_set():
                break
            with open(p, "ab") as fh:
                fh.write(b"y" * 4096)
            time.sleep(0.3)

    t = threading.Thread(target=_writer)
    t.start()
    try:
        # While the file is still growing, a stability check spanning ~0.9s sees
        # the size change and skips it.
        done = ac.scan_once(str(watch), str(iso / "out"),
                            settle_seconds=0.3, stable_checks=3)
        assert done == [], "a still-growing file must not be compressed"
    finally:
        stop.set()
        t.join()

    # Now stable -> it compresses on the next pass.
    done2 = _scan(watch, iso / "out")
    assert len(done2) == 1


def test_compress_failure_keeps_original_and_leaves_retry_marker(iso, monkeypatch):
    """If the encode raises, the original is never deleted (even with the flag
    ON) and a .processing marker is left so the next scan retries it."""
    def _boom(**kwargs):
        raise RuntimeError("encode failed")

    monkeypatch.setattr(ac, "run_pipeline", _boom)
    watch = iso / "watch"
    src = _mkvid(watch / "clip.mp4")

    done = _scan(watch, iso / "out", delete_original=True)
    assert done == []
    assert src.exists(), "a failed compress must never delete the original"
    assert (watch / "clip.mp4.processing").exists(), "retry marker should remain"
    assert cidx.is_compressed(src) is False  # nothing recorded


# ── R3.1e: live-save integration with a real CDnet clip (skips if absent) ─────

def _corpus():
    env = os.environ.get("SVCS_TEST_VIDEO_DIR", "").strip()
    if env and Path(env).is_dir():
        return Path(env)
    p = ROOT / "data" / "samples" / "cdnet_mp4"
    return p if p.is_dir() else None


def _first_clip():
    c = _corpus()
    if not c:
        return None
    clips = sorted(c.rglob("*.mp4"))
    return clips[0] if clips else None


_CLIP = _first_clip()


def _trim(src: Path, dst: Path, seconds: int = 2) -> bool:
    r = subprocess.run(
        [ffmpeg_path(), "-y", "-ss", "0", "-t", str(seconds), "-i", str(src),
         "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         str(dst)],
        capture_output=True, timeout=120,
    )
    return r.returncode == 0 and dst.exists() and dst.stat().st_size > 0


def _has_video(path: Path) -> bool:
    r = subprocess.run(
        [ffprobe_path(), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    return r.returncode == 0 and "video" in (r.stdout or "")


@pytest.fixture()
def real_iso(tmp_path, monkeypatch):
    """Isolate the index + gui-state to tmp WITHOUT stubbing the encode (the
    live-save tests run the real pipeline)."""
    monkeypatch.setattr(cidx._paths, "state_file", lambda name: tmp_path / name)
    try:
        from gui.services import gui_state_persist as gsp
    except ModuleNotFoundError:  # pragma: no cover
        from src.gui.services import gui_state_persist as gsp
    monkeypatch.setattr(gsp, "_GUI_STATE_FILE", tmp_path / "gui_state.json")
    return tmp_path


@pytest.mark.skipif(_CLIP is None,
                    reason="No CDnet corpus at data/samples/cdnet_mp4 "
                           "(set SVCS_TEST_VIDEO_DIR).")
def test_live_save_daemon_compresses_and_dedups(real_iso, tmp_path):
    """Start the daemon, simulate a recorder saving a clip into the watched
    folder, and assert it is compressed into compressed/, is a valid container,
    and is recorded in the index - then that a second pass dedups."""
    watch = tmp_path / "watch"
    watch.mkdir()
    out = tmp_path / "out"
    out.mkdir()

    # Prepare the clip OUTSIDE the watch folder, then "save" it in (a move/copy
    # is what a recorder does when it finalizes a segment).
    staged = tmp_path / "staged.mp4"
    if not _trim(_CLIP, staged, seconds=2):
        pytest.skip("could not trim a sample clip (ffmpeg unavailable?)")

    # _ac_status is module-level; reset the session counters so this test does
    # not see compressions from earlier tests in the same process.
    with ac._ac_lock:
        ac._ac_status.update({"recent": [], "compressed_total": 0,
                              "queue": 0, "last_error": None, "scans": 0})

    comp_dir = out / "compressed"
    config = {"folder": str(watch), "output_dir": str(out),
              "mode": "mode0", "poll_interval": 2, "delete_original": False}
    assert ac.start_autocompress(config) is True
    try:
        # Recorder saves the finished segment into the watched folder.
        saved = watch / "live_segment.mp4"
        saved.write_bytes(staged.read_bytes())

        # Wait for the daemon to actually write a compressed output (bounded).
        deadline = time.time() + 120
        while time.time() < deadline:
            if (comp_dir.is_dir() and any(comp_dir.glob("*.mp4"))) \
                    or cidx.is_compressed(saved):
                break
            time.sleep(1)
    finally:
        ac.stop_autocompress()
        # Give the thread a moment to exit cleanly.
        for _ in range(10):
            if not ac.is_running():
                break
            time.sleep(0.5)

    produced = list(comp_dir.glob("*.mp4")) if comp_dir.is_dir() else []
    assert produced, "the daemon should have written a compressed output"
    assert _has_video(produced[0]), "the output must be a valid video container"
    assert cidx.is_compressed(saved) is True, "the source->output must be recorded"

    # Dedup: a second scan over the same folder compresses nothing more, and the
    # index keeps a single entry for this source.
    before = len(cidx._load()["entries"])
    again = ac.scan_once(str(watch), str(out), mode="mode0",
                         settle_seconds=0.0, stable_checks=1)
    assert again == [], "an already-compressed clip must not be redone"
    assert len(cidx._load()["entries"]) == before, "no duplicate index entry"

    # A file already inside compressed/ is never recompressed.
    third = ac.scan_once(str(out), str(out), mode="mode0",
                         settle_seconds=0.0, stable_checks=1)
    assert third == [], "outputs under compressed/ must never be recompressed"
