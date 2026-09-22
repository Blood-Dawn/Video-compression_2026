# SVCS Mobile v0.9.0-beta - draft release notes

First mobile-only release. Earlier APKs shipped bundled inside a combined
desktop-plus-mobile tag (see the v2.2.0-beta notes); this is the first one
cut and tagged on its own, matching the plan in
`docs/project-records/PLANNER-FALL-2026.md` task 4.11. No desktop installer
is attached here.

## Mobile (SVCS-Mobile-0.9.0-beta.apk)

Thin client for a self-hosted SVCS server; it does not encode video on the
phone. Pair by server address and a device token minted in the desktop
TOOLS tab, then HOME, LIBRARY, METRICS, LIVE, and EVENTS. Sensitive
surfaces set `FLAG_SECURE`, so the OS blocks screenshots of your footage by
design. minSdk 29 (Android 10), self-signed release key, sideload install.

Everything since the last published mobile drop (0.5.0, in v2.2.0-beta):

- 0.6.0 (R6 Track A): EVENTS tab with a behavior-event list (line-crossing,
  loitering, direction) and a drag-to-draw zone/line editor per camera.
- 0.7.0 (R6 Track B): resumable chunked upload straight from the phone's
  gallery, with auto-compress on completion.
- 0.8.0: auto-compress-on-upload became a MORE toggle; INFO on every clip
  now shows per-video metrics (codec, resolution, fps, duration,
  provenance) instead of only server-wide numbers.
- 0.9.0 (R6 Track C): closed-app push notifications. MORE gained a remote
  control for the server's ntfy settings, so a job-complete or event alert
  reaches the phone through the ntfy app even after Android has stopped
  SVCS in the background.

Also fixed this release cycle, ahead of tagging: an earlier merge had
silently deleted the entire Android module (all of `app/src/main/` plus
the Gradle project files) from this branch without flagging a conflict.
It has been restored, the JVM test suite runs clean (37/38, the one
failure being a documented test-environment limitation, not a product
bug), and a real instrumented test now proves pairing survives an app
restart against a live Android Keystore and on-disk DataStore file. Full
detail in the `mobile` branch history (tasks 4.1/4.2).

Verified this cycle: `./gradlew assembleRelease` builds clean
(minification and the R8/ProGuard keep rules exercised, not just the debug
variant), installs on a fresh android-35 emulator, and launches without
crashing (checked via `adb logcat` for `FATAL`/`AndroidRuntime`, none
found). Not yet verified on a physical device for this specific build; the
0.9.0 feature set itself was verified on a physical Samsung device earlier
in the milestone.

## Install and verify

Android: enable installs from unknown sources for your browser or file
manager, download the APK, open it. On first run enter your server address
and a device token minted in the desktop TOOLS tab.

Checksum:

```
Get-FileHash .\SVCS-Mobile-0.9.0-beta.apk -Algorithm SHA256
```

Compare against `SHA256SUMS.txt` attached to the release. Expected:

```
1cfae4044bfee1f01d18cca4f6a07d9381d65210b4c850b9f05530860dac932b  SVCS-Mobile-0.9.0-beta.apk
```

License: AGPL-3.0. Source at the repository this release is attached to.
