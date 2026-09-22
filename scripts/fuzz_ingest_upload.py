#!/usr/bin/env python3
"""
scripts/fuzz_ingest_upload.py - Week 3 TASK 3.15.

Adversarial + mutation fuzzing of SVCS's two "untrusted bytes enter the app"
surfaces:

  1. POST /api/upload - the network-facing upload endpoint
     (gui/routes/files_bp.py). Runs a battery of filename-based attacks
     (path traversal, null bytes, double extensions, absolute paths,
     oversized names) and body-based attacks (empty file, an oversized body
     with no server-side MAX_CONTENT_LENGTH configured, content that does
     not match its claimed extension) against the real Flask blueprint via
     a test client. No live server, no network exposure - safe to run
     against the real repo any time, and it cleans up every file it writes.

  2. The video DECODE path (cv2.VideoCapture - what actually reads bytes as
     video frames once a file is on disk). Mutation-fuzzed starting from a
     real sample clip's header, plus a handful of deliberately-crafted
     structural cases (zero-byte file, truncated header, a box that claims
     an absurd size). Every candidate runs in its own subprocess with a
     hard wall-clock timeout, because the question here isn't "does this
     return an error" (fine, expected) but "can a malformed file hang or
     crash the decoder" - that would be a denial-of-service on whatever
     machine runs the pipeline, including a phone-triggered upload.

This is meant to be run by hand:

    python scripts/fuzz_ingest_upload.py
    python scripts/fuzz_ingest_upload.py --rounds 100 --report fuzz_report.json
    python scripts/fuzz_ingest_upload.py --skip-decode   # upload cases only, fast

as an authorized self-pentest of Kheiven's own app. See
docs/security/kali-pentest-guide.md for how to point Wireshark/a Kali VM at
a REAL running instance of SVCS; this script's job is the part that doesn't
need a second machine at all.

Writes a JSON report (default fuzz_report.json next to this script's CWD)
and prints a human-readable summary. Exit code is 1 if any HIGH-severity
finding fired, so it is CI-friendly.

Author: Bloodawn (KheivenD), Week 3 (3.15).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

SEED_CLIP = ROOT / "data" / "samples" / "parking_input.mp4"


# ── shared result shape ──────────────────────────────────────────────────────

class Finding:
    """One fuzz result. severity is "info" | "low" | "high"."""

    def __init__(self, case: str, severity: str, ok: bool, detail: str):
        self.case = case
        self.severity = severity
        self.ok = ok          # True = app behaved safely, False = a real finding
        self.detail = detail

    def to_dict(self) -> dict:
        return {"case": self.case, "severity": self.severity, "ok": self.ok,
                "detail": self.detail}


# ── Part 1: the /api/upload endpoint ────────────────────────────────────────

def _make_app_and_client(upload_dir: Path):
    """Register files_bp standalone (no pipeline/detection deps needed) and
    point its upload directory at a throwaway folder so this script never
    touches the real data/uploads/.
    """
    import flask
    from gui.routes import files_bp as files_bp_mod

    app = flask.Flask(__name__)
    app.register_blueprint(files_bp_mod.files_bp)
    files_bp_mod._upload_dir = lambda: upload_dir  # monkeypatch: throwaway dir
    return app, files_bp_mod


def _upload(client, filename: str, data: bytes, content_type: str = "application/octet-stream"):
    from io import BytesIO
    return client.post(
        "/api/upload",
        data={"file": (BytesIO(data), filename)},
        content_type="multipart/form-data",
    )


UPLOAD_CASES = [
    # (name, filename, body, expect_saved, severity_if_wrong, note)
    ("empty_file_allowed_ext", "clip.mp4", b"",
     True, "info",
     "A 0-byte .mp4 is accepted (extension-only check). Expected: the pipeline "
     "will fail to open it later, not the upload route's job to detect."),

    ("garbage_bytes_allowed_ext", "clip.mp4", os.urandom(4096),
     True, "info",
     "Random bytes with a .mp4 extension are accepted - SVCS does not "
     "content-sniff uploads, only checks the extension. By design; flagged "
     "so it's a documented tradeoff, not a surprise."),

    ("double_extension_dangerous_real", "invoice.mp4.exe", os.urandom(256),
     False, "high",
     "A file whose REAL extension is .exe (dangerous) must be rejected "
     "regardless of an earlier .mp4-looking segment in the name."),

    ("double_extension_disguised_exe", "clip.exe.mp4", os.urandom(256),
     True, "info",
     "clip.exe.mp4's real extension is .mp4, so it is accepted and saved "
     "with that name - the .exe segment is inert, just a filename. Nothing "
     "on this host EXECUTES an uploaded file, so this is not itself a code-"
     "execution path, but it means 'looks like an mp4' is a filename claim, "
     "not a content guarantee. Worth knowing if this ever feeds a tool that "
     "trusts the extension for more than opening a video."),

    ("path_traversal_forward_slash", "../../../etc/passwd.mp4", b"x" * 32,
     True, "high",
     "Path(name).name strips this to a bare 'passwd.mp4', so the upload IS "
     "saved (that's correct) - the real question the escape check below "
     "answers is whether it landed strictly inside the upload directory, "
     "not literally at /etc/passwd."),

    ("path_traversal_backslash", "..\\..\\..\\Windows\\win.ini.mp4", b"x" * 32,
     True, "high",
     "On the shipped desktop build (Windows, backslash IS a path separator) "
     "this strips to 'win.ini.mp4' just like the forward-slash case. This "
     "script runs on whatever platform it's invoked on, so treat this case's "
     "escape check as platform-informative, not platform-proof - the "
     "backslash-on-POSIX difference is exactly why the guide has you also "
     "run this for real against the actual Windows build."),

    ("absolute_path_filename", "/etc/passwd.mp4", b"x" * 32,
     True, "high",
     "An absolute-path filename must be treated as a bare filename (saved as "
     "'passwd.mp4' inside the upload dir), never honored as an absolute "
     "destination."),

    ("absolute_path_windows_drive", "C:\\Windows\\System32\\evil.mp4", b"x" * 32,
     True, "high",
     "A Windows drive-absolute filename must not be honored as a destination "
     "- it should land inside the upload dir under some safe name, never at "
     "the literal drive path."),

    ("null_byte_extension_bypass", "evil.mp4\x00.php", b"x" * 32,
     False, "high",
     "A NUL byte historically tricked C-based extension checks into stopping "
     "early at the .mp4 before it. Python's Path.suffix parses the whole "
     "string and correctly sees .php (the REAL extension) as what follows "
     "the last dot, so this should be rejected exactly like any other "
     ".php upload - confirming that, not assuming it, is the point."),

    ("very_long_filename", "a" * 400 + ".mp4", b"x" * 32,
     True, "low",
     "A very long filename must not crash the route. This exact case caught "
     "a real bug during development (files_bp.py's collision-avoidance loop "
     "raised an unhandled OSError past the filesystem's ~255-byte filename "
     "limit, returning a raw 500); files_bp.py now trims the stem and wraps "
     "the save in try/except so this returns a clean, saved response "
     "instead. A 500 here would mean that fix regressed."),

    ("filename_is_only_extension", ".mp4", b"x" * 32,
     False, "low",
     "Path('.mp4').suffix is '' (pathlib treats a leading-dot name as a "
     "hidden file with no extension), so this is rejected as an unrecognized "
     "type - not saved. The finding to watch for is a crash, not the reject "
     "itself."),

    ("disallowed_extension_rejected", "clip.exe", os.urandom(256),
     False, "info",
     "Sanity check: a plainly disallowed extension is rejected (control case "
     "- if this one fails the whole suite's assumptions are wrong)."),

    ("no_size_limit_moderate_body", "big.mp4", os.urandom(8 * 1024 * 1024),
     True, "low",
     "An 8 MB body is accepted with no MAX_CONTENT_LENGTH configured on the "
     "Flask app. That's fine for a LAN video-upload tool, but it means "
     "there is currently no server-side cap on upload size - an attacker "
     "who can reach the port could send an arbitrarily large body and fill "
     "disk. Worth an explicit MAX_CONTENT_LENGTH if this is ever exposed "
     "beyond a trusted LAN."),
]


def run_upload_fuzz() -> list[Finding]:
    findings: list[Finding] = []
    tmp_upload = Path(tempfile.mkdtemp(prefix="svcs_fuzz_upload_"))
    tmp_upload_resolved = tmp_upload.resolve()
    try:
        app, files_bp_mod = _make_app_and_client(tmp_upload)
        client = app.test_client()

        for name, filename, body, expect_saved, sev_if_wrong, note in UPLOAD_CASES:
            try:
                resp = _upload(client, filename, body)
            except Exception as exc:  # noqa: BLE001 - an uncaught exception IS the finding
                findings.append(Finding(
                    name, "high", False,
                    f"the upload route raised instead of returning a response: {exc!r}"))
                continue

            was_500 = resp.status_code >= 500
            data = resp.get_json(silent=True) or {}
            # api_upload's own success response echoes the exact path it wrote
            # to - the authoritative source for "where did this actually land",
            # rather than diffing directory listings.
            saved_path_str = data.get("path") if resp.status_code == 200 else None
            was_saved = saved_path_str is not None

            escaped = False
            if saved_path_str:
                try:
                    resolved = Path(saved_path_str).resolve()
                    escaped = not (resolved == tmp_upload_resolved
                                  or tmp_upload_resolved in resolved.parents)
                except (OSError, ValueError):
                    escaped = True  # an unresolvable "successful" path is itself suspicious

            if was_500:
                findings.append(Finding(
                    name, "high", False,
                    f"route returned HTTP {resp.status_code} (server error) instead "
                    f"of a clean 4xx/200: {resp.get_data(as_text=True)[:200]!r}"))
            elif escaped:
                findings.append(Finding(
                    name, "high", False,
                    f"saved file escaped the upload directory entirely: {saved_path_str}"))
            elif was_saved != expect_saved:
                findings.append(Finding(
                    name, sev_if_wrong, False,
                    f"expected saved={expect_saved}, got saved={was_saved} "
                    f"(status {resp.status_code}, body {data}). {note}"))
            else:
                findings.append(Finding(
                    name, "info", True,
                    f"behaved as expected (saved={was_saved}, status={resp.status_code}"
                    + (f", saved_path={saved_path_str}" if saved_path_str else "") + f"). {note}"))
    finally:
        shutil.rmtree(tmp_upload, ignore_errors=True)
    return findings


# ── Part 2: the video decode path (cv2.VideoCapture) ────────────────────────

_DECODE_PROBE_SRC = """
import sys
try:
    import cv2
