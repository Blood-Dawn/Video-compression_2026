# Author: Bloodawn (KheivenD), 2026-05-31 (M0 TASK 0.1 — reproducible test baseline).
#
# Reproducible full-suite run for SVCS. This is THE command that defines
# "green" (PLAN-V2 section 11). Run it on the Windows daily-driver before
# trusting any "tests pass" claim.
#
# What it does:
#   1. Syncs the environment with the documented extras (so the suite is
#      not under-provisioned the way the 2026-05-14 baseline run was —
#      that run was missing `cryptography` and the crash-reporting extra,
#      which accounted for 40 of its 48 failures).
#   2. Runs pytest with the project config.
#   3. Tees output to a timestamped log under logs/.
#   4. Prints the one-line summary.
#
# Usage:
#   pwsh scripts/run_tests.ps1            # full suite, all extras
#   pwsh scripts/run_tests.ps1 -NoSync    # skip uv sync (env already set up)
#   pwsh scripts/run_tests.ps1 -K "encrypt"   # pass -k filter to pytest

param(
    [switch]$NoSync,
    [string]$K = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "pytest_$stamp.log"

if (-not $NoSync) {
    Write-Host "==> Syncing environment with documented extras..." -ForegroundColor Cyan
    # Core deps include cryptography (encryption is core). The extras add
    # the optional features the suite exercises. Keep this list in sync
    # with docs/test-baseline.md.
    uv sync --extra enhance --extra plates --extra crash-reporting
}

Write-Host "==> Running full suite (log: $logFile)" -ForegroundColor Cyan
$pytestArgs = @("tests/")
if ($K -ne "") { $pytestArgs += @("-k", $K) }

# --tb=short -ra and basetemp=.pytest_tmp come from pyproject.toml.
uv run pytest @pytestArgs 2>&1 | Tee-Object -FilePath $logFile

$summary = Select-String -Path $logFile -Pattern "passed|failed|error" | Select-Object -Last 1
Write-Host ""
Write-Host "==> Summary:" -ForegroundColor Green
Write-Host $summary.Line
Write-Host "==> Full log: $logFile"
Write-Host "==> Record the counts in docs/test-baseline.md (date, commit SHA, OS, Python)."
