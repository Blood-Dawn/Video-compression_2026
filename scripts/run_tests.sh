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
  # cryptography is a CORE dep (encryption is core); the extras add the
  # optional features the suite exercises. The 2026-05-14 baseline failed
  # 40 tests purely because this sync was incomplete.
  uv sync --extra enhance --extra plates --extra crash-reporting
fi

echo "==> Running full suite (log: ${log_file})"
k_args=()
if [ -n "${PYTEST_K:-}" ]; then k_args=(-k "${PYTEST_K}"); fi

# --tb=short -ra and basetemp=.pytest_tmp come from pyproject.toml.
uv run pytest tests/ "${k_args[@]}" 2>&1 | tee "${log_file}"

echo ""
echo "==> Summary:"
grep -E "passed|failed|error" "${log_file}" | tail -1
echo "==> Full log: ${log_file}"
echo "==> Record the counts in docs/test-baseline.md (date, commit SHA, OS, Python)."
