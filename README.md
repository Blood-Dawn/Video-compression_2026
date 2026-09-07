# SVCS Mobile Companion (Beta)
**Part of Selective Video Compression for Surveillance Cameras**
**EGN 4950C Senior Design Capstone | Florida Atlantic University | Group 16**
Sponsored by the Defense Innovation Unit (DIU) / NIWC Pacific

---

## What the mobile app is

SVCS itself is a desktop system that compresses and manages security-camera
footage (the full writeup is further down this page). This branch adds an
Android app that acts as a phone-based remote control and viewer for a
desktop SVCS install you already have running. It is a companion to the
desktop app, not a replacement for it: the phone never records or compresses
video on its own, it just talks to a desktop server over your own network.

## What it can do today (beta, version 0.9.0)

- Watch a live camera feed from your phone, streamed from the desktop server.
- Browse the library and play back saved clips.
- Trigger a compression job remotely, right from the phone.
- Upload a video from your phone's own gallery to the server.
- Draw a zone on a camera view and get an alert when something crosses a
  line or lingers in it too long.
- Get a push notification even while the app itself is closed, delivered
  through a notification server you host yourself rather than through a
  third-party company.

## What it should do next

Two bigger milestones are still ahead of a first stable release: hardening
the app enough that it needs less by-hand testing on a physical device, and
rounding out the live-view and library screens with the same depth the
desktop dashboard already has. The concrete next steps, roughly in order:

1. Fix pairing so it survives closing and reopening the app. Today it can
   silently reconnect using an old server address or an old login.
2. Move uploads onto a proper background worker so a transfer survives the
   app being closed mid-upload.
3. Build out real automated test coverage. Today there is a single JVM
   unit-test file, so most changes are still verified by hand on a phone.
4. An external security test and a fuzzing pass against the upload path,
   both planned for the next few weeks.

## Known risks and limits: read this before relying on the beta

This is beta software, and it is worth being upfront about what that means:

- Pairing does not reliably survive restarting the app.
- An upload does not survive the app being closed mid-transfer; leave the
  app open until an upload finishes.
- Test coverage is thin. Most changes are checked by hand on a real phone
  rather than caught by an automated test suite.
- The app has not yet been through an outside security test.
- There is no signed release build and no Play Store listing. Anyone running
  it today is running a debug build made from source.

None of this is hidden. It is exactly why this is a beta and not a release,
and fixing it is the explicit plan for the next few weeks; see
`docs/PLANNER-FALL-2026.md` and the mobile section of
`docs/CHANGES-SUMMER-2026.md` for the details.

## Try it or build it

There is no download link yet, on purpose, since nothing has been signed or
reviewed for general use. To try it anyway:

1. Get a desktop SVCS server running first (see below); the phone app has
   nothing to do without one.
2. Follow the build steps in
   [mobile/android/README.md](mobile/android/README.md) to build a debug
   APK from source. It needs Android Studio and a JDK, nothing more exotic
   than that.
3. Point the app at your server's address on your own network and pair it
   using a device token generated from the desktop dashboard.

## The stack, in short

Native Kotlin with Jetpack Compose for the screens, and OkHttp talking to
the same REST API the desktop dashboard already uses. Nothing runs FFmpeg or
object detection on the phone itself; all of that stays on the desktop
server. The full technical reasoning (why native Kotlin over Flutter or a
web wrapper, why there is no Firebase, how push notifications work without
routing through a third party) lives in `docs/SYSTEM-ARCHITECTURE.md`, and
the contributor-facing build and architecture detail is in
[mobile/android/README.md](mobile/android/README.md).

---

## The desktop app it connects to

SVCS is a desktop app that watches security-camera footage and throws away
the boring parts. A camera watching an empty parking lot records 24 hours a
day, but almost none of that has anything happening in it, and a normal
camera system saves every quiet pixel anyway. SVCS instead watches the video
as it comes in, keeps the moving parts (a person, a car) at full quality,
and compresses or drops the static background depending on which of four
recording modes you pick. On the CDnet 2014 benchmark (52 real surveillance
clips) that came out to 6 to 16 times smaller files than standard
compression, running on a normal PC with no GPU required.

**Install it** with one line in PowerShell:

```powershell
irm https://raw.githubusercontent.com/Blood-Dawn/Video-compression_2026/app/installer/Install-SVCS.ps1 | iex
```

or [download the Windows installer directly](https://github.com/Blood-Dawn/Video-compression_2026/releases/latest)
from the Releases page. It is free and open source (AGPL-3.0), needs no
account or cloud service, and runs entirely on your own machine. Full
install instructions are in `docs/INSTALL.md`, and how the desktop app and
this mobile app fit together end to end is in `docs/SYSTEM-ARCHITECTURE.md`.

---

## The team

| Name | GitHub | What they built |
|---|---|---|
| Kheiven D'Haiti | [@Blood-Dawn](https://github.com/Blood-Dawn) | Pipeline orchestration, background subtraction tuning, dashboard, encryption, night-mode CLAHE, project lead |
| Jorge Sanchez | [@sanchez-jorge](https://github.com/sanchez-jorge) | Video encoding (ROI encoder / FFmpeg integration), algorithm benchmarking, stress testing, storage extrapolation |
| Ashleyn Montano | [@ashleyn07](https://github.com/ashleyn07) | SQLite metadata database, schema, pipeline integration, query system |
| Riley Roberts | [@sRileyRoberts](https://github.com/sRileyRoberts) | Motion detection pipeline (Modes 2 and 3), object isolation |
| Victor De Souza Teixeira | [@victort29](https://github.com/victort29) | Image enhancement module, Real-ESRGAN upscaler, CPU benchmark, security testing |

## License

SVCS, including this mobile module, is free and open source under the GNU
AGPL-3.0 (see `LICENSE`), by inheritance from the repository root. There is
no paid or commercial edition, and no plan to add one to this repository.
A commercial variant, if one is ever built, would live in its own separate
fork.

---

*EGN 4950C Senior Design Capstone | Florida Atlantic University | Group 16 | Fall 2026 semester runs through December 6, 2026*
