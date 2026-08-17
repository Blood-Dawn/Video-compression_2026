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

## Mobile (SVCS-Mobile-0.4.2-beta.apk)

Thin client for a self-hosted SVCS server; it does not encode on the phone.
Pair by server address and access token, then LIBRARY, METRICS, HOME, and a
LIVE tab with an HLS player. Sensitive surfaces set FLAG_SECURE, so the OS
blocks screenshots of your footage by design. minSdk 29 (Android 10),
self-signed release key, sideload install. Verified on a physical Samsung
device (Android 17) against a LAN server, including the full first-run
pairing flow.

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
