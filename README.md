# SVCS: Selective Video Compression

[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)
[![Desktop: v2.2.0-beta](https://img.shields.io/badge/desktop-v2.2.0--beta-orange)](https://github.com/Blood-Dawn/Video-compression_2026/releases/tag/v2.2.0-beta)
[![Android: v1-beta](https://img.shields.io/badge/android-v1--beta-brightgreen)](https://github.com/Blood-Dawn/Video-compression_2026/releases/tag/v1-beta)

**EGN 4950C Senior Design Capstone | Florida Atlantic University | Group 22**
Sponsored by the Defense Innovation Unit (DIU) / NIWC Pacific.

SVCS keeps the parts of a video that matter at full quality and squeezes the
rest. It started as a desktop system for security cameras and now also ships
an Android app that compresses video on the phone itself. Everything is free,
open source (AGPL-3.0), and runs on your own hardware with no account and no
cloud.

This repository holds three things:

| Product | What it is | Status |
|---|---|---|
| **Desktop app** (Python) | A local web dashboard that watches camera footage, keeps moving people and vehicles at high quality, and compresses the static background hard. The graded capstone deliverable. | v2.2.0-beta, Windows installer |
| **Android compressor** (Kotlin) | Compresses videos on the phone with its hardware encoder: quality presets, app size limits (Discord, WhatsApp, email...), on-device Smart Compress, a history of saved jobs. Fully offline. | v1-beta (1.1.0-beta) APK |
| **Android Server Mode** | The same app, paired to a desktop install: browse its library, watch live cameras, get event alerts. Optional. | Included in the APK |
| **SVCS Web** (React, [`web/`](web/)) | An optional, separate multi-user cloud companion: real accounts and roles (admin/operator/guest) via Supabase Auth + Postgres RLS, showing job history the desktop app syncs up through its existing outbound webhook. Never runs the actual compression, and the desktop/Android apps above work identically with or without it — this is the one opt-in exception to "no account and no cloud." Kheiven's own initiative, outside the team's Fall 2026 roadmap. | In review — see [`docs/plans/WEB-DASHBOARD-PLAN.md`](docs/plans/WEB-DASHBOARD-PLAN.md) and [`web/README.md`](web/README.md) |

## Download

- **Windows desktop app:** the installer is on the
  [v2.2.0-beta release](https://github.com/Blood-Dawn/Video-compression_2026/releases/tag/v2.2.0-beta),
  or install from PowerShell in one line:

  ```powershell
  irm https://raw.githubusercontent.com/Blood-Dawn/Video-compression_2026/main/installer/Install-SVCS.ps1 | iex
  ```

  It is an unsigned beta, so Windows SmartScreen will warn ("More info", then
  "Run anyway"). Check the download against `SHA256SUMS.txt` on the release
  page first. Full instructions: [docs/releases/INSTALL.md](docs/releases/INSTALL.md).
- **Android app:** `svcs-mobile-v1-beta.apk` from the
  [v1-beta release](https://github.com/Blood-Dawn/Video-compression_2026/releases/tag/v1-beta)
  (the `-universal` APK covers 32-bit phones and emulators). Android 10 or
  newer. It is sideloaded, so allow installs from your browser or file manager
  when Android asks.

## The desktop app

A camera watching an empty parking lot records 24 hours a day, and almost none
of it has anything happening in it. SVCS separates the moving foreground from
the static background (OpenCV background subtraction, confirmed by a YOLOv8n
detector running on ONNX Runtime), then encodes with FFmpeg so the regions of
interest keep their quality while the background is compressed or dropped,
depending on which of four recording modes you pick. On the CDnet 2014
benchmark (52 real surveillance clips) that came out 6 to 16 times smaller
than standard compression, on an ordinary PC with no GPU.

The dashboard runs locally at `http://localhost:5000` and stays on this
machine unless you bind it to the network with a password. How it all fits
together: [docs/SYSTEM-ARCHITECTURE.md](docs/SYSTEM-ARCHITECTURE.md).

## The Android app

Pick or share a video, choose a quality preset or a size limit, and the phone
compresses it with its own hardware encoder (Jetpack Media3 Transformer, no
FFmpeg). Output lands in `Movies/SVCS`. Opt-in **Smart Compress** runs
YOLOv8n on the phone (LiteRT, INT8) over a sample of frames and, when no
people, vehicles or animals appear anywhere, compresses harder; it never
spends more than you asked for. Nothing is uploaded and the app has no ads,
analytics or trackers.

Pairing with a desktop install is optional and adds Server Mode (library,
live view, events, metrics). Plans, research and progress:
[mobile/android/STANDALONE-COMPRESSOR-ROADMAP.md](mobile/android/STANDALONE-COMPRESSOR-ROADMAP.md).

## For developers

[DEV.md](DEV.md) is the developer guide: repo layout, setup for the desktop
app (`uv sync`) and the Android app (JDK 17, Android SDK 35, Gradle), tests,
packaging, releases and conventions. [CONTRIBUTING.md](CONTRIBUTING.md) covers
how to send changes, and [docs/README.md](docs/README.md) maps the rest of the
documentation.

## The team

| Name | GitHub | What they built |
|---|---|---|
| Kheiven D'Haiti | [@Blood-Dawn](https://github.com/Blood-Dawn) | Pipeline orchestration, background subtraction tuning, dashboard, encryption, night-mode CLAHE, Android app, project lead |
| Jorge Sanchez | [@sanchez-jorge](https://github.com/sanchez-jorge) | Video encoding (ROI encoder / FFmpeg integration), algorithm benchmarking, stress testing, storage extrapolation |
| Ashleyn Montano | [@ashleyn07](https://github.com/ashleyn07) | SQLite metadata database, schema, pipeline integration, query system |
| Riley Roberts | [@sRileyRoberts](https://github.com/sRileyRoberts) | Motion detection pipeline (Modes 2 and 3), object isolation |
| Victor De Souza Teixeira | [@victort29](https://github.com/victort29) | Image enhancement module, Real-ESRGAN upscaler, CPU benchmark, security testing |

## License

GNU AGPL-3.0 (see [LICENSE](LICENSE)), for the desktop app and the Android app
alike. The bundled YOLOv8n weights are AGPL-3.0 (Ultralytics), and the app's
fonts are SIL OFL 1.1. There is no paid or commercial edition.
