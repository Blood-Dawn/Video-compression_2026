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
    [switch]$WithPlates,   # opt-in: installs easyocr, which currently BREAKS cv2 (see below)
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
    # Core deps include cryptography (encryption is core). enhance + crash-reporting
    # are safe. `plates` (easyocr) is DELIBERATELY EXCLUDED by default: easyocr
    # depends on opencv-python-headless, which collides with the project's opencv
    # install and clobbers cv2 (createBackgroundSubtractorMOG2 disappears -> 8
    # test files fail at import). See docs/test-baseline.md "OpenCV / easyocr
    # conflict". Plate-reader tests are gated with importorskip and validated in a
    # separate environment until the dependency is fixed (TASK 0.3b).
    if ($WithPlates) {
        Write-Host "    WARNING: --WithPlates pulls easyocr; this currently breaks cv2." -ForegroundColor Yellow
        uv sync --extra enhance --extra crash-reporting --extra plates
    } else {
        uv sync --extra enhance --extra crash-reporting
    }

    Write-Host "==> Sanity-checking OpenCV (cv2 must be whole)..." -ForegroundColor Cyan
    # Fail fast with a clear message if cv2 got clobbered, instead of 8 cryptic
    # import errors deep in the test run.
    uv run --no-sync python -c "import cv2; cv2.createBackgroundSubtractorMOG2(); print('cv2 OK', cv2.__version__)"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "cv2 is broken (likely a dual opencv-python / opencv-python-headless install)." -ForegroundColor Red
        Write-Host "Repair: uv pip uninstall opencv-python opencv-python-headless opencv-contrib-python opencv-contrib-python-headless; then reinstall ONE flavor. See docs/test-baseline.md." -ForegroundColor Red
        exit 1
    }
}

Write-Host "==> Running full suite (log: $logFile)" -ForegroundColor Cyan
$pytestArgs = @("tests/")
if ($K -ne "") { $pytestArgs += @("-k", $K) }

# --tb=short -ra and basetemp=.pytest_tmp come from pyproject.toml.
# --no-sync so the run doesn't re-resolve and undo the verified cv2 install.
uv run --no-sync pytest @pytestArgs 2>&1 | Tee-Object -FilePath $logFile

$summary = Select-String -Path $logFile -Pattern "passed|failed|error" | Select-Object -Last 1
Write-Host ""
Write-Host "==> Summary:" -ForegroundColor Green
Write-Host $summary.Line
Write-Host "==> Full log: $logFile"
Write-Host "==> Record the counts in docs/test-baseline.md (date, commit SHA, OS, Python)."
