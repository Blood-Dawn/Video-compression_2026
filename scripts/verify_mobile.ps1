# scripts/verify_mobile.ps1
#
# One command, no human input: build the SVCS Android debug APK, install it on
# a connected device or emulator, launch it, and check that it actually reached
# its main screen without crashing. Exits non-zero on any failure, so it can
# gate a commit or run from a scheduled task.
#
# What "reached a known screen" means here (planner 5.1):
#   1. `am start -W` reports Status: ok for org.svcs.mobile.MainActivity.
#   2. `dumpsys activity activities` shows MainActivity as the resumed
#      activity within -TimeoutSec seconds.
#   3. The app process is still alive after a short settle period.
#   4. logcat holds no FATAL EXCEPTION or ANR for the app's package.
# None of these need app code changes or any tapping.
#
# Usage:
#   powershell -File scripts\verify_mobile.ps1
#   powershell -File scripts\verify_mobile.ps1 -StartEmulator
#   powershell -File scripts\verify_mobile.ps1 -SkipBuild -Serial emulator-5554
#
# Exit codes:
#   0  all checks passed
#   1  toolchain problem (JDK, SDK, adb, gradle wrapper missing)
#   2  Gradle build failed or produced no APK
#   3  no usable device or emulator
#   4  APK install failed
#   5  app failed to launch
#   6  app launched but a post-launch check failed (not resumed, died, crashed)
#
# Author: Bloodawn (KheivenD), 2026-10-07 (planner 5.1).

[CmdletBinding()]
param(
    # Boot the AVD named by -AvdName if no device is attached, and shut it
    # down again at the end (unless -KeepEmulator is given).
    [switch]$StartEmulator,
    [string]$AvdName = 'svcs_test',
    [switch]$KeepEmulator,

    # Target a specific device when more than one is attached.
    [string]$Serial = '',

    # Reuse an APK from an earlier build instead of running Gradle.
    [switch]$SkipBuild,

    # Gradle build variant to verify. Only debug is wired up (its package id
    # is org.svcs.mobile.debug); qa and release need their own suffix.
    [ValidateSet('debug')]
    [string]$Variant = 'debug',

    # Seconds to wait for the emulator to boot, and for MainActivity to resume.
    [int]$BootTimeoutSec = 240,
    [int]$TimeoutSec = 30,

    # Where to save a screenshot of the final screen. Empty means skip.
    [string]$ScreenshotPath = ''
)

$ErrorActionPreference = 'Continue'

$repoRoot   = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$androidDir = Join-Path $repoRoot 'mobile\android'
$appId      = 'org.svcs.mobile.debug'
$activity   = 'org.svcs.mobile.MainActivity'

$script:EmulatorProc = $null
$script:StartedEmu   = $false

function Say([string]$Label, [string]$Text) {
    Write-Output ("  {0,-8} {1}" -f $Label, $Text)
}

function Finish([int]$Code, [string]$Why) {
    if ($script:StartedEmu -and -not $KeepEmulator -and $script:Adb) {
        & $script:Adb @script:SerialArgs emu kill 2>&1 | Out-Null
        if ($script:EmulatorProc -and -not $script:EmulatorProc.HasExited) {
            Start-Sleep -Seconds 3
            if (-not $script:EmulatorProc.HasExited) { $script:EmulatorProc.Kill() }
        }
    }
    Write-Output ''
    if ($Code -eq 0) {
        Write-Output "PASS: $Why"
    } else {
        Write-Output "FAIL (exit $Code): $Why"
    }
    exit $Code
}

# ---- Toolchain -------------------------------------------------------------
Write-Output 'SVCS mobile verify'
Write-Output ('=' * 60)

