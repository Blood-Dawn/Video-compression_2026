# SVCS v2.0.0-beta — draft release notes

> **Draft for the owner to publish.** This is an **unsigned public beta**. Windows
> SmartScreen will warn on launch — choose *More info → Run anyway*. A signed
> build is planned (TASK 5b.1).

**SVCS** (Selective Video Compression for Surveillance) shrinks 24/7 camera
footage by keeping what moves at full quality and compressing the dead
background hard — the same useful footage at a fraction of the size. Free and
open source (AGPL-3.0). Runs offline on a regular PC — **no GPU required**, no
cloud, no telemetry by default.

## Highlights

- **Surveillance-first presets.** Pick what the camera watches (Continuous CCTV,
  Motion-event, Doorbell, Multi-camera/NVR, Active scene, Archive) plus a
  consumer family (Indoor cam, Outdoor yard, Baby/pet monitor) — no codec jargon.
- **Content auto-detection.** SVCS analyzes the first ~30 s of a clip and
  recommends a preset.
- **Camera ingestion, three honest ways.** Direct RTSP/ONVIF (with LAN discovery),
  watch-folder profiles for exports/NVR/microSD/NAS, or a bridge for cloud-locked
  cameras (Ring/Nest/Arlo). No vendor-cloud scraping.
- **Slim & self-contained.** Object detection runs on ONNX Runtime (no torch);
  FFmpeg is bundled. The Windows installer is ~210 MB.
- **Server-ready.** A Docker image and a bind-aware auth policy (the dashboard
  refuses to serve unauthenticated on the network).
- **Private by default.** Opt-in anonymous usage stats only; never any footage,
  filenames, or paths.

## Install

Download `SVCS-Setup-2.0.0-beta.exe` below and run it; the dashboard opens at
`http://localhost:5000`. **Verify your download** against `SHA256SUMS.txt`
(see the download page for steps).

System requirements: Windows 10/11 64-bit, any modern CPU (no GPU), 4 GB+ RAM,
~600 MB disk. Linux (Docker / AppImage) is also available.

## Known limitations

- **Unsigned** — SmartScreen warning on first launch (signing is the next milestone).
- Cloud-locked cameras (Ring/Nest/Arlo) require export or a bridge — see
  `docs/camera-ingestion.md`.
- Beta: please report issues on GitHub.

## Verify

```
# Windows
Get-FileHash .\SVCS-Setup-2.0.0-beta.exe -Algorithm SHA256
# Linux/macOS
sha256sum SVCS-Setup-2.0.0-beta.exe
```
Compare against `SHA256SUMS.txt` attached to this release.

---

*Full changelog: see the commit history on `app`. Draft prepared by Bloodawn
(KheivenD), 2026-06-03 (TASK 5.4).*
