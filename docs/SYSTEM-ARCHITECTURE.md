# SVCS System Architecture

This is the current, reader-facing description of how SVCS is built: the desktop
pipeline, how footage gets in, what formats it accepts, the Android companion
app, and how the two talk to each other. It replaces four narrower documents
that used to cover these topics separately (camera ingestion, format support,
mobile architecture, and push notifications); their original text is preserved
under `docs/archive/superseded/` for anyone who wants the full detail behind a
specific decision.

For the research behind the compression and detection algorithms, see
`docs/RESEARCH.md`. For the security model and audit history, see
`docs/SECURITY.md`. For build and packaging, see `docs/BUILD-AND-RELEASE.md`.

## 1. The system at a glance

SVCS is a Python and Flask desktop application (`src/gui/`) that runs on
Windows, macOS, and Linux. It watches surveillance footage, whether from a
live camera or an existing file, and compresses it with a background
subtractor and an object detector deciding which pixels are worth keeping at
full quality. Four modes trade completeness for size, from "keep everything
but compress the boring parts hard" down to "keep only the moving object."
Every saved clip is indexed in a searchable SQLite database and can be
encrypted with AES-256-GCM before it touches disk. An Android companion app
(`mobile/android/`, Kotlin and Jetpack Compose) pairs with a running SVCS
server over the LAN and gives an operator library access, live view,
compression control, and alerts from a phone.

The desktop app is the only thing that runs the pipeline: FFmpeg, OpenCV, and
the ONNX detection models all execute on the machine running SVCS. The Android
app is a thin client. It never processes video itself; it drives and monitors
the server over its REST API. That single decision, made when the mobile port
started, is what kept the phone app buildable in a single summer instead of
requiring a full port of a 20,000-line Python pipeline to a mobile runtime.

## 2. Camera ingestion

SVCS accepts footage from cameras three ways. Which one applies depends on
what the camera itself supports; there is no vendor-cloud scraping, ever.

| Path | Works for | How |
|------|-----------|-----|
| **Direct RTSP / ONVIF** | Cameras that expose an RTSP stream on the LAN (Reolink, Amcrest, Hikvision, Dahua, Axis, many Tapo/Wyze with RTSP firmware) | SVCS discovers the camera and pulls its live stream. |
| **Export / watch-folder** | Any camera that can write or export clips to a folder (microSD dumps, NVR exports, NAS sync, even Ring/Nest/Arlo via their own export feature) | SVCS watches a folder and compresses new files automatically. This path is universal. |
| **Bridge** | Cloud-locked cameras (Ring, Nest, Arlo) with no RTSP and no usable export | A local bridge such as Home Assistant, Scrypted, or Frigate re-exposes the camera as RTSP, which SVCS then ingests through the direct-RTSP path. |

When a camera supports more than one path, direct RTSP is the better choice
for live recording, and the export-folder path is the better choice for bulk
or after-the-fact compression.

**Direct RTSP / ONVIF.** The dashboard's "Discover ONVIF cameras" action sends
a WS-Discovery probe on the LAN and fills in a suggested RTSP URL once
credentials are entered; credentials are sent only to the local SVCS server to
build that URL and are never logged. If discovery finds nothing (Windows
Firewall commonly blocks the multicast used for discovery), the RTSP URL can be
pasted in directly.

**Export / watch-folder.** SVCS watches a folder, and every new video that
lands there is detected, compressed with an auto-chosen preset, and written to
the output tree. A profile sets sensible defaults for a given export layout:
whether to scan subfolders, how patient to be about half-written files (a NAS
sync is slow and bursty, an SD-card copy is fast), and how to pick the encode
preset. Profiles are data-driven rather than hard-coded per vendor, so adding a
new layout is a single new entry. Reliability comes from three checks: a file
is only ingested once its size is stable across several polls, a file killed
mid-encode is retried on the next scan without ever being marked done twice,
and each ingested file gets a sentinel next to it so it is never reprocessed.

