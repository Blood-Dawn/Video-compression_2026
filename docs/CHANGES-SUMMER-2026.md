# SVCS: what changed over summer 2026

Written for the team, September 2026. Author: Kheiven D'Haiti.

This is the catch-up document. Between May 1 and August 18 the repo took 158
commits, 401 files changed, 62,174 lines added and 11,278 removed. All of it is
pushed. If you last looked at SVCS in April, this is what is different.

The short version: the desktop app became a real product (installer, presets,
library, auto-compress, retention, security audit), the compression got
measurably better instead of just configurable, and the whole thing grew an
Android companion app that now does live view, library, playback, compression
from the phone, resumable upload, behavior alerts, and push notifications that
arrive while the app is closed.

## Headline numbers

| Metric | April 2026 | September 2026 |
|---|---|---|
| Python tests passing | 274 | 1,651 |
| Test files | about 20 | 96 |
| Flask routes | 48 | 87 across 22 blueprints |
| Desktop distribution | run from source | signed installer, 217 MB |
| Slim build size | 4.6 GB | 339 MB |
| Android app | did not exist | 0.9.0-beta, 4.5 MB APK |
| Library listing at 5,000 files | 2,153 ms | 3.3 ms |

Table 1. Project state before and after the summer.

## How to read the repo now

* Branch `mobile` is where work lands. `app` fast-forwards from it. Both are at
  `faeebd1` and pushed.
* `src/gui/` is no longer one giant `app.py`. It is `state.py`, `logging_setup.py`,
  a `services/` layer, and `routes/` blueprints. Import order is
  state, then logging_setup, then services, then routes, then app.
* `src/gui/static/js/` holds the dashboard front end split by feature, with
  `strings.js` as the single copy catalog.
* `mobile/android/` is the Android app, Kotlin and Jetpack Compose.
* `docs/RUNBOOK-LOCAL.md` tells you how to start everything without asking anyone.
* `docs/CLAUDE-CODE-R7.md` is the spec for what happens next.

## Round by round

### May: make v2 a real codebase

The starting problem was that the project worked but could not be handed to
anyone. This round fixed that.

* Test suite went from red to green at 513 passing, fixing a mode 2 CRF bug, a
  sqlite handle leak, and cross-test isolation.
* GitHub Actions CI on Linux and Windows, with portable mp4 validation through
  `ffprobe` rather than `cv2`.
* `gui/app.py` was carved apart: `state.py`, `logging_setup.py`, then nine
  service modules (`path_safety`, `cloud_detection`, `gui_state_persist`,
  `db_helpers`, `cpu_sampler`, `rtsp`, `demo_runner`, `hls_runner`,
  `pipeline_runner`), then 48 routes split into 12 blueprints.
* The inline JavaScript in `index.html` was split into feature modules.
* PyInstaller desktop bundle, first green build.
* **Codec law fixed in code**: mode 0 and mode 1 default to H.264, mode 2 and
  mode 3 default to AV1. Never H.265. This is now enforced per mode rather than
  set by hand.
* Relicensed and cleaned: open source only, commercial docs marked dormant,
  Python 3.11 floor, `easyocr`/`opencv` conflict documented.

### June 3: it installs, and it does not require a manual

* **Inno Setup installer**, a real `SVCS-Setup.exe`. FFmpeg is vendored and
  resolved bundle-first, so a fresh machine needs nothing preinstalled.
* Slim build: defaulting to ONNX and making torch optional took the build from
  4.6 GB to 339 MB.
* **Preset system**. Named surveillance presets replace exposed mode numbers,
  plus a consumer-camera preset family and rule-based content auto-detection
  that picks a preset from the footage.
* **ONVIF camera discovery** and RTSP auto-configuration, plus a bridge-ingestion
  guide for cloud-locked cameras.
* **Watchfolder** hardening: partial-write safety, crash resume, auto-preset,
  export-folder profiles, recursive scan.
* Docker server image, AppImage for Linux, public download page, opt-in
  anonymous usage stats defaulting to off.
* Auth is now required on any non-localhost bind.
* A nine-item usability round (FIX 1 to FIX 9): first-run destination chooser
  with no implicit cloud default, factory reset, pinned header, a TOOLS tab,
  MediaMTX resolution in the frozen app, **the first library tab**, verbose
  step-by-step compression logging, a Help overlay, and a guard test that fails
  the build if an em dash or en dash appears anywhere.

