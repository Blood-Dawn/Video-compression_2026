<#
.SYNOPSIS
    Build (and smoke-test) the SVCS desktop bundle with PyInstaller.

.DESCRIPTION
    Cleans any prior build/ and dist/ output, ensures pyinstaller is
    installed in the active venv, runs the build against
    installer/svcs.spec, then optionally launches the resulting .exe
    and confirms it answers on http://127.0.0.1:5000 within a timeout.

    Run from the repo root with the .venv activated:

        .\installer\build.ps1                # full server build + smoke test
        .\installer\build.ps1 -Edition field # offline field build (SVCS-Field)
        .\installer\build.ps1 -SkipSmoke     # build only
        .\installer\build.ps1 -Quick         # skip --clean (faster iteration)

    Build takes 5-15 minutes the first time, 1-3 minutes after that.
    Output: dist\SVCS\SVCS.exe (server) or dist\SVCS-Field\SVCS-Field.exe (field).
    R4 Phase 4: -Edition selects the build; both come from installer\svcs.spec
    (parameterized by the SVCS_BUILD_EDITION env var it sets).

.NOTES
    Author: Bloodawn (KheivenD), 2026-05-14 (installer prep).
#>

[CmdletBinding()]
param(
    [ValidateSet("server", "field")]
    [string]$Edition = "server", # R4 Phase 4: which build to produce
    [switch]$SkipSmoke,
    [switch]$Quick,
    [switch]$Installer,          # also package dist\SVCS into SVCS-Setup-*.exe via Inno Setup
    [switch]$Sign,               # Authenticode-sign the bundle exe + installer (TASK 5b.1)
    [int]$SmokePort = 5000,
    [int]$SmokeTimeoutSec = 60
)

$ErrorActionPreference = "Stop"

# ── Build edition (R4 Phase 4) ────────────────────────────────────────
# svcs.spec reads SVCS_BUILD_EDITION to pick the exe name + bundle the runtime
# edition marker. "server" -> dist\SVCS\SVCS.exe; "field" -> dist\SVCS-Field\...
$env:SVCS_BUILD_EDITION = $Edition
$AppName = if ($Edition -eq "field") { "SVCS-Field" } else { "SVCS" }

# ── Resolve repo root regardless of where the script is invoked from ──
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SpecFile = Join-Path $RepoRoot "installer\svcs.spec"
$DistDir  = Join-Path $RepoRoot "dist"
$BuildDir = Join-Path $RepoRoot "build"
$BundleExe = Join-Path $DistDir "$AppName\$AppName.exe"

# ── Code signing (TASK 5b.1) ──────────────────────────────────────────
# The signing STEP is wired here; the cert is the owner's to provide (gated  - 
# see docs/BLOCKERS.md). Credentials come from the environment so no secret
# ever lives in the repo:
#   SVCS_SIGN_CERT        path to a .pfx               (or)
#   SVCS_SIGN_THUMBPRINT  thumbprint of a cert in the cert store
#   SVCS_SIGN_PASSWORD    .pfx password (when using SVCS_SIGN_CERT)
#   SVCS_SIGN_TIMESTAMP   RFC3161 timestamp URL (default: DigiCert)
# With -Sign but no cert configured, signing is SKIPPED with a warning (so an
# unsigned beta still builds). Investigate SignPath.io's free OSS program for a
# cert before buying an EV cert.
function Resolve-SignTool {
    $cmd = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
    if ($cmd) { return $cmd }
    $kit = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (Test-Path $kit) {
        $cand = Get-ChildItem $kit -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\' } |
            Sort-Object FullName -Descending | Select-Object -First 1
        if ($cand) { return $cand.FullName }
    }
    return $null
}