**Bridge ingestion.** Some consumer cameras, Ring, Nest, and Arlo among them,
have no RTSP stream and no useful local export; their video only leaves the
device through the vendor's own app and cloud. SVCS will not scrape that cloud,
log into an account, or screen-scrape an app. The supported answer is a local
bridge: separate software, run on the operator's own hardware, that talks to
the camera (often through the same APIs the vendor app uses, with the
operator's own credentials) and re-exposes it as a standard local RTSP stream.
SVCS then ingests that stream exactly like any other camera. Expect this to be
more setup than a native camera, with coverage and reliability depending on the
bridge project rather than on SVCS; if the camera can export clips instead,
that path is simpler and more robust.

## 3. Universal multi-vendor format support

Surveillance cameras export in a wide range of proprietary containers, not
just the handful of formats OpenCV was built to read. SVCS handles this with a
two-stage decode path rather than by hand-listing formats: OpenCV's
`VideoCapture` is tried first, since it is fast and covers the common case
(and a probe read guards against builds that report themselves open while
failing on the first actual frame). If OpenCV cannot decode the container, SVCS
pipes the file through the bundled FFmpeg instead, which supports far more
demuxers, and reads raw frames from its output. The same central format list
gates every ingest surface, upload, watch-folder, library listing, and the
file-browser picker, so a vendor file is never rejected before it reaches the
decoder that could actually read it.

In practice this means SVCS can ingest H.264 and H.265 in almost any
container, raw elementary streams, MPEG transport and program streams, MXF,
and ASF/WMV among others, which covers the large majority of real-world
vendor exports. It does not cover encrypted or fully proprietary blobs, such as
some Hikvision `.g64` files or encrypted Dahua exports; FFmpeg cannot read
those either, so ingest fails with a clear error asking the operator to export
a standard file with the vendor's own tool first, rather than silently
producing a broken result. The compressed output is always mp4 and plays
everywhere; only browser playback of a vendor original in the library detail
view is limited to browser-playable containers.

## 4. Mobile client

### Current status (September 2026)

The Android app is at version 0.9.0-beta, a 4.5 MB APK. It gives an operator
live view, a library, playback, on-device-triggered compression, resumable
upload from the phone's gallery, event and behavior alerts, and push
notifications that arrive even while the app is closed. Two things are known
to be broken as of this writing and are the top priority for the next round of
work: pairing does not persist across an app restart (the app can come back
using a stale server address and token), and uploads do not survive the app
being killed mid-transfer, because the transfer runs in a scope that gets torn
down rather than in a background-safe worker. Both are tracked in
`docs/CLAUDE-CODE-R7.md`. The mobile test suite is also thin, one JVM test
file, which is why mobile changes have so far needed a human holding a physical
device to verify them.

### The decision that shaped the port: a thin client

The design that made an Android port tractable in one summer, rather than a
rewrite, is that the phone app drives and monitors the existing server over its
REST API. It does not run FFmpeg, OpenCV, or ONNX itself. The alternative,
porting roughly 20,000 lines of Python plus FFmpeg plus ONNX to Android, is not
a port but a rewrite, and was foreclosed anyway: FFmpegKit, the standard mobile
FFmpeg wrapper, was retired in January 2025. Because the server does all the
processing, most of the mobile work turned out to be server-side hardening
rather than Android code: the server had been built for a same-machine
browser, and pointing a phone at it over the LAN exposed a set of defects that
a localhost browser never triggers (see the archived `MOBILE-ARCHITECTURE.md`
for the full list, several of which were live defects in the desktop product
itself and are now fixed there too).

### Stack

Native Kotlin with Jetpack Compose, Media3/ExoPlayer for HLS playback,
OkHttp/Retrofit with kotlinx.serialization for REST, WorkManager plus a
foreground sync service for uploads, and DataStore with a Keystore-wrapped
AES-256-GCM key for stored credentials. The module lives at `mobile/android/`
and is AGPL-3.0 by inheritance from the repository root license.

This choice was made over Flutter, React Native, and a WebView/PWA wrapper.
Every hard requirement the app has, background upload, HLS decode, notification
while closed, hardware-backed credential storage, is an Android platform
capability that Flutter and React Native would reach through the same
underlying APIs anyway. The strongest argument against native Kotlin was
speed to a first working screen and the cost of a second language in a
Python-and-JavaScript repository; that argument was heard and overruled in
favor of the two-year maintenance story. A WebView wrapper was ruled out
outright: the server's CSRF guard runs ahead of the auth guard and rejects any
request whose Origin does not match the request host, so a WebView page served
from a foreign origin gets a 403 on every state-changing request even with
valid credentials, and no CORS configuration in the server could fix that. A
native client sends neither Origin nor Referer and is explicitly allowed by
that same guard, which is why native works today with no server change.

### Authentication

Each phone carries its own bearer device token, issued and revocable
independently of every other device. Auth rides on the `Authorization` header
rather than a session cookie, which lets the video player authenticate its own
connections directly. All API routes, including media and thumbnail routes,
reject anonymous requests.

### What the app can do today

* **Live view.** A Media3 HLS player, with the device token attached to every
  segment request through the same OkHttp client the rest of the app uses. The
  playlist takes a few seconds to appear after a stream starts, so the client
  polls the playlist itself rather than trusting the stream's own "running"
  flag as a readiness signal.
* **Library, playback, and metrics**, backed by the same paginated endpoints
  the desktop dashboard uses. Thumbnails are cached in memory only and never
  written to the phone's disk, because they are surveillance frames.
* **Compression from the phone**, including a mode picker, with results
  joining the same compressed-clip index the desktop app uses.
* **Chunked, resumable upload** from the phone's own gallery, so a flaky
  mobile link can resume a transfer from the last received byte instead of
  restarting at zero.
* **Zones and behavior events**: a drag-to-draw zone editor, and alerts for
  line crossing (with direction) and loitering (with dwell time), raised from
  tracked and classified objects rather than raw pixel motion.
* **Push notifications while the app is closed** (see the next section).

### What was deliberately not built

No on-device encoding: the APK never bundles FFmpeg. No in-app preview of
vendor-original files the phone's decoder cannot demux; those are
thumbnail-only on mobile, with preview scoped to already-compressed mp4, mkv,
mov, and webm. No CORS relaxation and no weakening of the CSRF guard, since
native clients already pass it. No analytics or crash telemetry that carries
personal data, matching the desktop app's default-off telemetry posture.

## 5. Push notifications while the app is closed

SVCS can tell a phone about a behavior alert or a finished compression even
when the app itself is not running, without routing that alert through a
third-party push service. The server posts a short message to an
[ntfy](https://ntfy.sh/docs/) topic the operator hosts, and the ntfy client on
the phone wakes up and shows it. This exists because the app's own polled
notifications die the moment Android kills the app's process, which happens
whenever the app is swiped away or the battery optimizer decides to act, and
because the usual industry answer to that problem, Firebase Cloud Messaging,
would route every alert about the operator's property through Google, and a
self-hosted server has no outbound path to Firebase in the first place. The
feature is off until an operator turns it on, and SVCS never opens a socket
for it without a topic URL configured.

**Setup, in short:** run an ntfy server anywhere the phone can reach it (the
same machine as SVCS is fine), pick a long, unguessable topic name since
knowing the topic name is, by default, the same as having the password, point
SVCS at the topic from the desktop TOOLS tab or the phone's MORE tab, and
subscribe to the same topic in the ntfy app with instant delivery turned on.
The full walkthrough, including the API for scripting this, lives in the
archived `PUSH-NOTIFICATIONS.md`.

**What gets sent** is text only: a title and a short description naming the
kind of event, the camera, and the zone for behavior alerts, or the before and
after size for a finished compression. A single batch caps at five messages
plus one summary line, so a person walking a fence line does not produce a
flood.

**What is deliberately never sent:** plate-reader text, file paths, camera
credentials, or any image, clip, or crop. An alert says what happened and
where; seeing the footage itself means opening SVCS.

**Why this is safe to expose.** The operator-supplied topic URL is fetched by
the server, which is the shape of a server-side request forgery vulnerability.
The pipeline's existing SSRF guard is the wrong tool here, because it refuses
LAN targets outright and a self-hosted ntfy server legitimately lives on the
LAN. This feature carries its own guard instead: only `http`/`https` schemes
are accepted; loopback, RFC1918, and unique-local addresses are allowed on
purpose, since that is the point; known cloud instance-metadata hosts and
addresses are refused, checked after DNS resolution so a friendly hostname
that resolves to a metadata address is caught too; redirects are never
followed; and credentials embedded directly in the URL are refused in favor of
a separate token field. Delivery itself runs on a single background worker
behind a bounded queue with a short timeout, so a slow or unreachable ntfy
server never stalls an encode.