### June 5: the library becomes usable

This is the piece most of you will notice first.

* Folder picker, search, extension filter, sort, and reliable population.
* Recursive listing and an in-app folder browser, from a bug report during use.
* A real-video integration test against the CDnet corpus, so the pipeline is
  tested on actual footage and not only synthetic frames.
* A full feature audit and end-to-end smoke test.

### June 20 to 21: auto-compress and the security audit

* **Auto-compress**: a watch-folder service that compresses new footage on
  arrival, with an already-compressed index so nothing is done twice, a
  `compressed/` output location, an AUTO-COMPRESS tab with live status and log,
  and a library view that separates Originals, Compressed, and All.
* Winget manifest, a WinUtil-style `Install-SVCS.ps1` terminal bootstrap, and
  install documentation.
* **Security audit, SEC-001 through SEC-016.** The ones worth knowing:
  * SEC-001: a same-origin CSRF guard on every state-changing request. The
    dashboard binds the LAN and browsers replay Basic auth, so a malicious page
    could previously drive `/api/start` or trigger footage deletion.
  * Media and library file serving confined to the operator's own folders.
  * Encrypt path confinement and XSS escaping in the scan list.
  * Delete-original can no longer lose footage on a stop or a mis-attribution.
  * `python -m gui.app` now enforces the auth policy, closing a bypass.
  * An SSRF input guard on `input_source`, blocking `file://` and cloud
    metadata hosts while keeping real RTSP cameras on the LAN working.
* Test baseline recorded at 1,025 passing.

### July 4: the compression actually got better

Round 4, six phases. This is the "fixed compression" part.

* **Phase 2, the encoder work**: long GOP, capped CRF, NVENC hardware encoding,
  denoise, encoder-level ROI (the encoder is told where the interesting pixels
  are rather than us blacking out the rest), and VMAF measurement. Plus review
  fixes to clamp infinite and NaN values and make ROI grid aging actually take
  effect.
* **Phase 3, retention**: disk-budget auto-purge. This was the single biggest
  gap against every other NVR. Oldest compressed clips are deleted to stay
  under an age or size budget. Originals are never touched, and it is off by
  default.
* **Phase 1, the UX round**: persistent job history, explicit completion
  summaries, and batch progress, all grounded in the NN/g long-running-work
  guidance written up in `docs/RESEARCH-UIUX.md`.
* **Phase 4**: one codebase now produces two builds, Server and Field. The
  Field build is offline and forces loopback.
* **Phase 5**: the plate reader moved in-process on ONNX, so it ships in one
  environment instead of clobbering opencv.
* **Phase 6**: universal multi-vendor format support through an FFmpeg decode
  fallback, so vendor formats like `.dav`, `.g64`, and `.mxf` ingest.

### July 16: quality-targeted compression

* **R5 5.1, VMAF-targeted rate control.** Instead of picking a CRF and hoping,
  the encoder searches for the smallest file that still meets a quality floor.
* **R5 5.2, static-scene measurement**, which also refuted the
  background-QP mode we had assumed would help. That mode was dropped rather
  than kept for appearances.

### July 18 to 19: the Android port begins

Before any Android code, the server had to stop being hostile to a phone client.
That is milestone M0, ten server fixes:

* A non-ASCII credential returned HTTP 500 instead of 401, which was an
  unauthenticated remote denial of service. Fixed.
* Failed-auth throttling and logging: ten failures from one IP locks that IP for
  300 seconds, with no credential material in any log line.
* HLS was emitting H.264 High 4:4:4, which Android cannot decode. Now
  `yuv420p` with an explicit GOP. The `.ts` content type was wrong on all three
  ship targets. Abandoned streams were never reaped and one global slot 409'd
  everyone, so an idle watchdog was added.
* `GET /api/capabilities` so a client can ask what edition it is talking to.
* Upload stopped preferring a cloud sync root.
* Port-forwarding and ngrok guidance removed from the docs.
* `/api/open_folder` confined, closing an existence oracle.
* **Per-device Bearer tokens with per-device revocation.** A phone gets its own
  credential that can be revoked without touching the others.

