# SVCS Mobile (Android)

Thin client for a self-hosted SVCS server. It drives and monitors the server
over its REST API; it does not encode video on the phone. See
`docs/MOBILE-ARCHITECTURE.md` for why, and for the full milestone plan.

Status: **M1.1, one screen (server pairing). Compiles, tests pass, APK builds.**
AGPL-3.0 by inheritance from the repo root `LICENSE`.

---

## Build status

Verified on 2026-07-19 (Windows 11, JDK 17.0.19, AGP 8.7.3, Gradle 8.11.1,
compileSdk 35, build-tools 36.0.0):

| | |
| --- | --- |
| `./gradlew assembleDebug` | **BUILD SUCCESSFUL**, 0 errors, 0 warnings |
| APK | `app/build/outputs/apk/debug/app-debug.apk`, 25.93 MB |
| `./gradlew testDebugUnitTest` | **11 tests, 0 failures**, 0 skipped |

Only one thing had to change to get there: `gradle.properties` was missing
entirely, so the build died at `:app:checkDebugAarMetadata` with
`android.useAndroidX is not enabled`. The Kotlin itself compiled clean on the
first attempt that reached the compiler.

### Still NOT verified

- **Nothing has run on a device.** The M1.1 acceptance from the plan, "on a real
  device on the same LAN, entering the server address and credentials and
  tapping Test shows the server's edition and feature list", is **unmet**. A
  clean compile says the code is well-formed, not that the screen works.
- No instrumented tests have been run.
- The release variant has not been built, so the ProGuard rules are unexercised.

### What HAS been verified server-side

The server side, which is the part the client cannot work without, is tested in
the Python suite that does run here:

| What | Where |
| --- | --- |
| Bearer auth works on API, media, HLS and thumbnail routes, on separate connections | `tests/test_mobile_client_contract.py` |
| A native client (no `Origin`/`Referer`) is not CSRF-blocked | same |
| Every key this app parses from `/api/capabilities` is present | same |
| Revoking one device locks out that device only | same |
| A stolen device token cannot mint or revoke | `tests/test_device_tokens.py` |
| `Color.kt` matches the design tokens exactly, and no font CDN is referenced | `tests/test_android_theme_sync.py` |

The Kotlin now compiles and the requests it issues are the ones these tests
pin, so the server will answer correctly. That is a real guarantee, and it is
still strictly less than "the app works" until it runs on a phone.

---

## Building it

```bash
cd mobile/android
pwsh -File verify-toolchain.ps1   # check JDK/SDK/licenses BEFORE building
./gradlew assembleDebug
./gradlew testDebugUnitTest
```

`verify-toolchain.ps1` exists because a missing SDK platform or an unaccepted
license fails deep inside a Gradle stack trace rather than saying what is
wrong. It reports each missing piece with the exact `sdkmanager` line to fix
it, and refreshes `JAVA_HOME`/`PATH` from the registry first, since the shell
you run it in is usually the one that predates the install.

Pass `-WriteLocalProperties` to generate `local.properties` (gitignored,
machine-specific).

`gradlew` and `gradlew.bat` are committed; the wrapper JAR is not (it is a
binary). Regenerate it with `gradle wrapper --gradle-version 8.11.1`, or just
open the folder in Android Studio.

### Toolchain this was built with

| Component | Version | Source |
| --- | --- | --- |
| JDK | Microsoft OpenJDK 17.0.19 LTS | `winget install Microsoft.OpenJDK.17` |
| Android Studio | 2026.1.2.10 | `winget install Google.AndroidStudio` |
| Android SDK platform | android-35 | SDK Manager (matches `compileSdk`) |
| Build tools | 36.0.0 | SDK Manager |
| Gradle | 8.11.1 | wrapper |

Note the SDK Manager installs the newest platform by default (android-36.1
here), but AGP 8.7.3 supports `compileSdk 35`, so android-35 must be added
explicitly. Moving to 36 means bumping AGP and Gradle together; that is a
deliberate follow-up, not a drive-by.

This build is deliberately **not** wired into `scripts/run_tests.ps1`. The
Python suite must stay runnable on a machine with no JDK, which is the normal
case for this project.

## Pairing against a real server

1. Start the server so the phone can reach it. Loopback is the default, so a
   LAN bind is required: `python run_gui.py --host 0.0.0.0 --username you
   --password <strong>`. Read the exposure warning it prints.
2. Mint a device token. `POST /api/auth/tokens` with the dashboard password,
   body `{"label": "Pixel 8"}`. The token is shown **once**.
3. In the app, enter `http://<server-lan-ip>:5000` and the token, then tap
   **Test connection**.

Reach the server over a VPN (WireGuard or Tailscale) if you are off the LAN.
Do not port-forward: the server is plain HTTP, so the token and the video both
cross the wire in the clear.

## Layout

```
app/src/main/java/org/svcs/mobile/
  MainActivity.kt              single activity, FLAG_SECURE for the window
  SvcsApplication.kt           empty on purpose: no analytics, no crash SDK
  data/TokenStore.kt           AES-256-GCM under a Keystore key, DataStore ciphertext
  net/HostClassifier.kt        private-range gate, mirrors src/gui/auth.py
  net/SvcsApi.kt               OkHttp + the /api/capabilities model
  ui/ServerSettingsScreen.kt   the pairing screen
  ui/ServerSettingsViewModel.kt
  ui/theme/Color.kt            GENERATED from mobile/design/tokens/colors.css
  ui/theme/Theme.kt            dark-only scheme and type scale
```

## Decisions worth not re-litigating

- **No `androidx.security:security-crypto`.** Deprecated April 2025.
  `TokenStore` does the equivalent directly against the Keystore.
- **No FCM, no Firebase.** Excluded three times over: the no-cloud-calls house
  rule, the architecture (a self-hosted server has no outbound path to FCM),
  and F-Droid policy. Notification transport is an open owner decision.
- **No analytics, no crash reporter.** Matches the server's
  `send_default_pii=False`. If wanted later: ACRA to a self-hosted endpoint,
  opt-in.
- **No FFmpeg in the APK.** The client encodes nothing. FFmpegKit was retired
  2025-01-06 regardless.
- **Cleartext HTTP is permitted app-wide** in `network_security_config.xml`,
  and the real gate is `HostClassifier`. The file explains why the narrower
  approach is not expressible: it is a build-time resource, and `<domain>`
  supports no CIDR, so denying by default would block a server at
  `192.168.x.x`, which is the primary use case. The actual fix is TLS on the
  server.
- **Port 5000**, not the 8000 the mockup pre-fills. 5000 is `run_gui.py`'s
  default.
- **Dark theme only.** The design system has no light palette.

## Fonts

Bebas Neue, Space Mono, and Outfit (all OFL-1.1) are **not bundled yet**, so
`Theme.kt` uses platform defaults at the correct sizes and tracking. Vendor the
`.ttf` files under `res/font/` with their license text to finish this.
`mobile/design/tokens/fonts.css` fetches them from the Google Fonts CDN, which
must not reach the app; a test in `tests/test_android_theme_sync.py` enforces
that.

## Next

M2 (LIBRARY, METRICS) and M3 (LIVE) per `docs/MOBILE-ARCHITECTURE.md`. Do not
start either until this module compiles and pairs against a real server.
