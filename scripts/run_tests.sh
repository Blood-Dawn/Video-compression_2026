#!/usr/bin/env bash
# Author: Bloodawn (KheivenD), 2026-05-31 (M0 TASK 0.1 — reproducible test baseline).
#
# POSIX counterpart to run_tests.ps1 (for CI / Linux). Same contract:
# sync with the documented extras, run the full suite with the project
# pytest config, tee to a timestamped log, print the summary.
#
# Usage:
#   scripts/run_tests.sh                 # full suite, all extras
#   NO_SYNC=1 scripts/run_tests.sh       # skip uv sync
#   PYTEST_K="encrypt" scripts/run_tests.sh   # pass -k filter

set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

stamp="$(date +%Y%m%d_%H%M%S)"
mkdir -p logs
log_file="logs/pytest_${stamp}.log"

if [ "${NO_SYNC:-0}" != "1" ]; then
  echo "==> Syncing environment with documented extras..."
  # cryptography is a CORE dep (encryption is core). enhance + crash-reporting
  # are safe. `plates` (easyocr) is EXCLUDED by default: easyocr pulls
  # opencv-python-headless, which collides with the project's opencv and
  # clobbers cv2 (createBackgroundSubtractorMOG2 disappears). Opt in with
  # WITH_PLATES=1 only in an environment dedicated to plate-reader testing.
  # See docs/test-baseline.md "OpenCV / easyocr conflict" (TASK 0.3b).
  if [ "${WITH_PLATES:-0}" = "1" ]; then
    echo "    WARNING: WITH_PLATES=1 pulls easyocr; this currently breaks cv2."
    uv sync --extra enhance --extra crash-reporting --extra plates
  else
    uv sync --extra enhance --extra crash-reporting
  fi

  echo "==> Sanity-checking OpenCV (cv2 must be whole)..."
  if ! uv run --no-sync python -c "import cv2; cv2.createBackgroundSubtractorMOG2(); print('cv2 OK', cv2.__version__)"; then
    echo "cv2 is broken (likely a dual opencv-python / opencv-python-headless install)." >&2
    echo "Repair: uv pip uninstall opencv-python opencv-python-headless opencv-contrib-python opencv-contrib-python-headless; reinstall ONE flavor." >&2
    exit 1
  fi
fi

echo "==> Running full suite (log: ${log_file})"
k_args=()
if [ -n "${PYTEST_K:-}" ]; then k_args=(-k "${PYTEST_K}"); fi

# --tb=short -ra and basetemp=.pytest_tmp come from pyproject.toml.
# --no-sync so the run doesn't re-resolve and undo the verified cv2 install.
uv run --no-sync pytest tests/ "${k_args[@]}" 2>&1 | tee "${log_file}"

echo ""
echo "==> Summary:"
grep -E "passed|failed|error" "${log_file}" | tail -1
echo "==> Full log: ${log_file}"
echo "==> Record the counts in docs/test-baseline.md (date, commit SHA, OS, Python)."
