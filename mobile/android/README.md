# SVCS Mobile (Android)

Thin client for a self-hosted SVCS server. It drives and monitors the server
over its REST API; it does not encode video on the phone. See
`docs/MOBILE-ARCHITECTURE.md` for why, and for the full milestone plan.

Status: **M1.1, one screen (server pairing).** AGPL-3.0 by inheritance from the
repo root `LICENSE`.

---

## Read this first: what has NOT been verified

**This module has never been compiled.** The machine it was written on has no
JDK, no Android SDK, and no Gradle. That means, concretely:

- it has **not been compiled**, so it may not build;
- `app/src/test/.../HostClassifierTest.kt` has **never been run**;
- **no APK exists**, and nothing has been on a device or emulator;
- the M1.1 acceptance from the plan, "on a real device on the same LAN,
  entering the server address and credentials and tapping Test shows the
  server's edition and feature list", is **unmet and untested**.

Treat the Kotlin as a reviewed first draft that needs a compile pass, not as
working software. The first `./gradlew assembleDebug` should be expected to
surface errors.

### What HAS been verified

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

So: if the Kotlin compiles and issues the requests it is written to issue, the
server will answer correctly. That is a real and useful guarantee, and it is
also strictly less than "the app works."

---

## Building it

```bash
# Requires JDK 17 and the Android SDK (via Android Studio or cmdline-tools).
cd mobile/android
./gradlew assembleDebug        # first run WILL likely need fixes
./gradlew test                 # runs HostClassifierTest
```

The Gradle wrapper JAR is not committed (see `.gitignore`); run
`gradle wrapper --gradle-version 8.11.1` once, or open the folder in Android
Studio and let it generate one.

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
