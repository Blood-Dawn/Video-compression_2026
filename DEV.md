# SVCS developer guide

Start here if you are new to the code, or coming back after a while. It covers
what lives in this repo, how to set up, run, test and package each part, and
the conventions the project follows. Depth lives in the documents it links to;
this file stays short so it can stay correct.

Last full rewrite: 2026-09-24 (the previous guide is kept at
[docs/archive/DEV-SPRING-2026.md](docs/archive/DEV-SPRING-2026.md)).

Contents: [What's new](#whats-new-september-2026) |
[The three products](#the-three-products) | [Repo layout](#repo-layout) |
[Desktop](#desktop-app-python) | [Android](#android-app-kotlin) |
[Releases](#releases) | [Conventions](#conventions) | [Where next](#where-to-read-next)

## What's new (September 2026)

The desktop app, the graded capstone deliverable, is done and delivered. Since
then the Android app turned from a remote control into a real compressor:

- **Standalone compressor** (Sep 22). The phone compresses video itself with
  its hardware encoder through Jetpack Media3 Transformer, in a WorkManager
  job promoted to a `mediaProcessing` foreground service, and writes to
  `Movies/SVCS` through MediaStore. Quality presets or size limits (Discord,
  Discord Nitro, WhatsApp, Instagram, X, email, or a typed size), H.265 or
  H.264, remove audio, share in from any app. No server, no network.
- **SAVED tab** (Sep 22): searchable, filterable history of on-device jobs with
  thumbnails.
- **Smart Compress, beta** (Sep 22-23): YOLOv8n exported to INT8 TFLite (3.3
  MB) runs on the phone through LiteRT over a sample of frames. If no person,
  vehicle, animal or carried item shows up anywhere, the bitrate is cut 35%;
  it never raises it. True per-region encoding is the next step.
- **UI redesign, 1.1.0-beta** (Sep 23): the SVCS design system (Bebas Neue,
  Space Mono and Outfit fonts, a full Material 3 color mapping, custom
  components and line icons), one layout per job state, honest size estimates.
- **Released** as GitHub Release `v1-beta` (arm64 and universal APKs plus
  checksums). F-Droid/IzzyOnDroid metadata is ready under
  `mobile/android/fastlane/`.
- **Cleanup sweep** (Sep 24): see
  [docs/CLEANUP-2026-09.md](docs/CLEANUP-2026-09.md). Highlights: CI runs
  again (it had been pointing at a deleted branch) and now covers Android
  too, `requirements.txt` is generated from `uv.lock`, the Windows download
  links and one-line installer work again, the Android `ui/` package is
  organized by feature, and the flaky Android settings test is fixed.

- **Roadmap work, 1.2.0-beta prepared** (Sep 24, not released yet):
  Smart Compress region-of-interest encoding on phones whose encoder
  supports Android 15's FEATURE_Roi (built and unit-tested, not yet seen on
  such a phone), per-phone calibration so size-limit jobs land closer to
  the limit without going over, a notice when the encoder quietly lowers
  the resolution or switches codec, and one SERVER tab for Server Mode.
  Draft notes: [docs/releases/release-notes-mobile-1.2.0-beta.md](docs/releases/release-notes-mobile-1.2.0-beta.md).

The Android plan and progress notes live in
[mobile/android/STANDALONE-COMPRESSOR-ROADMAP.md](mobile/android/STANDALONE-COMPRESSOR-ROADMAP.md);
open UI work is ranked in [mobile/android/UI-REVIEW.md](mobile/android/UI-REVIEW.md).

## The three products

| Product | Tech | Where | Status |
|---|---|---|---|
| Desktop app: web dashboard + selective compression pipeline for camera footage | Python 3.11, Flask, OpenCV (contrib), ONNX Runtime (YOLOv8n), FFmpeg | `src/`, `run_gui.py`, `installer/` | v2.2.0-beta (Windows installer), `2.2.0.dev1` on `main` |
| Android standalone compressor | Kotlin, Jetpack Compose, Media3 Transformer, WorkManager, LiteRT | `mobile/android/` | 1.1.0-beta released (tag `v1-beta`); 1.2.0-beta (versionCode 15) prepared on `mobile` |
| Android Server Mode: pair with a desktop install for library, live view, events, metrics | Kotlin, OkHttp, ExoPlayer (HLS) | `mobile/android/` (`net/`, `ui/server/`) | Same APK, optional |

The desktop pipeline in one paragraph: background subtraction (MOG2, KNN or
GMG) finds moving regions, the YOLOv8n detector confirms which ones are people,
vehicles or animals, and FFmpeg encodes those regions at high quality while the
static background is compressed hard or dropped, depending on the recording
mode (0 to 3). Details: [docs/SYSTEM-ARCHITECTURE.md](docs/SYSTEM-ARCHITECTURE.md).

## Repo layout

```
run_gui.py            desktop entry point (Dockerfile, AppImage and the frozen exe use it)
src/                  desktop app (Python)
  pipeline/           the capture -> detect -> encode loop, modes, presets
  background_subtraction/, detection/, compression/, enhancement/
  gui/                Flask app: app.py, routes/ (one blueprint per area),
                      services/, templates/, static/js
  utils/              db, ffmpeg resolution, paths, encryption, retention, ...
tests/                desktop tests (~100 files), tests/security/ for the security guards
installer/            PyInstaller spec, Inno Setup script, build.ps1, AppImage, winget, one-line installer
mobile/android/       Android app (Gradle project) and its docs
docs/                 documentation; docs/README.md is the map
scripts/              helper scripts; scripts/README.md lists them
data/, models/        local test data and model weights (mostly gitignored)
pyproject.toml, uv.lock   the Python dependency source of truth
```

The Python code uses a flat `src/` package that is imported two ways, as
`gui.x` (when `src/` is on `sys.path`, like `run_gui.py` does) and as
`src.gui.x`, which is why most modules have a `try: ... except
ModuleNotFoundError:` import shim. Keep both branches in step when you change
an import.

## Desktop app (Python)

### Set up

1. Install [uv](https://docs.astral.sh/uv/) (it also provides Python 3.11) and
   FFmpeg on your PATH (`sudo apt install ffmpeg`, `brew install ffmpeg`,
   `winget install Gyan.FFmpeg`). Windows, Linux and macOS all work; the
   Windows installer and PowerShell scripts are first-class.
2. `uv sync --frozen` installs the core app from `uv.lock` into `.venv`.
   Optional extras: `--extra enhance` (Real-ESRGAN super-resolution),
   `--extra torch` (PyTorch detector and ONNX export parity),
   `--extra onnx-export`, `--extra crash-reporting`. Do not use
   `--extra plates` in your main environment: it replaces
   `opencv-contrib-python` and breaks background subtraction. Install the
   plate reader with `scripts/install_plates.ps1` instead.
3. Check the machine: `bash scripts/check_deps.sh` (Linux/macOS) or
   `.\scripts\setup_new_pc.ps1` (Windows, also installs what is missing).

OpenCV must be the contrib build (`cv2.bgsegm` provides GMG).
`requirements.txt` is generated from the lock for pip-only users
(`python scripts/export_requirements.py`); never edit it by hand, and add
dependencies in `pyproject.toml` followed by `uv lock`.

### Run

```bash
uv run python run_gui.py                 # dashboard on http://localhost:5000
uv run python run_gui.py --host 127.0.0.1 --no-browser
uv run python src/pipeline/pipeline.py --help   # the pipeline without the GUI
```

Binding to anything other than localhost requires a dashboard login
(`--username/--password` or `SVCS_DASHBOARD_USER`/`SVCS_DASHBOARD_PASSWORD`).
To reach a server from outside your network, use a VPN such as WireGuard or
Tailscale. Do not port-forward and do not use a public tunnel such as ngrok:
the dashboard is plain HTTP serving footage of real people.

Test footage is not in the repo; [docs/testing/TEST-DATA.md](docs/testing/TEST-DATA.md)
explains how to build the CDnet 2014 and VIRAT sets locally.

### Test and lint

```bash
uv run pytest                            # full suite (~1,660 tests, a few minutes)
uv run pytest tests/security             # auth, CSRF, SQLi, XSS, SSRF, traversal, crypto
uv run pytest tests/test_encoder_r4.py -q   # one file
uvx ruff check .                         # pyflakes rules, kept clean (config in pyproject)
python scripts/check_doc_links.py        # after moving or renaming docs
```

Skips are expected for things this machine lacks: CDnet clips, a webcam, an
NVIDIA GPU for NVENC, libvmaf. CI (`.github/workflows/ci.yml`) runs the suite
on Linux and Windows for every push to `main` and `mobile` and every PR to
`main`. More: [docs/TESTING.md](docs/TESTING.md).

Some tests pin things you might want to move, so check before renaming:
`tests/test_gui_state_reexports.py` pins the private names re-exported from
`gui.app`, the route-registration tests list every Flask route, and the
release tests read `docs/RELEASE-CHECKLIST.md`, `docs/BLOCKERS.md` and
`docs/releases/release-notes-v2.2.0-beta.md`. `installer/svcs.spec` has
PyInstaller hidden imports for modules loaded dynamically.

### Package

- **Windows installer:** `installer\build.ps1 -Installer` (PyInstaller, then
  Inno Setup), with `-Edition server|field` and `-Sign`. See
  [docs/BUILD-AND-RELEASE.md](docs/BUILD-AND-RELEASE.md).
- **Linux AppImage:** `installer/build.sh`, also built by the manual
  `AppImage` workflow.
- **Docker:** `docker compose up --build` (set `SVCS_DASHBOARD_PASSWORD`).
- **Version** lives in three places that must match: `pyproject.toml`,
  `installer/svcs.iss` and `src/utils/version.py`.

## Android app (Kotlin)

Full module guide: [mobile/android/README.md](mobile/android/README.md).

### Set up

- JDK 17 and the Android SDK with platform 35 and build-tools 35 (Android
  Studio installs both; AGP fetches build-tools 34 itself). Without Android
  Studio: install the command-line tools, then
  `sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0"`.
- Point Gradle at the SDK with `ANDROID_HOME` or an untracked
  `mobile/android/local.properties` containing `sdk.dir=/path/to/sdk`
  (`pwsh -File mobile/android/verify-toolchain.ps1 -WriteLocalProperties`
  writes it on Windows).
- Pinned versions: Kotlin 2.1.0, AGP 8.7.3, Gradle 8.11.1, Compose BOM
  2024.12.01, Media3 1.5.1, LiteRT 1.4.2 (2.x needs Kotlin 2.3), minSdk 29,
  targetSdk 35.

### Build and test

```bash
cd mobile/android
./gradlew testDebugUnitTest              # ~100 JVM tests, all green
./gradlew assembleDebug                  # package org.svcs.mobile.debug
./gradlew assembleRelease                # R8, ABI splits + universal APK
./gradlew assembleQa                     # minified like release, HTTP logging on
./gradlew assembleDebug -PsvcsAllowScreenshots=true   # turns FLAG_SECURE off
```

- Screenshots of normal builds are black on purpose (FLAG_SECURE); use the
  screenshot flag above, never in a release.
- Release builds sign with the building machine's debug key unless
  `SVCS_ANDROID_KEYSTORE` is set, and phones only accept updates with the same
  key. Do not publish an APK built anywhere except the owner's release
  machine until a real release keystore exists.
- On emulators, the software HEVC encoder caps near 512 px: use H.264 when
  checking resolution behavior. Emulator setup:
  [mobile/android/EMULATOR-GUIDE.md](mobile/android/EMULATOR-GUIDE.md).
- Do not rename or move `compress/CompressionWorker.kt`: WorkManager stores
  worker class names in its database and `proguard-rules.pro` keeps its
  constructor.
- New pure logic gets a JVM unit test next to its package (see
  `CompressionPresetsTest`, `RoiPlannerTest`, `SizeCalibrationTest`).

## Releases

One checklist covers both products:
[docs/RELEASE-CHECKLIST.md](docs/RELEASE-CHECKLIST.md). Everything up to the
tag can be done by anyone; tagging and publishing is the repo owner's call.
Desktop tags look like `v2.2.0-beta`; the Android app uses its own tags
(`v1-beta`) and bumps `versionCode`/`versionName` in
`mobile/android/app/build.gradle.kts` plus a fastlane changelog
(`changelogs/<versionCode>.txt`). Open gates such as code signing and the
Android keystore are in [docs/BLOCKERS.md](docs/BLOCKERS.md).

## Conventions

- **Branches.** `main` is the public, stable branch. `mobile` is the active
  working branch (desktop and Android). Open PRs into `main`. The old `dev`
  and `app` branches no longer exist.
- **Writing style.** ASCII hyphens only: no em or en dashes anywhere (code,
  comments, UI strings, docs, commit messages).
  `tests/test_no_unicode_dashes.py` enforces it.
- **Comments explain why**, not what. Notable changes carry a short author
  line: `Author: Bloodawn (KheivenD), YYYY-MM-DD (context).` Keep existing
  author lines when editing.
- **Commits.** Imperative subject line, then a body that says why and what was
  verified. One concern per commit. AI-assisted commits end with the
  `Co-Authored-By:` and `Claude-Session:` trailers the tool provides. No force
  pushes, no history rewrites, no `--no-verify`.
- **Tests with behavior.** New behavior comes with a test; the bar is "if it
  broke, would anyone find out". Never skip or weaken a test to get green.
- **Generated files** are not edited by hand: `requirements.txt` (from
  `uv.lock`) and the Android `ui/theme/Color.kt` (from the design
  tokens, recoverable with `git show 4558c5e:mobile/design/tokens/colors.css`).
- **Security-sensitive code** (dashboard auth and CSRF, device tokens, the
  encryption code, the phone's TokenStore and FLAG_SECURE) changes only with a
  test that shows why, and `tests/security/` must stay green.

Organization choices behind the layout, for reference: docs are indexed by
reader need following [Diataxis](https://diataxis.fr/); the Android `ui/`
package is split by feature, as Android's
[app architecture guide](https://developer.android.com/topic/architecture/recommendations)
recommends for modularity; the Python side keeps its existing flat `src/`
package rather than a full [src layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)
migration, because the dual import paths are baked into the frozen build and
many tests.

## Where to read next

- [docs/README.md](docs/README.md): the map of every document.
- [docs/SYSTEM-ARCHITECTURE.md](docs/SYSTEM-ARCHITECTURE.md) and
  [docs/RESEARCH.md](docs/RESEARCH.md): how the desktop system works and why.
- [mobile/android/STANDALONE-COMPRESSOR-ROADMAP.md](mobile/android/STANDALONE-COMPRESSOR-ROADMAP.md):
  the Android plan.
- [ROADMAP.md](ROADMAP.md): the team's Fall 2026 semester plan.
- [CONTRIBUTING.md](CONTRIBUTING.md): how to send a change.
