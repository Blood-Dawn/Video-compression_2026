# =============================================================================
#  setup_new_pc.ps1  -  EGN4950C Capstone | Fresh Windows PC Setup
#  Run this FROM INSIDE your project folder (Video-compression_2026):
#    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#    .\setup_new_pc.ps1
# =============================================================================

$ErrorActionPreference = 'Stop'

function Write-Step { param($msg) Write-Host '' ; Write-Host ">>> $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "  [FAIL] $msg" -ForegroundColor Red ; exit 1 }

Write-Host ''
Write-Host '=============================================' -ForegroundColor Magenta
Write-Host '  Capstone Compression - PC Setup Script    ' -ForegroundColor Magenta
Write-Host '  EGN4950C | FAU | Spring 2026              ' -ForegroundColor Magenta
Write-Host '=============================================' -ForegroundColor Magenta

# ---------------------------------------------------------------------------
# STEP 1 - Confirm we are inside the project folder
# ---------------------------------------------------------------------------
Write-Step 'Confirming project location...'
$projectDir = (Get-Location).Path
if (-not (Test-Path (Join-Path $projectDir 'requirements.txt'))) {
    Write-Fail 'requirements.txt not found here. cd into your project folder first.'
}
Write-OK "Project folder: $projectDir"

# ---------------------------------------------------------------------------
# STEP 2 - Check Python
# ---------------------------------------------------------------------------
Write-Step 'Checking Python...'
try {
    $pyVer = & python --version 2>&1
    Write-OK "Found: $pyVer"
    $pyMajor = [int](& python -c 'import sys; print(sys.version_info.major)')
    $pyMinor = [int](& python -c 'import sys; print(sys.version_info.minor)')
    if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 9)) {
        Write-Fail "Python 3.9+ required. You have $pyVer. Download from https://python.org"
    }
} catch {
    Write-Fail 'Python not found. Install Python 3.11 from https://python.org (check Add Python to PATH), then re-run.'
}

# ---------------------------------------------------------------------------
# STEP 3 - Check Git
# ---------------------------------------------------------------------------
Write-Step 'Checking Git...'
try {
    $gitVer = & git --version 2>&1
    Write-OK "Found: $gitVer"
} catch {
    Write-Fail 'Git not found. Install from https://git-scm.com then re-run.'
}

# ---------------------------------------------------------------------------
# STEP 4 - FFmpeg
# ---------------------------------------------------------------------------
Write-Step 'Checking FFmpeg...'
try {
    $ffVer = & ffmpeg -version 2>&1 | Select-Object -First 1
    Write-OK "Already installed: $ffVer"
} catch {
    Write-Warn 'FFmpeg not found. Attempting install via winget...'
    try {
        & winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
        Write-OK 'FFmpeg installed. Restart your terminal when the script finishes so ffmpeg is on PATH.'
    } catch {
        Write-Warn 'winget failed. Install FFmpeg manually:'
        Write-Warn '  1. Download ffmpeg-release-essentials.zip from https://www.gyan.dev/ffmpeg/builds/'
        Write-Warn '  2. Extract to C:\ffmpeg'
        Write-Warn '  3. Add C:\ffmpeg\bin to System PATH in Environment Variables'
        Write-Warn '  4. Restart terminal and re-run this script'
    }
}

# ---------------------------------------------------------------------------
# STEP 5 - Virtual environment
# ---------------------------------------------------------------------------
Write-Step 'Setting up Python virtual environment...'
$venvActivate = Join-Path $projectDir 'venv\Scripts\Activate.ps1'

if (Test-Path $venvActivate) {
    Write-OK 'venv already exists, skipping creation.'
} else {
    & python -m venv venv
    Write-OK 'Virtual environment created.'
}

& $venvActivate
Write-OK 'Virtual environment activated.'

# ---------------------------------------------------------------------------
# STEP 6 - Install Python packages
# ---------------------------------------------------------------------------
Write-Step 'Installing Python packages from requirements.txt...'
& python -m pip install --upgrade pip --quiet
& pip install -r requirements.txt
Write-OK 'All packages installed.'

# ---------------------------------------------------------------------------
# STEP 7 - Create gitignored local folders
# ---------------------------------------------------------------------------
Write-Step 'Creating required local directories...'
$dirs = @('outputs', 'logs', 'models', (Join-Path 'data' 'samples'))
foreach ($d in $dirs) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Path $d | Out-Null
        Write-OK "Created: $d"
    } else {
        Write-OK "Already exists: $d"
    }
}

# ---------------------------------------------------------------------------
# STEP 8 - Import sanity check
# ---------------------------------------------------------------------------
Write-Step 'Running import sanity check...'
$checkScript = 'import cv2, numpy, PIL, ffmpeg, tqdm, yaml, click, skimage, scipy, pytest, matplotlib, pandas, flask, cryptography; print("ALL_OK")'
$importResult = & python -c $checkScript 2>&1
if ($importResult -match 'ALL_OK') {
    Write-OK 'All Python packages import correctly.'
} else {
    Write-Warn 'One or more imports may have issues:'
    Write-Warn "$importResult"
}

# FFmpeg final check
Write-Step 'Final FFmpeg check...'
try {
    $ff2 = & ffmpeg -version 2>&1 | Select-Object -First 1
    Write-OK "FFmpeg on PATH: $ff2"
} catch {
    Write-Warn 'FFmpeg not on PATH yet. Close this terminal and open a new one.'
}

# ---------------------------------------------------------------------------
# DONE
# ---------------------------------------------------------------------------
Write-Host ''
Write-Host '=============================================' -ForegroundColor Magenta
Write-Host '  Setup complete!' -ForegroundColor Green
Write-Host '=============================================' -ForegroundColor Magenta
Write-Host ''
Write-Host 'Next steps:' -ForegroundColor White
Write-Host '  1. RESTART your terminal (FFmpeg PATH needs to refresh)' -ForegroundColor Yellow
Write-Host '  2. Re-activate venv in the new terminal:' -ForegroundColor Gray
Write-Host "       cd '$projectDir'" -ForegroundColor Gray
Write-Host '       .\venv\Scripts\Activate.ps1' -ForegroundColor Gray
Write-Host '  3. Drop a test .mp4 into data\samples\' -ForegroundColor Gray
Write-Host '  4. Run the pipeline:' -ForegroundColor Gray
Write-Host '       python src\pipeline\pipeline.py --input data\samples\clip.mp4 --camera-id cam_test --output outputs\ --preview' -ForegroundColor Gray
Write-Host '  5. Run tests: pytest tests\ -v' -ForegroundColor Gray
Write-Host ''
