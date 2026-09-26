# Release checklist

The one checklist for cutting a release, desktop or mobile. Before
2026-09-24 there were two (this file and a second copy under docs/releases/)
that disagreed about the branch, the tag and where the notes go; they are
merged here.

Every step up to the last one can be run by any contributor. **Tagging and
publishing the GitHub Release is the repo owner's action alone**; nothing
before that step touches the public remote's tags or releases. Open gates
(signing cert, release keystore) are tracked in [BLOCKERS.md](BLOCKERS.md).

Current tags: desktop `v2.2.0-beta`, mobile `v1.2-beta` (app 1.2.0-beta,
versionCode 15). Prepared but unreleased: mobile 1.2.1-beta (versionCode 16),
a hotfix for a compression bitrate bug found in 1.2.0-beta; notes drafted in
`docs/releases/release-notes-mobile-1.2.1-beta.md`.

## Desktop (Windows installer)

1. **Pre-flight.** Release from `mobile` (the active integration branch
   all work actually lands on; `main` trails it and should not be used
   for a build) with a clean working tree. The
   version must match in three places: `pyproject.toml`,
   `installer/svcs.iss` (`MyAppVersion`) and `src/utils/version.py`
   (`APP_VERSION`, which also feeds the in-app update check and
   `/api/capabilities`). `tests/test_version_consistency.py` checks the
   first two. Then `uv sync --frozen --extra enhance --extra crash-reporting`.
2. **run_tests.** `uv run pytest` (or `pwsh scripts/run_tests.ps1`). Everything
   passes or has a documented skip, on the Linux and Windows CI matrix too.
   `tests/security/` must be green: it guards auth, CSRF, SQLi, XSS, SSRF,
   path traversal and crypto regressions.
3. **build.** `installer\build.ps1 -Installer` with the venv active
   (`-Edition server` is the default; `-Edition field` builds the offline
   field kit). It vendors FFmpeg, runs PyInstaller, then `iscc`. Add `-Sign`
   to Authenticode-sign (see Code signing below); without a cert it warns and
   builds unsigned.
4. **smoke.** `build.ps1` launches the new exe and waits for
   `http://127.0.0.1:5000` (`-SmokeTimeoutSec`, default 60). Never pass
   `-SkipSmoke` for a release. Then, on a clean Windows VM with no Python or
   FFmpeg: install, launch, compress a short clip, check the output with
   `ffprobe`, confirm ONNX detection works with no torch, and confirm
   uninstall keeps user data in `%APPDATA%`.
5. **checksum / sha256.** Write `SHA256SUMS.txt` for every artifact you will
   attach:
   ```powershell
   Get-FileHash .\SVCS-Setup-<version>.exe -Algorithm SHA256 |
     ForEach-Object { "$($_.Hash.ToLower())  $(Split-Path $_.Path -Leaf)" } |
     Out-File -Encoding ascii SHA256SUMS.txt
   ```
6. **draft.** Write `docs/releases/release-notes-v<version>-beta.md` in the
   repo first, so it gets reviewed like everything else. It must say plainly
   that the build is an unsigned beta, explain the SmartScreen warning and
   how to get past it, list the checksums, and state the license (AGPL-3.0).
   If the winget manifests are being updated, recompute their SHA with
   `pwsh scripts/winget_validate.ps1 -Recompute` against the real asset.
7. **owner / publish / tag.** The owner creates the tag (`git tag vX.Y.Z-beta`),
   pushes it, and publishes a pre-release with the installer and
   `SHA256SUMS.txt` attached. Afterwards, check that the download page link
   (`docs/site/index.html`, Releases/latest) resolves to the new asset.

### Code signing

`installer\build.ps1 -Sign` signs both the bundle exe and the installer with
`signtool`, SHA-256 file digest and an RFC3161 timestamp (`/fd SHA256 /tr ...`)
so signatures outlive the cert. The cert comes from the environment, never the
repo: `SVCS_SIGN_CERT` (path to a `.pfx`) plus `SVCS_SIGN_PASSWORD`, or
`SVCS_SIGN_THUMBPRINT` for a cert already in the store. Verify with
`signtool verify /pa /v dist\SVCS-Setup-<version>.exe` (and `dist\SVCS\SVCS.exe`).
Getting a cert (SignPath's free OSS program first) is an owner gate in
[BLOCKERS.md](BLOCKERS.md).

## Mobile (Android APK)

Mobile releases use their own tags (`v1-beta` so far) so the two release
trains never collide. The desktop update check ignores mobile tags on purpose
(see `src/gui/routes/setup_bp.py`).

1. **Pre-flight.** Bump `versionCode` and `versionName` in
   `mobile/android/app/build.gradle.kts` (and add a line to the history
   comment there) whenever the release contains new commits. Add
   `mobile/android/fastlane/metadata/android/en-US/changelogs/<versionCode>.txt`
   for F-Droid and IzzyOnDroid.
2. **run_tests.** From `mobile/android`: `./gradlew testDebugUnitTest`. All
   tests must pass (CI's `android` job runs the same command). The old
   `ServerSettingsViewModelTest` Keystore failure was fixed on 2026-09-24.
3. **build.** `./gradlew assembleRelease`. ABI splits produce
   `app/build/outputs/apk/release/app-arm64-v8a-release.apk` and
   `app-universal-release.apk` (plus armeabi-v7a and x86_64). R8 is on.
   **Signing matters:** without `SVCS_ANDROID_KEYSTORE` the release build
   falls back to the debug key of the machine that built it, and Android
   refuses to install an update signed with a different key than the
   installed app. Build releases on the same machine as the previous ones
   (the owner's Windows PC) until a real release keystore exists (an owner
   gate in [BLOCKERS.md](BLOCKERS.md)). Never publish a cloud- or CI-built APK.
4. **smoke.** Install the release APK over the previous version on an
   emulator or phone (`adb install -r`), launch it, confirm the process stays
   up and `adb logcat -d | grep -E "FATAL|AndroidRuntime"` is empty, then run
   one compression job end to end. This is the first real exercise of the R8
   keep rules, so do not skip it.
5. **checksum / sha256.** Rename to `svcs-mobile-<tag>.apk` (arm64) and
   `svcs-mobile-<tag>-universal.apk`, then write `SHA256SUMS.txt` for both
   (`sha256sum` or the `Get-FileHash` snippet above).
6. **draft.** Notes in `docs/releases/release-notes-mobile-<tag>.md` (see
   `release-notes-mobile-v1-beta.md` for the shape: which APK to pick, what
   changed, what was verified, known limits).
7. **owner / publish / tag.** The owner tags and publishes a pre-release with
   both APKs and `SHA256SUMS.txt`.

## Keeping this honest

If a release stops matching these steps, fix this file in the same change
that alters the process. A checklist nobody follows is worse than none.

Authors: Bloodawn (KheivenD), 2026-06-03 (desktop checklist), 2026-09-22
(mobile-only section, TASK 4.11), 2026-09-24 (merged into one file).
