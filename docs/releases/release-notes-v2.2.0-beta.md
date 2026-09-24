# SVCS v2.2.0-beta - draft release notes

Second public beta. Two artifacts this time: the Windows desktop app and the
first SVCS Mobile companion APK for Android.

## Desktop (SVCS-Setup-2.2.0.dev0.exe)

Everything since the 2.1 beta:

- Security hardening round SEC-001 to SEC-016: CSRF guard, media and library
  path confinement, auth enforced on every non-localhost bind, delete-original
  data-loss guards, XSS escaping, SSRF input guard, dependency floor bumps.
- R4: job history and batch progress, long GOP, capped CRF, NVENC hardware
  encoding, denoise, encoder-level ROI, VMAF measurement, disk-budget
  retention auto-purge, Server and Field editions, in-process ONNX license
  plate reader, universal multi-vendor format ingest via FFmpeg fallback.
- R5 so far: VMAF-targeted rate control (smallest file at a quality floor),
  static-scene measurement with honest fallback, scene-change keyframe
  placement, natural-language search over segment metadata (/api/nl_search),
  tamper-evident SHA-256 output manifests with a verify CLI.
- Server hardening for mobile clients: per-device Bearer tokens with
  revocation, auth throttling, GET /api/capabilities, HLS liveness fixes,
  camera passwords redacted from status endpoints.
- Fixed: the frozen exe now bundles OpenCV explicitly (2.1 packaging gap).

## Mobile (SVCS-Mobile-0.5.0-beta.apk)

Thin client for a self-hosted SVCS server; it does not encode on the phone.
Pair by server address and access token, then LIBRARY, METRICS, HOME, and a
LIVE tab with an HLS player. Sensitive surfaces set FLAG_SECURE, so the OS
blocks screenshots of your footage by design. minSdk 29 (Android 10),
self-signed release key, sideload install. Verified on a physical Samsung
device (Android 17) against a LAN server, including the full first-run
pairing flow.

0.5.0: system notifications when a server job finishes (while the app is
running; grant the notification permission on first launch), and the APK is
84 percent smaller (4.4 MB) with minification re-enabled under completed R8
keep rules, re-verified on a physical device. Server side, the pipeline
gained per-camera exclude zones and behavior events (line-crossing,
loitering, direction) recorded to events.jsonl with /api/zones and
/api/events/recent to drive them.

0.4.2: COMPRESS opens a mode picker mirroring the desktop's four presets
(live surveillance / event recording / smart compress / object only) with
honest codec notes; an OUTPUTS chip jumps straight to the server's save
folder; compressions started from any client now appear under the
COMPRESSED view; the desktop moving its library folder no longer breaks the
phone mid-session. Desktop gains a plain-English Smart Search on the SEARCH
tab, a race fix so two simultaneous start requests cannot double-start the
pipeline, job ids across status and history, and tamper-evident output
manifests.

0.4.0 (M4 first slice, verified on device against a LAN server): tap a clip
to PLAY it in the app (range-streamed, hardware-decoded, token on every
request); ALL | ORIGINALS | COMPRESSED filter views plus REFRESH; COMPRESS
starts a server-side encode of an original from the phone (zero phone bytes)
with progress on HOME. Server side, the library file and thumb routes accept
an explicit folder context so the desktop changing its library folder no
longer breaks the phone's playback mid-session.

0.3.1: fixed a save-event replay that made the app cycle between the splash
and the settings screen after visiting MORE (it read as constant screen
glitching); pairing now ends with an explicit SAVE & OPEN button that lands
on HOME; the CONNECTED card labels the server's version as the server's, and
the app's own version is shown on the settings screen.

## Install and verify

Windows: run the installer; SmartScreen will warn because the beta is
unsigned ("More info" then "Run anyway"). The dashboard opens at
http://127.0.0.1:5000 and stays localhost-only unless you deliberately bind
the network with auth.

Android: enable installs from unknown sources for your browser or file
manager, download the APK, open it. On first run enter your server address
and a device token minted in the desktop TOOLS tab.

Checksums:

```
Get-FileHash .\SVCS-Setup-2.2.0.dev0.exe -Algorithm SHA256
Get-FileHash .\SVCS-Mobile-0.3.0-beta.apk -Algorithm SHA256
```

Compare against SHA256SUMS.txt attached to the release.

License: AGPL-3.0. Source at the repository this release is attached to.

## Addendum (2026-09-21): unsigned build, verification, known issues

Written after release when the checklist tests were repointed at
`v2.2.0-beta`; merged here on 2026-09-24 so there is one set of notes per
tag.

### This build is unsigned

Neither the installer exe nor the bundled `SVCS.exe` is Authenticode-signed
in this release. That is a known, tracked gap (see `docs/BLOCKERS.md`), not
an oversight you need to report.

**What this means for you:** Windows SmartScreen will show a blue "Windows
protected your PC" warning when you run the installer, because the exe has
no publisher signature yet. To proceed:

1. Click "More info" on the SmartScreen dialog.
2. Click "Run anyway."

This is expected for an unsigned open-source beta. If you would rather not
click through that warning, verify the download integrity yourself first
(see below) and make your own call, or wait for a signed release.

### Verify your download

Every artifact in this release has a published SHA-256 checksum in
`dist/SHA256SUMS.txt` (also attached to the GitHub release). Before running
the installer, confirm the hash matches:

```powershell
Get-FileHash SVCS-Setup-2.2.0.dev0.exe -Algorithm SHA256
```

Compare the output against the matching line in `SHA256SUMS.txt`. If it does
not match, do not run the file. Re-download it, and if it still does not
match, open an issue rather than proceeding.

### License

SVCS is free and open source, licensed under AGPL-3.0. See `LICENSE` at the
repo root for the full text.

### Known issues

- AV1 (SVT-AV1) encoding for Modes 2-3 requires an ffmpeg build with
  `libsvtav1`; the stock ffmpeg on some systems falls back to H.264 for
  those modes instead of failing outright.
- The mobile app is still in beta (0.8.0); expect rough edges around
  playback of very long clips over slow connections.