function Invoke-CodeSign {
    param([Parameter(Mandatory)][string]$FilePath)
    $pfx   = $env:SVCS_SIGN_CERT
    $thumb = $env:SVCS_SIGN_THUMBPRINT
    if (-not $pfx -and -not $thumb) {
        Write-Warning ("Signing requested but no cert configured " +
            "(set SVCS_SIGN_CERT or SVCS_SIGN_THUMBPRINT). Skipping $(Split-Path $FilePath -Leaf). " +
            "See docs/BLOCKERS.md.")
        return $false
    }
    $signtool = Resolve-SignTool
    if (-not $signtool) {
        Write-Warning "signtool.exe not found (install the Windows SDK). Skipping signing."
        return $false
    }
    $ts = if ($env:SVCS_SIGN_TIMESTAMP) { $env:SVCS_SIGN_TIMESTAMP } else { "http://timestamp.digicert.com" }
    $signArgs = @("sign", "/fd", "SHA256", "/tr", $ts, "/td", "SHA256")
    if ($pfx) {
        $signArgs += @("/f", $pfx)
        if ($env:SVCS_SIGN_PASSWORD) { $signArgs += @("/p", $env:SVCS_SIGN_PASSWORD) }
    } else {
        $signArgs += @("/sha1", $thumb)
    }
    $signArgs += $FilePath
    & $signtool @signArgs
    if ($LASTEXITCODE -ne 0) { throw "signtool failed ($LASTEXITCODE) for $FilePath" }
    Write-Host "      Signed: $(Split-Path $FilePath -Leaf)" -ForegroundColor Green
    return $true
}

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

