<#
.SYNOPSIS
    Validate the SVCS winget manifest, and optionally recompute the installer
    SHA256 against a built asset (R3.2a).

.DESCRIPTION
    Runs `winget validate` over installer/winget so the triplet (version /
    installer / locale) is checked before it is submitted to
    microsoft/winget-pkgs. With -Recompute, it hashes the built installer and
    rewrites InstallerSha256 in the installer manifest so the manifest matches
    the EXACT released asset (do this after rebuilding the installer).

    This does NOT submit anything. The public submission is owner-gated; see
    docs/winget-submission.md and docs/BLOCKERS.md.

.PARAMETER Recompute
    Recompute InstallerSha256 from -InstallerPath and patch the installer
    manifest in place.

.PARAMETER InstallerPath
    Path to the built installer. Defaults to dist/SVCS-Setup-<version>.exe.

.EXAMPLE
    pwsh scripts/winget_validate.ps1

.EXAMPLE
    pwsh scripts/winget_validate.ps1 -Recompute
#>
[CmdletBinding()]
param(
    [switch]$Recompute,
    [string]$InstallerPath
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$WingetDir = Join-Path $RepoRoot 'installer/winget'
$InstallerManifest = Join-Path $WingetDir 'Blood-Dawn.SVCS.installer.yaml'

function Get-PackageVersion {
    $pyproject = Join-Path $RepoRoot 'pyproject.toml'
    foreach ($line in Get-Content $pyproject) {
        if ($line -match '^\s*version\s*=\s*"([^"]+)"') { return $Matches[1] }
    }
    throw 'Could not read version from pyproject.toml'
}

$version = Get-PackageVersion
Write-Host "SVCS winget manifest validation (version $version)" -ForegroundColor Cyan

if ($Recompute) {
    if (-not $InstallerPath) {
        $InstallerPath = Join-Path $RepoRoot "dist/SVCS-Setup-$version.exe"
    }
    if (-not (Test-Path $InstallerPath)) {
        throw "Installer not found: $InstallerPath (build it first with installer/build.ps1 -Installer)"
    }
    $sha = (Get-FileHash -Algorithm SHA256 -Path $InstallerPath).Hash.ToUpper()
    Write-Host "Computed SHA256: $sha" -ForegroundColor Green
    $content = Get-Content $InstallerManifest -Raw
    $patched = [System.Text.RegularExpressions.Regex]::Replace(
        $content, 'InstallerSha256:\s*[0-9A-Fa-f]+', "InstallerSha256: $sha")
    Set-Content -Path $InstallerManifest -Value $patched -NoNewline
    Write-Host "Patched InstallerSha256 in $InstallerManifest" -ForegroundColor Green
}

$winget = Get-Command winget -ErrorAction SilentlyContinue
if ($winget) {
    Write-Host "Running: winget validate --manifest $WingetDir" -ForegroundColor Cyan
    & winget validate --manifest $WingetDir
    if ($LASTEXITCODE -ne 0) {
        throw "winget validate failed with exit code $LASTEXITCODE"
    }
    Write-Host 'winget validate: OK' -ForegroundColor Green
}
else {
    Write-Host 'winget not found on PATH.' -ForegroundColor Yellow
    Write-Host 'Install "App Installer" from the Microsoft Store, then re-run,' -ForegroundColor Yellow
    Write-Host "or validate with wingetcreate: wingetcreate validate $WingetDir" -ForegroundColor Yellow
    Write-Host 'Skipping the live validate step (manifest files were still checked structurally by tests/test_winget_manifest.py).' -ForegroundColor Yellow
}
