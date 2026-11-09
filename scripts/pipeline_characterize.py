"""Characterize run_pipeline on a real clip, before and after a refactor.

Rule for this repo: a change to src/pipeline or src/compression needs a size
and retention check on a real clip, with numbers before and after. Run `run`
on the code before the change into one folder, again after into another, then
`compare` the two.

    python scripts/pipeline_characterize.py run <out_dir> <clip.mp4> [mode ...]
    python scripts/pipeline_characterize.py compare <before_dir> <after_dir>

`run` processes the clip in each mode with fixed settings (60 s segments, 120
warmup frames, no enhancement, no encryption) and writes <out_dir>/result.json:
per output file the size, sha256 and a decoded-frames md5, plus the totals from
the metadata database (segments, detections kept, bytes, duration).

`compare` exits 1 unless mode0, mode1 and mode3 are byte identical with the
same database totals. mode2 is not deterministic run to run (AV1 timing, tens
of bytes), so it only has to match segment count, detection count and a size
within 64 bytes per file.

Needs ffmpeg on PATH. Use a clip longer than 60 s or segments saved in the same
wall clock second overwrite each other (the file name has one second
resolution).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALL_MODES = ["mode0", "mode1", "mode2", "mode3"]
MODE2_TOLERANCE_BYTES = 64


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _frames_md5(path: str) -> str:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "md5", "-"],
                         capture_output=True, text=True, check=False)
    return out.stdout.strip()


def _db_totals(db_path: str) -> dict:
    if not os.path.exists(db_path):
        return {}
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(roi_count),0), COALESCE(SUM(target_detected),0),"
            " COALESCE(SUM(file_size),0), COALESCE(SUM(duration),0) FROM segments").fetchone()
    finally:
        conn.close()
    return {"segments": row[0], "roi_detections": row[1], "segments_with_targets": row[2],
            "bytes": row[3], "duration": round(row[4], 3)}


def run(out_root: str, clip: str, modes: list[str]) -> int:
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from pipeline.pipeline import run_pipeline

    result = {}
    for mode in modes:
        out = os.path.join(out_root, mode)
        shutil.rmtree(out, ignore_errors=True)
        os.makedirs(out)
        started = time.time()
        run_pipeline(clip, camera_id="cam_char", output_dir=out, segment_seconds=60,
                     warmup_frames=120, mode=mode, show_preview=False, enhance=False,
                     encrypt=False)
        files = []
        for folder, _dirs, names in os.walk(out):
            for name in sorted(names):
                if name.endswith(".mp4"):
                    path = os.path.join(folder, name)
                    files.append([re.sub(r"\d{8}T\d{6}Z", "TS", name), os.path.getsize(path),
                                  _sha256(path), _frames_md5(path)])
        result[mode] = {"secs": round(time.time() - started, 1), "files": sorted(files),
                        "db": _db_totals(os.path.join(out, "metadata.db"))}
        print(mode, result[mode]["secs"], "s", [(f[0], f[1]) for f in sorted(files)],
              result[mode]["db"], flush=True)
    with open(os.path.join(out_root, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
    return 0


def compare(before_dir: str, after_dir: str) -> int:
    with open(os.path.join(before_dir, "result.json"), encoding="utf-8") as fh:
        before = json.load(fh)
    with open(os.path.join(after_dir, "result.json"), encoding="utf-8") as fh:
        after = json.load(fh)
    ok = True
    for mode in before:
        if mode not in after:
            print(f"{mode}: missing from after")
            ok = False
            continue
        fb, fa = before[mode]["files"], after[mode]["files"]
        db_b, db_a = before[mode]["db"], after[mode]["db"]
        same_bytes = [f[2] for f in fb] == [f[2] for f in fa]
        same_frames = [f[3] for f in fb] == [f[3] for f in fa]
        print(f"{mode}: sizes {[f[1] for f in fb]} -> {[f[1] for f in fa]}, "
              f"byte identical={same_bytes}, frames identical={same_frames}, "
              f"db {db_b} -> {db_a}")
        if mode == "mode2":
            good = (len(fb) == len(fa)
                    and all(abs(x[1] - y[1]) <= MODE2_TOLERANCE_BYTES for x, y in zip(fb, fa))
                    and db_b.get("segments") == db_a.get("segments")
                    and db_b.get("roi_detections") == db_a.get("roi_detections"))
        else:
            good = same_bytes and same_frames and db_b == db_a
        ok = ok and good
    print("RESULT", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("out_dir")
    p_run.add_argument("clip")
    p_run.add_argument("modes", nargs="*", default=ALL_MODES)
    p_cmp = sub.add_parser("compare")
    p_cmp.add_argument("before_dir")
    p_cmp.add_argument("after_dir")
    args = parser.parse_args(argv)
    if args.cmd == "run":
        return run(args.out_dir, args.clip, args.modes)
    return compare(args.before_dir, args.after_dir)


if __name__ == "__main__":
    sys.exit(main())