# ── Step 2.5: vendor FFmpeg (M2 TASK 2.3) ─────────────────────────────
# Download a pinned FFmpeg once into tools/ffmpeg/bin so the installer is
# self-contained (the app resolves the bundled binary first; see
# src/utils/ffmpeg.py and docs/ffmpeg-licensing.md). tools/ is gitignored.
# We ship a GPL win64 build because the per-mode codec policy uses libx264
# (GPL) for Mode 0/1; that is licence-compatible with our AGPL app. A future
# non-GPL fork would swap this for an LGPL build + libopenh264 (see the doc).
# We use the SHARED win64 GPL build, not the static one: the static ffmpeg.exe
# is ~200 MB (and ~400 MB with ffprobe), which would blow the installer budget;
# the shared build is small exes + shared av*.dll, ~120 MB total for everything,
# and ffmpeg.exe loads its sibling DLLs from the same bin/ dir.
$FFmpegVersion = "latest"   # BtbN tag; pin to a dated autobuild-* tag per release
$FFmpegUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/$FFmpegVersion/ffmpeg-master-latest-win64-gpl-shared.zip"
$FFmpegDir = Join-Path $RepoRoot "tools\ffmpeg"
$FFmpegBin = Join-Path $FFmpegDir "bin\ffmpeg.exe"
Write-Host "[2.5] Vendoring FFmpeg (GPL win64 shared, $FFmpegVersion)..." -ForegroundColor Cyan
if (Test-Path $FFmpegBin) {
    Write-Host "      already present: $FFmpegBin" -ForegroundColor Green
} else {
    try {
        $tmpZip = Join-Path $env:TEMP "svcs-ffmpeg.zip"
        $tmpExtract = Join-Path $env:TEMP "svcs-ffmpeg-extract"
        Write-Host "      downloading $FFmpegUrl"
        Invoke-WebRequest -Uri $FFmpegUrl -OutFile $tmpZip -UseBasicParsing
        if (Test-Path $tmpExtract) { Remove-Item $tmpExtract -Recurse -Force }
        Expand-Archive -Path $tmpZip -DestinationPath $tmpExtract -Force
        # Archive: ffmpeg-*-win64-gpl-shared/{bin/*.exe+*.dll, LICENSE, ...}
        $srcExe = Get-ChildItem -Path $tmpExtract -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
        if (-not $srcExe) { throw "ffmpeg.exe not found in the downloaded archive" }
        $root = $srcExe.Directory.Parent.FullName     # the ffmpeg-*-win64-gpl-shared dir
        if (Test-Path $FFmpegDir) { Remove-Item $FFmpegDir -Recurse -Force }
        New-Item -ItemType Directory -Force $FFmpegDir | Out-Null
        # Copy the whole bin/ (exes + shared DLLs) and the license text.
        Copy-Item (Join-Path $root "bin") (Join-Path $FFmpegDir "bin") -Recurse -Force
        Get-ChildItem -Path $root -Filter "LICENSE*" -ErrorAction SilentlyContinue |
            ForEach-Object { Copy-Item $_.FullName (Join-Path $FFmpegDir $_.Name) -Force }
        Remove-Item $tmpZip -Force -ErrorAction SilentlyContinue
        Remove-Item $tmpExtract -Recurse -Force -ErrorAction SilentlyContinue
        $sz = [math]::Round(((Get-ChildItem $FFmpegDir -Recurse | Measure-Object Length -Sum).Sum/1MB),1)
        Write-Host "      vendored to $FFmpegBin ($sz MB)" -ForegroundColor Green
    } catch {
        Write-Warning "FFmpeg vendoring failed ($($_.Exception.Message)). The build will continue, but the bundle will rely on a system FFmpeg on PATH."
    }
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

# ── Step 3.5: package the Inno Setup installer (M2 TASK 2.4, opt-in) ───
# Sign the bundle exe BEFORE Inno packages it, so the installed app is signed too.
if ($Sign) {
    Write-Host "[3b/4] Signing bundle exe..." -ForegroundColor Cyan
    [void](Invoke-CodeSign -FilePath $BundleExe)
}

if ($Installer) {
    Write-Host "[3.5] Packaging Inno Setup installer..." -ForegroundColor Cyan
    $issFile = Join-Path $RepoRoot "installer\svcs.iss"
    if (-not (Test-Path $issFile)) { throw "Inno Setup script not found: $issFile" }
    $iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
    if (-not $iscc) {
        $isccCands = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
            "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
        )
        $iscc = $isccCands | Where-Object { Test-Path $_ } | Select-Object -First 1
    }
    if (-not $iscc) {
        Write-Warning "Inno Setup (ISCC.exe) not found. Install it (winget install JRSoftware.InnoSetup) to build the installer. Skipping."
    } else {
        & $iscc $issFile
        if ($LASTEXITCODE -ne 0) { throw "ISCC failed with exit code $LASTEXITCODE" }
        $setupExe = Get-ChildItem (Join-Path $RepoRoot "dist") -Filter "SVCS-Setup-*.exe" |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($setupExe) {
            $setupMB = [math]::Round($setupExe.Length / 1MB, 1)
            Write-Host "      Installer: $($setupExe.FullName) ($setupMB MB)" -ForegroundColor Green
            # Sign the installer itself (TASK 5b.1). Skips gracefully if no cert.
            if ($Sign) { [void](Invoke-CodeSign -FilePath $setupExe.FullName) }
        }
    }
}

# ── Step 4: smoke test ────────────────────────────────────────────────
if ($SkipSmoke) {
    Write-Host "[4/4] Smoke test skipped (-SkipSmoke passed)" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "Done. Try it manually:  $BundleExe"
    return
}

Write-Host "[4/4] Smoke test - launching exe and probing port $SmokePort..." -ForegroundColor Cyan

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
        # Connection refused while Flask is still booting - keep trying.
        Start-Sleep -Milliseconds 500
    }
}

# Tear down the test process. Try graceful stop first, then kill the tree.
if (-not $proc.HasExited) {
    try { Stop-Process -Id $proc.Id -Force } catch { }
}

if ($probeOk) {
    Write-Host ""
    Write-Host "✓ Smoke test passed - dashboard answered on $probeUrl" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next:  double-click $BundleExe to use it for real,"
    Write-Host "       or hand off the dist\SVCS\ folder to Inno Setup."
    exit 0
} else {
    Write-Host ""
    Write-Host "✗ Smoke test FAILED - dashboard didn't answer within $SmokeTimeoutSec sec" -ForegroundColor Red
    Write-Host "  Re-run with the exe directly to see the traceback:"
    Write-Host "    $BundleExe --no-sync --no-browser"
    exit 1
}