Then the app itself:

* **M1.1**: Android module, pairing screen, and a live capabilities probe.
  Verified on a physical Samsung SM-S948U1.
* **M2**: LIBRARY, METRICS, and HOME tabs. Thumbnails are memory-cached only
  and never written to disk, because they are surveillance frames.
* **M2.1a**: the library folder walk is cached. At 5,000 files this took the
  listing from 2,153 ms to 3.3 ms.
* **M2.3**: an honest savings figure. The desktop had been deriving "277x
  smaller" client-side by comparing against raw uncompressed RGB, which answers
  a question nobody asked. The server now reports measured source-versus-output
  bytes separately from merely-recorded totals, and refuses to blend them.
* **M3**: LIVE tab with a Media3 HLS player. Measured finding: the playlist
  404s for about 3.2 seconds after `/api/hls/start` returns 200, and
  `running: true` is useless as a readiness gate, so the client polls the
  playlist itself.
* Two security defects found while building it: `/api/hls/status` and
  `/api/status` were echoing `input_source` verbatim, handing the camera's RTSP
  password to any device token. Redacted. And a new stream was being reaped 8.1
  seconds in because the liveness stamp was not reset.

### August 16 to 18: search, zones, events, and the mobile app fills out

Server side:

* **R5 5.4, natural-language search** (`/api/nl_search`) plus the smart-search UI.
* **R5 5.8, tamper-evident manifests.**
* **R5 5.6, zone masks**: per-camera exclude regions in normalized coordinates,
  so you can mask the road and the tree line and watch the door. Fewer false
  alerts and smaller files at the same time.
* **R5 5.7, behavior events**: line crossing with direction, loitering with
  dwell time, and movement direction, raised from tracked and classified
  objects rather than raw pixel motion. That is what makes an alert fire on a
  person crossing a fence line instead of on wind and headlights. Events append
  to `events.jsonl` next to the footage.
* **M4 job registry and a TOCTOU fix on `/api/start`**, because two
  near-simultaneous POSTs from a retrying phone could both start worker threads.

Mobile, versions 0.3.0 through 0.9.0:

* 0.3.0: release signing.
* 0.3.1: fixed a save-event replay loop that made the MORE screen visibly
  glitch, and reworked pairing into SAVE and OPEN.
* 0.4.0: in-app playback, library views, and compression started from the phone.
* 0.4.1 and 0.4.2: pipeline outputs join the compressed index, plus a
  compression-mode picker.
* 0.5.0: job-completion notifications, and R8 minification turned back on.
  **The APK went from 27.5 MB to 4.39 MB, 84 percent smaller.** The first
  minified build had rendered a black screen because the keep rules stripped
  the generated kotlinx-serialization `$$serializer` classes; the rules file now
  explains this so it does not recur.
* 0.6.0: EVENTS tab, event notifications, and a drag-to-draw zone editor.
* 0.7.0: **chunked resumable upload**, phone gallery to compressed output. The
  protocol supports resume from a byte offset, which matters because a
  non-resumable POST restarts at zero every time the link flaps.
* 0.8.0: auto-compress-on-upload toggle and per-clip INFO metrics.
* 0.9.0: **closed-app push**.

### Closed-app push, in more detail

The phone notifications up to 0.8.0 only fired while the app process was alive.
Android kills that process when you swipe the app away, and polled notifications
die with it. The usual industry answer is Firebase, which would route every
alert about the operator's property through Google and which a self-hosted
server has no outbound path to anyway.

