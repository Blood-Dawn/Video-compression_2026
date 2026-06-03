<#
.SYNOPSIS
    Build (and smoke-test) the SVCS desktop bundle with PyInstaller.

.DESCRIPTION
    Cleans any prior build/ and dist/ output, ensures pyinstaller is
    installed in the active venv, runs the build against
    installer/svcs.spec, then optionally launches the resulting .exe
    and confirms it answers on http://127.0.0.1:5000 within a timeout.

    Run from the repo root with the .venv activated:

        .\installer\build.ps1                # full build + smoke test
        .\installer\build.ps1 -SkipSmoke     # build only
        .\installer\build.ps1 -Quick         # skip --clean (faster iteration)

    Build takes 5-15 minutes the first time, 1-3 minutes after that.
    Output: dist\SVCS\SVCS.exe  (~1.5 GB folder).

.NOTES
    Author: Bloodawn (KheivenD), 2026-05-14 (installer prep).
#>

[CmdletBinding()]
param(
    [switch]$SkipSmoke,
    [switch]$Quick,
    [int]$SmokePort = 5000,
    [int]$SmokeTimeoutSec = 60
)

$ErrorActionPreference = "Stop"

# ── Resolve repo root regardless of where the script is invoked from ──
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SpecFile = Join-Path $RepoRoot "installer\svcs.spec"
$DistDir  = Join-Path $RepoRoot "dist"
$BuildDir = Join-Path $RepoRoot "build"
$BundleExe = Join-Path $DistDir "SVCS\SVCS.exe"

Write-Host ""
Write-Host "─────────────────────────────────────────────────────────"
Write-Host "  SVCS PyInstaller build"
Write-Host "  Repo:  $RepoRoot"
Write-Host "  Spec:  $SpecFile"
Write-Host "─────────────────────────────────────────────────────────"
Write-Host ""

# ── Sanity checks ─────────────────────────────────────────────────────
if (-not (Test-Path $SpecFile)) {
    throw "Spec file not found: $SpecFile"
}

# Confirm we're inside a virtualenv. PyInstaller pulled into the system
# Python is a bad time on Windows; we want the same interpreter that
# was used to install our deps.
if (-not $env:VIRTUAL_ENV) {
    Write-Warning "No VIRTUAL_ENV detected. You probably want to activate .venv first:"
    Write-Warning "    .\venv\Scripts\Activate.ps1"
    Write-Warning "Continuing anyway."
}

# ── Step 1: make sure pyinstaller is installed ─────────────────────────
Write-Host "[1/4] Checking pyinstaller install..." -ForegroundColor Cyan
$pyinstallerCheck = & python -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null
if ($LASTEXITCODE -ne 0) {
    # PyInstaller is a build-time tool, not a project dependency, so a plain
    # `uv sync` removes it. The repo's .venv is uv-managed and has no `pip`,
    # so prefer `uv pip install`; fall back to `python -m pip` for non-uv envs.
    # Author: Bloodawn (KheivenD), 2026-06-02 (uv-venv build robustness).
    Write-Host "      pyinstaller not found, installing into current venv..." -ForegroundColor Yellow
    & uv pip install --upgrade pyinstaller
    if ($LASTEXITCODE -ne 0) {
        & python -m pip install --upgrade pyinstaller
        if ($LASTEXITCODE -ne 0) { throw "could not install pyinstaller (tried uv pip and python -m pip)" }
    }
} else {
    Write-Host "      pyinstaller $pyinstallerCheck OK" -ForegroundColor Green
}

# ── Step 2: clean prior artifacts (skip with -Quick) ──────────────────
if (-not $Quick) {
    Write-Host "[2/4] Cleaning prior build artifacts..." -ForegroundColor Cyan
    foreach ($d in @($DistDir, $BuildDir)) {
        if (Test-Path $d) {
            Write-Host "      removing $d"
            Remove-Item -Path $d -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
} else {
    Write-Host "[2/4] Skipping clean (-Quick passed)" -ForegroundColor DarkGray
}

# ── Step 3: run PyInstaller ───────────────────────────────────────────
Write-Host "[3/4] Building bundle (this can take 5-15 min on a cold run)..." -ForegroundColor Cyan
$pyinstallerArgs = @("--noconfirm", $SpecFile)
if (-not $Quick) { $pyinstallerArgs = @("--clean") + $pyinstallerArgs }

$buildStart = Get-Date
Push-Location $RepoRoot
try {
    & python -m PyInstaller @pyinstallerArgs
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
}
$buildElapsed = (Get-Date) - $buildStart

if (-not (Test-Path $BundleExe)) {
    throw "Build appeared to succeed but $BundleExe is missing"
}

$bundleSizeMB = [math]::Round(((Get-ChildItem (Split-Path $BundleExe) -Recurse | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host ""
Write-Host "      Build OK in $([math]::Round($buildElapsed.TotalSeconds,1)) sec" -ForegroundColor Green
Write-Host "      Exe:  $BundleExe"
Write-Host "      Size: $bundleSizeMB MB (dist\SVCS\ total)"

# ── Step 4: smoke test ────────────────────────────────────────────────
if ($SkipSmoke) {
    Write-Host "[4/4] Smoke test skipped (-SkipSmoke passed)" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "Done. Try it manually:  $BundleExe"
    return
}

Write-Host "[4/4] Smoke test — launching exe and probing port $SmokePort..." -ForegroundColor Cyan

# Launch the exe in the background. --no-browser keeps it from popping
# a window during CI / unattended runs.
$proc = Start-Process -FilePath $BundleExe `
    -ArgumentList @("--no-browser", "--no-sync", "--port", "$SmokePort", "--host", "127.0.0.1") `
    -PassThru `
    -WindowStyle Hidden

if (-not $proc) { throw "Failed to launch $BundleExe" }
Write-Host "      PID $($proc.Id), waiting for dashboard..."

$probeUrl = "http://127.0.0.1:$SmokePort/"
$probeOk = $false
$deadline = (Get-Date).AddSeconds($SmokeTimeoutSec)

while ((Get-Date) -lt $deadline) {
    if ($proc.HasExited) {
        Write-Host "      Process exited prematurely with code $($proc.ExitCode)" -ForegroundColor Red
        break
    }
    try {
        $r = Invoke-WebRequest -Uri $probeUrl -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($r.StatusCode -eq 200) {
            $probeOk = $true
            break
        }
    } catch {
        # Connection refused while Flask is still booting — keep trying.
        Start-Sleep -Milliseconds 500
    }
}

# Tear down the test process. Try graceful stop first, then kill the tree.
if (-not $proc.HasExited) {
    try { Stop-Process -Id $proc.Id -Force } catch { }
}

if ($probeOk) {
    Write-Host ""
    Write-Host "✓ Smoke test passed — dashboard answered on $probeUrl" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next:  double-click $BundleExe to use it for real,"
    Write-Host "       or hand off the dist\SVCS\ folder to Inno Setup."
    exit 0
} else {
    Write-Host ""
    Write-Host "✗ Smoke test FAILED — dashboard didn't answer within $SmokeTimeoutSec sec" -ForegroundColor Red
    Write-Host "  Re-run with the exe directly to see the traceback:"
    Write-Host "    $BundleExe --no-sync --no-browser"
    exit 1
}
