# SVCS Architecture (v2)

This document describes where the project is going. The current Python
codebase on `main` and `dev` is v1, built for the FAU EGN 4950C capstone
sponsored by NIWC Pacific. v2 is the consumer / commercial product.

## Goals for v2

1. Ship a desktop application (Windows, macOS, Linux) that competes with
   HandBrake on usability and beats it on AI-aware compression.
2. Ship an Android app that compresses video in the background and lets
   the user view compressed videos in-app.
3. Expand the use case from "surveillance only" to "any video": movies,
   shows, vlogs, music videos, screen recordings, surveillance, animation.
4. Auto-detect the type of input video and recommend the best preset.
5. Maintain a single codebase across platforms (no separate iOS / Android
   / desktop forks).
6. Stay open source under AGPL-3.0 with a commercial license tier for
   companies that need it.

## Non-goals for v2

- iOS app (deferred to v3; the path is open via the same Rust core but
  Apple's App Store review and Core ML conversion add work we don't have
  time for this summer).
- Live camera capture on mobile (background batch processing only).
- Real-time HLS streaming on mobile (desktop only).
- A hosted cloud service. People run SVCS locally.

## Architecture stack

```
┌──────────────────────────────────────────────┐
│  Flutter UI (Dart)                           │
│  - Same UI code for desktop, Android, iOS    │
│  - File picker, preset selector, progress    │
│  - Inline video player for compressed output │
└──────────────────────────────────────────────┘
                      │
                      │  flutter_rust_bridge (FFI, generated)
                      ▼
┌──────────────────────────────────────────────┐
│  svcs-core (Rust)                            │
│                                              │
│  Modules:                                    │
│    frame_source  — file, RTSP, camera        │
│    bg_subtract   — MOG2, scene detect        │
│    detect        — face, object (ONNX)       │
│    mode          — dispatch (0, 1, 2, 3)     │
│    encoder       — FFmpeg dual-CRF           │
│    enhance       — ESRGAN via ONNX           │
│    db            — SQLite metadata           │
│    crypto        — AES-256-GCM               │
│    preset        — auto-detect content type  │
└──────────────────────────────────────────────┘
                      │
                      │  C ABI
                      ▼
┌──────────────────────────────────────────────┐
│  Platform-native bindings                    │
│  - FFmpeg static (bundled in installer)      │
│  - ONNX Runtime mobile (bundled in app)      │
│  - OpenCV (linked from opencv-rust crate)    │
│  - SQLite (linked from rusqlite)             │
└──────────────────────────────────────────────┘
```

## Why these choices

### Rust for the core

| Property | Why it matters |
|---|---|
| Cross-compile | Same source compiles to Windows / macOS / Linux / Android / iOS |
| Memory safety | Video processing is full of buffer math; one bug becomes a security CVE |
| Mature FFmpeg bindings | `ffmpeg-next` crate is production-grade |
| ONNX Runtime support | `ort` crate is well-maintained, supports CPU and most accelerators |
| Tooling | `cargo` is significantly better than `pip` + virtualenv |
| Single binary output | No Python runtime to ship, no DLL hell |

Alternatives considered: C++ (no memory safety, painful build systems),
Go (mobile story is weak), Zig (too young), Kotlin Multiplatform (UI yes,
core no).

### Flutter for the UI

| Property | Why it matters |
|---|---|
| One UI codebase | Desktop, Android, iOS from the same Dart source |
| Good video player | `video_player` package is production-grade |
| Mature FFI to Rust | `flutter_rust_bridge` auto-generates the binding code |
| Fast iteration | Hot reload during development |
| Material + Cupertino | Both Android and iOS look native |

Alternatives considered: React Native (slower video performance,
heavier bridge), Tauri (great for desktop, no mobile story), native
Kotlin + Swift (two UI codebases to maintain).

### Why not just stay on Python

We will, for v1. The `app` branch keeps the Python pipeline and adds
desktop installers (PyInstaller), audit fixes, and presets. That ships
first because it's lower risk.

The Rust port on `kdev` proceeds in parallel. When a Rust module passes
parity with the Python reference implementation on the same test vectors,
that module becomes the implementation on `app` via a thin FFI shim.

## Migration strategy

Phase 1 (June): Python desktop installer ships. `app` branch.