$sdk = $env:ANDROID_HOME
if (-not $sdk) { $sdk = $env:ANDROID_SDK_ROOT }
if (-not $sdk) { $sdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
if (-not (Test-Path $sdk)) {
    Finish 1 "Android SDK not found at $sdk. Run mobile\android\verify-toolchain.ps1."
}
# Gradle finds the SDK through ANDROID_HOME when local.properties is absent.
if (-not $env:ANDROID_HOME) { $env:ANDROID_HOME = $sdk }

$script:Adb = Join-Path $sdk 'platform-tools\adb.exe'
if (-not (Test-Path $script:Adb)) {
    $cmd = Get-Command adb -ErrorAction SilentlyContinue
    if ($cmd) { $script:Adb = $cmd.Source } else {
        Finish 1 'adb not found. Install platform-tools (sdkmanager "platform-tools").'
    }
}

if (-not $env:JAVA_HOME) {
    $jdk = Get-ChildItem 'C:\Program Files\Microsoft' -Directory -Filter 'jdk-*' -ErrorAction SilentlyContinue |
           Sort-Object Name -Descending | Select-Object -First 1
    if ($jdk) { $env:JAVA_HOME = $jdk.FullName }
}
if (-not (Get-Command java -ErrorAction SilentlyContinue) -and $env:JAVA_HOME) {
    $env:Path = (Join-Path $env:JAVA_HOME 'bin') + ';' + $env:Path
}
if (-not (Get-Command java -ErrorAction SilentlyContinue)) {
    Finish 1 'No JDK on PATH and no JAVA_HOME. Install JDK 17 or newer.'
}

$gradlew = Join-Path $androidDir 'gradlew.bat'
if (-not (Test-Path $gradlew)) { Finish 1 "gradlew.bat missing at $gradlew" }

Say '[ok]' "sdk      $sdk"
Say '[ok]' "adb      $($script:Adb)"
Say '[ok]' "java     $((& java -version 2>&1 | Select-Object -First 1))"

# ---- Device ----------------------------------------------------------------
function Get-AttachedDevices {
    $lines = & $script:Adb devices 2>&1 | Select-String -Pattern "\tdevice$"
    $out = @()
    foreach ($l in $lines) { $out += ($l.Line -split "\t")[0] }
    return $out
}

$devices = @(Get-AttachedDevices)

if ($devices.Count -eq 0 -and $StartEmulator) {
    $emuExe = Join-Path $sdk 'emulator\emulator.exe'
    if (-not (Test-Path $emuExe)) { Finish 3 "emulator.exe not found at $emuExe" }
    $avds = & $emuExe -list-avds 2>&1
    if (-not ($avds -contains $AvdName)) { Finish 3 "AVD '$AvdName' does not exist. Existing: $($avds -join ', ')" }

    Say '[boot]' "starting AVD $AvdName (headless)"
    $emuArgs = @('-avd', $AvdName, '-no-window', '-no-audio', '-no-snapshot-save', '-no-boot-anim', '-gpu', 'swiftshader_indirect')
    $script:EmulatorProc = Start-Process -FilePath $emuExe -ArgumentList $emuArgs -PassThru -WindowStyle Hidden
    $script:StartedEmu = $true

    $deadline = (Get-Date).AddSeconds($BootTimeoutSec)
    $booted = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        $devices = @(Get-AttachedDevices)
        if ($devices.Count -gt 0) {
            $b = (& $script:Adb -s $devices[0] shell getprop sys.boot_completed 2>&1 | Out-String).Trim()
            if ($b -eq '1') { $booted = $true; break }
        }
        if ($script:EmulatorProc.HasExited) { break }
    }
    if (-not $booted) { Finish 3 "emulator did not finish booting within $BootTimeoutSec seconds" }
    Say '[ok]' "emulator booted as $($devices[0])"
}

if ($devices.Count -eq 0) {
    Finish 3 'No device attached. Plug in a phone with USB debugging, start an emulator, or pass -StartEmulator.'
}

if ($Serial) {
    if ($devices -notcontains $Serial) { Finish 3 "Serial '$Serial' is not attached. Attached: $($devices -join ', ')" }
    $target = $Serial
} elseif ($devices.Count -gt 1) {
    Finish 3 "More than one device attached ($($devices -join ', ')). Pass -Serial."
} else {
    $target = $devices[0]
}
$script:SerialArgs = @('-s', $target)
$api = (& $script:Adb @script:SerialArgs shell getprop ro.build.version.sdk 2>&1 | Out-String).Trim()
$abi = (& $script:Adb @script:SerialArgs shell getprop ro.product.cpu.abi 2>&1 | Out-String).Trim()
Say '[ok]' "device   $target (API $api, $abi)"

