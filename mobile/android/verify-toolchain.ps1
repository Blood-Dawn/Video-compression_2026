# mobile/android/verify-toolchain.ps1
#
# Checks that this machine can actually build the SVCS Android module.
#
# Written because the module was authored on a machine with no JDK and no
# Android SDK, so "it compiles" was never true here. Run this first on any new
# machine; it reports what is missing rather than failing at a Gradle stack
# trace 40 lines deep.
#
# Usage:
#   pwsh -File mobile/android/verify-toolchain.ps1
#   pwsh -File mobile/android/verify-toolchain.ps1 -WriteLocalProperties
#
# Author: Bloodawn (KheivenD), 2026-07-19 (Android toolchain setup).

[CmdletBinding()]
param(
    # Write local.properties pointing at the detected SDK. Off by default:
    # the file is gitignored and machine-specific, so it is generated on
    # request rather than silently created by a script called "verify".
    [switch]$WriteLocalProperties
)

$ErrorActionPreference = 'Continue'
$script:Failures = 0
$script:Warnings = 0

# Refresh PATH and JAVA_HOME from the registry before checking anything.
#
# This script's whole purpose is "run me right after installing the toolchain",
# and that is exactly the moment the current shell holds a STALE environment:
# an MSI writes machine-level JAVA_HOME and PATH, but already-running processes
# keep the copy they inherited at launch. Without this, the script reports a
# perfectly good JDK as missing and sends you chasing an install you already
# did. Machine scope first, then user, matching how Windows composes them.
function Sync-EnvironmentFromRegistry {
    foreach ($name in 'JAVA_HOME', 'ANDROID_HOME', 'ANDROID_SDK_ROOT') {
        $v = [System.Environment]::GetEnvironmentVariable($name, 'Machine')
        if (-not $v) { $v = [System.Environment]::GetEnvironmentVariable($name, 'User') }
        if ($v) { Set-Item -Path "Env:$name" -Value $v }
    }
    $machinePath = [System.Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath    = [System.Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machinePath, $userPath) | Where-Object { $_ }) -join ';'
    # A JDK MSI may set JAVA_HOME without putting java on PATH. Add its bin so
    # the rest of the checks can just call java.
    if ($env:JAVA_HOME) {
        $jbin = Join-Path $env:JAVA_HOME 'bin'
        if ((Test-Path $jbin) -and ($env:Path -notlike "*$jbin*")) {
            $env:Path = "$jbin;$env:Path"
        }
    }
}
Sync-EnvironmentFromRegistry

function Test-Item {
    param([string]$Label, [scriptblock]$Check, [string]$Fix, [switch]$Warn)
    $result = & $Check
    if ($result) {
        "  [ok]   {0,-26} {1}" -f $Label, $result
    } elseif ($Warn) {
        $script:Warnings++
        "  [warn] {0,-26} missing. {1}" -f $Label, $Fix
    } else {
        $script:Failures++
        "  [FAIL] {0,-26} missing. {1}" -f $Label, $Fix
    }
}

Write-Output "SVCS Android toolchain check"
Write-Output ("=" * 60)

# ---- JDK ----------------------------------------------------------------
Write-Output "`nJDK (AGP 8.7.3 requires 17 or newer)"
Test-Item "java on PATH" {
    $c = Get-Command java -ErrorAction SilentlyContinue
    if ($c) { (& java -version 2>&1 | Select-Object -First 1) } else { $null }
} "Install with: winget install --id Microsoft.OpenJDK.17 --exact"

Test-Item "JAVA_HOME" {
    if ($env:JAVA_HOME -and (Test-Path $env:JAVA_HOME)) { $env:JAVA_HOME } else { $null }
} "Set JAVA_HOME to the JDK root, or reopen the shell after installing."

Test-Item "JDK major version >= 17" {
    # Guarded: without java on PATH this used to throw an unhandled
    # CommandNotFoundException and print a red stack trace in the middle of an
    # otherwise readable report.
    if (-not (Get-Command java -ErrorAction SilentlyContinue)) { return $null }
    $line = (& java -version 2>&1 | Select-Object -First 1) -as [string]
    if ($line -match 'version\s+"?(\d+)') {
        $major = [int]$Matches[1]
        if ($major -ge 17) { "major $major ($line)" } else { $null }
    } else { $null }
} "The build pins JavaVersion.VERSION_17. Install JDK 17."

# ---- Android SDK --------------------------------------------------------
Write-Output "`nAndroid SDK"
$sdk = $env:ANDROID_HOME
if (-not $sdk) { $sdk = $env:ANDROID_SDK_ROOT }
if (-not $sdk) { $sdk = "$env:LOCALAPPDATA\Android\Sdk" }

Test-Item "SDK root" {
    if (Test-Path $sdk) { $sdk } else { $null }
} "Install Android Studio, or unpack cmdline-tools and run sdkmanager."