Phase 2 (June to July): Rust `svcs-core` skeleton compiles for all target
platforms. Single hello-world function exposed via FFI. `kdev` branch.

Phase 3 (July): Port the encoder module first (lowest risk, highest
impact). Validate against Python on the 19 CDnet clips. Once parity is
proven, the desktop installer on `app` starts using the Rust encoder via
FFI for the heavy lifting while Python orchestrates.

Phase 4 (August): Port background subtraction and mode dispatch.

Phase 5 (August): Flutter desktop UI prototype, talking to the now-mixed
Rust + Python backend.

Phase 6 (August / September): Flutter Android client, calling pure Rust
core (no Python).

Phase 7 (Fall): Pure Rust desktop, retire Python from the user-facing
path. Python stays in the repo as reference and as the testing oracle.

## Platform targets

| Platform | Tier | Notes |
|---|---|---|
| Windows 10 / 11 (x86_64) | First class | Installer via Inno Setup |
| macOS (arm64 + x86_64) | First class | DMG, signed and notarized |
| Linux (x86_64) | Best effort | AppImage initially, .deb / .rpm later |
| Android 10+ (arm64) | First class | Play Store + APK direct |
| iOS | Future | Out of scope for v2 |

## Edition: one open-source build

> Updated 2026-05-31: v2 is **open-source only**. The earlier casual/premium
> dual-edition split is dropped; the `premium` branch is dormant (see
> `CONTRIBUTING.md` and the dormant `LICENSE-COMMERCIAL.md`).

SVCS v2 ships as a single edition built from `app`, under AGPL-3.0, with the
full feature set free: compression, the four modes, search, encryption,
Real-ESRGAN enhancement, YOLO object filter, and the AI plate reader.

Some features sit behind optional `pyproject.toml` extras purely to keep the
default install small — `[plates]` (AI plate reader, EasyOCR), `[enhance]`
(Real-ESRGAN), `[crash-reporting]` (opt-in Sentry). These are free; the UI
hides a feature's controls when its backing dependency isn't installed.

A commercial fork remains *possible* but is out of scope for v2 and
conditional on IP clearance (PLAN-V2 §0/§13); the dormant `premium` branch
is its natural seam.

## Dependencies cleanup

The current Python pipeline has license issues that prevent commercial
*closed-source* distribution. v2 keeps AGPL deps in the AGPL casual
edition (where they're fine) and plans replacements only where a
commercial customer's deal terms require it.

| Dep | License | Action |
|---|---|---|
| `ultralytics` (YOLOv8) | AGPL-3.0 | **Keep in core deps**. Compatible with our AGPL casual edition. For commercial customers who can't take AGPL, we either sublicense an Ultralytics enterprise license through their deal, or swap to MediaPipe / RT-DETR via ONNX at that point. |
| `paddlepaddle` / `paddleocr` | Apache-2.0 but huge | **Dropped from defaults**. The premium plate reader uses EasyOCR. PaddleOCR remains supported at runtime if a customer installs it themselves. |
| `easyocr` | Apache-2.0 | **Premium-only**. In the `[plates]` optional extra, included only in the premium edition build. |
| `basicsr` + `realesrgan` | BSD / Apache | Keep. Export model to ONNX for v2. |
| `opencv-python` | Apache-2.0 | Keep. Use `opencv-rust` in v2. |
| `ffmpeg-python` | Apache-2.0 | Drop the wrapper, call FFmpeg directly. |
| `flask` | BSD | Used for v1 desktop. Replace with Flutter in v2. |
| `cryptography` | Apache-2.0 | Keep. Use `aes-gcm` + `pbkdf2` crates in v2. |

## Repository layout (v2)

```
.
├── LICENSE                      AGPL-3.0
├── LICENSE-COMMERCIAL.md        Commercial offering
├── CLA.md                       Contributor agreement
├── CONTRIBUTING.md              How to contribute
├── ARCHITECTURE.md              This file
├── ROADMAP-V2.md                Productization roadmap
├── README.md                    What is SVCS
├── src/                         Python v1 (reference impl)
├── svcs-core/                   Rust core (v2, on kdev branch)
├── svcs-flutter/                Flutter UI (v2, on app branch)
├── tests/                       Python tests
└── installer/                   Platform installer configs
```
