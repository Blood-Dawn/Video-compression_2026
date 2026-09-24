# SVCS Mobile (Android)

One app, two jobs:

- **Standalone compressor** (the main use since 1.0.0-beta). Compresses
  videos on the phone with its hardware encoder through Jetpack Media3
  Transformer. No server, no network, no account. COMPRESS, SAVED and the
  opt-in Smart Compress (YOLOv8n on LiteRT) all live here.
- **Server Mode** (optional). Pair with a desktop SVCS install to browse its
  library, watch live cameras, see events and metrics.

Current release: **1.1.0-beta** (versionCode 14), GitHub tag `v1-beta`.
AGPL-3.0, like the rest of the repo.

| Read | For |
|---|---|
| [STANDALONE-COMPRESSOR-ROADMAP.md](STANDALONE-COMPRESSOR-ROADMAP.md) | Why Media3 and LiteRT, the phased plan, and progress notes. Start here. |
| [UI-REVIEW.md](UI-REVIEW.md) | The design-system pass and the ranked list of open UI work. |
| [EMULATOR-GUIDE.md](EMULATOR-GUIDE.md) | Running the app with no phone, step by step. |
| [UPLOAD-WORKER-DESIGN.md](UPLOAD-WORKER-DESIGN.md) | Moving Server Mode uploads onto WorkManager. |
| [../../docs/architecture/MOBILE-ARCHITECTURE.md](../../docs/architecture/MOBILE-ARCHITECTURE.md) | Server Mode's design: pairing, device tokens, push. |
| [../../docs/RELEASE-CHECKLIST.md](../../docs/RELEASE-CHECKLIST.md) | Cutting an APK release (Mobile section). |

## Build and test

Toolchain: JDK 17, Android SDK platform 35 and build-tools 35 (AGP pulls
34.0.0 itself), Gradle 8.11.1 through the committed wrapper. Kotlin 2.1.0,
AGP 8.7.3, Compose BOM 2024.12.01, minSdk 29, targetSdk 35.

```bash
cd mobile/android
./gradlew testDebugUnitTest     # JVM tests (Robolectric where needed)
./gradlew assembleDebug         # app-<abi>-debug.apk, package org.svcs.mobile.debug
./gradlew assembleRelease       # R8-minified, ABI splits + universal APK
./gradlew assembleQa            # minified like release, HTTP logging on
./gradlew assembleDebug -PsvcsAllowScreenshots=true   # FLAG_SECURE off
```

- `local.properties` (gitignored) needs `sdk.dir=...` if `ANDROID_HOME` is not
  set. On Windows, `pwsh -File verify-toolchain.ps1 -WriteLocalProperties`
  checks the JDK, SDK and licenses and writes it for you.
- **Release signing:** with no `SVCS_ANDROID_KEYSTORE` set, `assembleRelease`
  signs with the building machine's debug key. Phones only accept an update
  signed with the same key as the installed app, so releases are built on
  the owner's machine until a real keystore exists (docs/BLOCKERS.md).
- **Screenshots:** the whole window is FLAG_SECURE, so screenshots come out
  black unless you build with `-PsvcsAllowScreenshots=true`. Never ship that.
- **Emulator notes:** the emulator's software HEVC encoder caps near 512 px,
  so use H.264 when checking resolution behavior there. To pair with a
  server on your own PC, use `10.0.2.2`, not `127.0.0.1`.
- CI (`.github/workflows/ci.yml`, job `android`) runs `testDebugUnitTest`
  and `assembleDebug` on every push to `main` and `mobile`.

## Code layout

Package by feature under `app/src/main/java/org/svcs/mobile/`:

```
MainActivity.kt        the one activity: FLAG_SECURE, share-in (ACTION_SEND)
SvcsApplication.kt     empty on purpose: no analytics, no crash SDK
JobNotifier.kt         Server Mode job and event notifications

compress/              the on-device engine (no UI)
  CompressionWorker.kt   WorkManager job, Media3 Transformer, MediaStore output.
                         Do not rename or move: WorkManager stores the class name
                         and proguard-rules.pro keeps its constructor.
  CompressionPresets.kt  presets, size-target bitrate math, frame-size capping
  CompressionHistoryStore.kt  SAVED's local JSON history
  MediaProbe.kt          duration, audio, size and rotation of a source
detect/                Smart Compress: ObjectDetector (LiteRT), SmartCompressAnalyzer
data/TokenStore.kt     server URL + device token (AES-GCM under an Android Keystore key)
net/                   Server Mode REST client (OkHttp) and models

ui/
  SvcsApp.kt             tabs and navigation
  Format.kt              humanBytes, decimalMb, clock
  VideoIntents.kt        share / play a video in another app
  compress/              COMPRESS tab: CompressScreen, CompressViewModel
  saved/                 SAVED tab: CompressLibraryScreen, CompressLibraryViewModel
  server/{home,library,live,events,metrics,settings}/
                         Server Mode tabs; settings is also the MORE tab
  components/            SVCS design-system widgets, line icons, VideoThumbnail
  theme/                 Color.kt (design tokens, generated), DerivedColors.kt,
                         Theme.kt (fonts, Material 3 scheme, type scale)
```

Tests mirror the packages under `app/src/test/`: pure logic (presets,
formatting, probing, SAVED's filter/sort) plus Server Mode ViewModels against
`net/FakeSvcsApi.kt`. `app/src/androidTest/` holds the on-device TokenStore
persistence test.

## Things that are easy to get wrong

- **LiteRT is pinned to `com.google.ai.edge.litert:litert` 1.4.2.** The 2.x
  line's metadata needs Kotlin 2.3. Keep the `org.tensorflow.lite.*` imports;
  R8 keeps that package because the JNI library calls back into it.
- **Media3 1.5.1** has no `Presentation.createForShortSide()`.
  `scaledFrameSize()` computes exact output dimensions from width, height and
  rotation; Media3 hands effects upright frames.
- `FlowRow` needs `@OptIn(ExperimentalLayoutApi::class)` on this Compose version.
- Material 3 Expressive components exist only in material3 1.5 alpha; the app
  does not ship alpha libraries.
- The fonts (Bebas Neue, Space Mono, Outfit) are bundled under `res/font`,
  SIL OFL 1.1, with license texts in `assets/licenses/`.
- `Color.kt` is generated from the design tokens; do not hand-edit it. The
  design folder is recoverable with
  `git show 4558c5e:mobile/design/tokens/colors.css`.

## Decisions worth not re-litigating

- **No FFmpeg.** Media3 Transformer on the hardware encoders is faster,
  smaller and license-clean; the roadmap explains why FFmpeg-on-Android is
  the wrong engine in 2026.
- **LiteRT, not ONNX Runtime Mobile**, for the detector (NNAPI is deprecated;
  LiteRT is Google's path to GPU/NPU).
- **No `androidx.security:security-crypto`** (deprecated April 2025).
  TokenStore does the equivalent directly against the Keystore.
- **No Firebase, no analytics, no crash reporter.** F-Droid friendly, and the
  app never phones home.
- **Cleartext HTTP is allowed app-wide** for Server Mode, gated at runtime by
  `HostClassifier` (private ranges only unless the user consents);
  `network_security_config.xml` explains why a narrower config is not
  expressible.
- **Dark theme only.** The design system has no light palette.