Instead the **server** posts to an [ntfy](https://ntfy.sh/docs/) topic the
operator hosts, and the ntfy client on the phone wakes up for it. Off by
default, with no third-party server baked in.

The interesting engineering is the URL guard in `src/utils/push_notify.py`. The
pipeline's existing SSRF guard is exactly backwards for this feature, because a
self-hosted ntfy legitimately lives on `127.0.0.1` or a `192.168.x.x` box. So
this one allows loopback and RFC1918 and refuses instead: non-http schemes,
credentials embedded in the URL, a missing topic path, the cloud metadata hosts
and addresses (`169.254.0.0/16`, `fe80::/10`, `100.100.100.100`,
`fd00:ec2::254`), any hostname whose DNS answer lands on one of those,
IPv4-mapped IPv6 forms of the same, and redirects, which are never followed.
Titles and tags ride as HTTP headers in ntfy's protocol, so header values are
stripped of control characters before the request is built.

Verified end to end on August 17 against a real ntfy 2.23.0 server on the LAN
with the SVCS app force-stopped. Three messages arrived on the phone:

```
SVCS: line crossed          A person crossed at front_gate heading right on cam_00.
SVCS: loitering             A person is loitering in driveway for 41s on cam_00.
SVCS: compression finished  highway_demo.mp4 finished in 42.3s, 209.8 MB to 29.6 MB, 86 percent saved.
```

Full operator guide: `docs/PUSH-NOTIFICATIONS.md`.

## One bug worth everyone's attention

`tests/security/test_csrf.py` keeps a list of real state-changing routes and
asserts the CSRF guard lets same-origin requests through, which means the
handlers actually execute. One of those routes is `/api/setup/reset`, which is
a factory reset: it deletes `flask_secret`, `gui_state.json`,
`job_history.json`, and `device_tokens.json` from the real app data directory.

So every full test run was silently unpairing every phone that had ever paired
with that install, twice per run, and resetting the first-run wizard. It looked
like a broken phone, not a broken test, and it cost most of a debugging session
before the cause was found.

Fixed in commit `f44f51e` with a fixture that redirects `data_dir` and the
configured output directory to a temp folder. The assertions were not weakened.

**The rule that came out of it:** any test that lets a real destructive handler
run must first redirect `utils.paths.data_dir`, or the specific state file, to
tmp. Patch the narrow thing, never `utils.paths.state_file` itself, because that
attribute is shared and patching it drags every other module along with it.

## What is broken right now

* **Mobile pairing does not persist.** After TEST CONNECTION succeeds and SAVE
  and OPEN is tapped, restarting the app comes back using an older token and an
  older server address. Proven by pointing the app at a logging listener: it
  sent a token ending `s6WlSc` while the validated one ended `62jf5Y`. This
  blocks the phone's push settings panel from working and is the top item in
  `docs/CLAUDE-CODE-R7.md`. Best suspect is that `save()` runs in
  `viewModelScope` while `onCredentialsSaved` bumps `sessionEpoch` and tears
  that scope down mid-write.
* **Uploads do not survive the app being killed.** The resumable protocol is
  there, but the transfer runs in `viewModelScope`. It needs a WorkManager
  wrapper.
* **The launcher icon is still the Android Studio template robot.**
* **Mobile has almost no automated tests.** One JVM test file. This is why every
  mobile change so far has needed a human holding the phone, and it is the first
  thing R7 fixes.

## Things that will bite you

* The auth throttle locks an IP for 300 seconds after ten failures. A phone
  holding a stale token spends that budget in about 25 seconds, and then
  everything looks like a bad token. Restarting the server clears it instantly.
* The app sets `FLAG_SECURE`, so adb screenshots of it come back black by
  design. Read the UI with `adb shell uiautomator dump` instead.
* Piping gradle through `Select-Object -First N` kills the build partway and
  leaves a stale APK that looks fine. Always check the APK timestamp before
  installing.
* Adding a Flask route means updating three guards in the same commit: the
  blueprint registration test, the route resolution test, and `register_blueprints`.
  Current counts are 87 rule strings and 88 url_map rules.
* Use `.venv`, never `venv`.
* No em dashes or en dashes anywhere. There is a test that fails the build.

## Where to start reading

| If you own | Read |
|---|---|
| Encoder and modes | `src/compression/`, then the R4 Phase 2 and R5 5.1 commits |
| Metadata and queries | `src/utils/db/`, `src/gui/routes/queries_bp.py`, and the nl_search work |
| Encryption | unchanged this summer, but note the security audit touched adjacent paths |
| Ingest and streams | `src/utils/watchfolder.py`, `multi_source.py`, R4 Phase 6 |
| Anything mobile | `docs/MOBILE-ARCHITECTURE.md`, then `mobile/android/` |
| Everything | `docs/RUNBOOK-LOCAL.md` to get it running, then `docs/CLAUDE-CODE-R7.md` |

Table 2. Suggested reading by subsystem owner.

Author: Bloodawn (KheivenD), 2026-09-07.
