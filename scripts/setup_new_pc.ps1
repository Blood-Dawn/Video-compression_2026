# =============================================================================
#  setup_new_pc.ps1 - one-time developer setup for the SVCS desktop app on a
#  fresh Windows PC. Run it from the repo root:
#    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#    .\scripts\setup_new_pc.ps1
#
#  pyproject.toml + uv.lock are the single source of Python dependencies, so
#  this installs uv and runs `uv sync --frozen` rather than building a pip
#  venv from requirements.txt (which is only a generated export now).
#
#  Author: Bloodawn (KheivenD), Spring 2026; moved to uv 2026-09-24 (cleanup).
# =============================================================================

$ErrorActionPreference = 'Stop'

function Write-Step { param($msg) Write-Host '' ; Write-Host ">>> $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "  [FAIL] $msg" -ForegroundColor Red ; exit 1 }

Write-Host ''
Write-Host '=============================================' -ForegroundColor Magenta
Write-Host '  SVCS desktop - developer setup            ' -ForegroundColor Magenta
Write-Host '=============================================' -ForegroundColor Magenta

# --- 1. Repo root ------------------------------------------------------------
Write-Step 'Confirming project location...'
$projectDir = (Get-Location).Path
if (-not (Test-Path (Join-Path $projectDir 'pyproject.toml'))) {
    Write-Fail 'pyproject.toml not found here. cd into the repo root first.'
}
Write-OK "Project folder: $projectDir"

# --- 2. Git ------------------------------------------------------------------
Write-Step 'Checking Git...'
if (Get-Command git -ErrorAction SilentlyContinue) {
    Write-OK (& git --version)
} else {
    Write-Fail 'Git not found. Install it (winget install Git.Git) and re-run.'
}

# --- 3. uv (it also provides Python 3.11, no separate install needed) --------
Write-Step 'Checking uv...'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Warn 'uv not found. Installing via winget...'
    & winget install --id astral-sh.uv -e --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'Machine')
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Fail 'uv installed but not on PATH yet. Open a new terminal and re-run.'
    }
}
Write-OK (& uv --version)

# --- 4. FFmpeg (a system binary, not a Python package) -----------------------
Write-Step 'Checking FFmpeg...'
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    Write-OK ((& ffmpeg -version 2>&1) | Select-Object -First 1)
} else {
    Write-Warn 'FFmpeg not found. Installing via winget...'
    & winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
    Write-Warn 'Restart your terminal when this finishes so ffmpeg is on PATH.'
}

# --- 5. Python environment from the lockfile ---------------------------------
Write-Step 'Installing Python dependencies (uv sync --frozen)...'
& uv sync --frozen
if ($LASTEXITCODE -ne 0) { Write-Fail 'uv sync failed; see the output above.' }
Write-OK 'Environment matches uv.lock (.venv).'

# --- 6. Local, gitignored folders --------------------------------------------
Write-Step 'Creating local folders...'
foreach ($d in @('outputs', 'logs', 'models', (Join-Path 'data' 'samples'))) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null }
    Write-OK $d
}

# --- 7. Sanity check: the imports the pipeline and dashboard need ------------
Write-Step 'Checking key imports...'
$check = 'import cv2, cv2.bgsegm, numpy, onnxruntime, flask, cryptography, platformdirs; print("ALL_OK")'
$result = & uv run --frozen python -c $check 2>&1
if ($result -match 'ALL_OK') {
    Write-OK 'OpenCV (contrib), ONNX Runtime, Flask and crypto all import.'
} else {
    Write-Warn "Import check failed: $result"
}

Write-Host ''
Write-Host 'Setup complete. Next:' -ForegroundColor Green
Write-Host '  uv run python run_gui.py       # dashboard at http://localhost:5000' -ForegroundColor Gray
Write-Host '  uv run pytest                  # test suite' -ForegroundColor Gray
Write-Host '  See DEV.md for everything else, including the Android app.' -ForegroundColor Gray
Write-Host ''
