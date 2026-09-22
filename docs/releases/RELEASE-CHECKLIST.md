# SVCS release checklist

A repeatable checklist for cutting a public release. The build/verify steps are
done by whoever prepares the release; **tagging and publishing the GitHub Release
is the owner's action** (it's a gated step - see `docs/plans/BLOCKERS.md`).

Versions follow the installer name: `SVCS-Setup-<version>.exe`. The first public
drop is the **unsigned beta** `v2.1.0-beta`.

---

## 1. Pre-flight (clean checkout)

- [ ] `git switch app && git pull` - release from `app`, working tree clean.
- [ ] Confirm the version in `pyproject.toml` / installer matches the intended tag.
- [ ] `uv sync --extra enhance --extra crash-reporting` - env matches the lockfile.

## 2. Quality gate

- [ ] `pwsh scripts/run_tests.ps1` → **green** (≥513 passed, 0 failed, 3 webcam skips).
- [ ] No open tasks remain for this milestone in the team's project tracker.

## 3. Build the installer

- [ ] `pwsh installer/build.ps1 -Installer` (vendors FFmpeg, runs PyInstaller, then `iscc`).
- [ ] Output present: `installer/dist/SVCS-Setup-<version>.exe`.
- [ ] Note the unpacked size and the installer size for the release notes.

## 4. Smoke-test the installer

- [ ] On a clean Windows VM (no Python, no FFmpeg): install → launch → dashboard opens.
- [ ] Run a short clip through a preset; confirm a compressed `.mp4` is produced
      and plays. Validate with `ffprobe`, not `cv2`.
- [ ] ONNX object detection works (no torch present).
- [ ] Uninstall leaves `%APPDATA%` user data intact.

## 5. Checksums

- [ ] Generate `SHA256SUMS.txt` next to the installer:
      ```powershell
      Get-FileHash .\SVCS-Setup-<version>.exe -Algorithm SHA256 |
        ForEach-Object { "$($_.Hash.ToLower())  $(Split-Path $_.Path -Leaf)" } |
        Out-File -Encoding ascii SHA256SUMS.txt
      ```
- [ ] Verify the printed hash matches what the download page tells users to check.

## 6. Draft the GitHub Release  🚦 *owner publishes*

- [ ] Draft a release from the **draft notes** (`docs/release-notes-v2.1.0-beta.md`).
- [ ] Attach `SVCS-Setup-<version>.exe` and `SHA256SUMS.txt`.
- [ ] Mark it a **pre-release**; the title/notes state clearly it is an
      **unsigned beta** and SmartScreen will warn.
- [ ] **Owner action:** create the tag (`v2.1.0-beta`) and click *Publish*.
      The agent does not tag or publish (gated - `docs/plans/BLOCKERS.md`).

## 6b. Code signing (GA - TASK 5b.1)  🚦 *needs a cert*

The signing step is wired into `installer/build.ps1` (`-Sign`); it signs the
bundle exe *and* the installer with `signtool`. It needs a Windows code-signing
certificate, which is the **owner's to obtain** - investigate
[SignPath.io's free OSS program](https://signpath.io/) before buying an EV cert.
The unsigned **beta** ships without this; a **GA** build should be signed.

- [ ] Provide the cert via env (never commit it):
      `SVCS_SIGN_CERT` (path to `.pfx`) + `SVCS_SIGN_PASSWORD`, **or**
      `SVCS_SIGN_THUMBPRINT` (cert already in the store).
- [ ] Build signed: `pwsh installer/build.ps1 -Installer -Sign`.
- [ ] Verify both binaries: `signtool verify /pa /v dist\SVCS-Setup-<version>.exe`
      (and `dist\SVCS\SVCS.exe`).
- [ ] Confirm SmartScreen no longer warns on a clean machine after some reputation builds.

## 7. Post-publish

- [ ] Confirm the download page link (`docs/site/index.html` → Releases/latest) resolves to the new asset.
- [ ] Spot-check the published `SHA256SUMS.txt` against a fresh download.
- [ ] Open a tracking issue for the next milestone (signing - TASK 5b.1).

---

*Author: Bloodawn (KheivenD), 2026-06-03 (TASK 5.4 - release checklist).*


---

## Mobile-only release (TASK 4.11)

A separate, smaller checklist for cutting a **mobile-only** release: just the
Android APK, tagged apart from the desktop installer's `vX.Y.Z` tags so the
two release trains never collide. Earlier APKs shipped bundled inside a
combined desktop-plus-mobile tag (see `release-notes-v2.2.0-beta.md`); this
path is for shipping the phone app on its own, e.g. between desktop cuts.

Same gate as above applies: **tagging and publishing is the owner's action.**
The agent prepares everything up to that point.

### 1. Build

```powershell
cd mobile/android
.\gradlew.bat assembleRelease
```

Output: `app/build/outputs/apk/release/app-release.apk`. The build falls back
to debug signing when the `SVCS_ANDROID_KEYSTORE` env vars are not set (see
the comment above `signingConfigs` in `app/build.gradle.kts`), which is fine
for a sideloaded beta - a self-signed key is the normal, correct thing here.

- [ ] Confirm `versionCode`/`versionName` in `app/build.gradle.kts` match the
      intended tag. Bump both first if this release contains new commits
      since the last one; if not (a same-day catch-up release), leave them.
- [ ] Rename/copy to `SVCS-Mobile-<versionName>.apk` next to the original.

### 2. Smoke-test

- [ ] `adb install -r SVCS-Mobile-<versionName>.apk` on an emulator or device.
- [ ] `adb shell am start -n org.svcs.mobile/.MainActivity`, confirm the
      process stays alive (`adb shell pidof org.svcs.mobile`) and
      `adb logcat -d | grep -E "FATAL|AndroidRuntime"` shows nothing - this is
      the release variant, so it is the first real exercise of the R8/ProGuard
      keep rules, not just the debug build.

### 3. Checksum

```powershell
Get-FileHash .\SVCS-Mobile-<versionName>.apk -Algorithm SHA256 |
  ForEach-Object { "$($_.Hash.ToLower())  $(Split-Path $_.Path -Leaf)" } |
  Out-File -Encoding ascii SHA256SUMS.txt
```

### 4. Draft the GitHub Release 🚦 *owner publishes*

- [ ] Draft notes: `docs/releases/release-notes-mobile-<tag>.md` (see the
      `v0.9.0-beta` one for the template).
- [ ] Attach the renamed APK and `SHA256SUMS.txt`.
- [ ] Mark it a **pre-release** while the app is still beta.
- [ ] **Owner action:** create the tag (e.g. `mobile-v0.9.0-beta` - the
      `mobile-` prefix keeps it out of the desktop tag sequence) and click
      *Publish*. The agent does not tag or publish, same as the desktop flow.

*Added 2026-09-22 (TASK 4.11, Week 4).*
