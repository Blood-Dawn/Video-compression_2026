# SVCS v2.2.0-beta

Desktop (Windows) and mobile companion app, released as an unsigned beta.

## What's in this build

- Desktop server edition: `SVCS-Setup-2.2.0.dev0.exe` (Inno Setup installer,
  built from `installer/svcs.spec` with PyInstaller). Bundles ffmpeg, OpenCV,
  ONNX Runtime, and the YOLOv8n detector, so there is nothing else to install.
- Mobile companion app: `SVCS-Mobile-0.8.0-beta.apk` (Android), for viewing
  and pulling compressed clips from a phone.
- Modes 0-3 (live surveillance, event recording, smart compress, object
  only), chunked resumable upload from mobile, zone masks and behavior
  events, and a self-hosted push channel for closed-app notifications.

## This build is unsigned

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

## Verify your download

Every artifact in this release has a published SHA-256 checksum in
`dist/SHA256SUMS.txt` (also attached to the GitHub release). Before running
the installer, confirm the hash matches:

```powershell
Get-FileHash SVCS-Setup-2.2.0.dev0.exe -Algorithm SHA256
```

Compare the output against the matching line in `SHA256SUMS.txt`. If it does
not match, do not run the file. Re-download it, and if it still does not
match, open an issue rather than proceeding.

## License

SVCS is free and open source, licensed under AGPL-3.0. See `LICENSE` at the
repo root for the full text.

## Known issues

- AV1 (SVT-AV1) encoding for Modes 2-3 requires an ffmpeg build with
  `libsvtav1`; the stock ffmpeg on some systems falls back to H.264 for
  those modes instead of failing outright.
- The mobile app is still in beta (0.8.0); expect rough edges around
  playback of very long clips over slow connections.

Author: Bloodawn (KheivenD), 2026-09-21.