except Exception as exc:
    print("IMPORT_ERROR:" + repr(exc))
    sys.exit(3)
path = sys.argv[1]
try:
    cap = cv2.VideoCapture(path)
    opened = cap.isOpened()
    frames = 0
    for _ in range(5):
        ret, frame = cap.read()
        if not ret:
            break
        frames += 1
    cap.release()
    print(f"OK opened={opened} frames_read={frames}")
    sys.exit(0)
except Exception as exc:
    print("DECODE_EXCEPTION:" + repr(exc))
    sys.exit(2)
"""


def _probe_decode(path: Path, timeout_s: float) -> Finding:
    case = path.name
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _DECODE_PROBE_SRC, str(path)],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return Finding(case, "high", False,
                       f"decode HUNG past the {timeout_s}s timeout - a malformed "
                       "file can wedge the decoder (DoS on whatever runs the "
                       "pipeline, including a phone-triggered upload).")
    if proc.returncode < 0:
        return Finding(case, "high", False,
                       f"decoder was killed by signal {-proc.returncode} "
                       f"(likely a native crash/segfault): stderr={proc.stderr[:200]!r}")
    if proc.returncode == 2:
        return Finding(case, "low", True,
                       f"decode raised a caught Python exception (handled, not a "
                       f"crash): {proc.stdout.strip()}")
    if proc.returncode == 3:
        return Finding(case, "info", True, "cv2 not importable in this environment; skipped.")
    return Finding(case, "info", True, proc.stdout.strip() or "decoded cleanly")


def _structural_cases(tmp_dir: Path) -> list[Path]:
    """A handful of deliberately-crafted malformed containers, not random."""
    cases = []

    p = tmp_dir / "struct_zero_byte.mp4"
    p.write_bytes(b"")
    cases.append(p)

    p = tmp_dir / "struct_ftyp_only.mp4"
    # A real MP4 starts with a box: 4-byte size + b"ftyp" + brand info. Give
    # it a plausible ftyp box and nothing else - no moov, no mdat.
    p.write_bytes((20).to_bytes(4, "big") + b"ftypisom" + b"\x00" * 12)
    cases.append(p)

    p = tmp_dir / "struct_huge_declared_box.mp4"
    # A box that claims to be ~4GB but the file is actually a few bytes -
    # the classic "trust the declared length" overread/DoS shape.
    p.write_bytes((0xFFFFFFFF).to_bytes(4, "big") + b"mdat" + b"\x00" * 8)
    cases.append(p)

    p = tmp_dir / "struct_truncated_real_clip.mp4"
    if SEED_CLIP.exists():
        data = SEED_CLIP.read_bytes()
        p.write_bytes(data[: max(1, len(data) // 200)])  # first ~0.5%: header, no frames
    else:
        p.write_bytes(b"\x00" * 64)
    cases.append(p)

    return cases


def _mutation_cases(tmp_dir: Path, rounds: int, rng: random.Random) -> list[Path]:
    """Random byte-flip mutations of a real clip's header, the actual 'fuzz'."""
    cases = []
    if not SEED_CLIP.exists():
        return cases
    seed = SEED_CLIP.read_bytes()[:65536]  # header/metadata region only - the
    # part a parser actually branches on; mutating deep into raw frame data
    # almost never changes decoder control flow and just wastes rounds.
    for i in range(rounds):
        buf = bytearray(seed)
        n_flips = rng.randint(1, 64)
        for _ in range(n_flips):
            idx = rng.randrange(len(buf))
            buf[idx] = rng.randrange(256)
        p = tmp_dir / f"mutant_{i:04d}.mp4"
        p.write_bytes(bytes(buf))
        cases.append(p)
    return cases


