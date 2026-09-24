#!/usr/bin/env python3
"""
scripts/export_requirements.py - regenerate requirements.txt from uv.lock.

pyproject.toml (what we depend on) and uv.lock (the exact resolved versions)
are the single source of truth for Python dependencies. requirements.txt is
kept only as a generated export for pip-only users and for scanners that read
it, because a hand-edited copy drifted badly: by September 2026 it listed
opencv-python instead of the opencv-contrib-python the GMG subtractor needs,
pulled ultralytics/basicsr/realesrgan in as if they were core, and was missing
cryptography, platformdirs and onnxruntime entirely.

Usage:
    python scripts/export_requirements.py           # rewrite requirements.txt
    python scripts/export_requirements.py --check   # exit 1 if it is stale

tests/test_requirements_export.py runs the --check comparison.

Author: Bloodawn (KheivenD), 2026-09-24 (repo cleanup sweep).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "requirements.txt"

HEADER = """\
# GENERATED from uv.lock by scripts/export_requirements.py. Do not edit.
#
# pyproject.toml (dependencies) and uv.lock (exact versions) are the single
# source of truth. This file exists for tools and people that only speak pip:
# `pip install -r requirements.txt` gives the core (slim, torch-free) install.
# Optional extras (torch, enhance, plates, crash-reporting) are not included;
# use `uv sync --extra <name>` for those.
#
# Regenerate after `uv lock`:  python scripts/export_requirements.py
"""

EXPORT_CMD = [
    "uv", "export", "--frozen", "--no-dev", "--no-hashes", "--no-annotate",
    "--no-emit-project", "--no-header", "--format", "requirements-txt",
]


def render() -> str:
    """The exact text requirements.txt should contain."""
    if shutil.which("uv") is None:
        raise RuntimeError("uv is not on PATH; install it from https://docs.astral.sh/uv/")
    out = subprocess.run(EXPORT_CMD, cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return HEADER + "\n" + out


def main() -> int:
    ap = argparse.ArgumentParser(description="Regenerate requirements.txt from uv.lock")
    ap.add_argument("--check", action="store_true", help="only report whether it is stale")
    args = ap.parse_args()
    want = render()
    have = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
    if args.check:
        if want != have:
            print("requirements.txt is stale: run python scripts/export_requirements.py")
            return 1
        print("requirements.txt matches uv.lock")
        return 0
    TARGET.write_text(want, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