# ---- Build -----------------------------------------------------------------
$apkDir = Join-Path $androidDir 'app\build\outputs\apk\debug'
if (-not $SkipBuild) {
    Say '[build]' 'gradlew assembleDebug (this can take several minutes)'
    $buildLog = Join-Path $env:TEMP 'svcs_verify_mobile_build.log'
    Push-Location $androidDir
    try {
        & $gradlew assembleDebug --console=plain --no-daemon 2>&1 | Out-File -FilePath $buildLog -Encoding ascii
        $gradleExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($gradleExit -ne 0) {
        Write-Output '  --- last 25 lines of the Gradle log ---'
        Get-Content $buildLog -Tail 25 | ForEach-Object { Write-Output "  $_" }
        Finish 2 "Gradle assembleDebug exited $gradleExit (full log: $buildLog)"
    }
    Say '[ok]' 'assembleDebug succeeded'
} else {
    Say '[skip]' 'build (using the existing APK)'
}

# The universal APK installs on any ABI, so it is the safe pick for any device.
$apk = Join-Path $apkDir 'app-universal-debug.apk'
if (-not (Test-Path $apk)) {
    $apk = (Get-ChildItem $apkDir -Filter '*debug.apk' -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
}
if (-not $apk -or -not (Test-Path $apk)) { Finish 2 "No debug APK found under $apkDir" }
Say '[ok]' ("apk      {0} ({1:N0} bytes)" -f (Split-Path $apk -Leaf), (Get-Item $apk).Length)

# ---- Install ---------------------------------------------------------------
$inst = & $script:Adb @script:SerialArgs install -r $apk 2>&1 | Out-String
if ($inst -notmatch 'Success') {
    Finish 4 "adb install did not report Success: $($inst.Trim())"
}
Say '[ok]' "installed $appId"

# Notification permission is a runtime prompt on API 33+; grant it up front so
# no dialog sits on top of the screen being checked.
if ([int]$api -ge 33) {
    & $script:Adb @script:SerialArgs shell pm grant $appId android.permission.POST_NOTIFICATIONS 2>&1 | Out-Null
}

# ---- Launch ----------------------------------------------------------------
& $script:Adb @script:SerialArgs shell am force-stop $appId 2>&1 | Out-Null
& $script:Adb @script:SerialArgs logcat -c 2>&1 | Out-Null

$start = & $script:Adb @script:SerialArgs shell am start -W -n "$appId/$activity" 2>&1 | Out-String
if ($start -match 'Error' -or $start -notmatch 'Status:\s*ok') {
    Finish 5 "am start did not report Status: ok: $($start.Trim())"
}
Say '[ok]' 'am start -W reported Status: ok'

# ---- Assertions ------------------------------------------------------------
$resumed = $false
$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
    $dump = & $script:Adb @script:SerialArgs shell dumpsys activity activities 2>&1 | Out-String
    if ($dump -match "(topResumedActivity|mResumedActivity)[^\r\n]*$([regex]::Escape($appId))/") {
        $resumed = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $resumed) { Finish 6 "$activity never became the resumed activity within $TimeoutSec seconds" }
Say '[ok]' 'MainActivity is the resumed activity'

# Let startup work (DataStore reads, WorkManager init) run, then re-check.
Start-Sleep -Seconds 4
$pid1 = (& $script:Adb @script:SerialArgs shell pidof $appId 2>&1 | Out-String).Trim()
if (-not $pid1 -or $pid1 -notmatch '^\d+') { Finish 6 'app process is gone 4 seconds after launch (it died)' }
Say '[ok]' "process alive (pid $pid1)"

$log = & $script:Adb @script:SerialArgs logcat -d 2>&1 | Out-String
$crash = [regex]::Match($log, "FATAL EXCEPTION[\s\S]{0,400}?Process:\s*$([regex]::Escape($appId))")
if ($crash.Success) {
    Write-Output '  --- crash excerpt ---'
    $crash.Value -split "`n" | Select-Object -First 8 | ForEach-Object { Write-Output "  $_" }
    Finish 6 'logcat holds a FATAL EXCEPTION for the app'
}
if ($log -match "ANR in $([regex]::Escape($appId))") { Finish 6 'logcat holds an ANR for the app' }
Say '[ok]' 'logcat clean (no FATAL EXCEPTION, no ANR)'

if ($ScreenshotPath) {
    & $script:Adb @script:SerialArgs shell screencap -p /sdcard/svcs_verify.png 2>&1 | Out-Null
    & $script:Adb @script:SerialArgs pull /sdcard/svcs_verify.png $ScreenshotPath 2>&1 | Out-Null
    & $script:Adb @script:SerialArgs shell rm /sdcard/svcs_verify.png 2>&1 | Out-Null
    if (Test-Path $ScreenshotPath) { Say '[ok]' "screenshot $ScreenshotPath" }
}

Finish 0 "$appId built, installed, launched, and stayed up on $target (API $api)"