def run_decode_fuzz(rounds: int, timeout_s: float, seed: int) -> list[Finding]:
    if not SEED_CLIP.exists():
        return [Finding("decode_fuzz", "info", True,
                        f"seed clip not found at {SEED_CLIP}; skipped decode fuzzing.")]
    findings: list[Finding] = []
    tmp_dir = Path(tempfile.mkdtemp(prefix="svcs_fuzz_decode_"))
    try:
        rng = random.Random(seed)
        all_cases = _structural_cases(tmp_dir) + _mutation_cases(tmp_dir, rounds, rng)
        for path in all_cases:
            findings.append(_probe_decode(path, timeout_s))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return findings


# ── report + CLI ─────────────────────────────────────────────────────────────

def _print_summary(findings: list[Finding], title: str) -> None:
    print(f"\n=== {title} ({len(findings)} case(s)) ===")
    for f in findings:
        mark = "PASS" if f.ok else "FINDING"
        print(f"  [{f.severity.upper():4}] {mark:7} {f.case}: {f.detail}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rounds", type=int, default=40,
                    help="number of random mutation rounds for the decode fuzzer (default 40)")
    ap.add_argument("--timeout-s", type=float, default=6.0,
                    help="per-candidate decode timeout in seconds (default 6.0)")
    ap.add_argument("--seed", type=int, default=1337,
                    help="RNG seed, for a reproducible mutation run (default 1337)")
    ap.add_argument("--skip-decode", action="store_true",
                    help="skip the cv2 decode-path fuzzing (upload-endpoint cases only, fast)")
    ap.add_argument("--report", default=str(ROOT / "fuzz_report.json"),
                    help="where to write the JSON report (default fuzz_report.json)")
    args = ap.parse_args()

    t0 = time.time()
    upload_findings = run_upload_fuzz()
    _print_summary(upload_findings, "Upload endpoint (/api/upload)")

    decode_findings: list[Finding] = []
    if not args.skip_decode:
        decode_findings = run_decode_fuzz(args.rounds, args.timeout_s, args.seed)
        _print_summary(decode_findings, "Video decode path (cv2.VideoCapture)")
    else:
        print("\n(decode fuzzing skipped: --skip-decode)")

    all_findings = upload_findings + decode_findings
    high = [f for f in all_findings if f.severity == "high" and not f.ok]
    low = [f for f in all_findings if f.severity == "low" and not f.ok]
    elapsed = time.time() - t0

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_s": round(elapsed, 2),
        "rng_seed": args.seed,
        "decode_rounds": 0 if args.skip_decode else args.rounds,
        "upload_cases": [f.to_dict() for f in upload_findings],
        "decode_cases": [f.to_dict() for f in decode_findings],
        "high_severity_findings": len(high),
        "low_severity_findings": len(low),
    }
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\n{len(all_findings)} case(s) run in {elapsed:.1f}s. "
         f"{len(high)} HIGH finding(s), {len(low)} low finding(s). "
         f"Report written to {args.report}")
    if high:
        print("\nHIGH-severity findings:")
        for f in high:
            print(f"  - {f.case}: {f.detail}")
    return 1 if high else 0


if __name__ == "__main__":
    raise SystemExit(main())
