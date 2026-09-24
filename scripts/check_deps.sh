#!/usr/bin/env bash
# check_deps.sh - verify a Linux/macOS dev machine is ready for the SVCS
# desktop app. Windows developers: scripts/setup_new_pc.ps1 does the same
# checks and installs what is missing.
#
# Usage (from the repo root):  bash scripts/check_deps.sh
#
# Python dependencies come from pyproject.toml + uv.lock via `uv sync`, so this
# checks for uv and the lockfile environment rather than pip packages from
# requirements.txt (a generated export now; see scripts/export_requirements.py).
#
# Author: Bloodawn (KheivenD), Spring 2026; moved to uv 2026-09-24 (cleanup).

set -uo pipefail

PASS=0
FAIL=0
ok()   { echo "  [OK]   $1"; PASS=$((PASS + 1)); }
bad()  { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }
hint() { echo "         -> $1"; }

cd "$(dirname "$0")/.." || exit 1

echo "SVCS desktop - dependency check"

echo
echo "[1/4] uv"
if command -v uv >/dev/null 2>&1; then
    ok "$(uv --version)"
else
    bad "uv not found"
    hint "curl -LsSf https://astral.sh/uv/install.sh | sh   (it also provides Python 3.11)"
fi

echo
echo "[2/4] FFmpeg (system binary)"
if command -v ffmpeg >/dev/null 2>&1; then
    ok "$(ffmpeg -version 2>/dev/null | head -1)"
else
    bad "ffmpeg not on PATH"
    hint "Ubuntu/Debian: sudo apt install ffmpeg    macOS: brew install ffmpeg"
fi

echo
echo "[3/4] Python environment (uv.lock)"
if command -v uv >/dev/null 2>&1; then
    if uv sync --frozen --quiet >/dev/null 2>&1; then
        ok ".venv matches uv.lock"
    else
        bad "uv sync --frozen failed"
        hint "run 'uv sync --frozen' to see the error"
    fi
    if uv run --frozen python -c "import cv2, cv2.bgsegm, onnxruntime, flask, cryptography, platformdirs" >/dev/null 2>&1; then
        ok "OpenCV (contrib), ONNX Runtime, Flask and crypto import"
    else
        bad "a core import failed"
        hint "uv run python -c 'import cv2, cv2.bgsegm, onnxruntime, flask'"
    fi
else
    bad "skipped (needs uv)"
fi

echo
echo "[4/4] Local folders"
for d in outputs logs models data/samples; do
    mkdir -p "$d" && ok "$d/"
done

echo
echo "Passed: $PASS   Failed: $FAIL"
if [ "$FAIL" -eq 0 ]; then
    echo "Ready. Next: uv run python run_gui.py   (dashboard on http://localhost:5000)"
    exit 0
fi
echo "Fix the items above and re-run."
exit 1