Test-Item "platform-tools (adb)" {
    $adb = Join-Path $sdk "platform-tools\adb.exe"
    if (Test-Path $adb) { (& $adb version 2>&1 | Select-Object -First 1) } else { $null }
} "sdkmanager `"platform-tools`""

# compileSdk / targetSdk are 35 in app/build.gradle.kts.
Test-Item "platforms;android-35" {
    $p = Join-Path $sdk "platforms\android-35"
    if (Test-Path $p) { $p } else { $null }
} "sdkmanager `"platforms;android-35`"  (compileSdk = 35)"

Test-Item "build-tools" {
    $bt = Join-Path $sdk "build-tools"
    if (Test-Path $bt) {
        $v = Get-ChildItem $bt -Directory -ErrorAction SilentlyContinue |
             Sort-Object Name -Descending | Select-Object -First 1
        if ($v) { $v.Name } else { $null }
    } else { $null }
} "sdkmanager `"build-tools;35.0.0`""

Test-Item "cmdline-tools" {
    $ct = Join-Path $sdk "cmdline-tools"
    if (Test-Path $ct) { (Get-ChildItem $ct -Directory | ForEach-Object Name) -join ', ' } else { $null }
} "sdkmanager `"cmdline-tools;latest`"" -Warn

Test-Item "licenses accepted" {
    $l = Join-Path $sdk "licenses"
    if ((Test-Path $l) -and (Get-ChildItem $l -File -ErrorAction SilentlyContinue)) {
        "$((Get-ChildItem $l -File).Count) license file(s)"
    } else { $null }
} "Run: sdkmanager --licenses   (Gradle refuses to build without these)"

# ---- Gradle wrapper -----------------------------------------------------
Write-Output "`nGradle"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Test-Item "wrapper properties" {
    # Anchored: an unanchored 'distributionUrl' also matches
    # validateDistributionUrl, which is a different key on a later line, so the
    # check reported "validateDistributionUrl=true" as the Gradle version.
    $p = Join-Path $here "gradle\wrapper\gradle-wrapper.properties"
    if (-not (Test-Path $p)) { return $null }
    $m = Select-String -Path $p -Pattern '^distributionUrl=' | Select-Object -First 1
    if ($m) { ($m.Line -split '/')[-1] } else { $null }
} "gradle/wrapper/gradle-wrapper.properties is missing from the repo."

Test-Item "wrapper jar" {
    $p = Join-Path $here "gradle\wrapper\gradle-wrapper.jar"
    if (Test-Path $p) { "{0:N0} bytes" -f (Get-Item $p).Length } else { $null }
} "Not committed by design. Run 'gradle wrapper' once, or open the folder in Android Studio." -Warn

$localProps = Join-Path $here "local.properties"
if ($WriteLocalProperties -and (Test-Path $sdk)) {
    # Gradle reads sdk.dir from here. Backslashes must be escaped in a Java
    # properties file, so C:\Users\... has to be written C:\\Users\\...
    $escaped = $sdk -replace '\\', '\\\\'
    @(
        "# Generated by verify-toolchain.ps1 on $(Get-Date -Format 'yyyy-MM-dd').",
        "# Machine-specific and gitignored: do not commit.",
        "sdk.dir=$escaped"
    ) | Set-Content -Path $localProps -Encoding ascii
    "  [new]  local.properties            written, sdk.dir=$sdk"
}
Test-Item "local.properties" {
    if (Test-Path $localProps) {
        $line = (Select-String -Path $localProps -Pattern '^sdk\.dir=' | Select-Object -First 1)
        if ($line) { "sdk.dir set" } else { "present but has no sdk.dir" }
    } else { $null }
} "Gradle needs sdk.dir. Re-run this script with -WriteLocalProperties." -Warn

# ---- Device -------------------------------------------------------------
Write-Output "`nDevice"
Test-Item "adb device attached" {
    $adb = Join-Path $sdk "platform-tools\adb.exe"
    if (Test-Path $adb) {
        $devs = (& $adb devices 2>&1 | Select-String -Pattern "\tdevice$")
        if ($devs) { "$($devs.Count) device(s)" } else { $null }
    } else { $null }
} "Enable USB debugging on the phone and reconnect. Needed only to RUN, not to build." -Warn

# ---- Summary ------------------------------------------------------------
Write-Output ("`n" + ("=" * 60))
if ($script:Failures -eq 0) {
    Write-Output "READY: $($script:Warnings) warning(s), 0 blocking failure(s)."
    Write-Output "Next:  cd mobile/android; ./gradlew assembleDebug"
} else {
    Write-Output "NOT READY: $($script:Failures) blocking failure(s), $($script:Warnings) warning(s)."
    Write-Output "Fix the [FAIL] lines above, then re-run this script."
}
exit $script:Failures
