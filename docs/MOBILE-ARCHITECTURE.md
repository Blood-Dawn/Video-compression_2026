# SVCS Mobile - architecture and port plan

Status: **M0 complete. M1.1 built and VERIFIED on a physical device**
(Samsung SM-S948U1, 2026-07-19): the pairing screen reaches a real LAN server
with a device token and renders its edition and feature list. Owner decisions
in section 7 were taken on 2026-07-18.
Branch: `mobile`. Created 2026-07-18 from `app` at `741861e`.
Design source: `mobile/design/` (built with an AI-assisted design tool, then
adapted here by hand).

Grounded in a thorough pass over the live codebase, with every
blocker-or-major claim independently re-verified against source. Roughly a third
of the first-pass claims were refuted or corrected in that second pass; only
survivors are recorded here.

---

## 1. The decision that shapes everything: this is a thin client

The imported mockup settles the biggest question of the port. Its own copy:

> "Files are processed on your local SVCS server."
> "Credentials are sent only to your local SVCS server and are never logged."
> Settings fields: **Server Address**, **Access Token**
> METRICS tile: "POWER DURING ENCODING / server draw - avg watts"

So the Android app **drives and monitors the existing server over its REST API**.
It does not run FFmpeg, OpenCV, or ONNX on-device.

This is what makes the port tractable. The alternative reading, "port 21k lines
of Python plus FFmpeg plus ONNX to Android", is not a port but a rewrite, and it
is foreclosed anyway: FFmpegKit, the standard mobile FFmpeg wrapper, was retired
2025-01-06. The ~21k lines of Python stay exactly where they are.

**Consequence: most of the work in this plan is server-side, not Android.** The
server was built for a same-machine browser. Pointing a phone at it exposes a set
of defects that a localhost browser never triggers.

---

## 2. Recommended stack

**Native Kotlin + Jetpack Compose.** Media3/ExoPlayer for HLS, OkHttp/Retrofit +
kotlinx.serialization for REST, WorkManager plus a `dataSync` foreground service
for uploads, DataStore with a Keystore-wrapped AES-256-GCM key for credentials.
Module at `mobile/android/`, AGPL-3.0 by inheritance from the root `LICENSE`.

Why:

- Every hard requirement (background upload, HLS decode, notification while
  closed, hardware-backed credential storage) is an Android platform capability.
  Flutter and React Native wrap the same APIs; Flutter's `video_player` delegates
  to Media3 anyway.
- The "the team already knows JS" argument does not survive contact with the
  code. `src/gui/static/js/` is deliberately framework-free hand-written JS with
  zero imports across all 19 files, so React Native means learning React, JSX,
  hooks, Metro, and npm from scratch. There is no transferable React skill to
  reuse.
- Licensing is not a differentiator: Compose and Media3 (Apache-2.0), Flutter
  (BSD-3), RN (MIT) are all one-way compatible into AGPL-3.0.

**The strongest argument against it:** native Kotlin is the slowest of the four
to a first running screen, and it commits to a second language in a
Python-and-JS repo that no current contributor has shipped. If a working phone
screen this week matters more than the two-year maintenance story, that argument
wins and the answer is Flutter. It is a real trade, not a formality.

**Why not a WebView or PWA wrapper** (the option that looks cheapest, and the one
worth killing explicitly): the CSRF guard at `src/gui/csrf.py:41-52` runs as a
`before_request` hook **ahead of** the auth guard, and rejects any request whose
`Origin` does not match the request host. A WebView page served from a foreign
origin gets 403 on every state-changing POST *even with valid credentials*, and
there is zero CORS configuration anywhere in `src/` to fix the preflight. Adding
CORS would not even help, because response headers cannot defeat a
`before_request` origin check. A native client sends neither `Origin` nor
`Referer` and is explicitly allowed by that same guard, which is why native works
today with no server change. Beyond that, a WebView cannot deliver background
uploads or notifications, and reproducing the mockup's 5-tab layout inside it
means writing a whole mobile template anyway.

---

## 3. What already works in our favor

Verified empirically, not assumed:

- **Auth is stateless HTTP Basic on every route**, including `/media/<path>`,
  `/api/library/file`, `/api/library/thumb`, and both HLS routes. Anonymous
  requests were confirmed 401 on all ten paths tested. Because the credential
  rides an `Authorization` header rather than a cookie, ExoPlayer authenticates
  on its own connection with `setDefaultRequestProperties`. A cookie-session
  design would have made the LIVE tab far harder.
- **HTTP Range works** on both video routes (confirmed 206 plus `Content-Range`),
  so scrubbing and seeking work.
- **The CSRF guard deliberately passes non-browser clients**, asserted at
  `tests/security/test_csrf.py:71-75`.
- **`/api/library/videos` already paginates** (`page`/`page_size`, default 60,
  clamped to 200).
- The API surface maps cleanly onto the mockup's five tabs.

---

## 4. Blockers

`SERVER` = server-side work. `CLIENT` = Android work. `OWNER` = a decision an
agent should not make alone.

| # | Blocker | Kind | Status |
| --- | --- | --- | --- |
| B1 | Server unreachable from a phone by default (installer ships loopback) | OWNER + SERVER | open |
| B2 | "Access Token" has no server-side counterpart | OWNER then CLIENT | **done** (M0.10, real tokens) |
| B3 | Non-ASCII credential is an unauthenticated remote 500 | SERVER | **fixed** |
| B4 | No rate limiting, lockout, or failed-auth logging | SERVER | **done** (M0.2) |
| B5 | No TLS anywhere; Basic replays the password on every `.ts` fetch | OWNER then CLIENT | open (client-side gate landed) |
| B6 | The app recommends port-forwarding and ngrok | SERVER (docs) | **done** (M0.8) |
| B7 | HLS emits H.264 High 4:4:4, undecodable on Android | SERVER | **fixed** (M0.3) |
| B8 | `.ts` Content-Type wrong on all three ship targets | SERVER | **fixed** (M0.4) |
| B9 | Abandoned HLS streams never reaped; one global slot 409s everyone | SERVER | **fixed** (M0.5) |
| B10 | Upload unusable for a phone clip; also prefers a cloud sync root | SERVER | cloud regression **fixed** (M0.7); chunked upload open (M4.3) |
| B11 | SSE log tail is destructive with more than one client | SERVER | open |
| B12 | No capabilities endpoint; edition is only in rendered HTML | SERVER | **done** (M0.6) |
| B13 | `/api/open_folder` remotely reachable, spawns a host subprocess | SERVER | **fixed** (M0.9) |
| B14 | Shipped FFmpeg is GPL, not LGPL; no corresponding-source offer | OWNER + SERVER | open |
| B15 | Notification transport for the closed-app case | OWNER | open |

**M0 is complete.** Owner decisions taken 2026-07-18: native Kotlin/Compose;
real device-token auth rather than repurposing Basic; all of M0 plus the Android
skeleton; distribution direct-APK first, then Google Play, then F-Droid.

Several of these are **live defects in the shipping desktop product**, not
mobile-only concerns:

- **B3** (fixed in this branch): `hmac.compare_digest` raises `TypeError` on str
  operands containing non-ASCII, and the client half is attacker-controlled. Any
  unauthenticated caller who sent a non-ASCII password got HTTP 500 plus a logged
  traceback, and any operator with an accent in their password could never log
  in. Reproduced end to end before the fix (401 for wrong ASCII, **500** for
  non-ASCII), and after (401 for both).
- **B7**: `hls_runner.py` sets no output `-pix_fmt`, so FFmpeg auto-selects
  `yuv444p` from the rawvideo bgr24 input and emits H.264 High 4:4:4 Predictive.
  No Android MediaCodec decoder handles 4:4:4. It also sets `-hls_time 2` with no
  `-g`, so x264's default keyint of 250 governs IDR placement and real segments
  are 10s, not 2s.
- **B9**: the dashboard's only `/api/hls/stop` caller is an explicit button, with
  no `pagehide` or `visibilitychange` handler, so a closed tab already leaks an
  FFmpeg process today and 409s every later start for everyone.
- **B10**: `_upload_dir()` prefers a OneDrive or Google Drive sync root with no
  opt-in. This is a **regression against adopted policy**: FIX 1 de-clouded the
  output directory, `cloud_detection.py` documents "The app NEVER falls through
  to a OneDrive / Google Drive / iCloud root on its own", and `files_bp.py` was
  listed as a consumer to fix and was overlooked. It has zero test coverage.
- **B11**: `_log_queue` is one module-level queue and every SSE generator calls
  the destructive `.get()`, so each log line reaches exactly one client. The
  dashboard already opens two EventSources from the same page.

Two mockup details that cannot be built as drawn:

- **The "server draw - avg watts" tile has no data source.** Nothing in `src/`
  reads wattage; the only sensors are `psutil` CPU, RAM, and battery, and no
  design capacity in Wh is read anywhere, so watts cannot even be derived.
  Degrade the tile to CPU percentage or drop it. Do not fabricate a number.
- **The mockup pre-fills port 8000**; the server default is 5000.

---

## 5. Phased plan

Repo convention holds: one reviewable commit per task, tests in the same commit.

### M0 - server hardening the client depends on (no Android code yet)

| Task | What | Acceptance |
| --- | --- | --- |
| **M0.1** | **Fix the non-ASCII credential 500 (B3)** | **Done in this branch.** Non-ASCII credential returns 401 not 500; a non-ASCII configured password authenticates. |
| M0.2 | Rate limit and log failed auth (B4) | N failures from one IP return 429; no credential material in any log line. No new dependency. |
| M0.3 | HLS `-pix_fmt yuv420p` and explicit GOP (B7) | argv asserts `-pix_fmt yuv420p` and `-g` = segment seconds * fps; a run yields `EXT-X-TARGETDURATION:2` and Constrained Baseline 4:2:0. |
| M0.4 | `.ts` Content-Type `video/mp2t` (B8) | Asserted on Windows, Linux, Docker. |
| M0.5 | HLS idle watchdog (B9) | Simulated abandonment clears the running flag within the timeout; an actively-fetched stream is never killed. |
| M0.6 | `GET /api/capabilities` (B12) | Server edition reports `hls: true`, field edition `false`. Route-count guard updated in the same commit. |
| M0.7 | De-cloud `_upload_dir()` (B10) | With OneDrive and Drive roots present, destination stays local. Closes a zero-coverage gap. |
| M0.8 | Replace port-forward and ngrok guidance (B6) | No SaaS tunnel recommended anywhere; a non-loopback bind logs a warning naming the risk. |
| M0.9 | Confine `/api/open_folder`, gate dialog routes (B13) | Outside-roots path returns an identical 403 whether or not it exists, closing the existence oracle. |

### M1 - first real screen

**M1.1** Android module skeleton plus a Server Settings screen and a live
connection check. One screen: server address, credential, Save, and a Test button
issuing `GET /api/capabilities` with Basic auth, rendering the returned edition
and feature flags.

Acceptance: **MET 2026-07-19** on a Samsung SM-S948U1 over Wi-Fi debugging.
The phone rendered "SVCS 2.2.0.dev0 / Server" plus all 12 feature flags, and the
token's `last_used_at` was stamped server-side at the moment of the tap, so the
Bearer credential was genuinely verified rather than merely parsed client-side.
`normalizeUrl()`, `PasswordVisualTransformation` and `FLAG_SECURE` were all
exercised incidentally and behaved. 11 JVM unit tests pass.

Still open from the original acceptance: the wrong-credential 401 path and the
public-IP typed confirmation were not driven on-device (both are covered by the
server-side contract tests and the host-classifier unit tests, which is weaker),
and no instrumented test yet asserts that release-variant logcat contains no
`Authorization` value.

Notes that matter: use `androidx.security-crypto` **not at all** (deprecated April
2025); wrap an AES-256-GCM key in Keystore and store ciphertext in DataStore.
Network security config is a **build-time compiled resource** with no runtime API
and no CIDR or wildcard support, so "add the user's host at runtime" is not
implementable. The workable posture is `cleartextTrafficPermitted="false"` in
`base-config`, cleartext permitted only for the server connection, plus a Kotlin
check that the host is loopback, RFC1918, RFC4193, link-local, or `100.64.0.0/10`
before any request.

### M2 - read-only surfaces
LIBRARY against the existing paginated endpoint (thumbnails memory-cached only,
never to disk: these are surveillance frames). METRICS against
`/api/system_metrics`, with the watts tile degraded. HOME against `/api/status`.

HOME has a server-side prerequisite: `_status` carries no byte counters and
`_record_job_history` omits `bytes_in`/`bytes_out` for pipeline runs entirely, so
there is no server-side savings figure to show. The desktop derives it
client-side from a crude estimate. Add a real cumulative figure server-side
rather than re-deriving that estimate on the phone.

### M3 - LIVE  (built 2026-07-19)
Media3 HLS, with the token on the data source via `OkHttpDataSource` wrapping
the app's own OkHttp client. Gate readiness by polling the **playlist URL
itself**, mirroring `hls.js`.

Measured on a real-time source (synthetic 25fps feed over UDP, so the timing
profile of an always-on RTSP camera):

| event | t+ |
|---|---|
| `POST /api/hls/start` returns 200 | 0.02s |
| `/api/hls/status` reports `running: true` | 0.0s |
| playlist first returns 200 with an `#EXTINF` | **3.2s** |
| second segment listed | 5.2s |

So the gate is mandatory, and `running: true` is useless for it. Media3's
default retry budget is shorter than the 3.2s gap, so a player built on the
start response gives up before the stream exists.

CORRECTION to the original note here, which claimed `ingest_latency_s` goes
non-null a full segment before the playlist exists. It does not. That value is
set when `hls_dir.glob("*.ts")` first matches, and at 100ms sampling the `.ts`
file, the `.m3u8` file and the first `#EXTINF` all appear in the SAME sample:
ffmpeg buffers the segment and writes it out when the segment closes, rather
than pre-creating the file at segment start. The conclusion (poll the playlist)
was right; the stated mechanism was wrong. `ingest_latency_s` is simply no
earlier than the playlist, not misleadingly earlier.

Also measured, and load-bearing for the client:

* segment URIs in the playlist are RELATIVE (`playlist0.ts`), so ExoPlayer
  resolves them against the playlist URL and no rewriting is needed;
* a GET of a `.ts` with no `Authorization` header returns **401**, so the token
  has to ride on segment requests, not just the media item;
* segments are served `video/mp2t`, the playlist `application/vnd.apple.mpegurl`;
* a device token can call `/api/hls/start` and `/api/hls/stop`.

Shipped single-camera, as planned; the per-camera registry refactor (B-side of
B9) is still the largest server change in the plan and rewrites an existing
asserted test.

Two server defects surfaced while building this, both fixed:

* `/api/hls/status` and `/api/status` echoed `input_source` verbatim, handing
  the camera's RTSP password to any device token (commit `7543968`);
* `/api/hls/start` did not clear `last_segment_fetch`, so the idle watchdog
  inherited the previous stream's timestamp and reaped a new stream 8.1s in,
  before any client could reach it. Affects the desktop too (commit `7671b7c`).

### M4 - control and ingest
Job registry and a TOCTOU fix on `/api/start` (two near-simultaneous POSTs, easy
from a phone retrying on a flaky link, can both start worker threads). Then
starting an encode from a **server-side path**, which needs zero phone bytes and
is the correct v1 ingest. Chunked resumable upload is last and is a hard
prerequisite for any phone upload, native or not, because WorkManager retrying
the current non-resumable POST restarts at byte 0.

### M5 - notifications
Structured job-event schema first (the existing SSE stream carries formatted log
lines, not machine-readable job state), then delivery per the B15 decision.

---

## 6. What not to build

- **No WebView stopgap.** Killed by CSRF-before-auth and no CORS, above.
- **No token auth in v1.** Ship on Basic in the "Access Token" field. Build real
  tokens in v1.1 together with revocation, which is the part that actually
  matters for a credential sitting on a phone.
- **No on-device encoding, ever, for v1.** No FFmpeg in the APK.
- **No in-app preview of vendor-format originals.** The Library lists 40
  extensions including `.dav`, `.g64`, `.mxf`, and raw `.264` that Android cannot
  demux. The repo already models this for the web UI as `BROWSER_PLAYABLE_EXTS`.
  Scope v1 preview to compressed mp4/mkv/mov/webm; treat vendor originals as
  thumbnail-only.
- **No CORS, and do not relax the CSRF guard.** Native passes already.
- **No Crashlytics, Sentry-with-PII, or analytics.** Match the existing
  `send_default_pii=False` posture. If crash reporting is wanted, ACRA to a
  self-hosted endpoint, opt-in behind the same two-flag pattern.
- **No Android CI yet.** One screen on one device first.

---

## 7. Open questions for the owner

1. **Stack: confirm native Kotlin/Compose, or prefer Flutter?** Section 2 states
   the case and the counter-case honestly. This is the one decision that is
   expensive to reverse later.
2. **Does "Access Token" mean a repurposed Basic blob, or real token auth?**
   Repurposing works against today's server with zero backend change. Real tokens
   buy per-device revocation.
3. **How does a user turn on LAN access?** Documented launch flags, an installer
   checkbox, or an in-app toggle. This decides how much of onboarding is docs
   versus code.
4. **Closed-app notification transport: self-hosted UnifiedPush/ntfy, or an
   always-on foreground service?** FCM is excluded by the no-cloud house rule and
   by architecture (a self-hosted server has no outbound path to FCM), not merely
   by F-Droid policy.
5. **Distribution: F-Droid, Google Play, or both?** F-Droid is the conventional
   home for copyleft Android apps with no AGPL friction. Play has direct
   precedent: Signal-Android is AGPL-3.0-only and ships there, and Immich is AGPL
   with a self-hosted server plus a Play-distributed client, which is almost
   exactly this architecture. Play does require reviewer access to working
   functionality, which a thin client cannot provide without a server; the right
   mitigation is an in-app offline demo using the clips in `data/samples/`, not a
   public demo server. Given the DoD/DIU sponsorship, confirm with whoever
   handles legal clearance.
6. **B14 remediation timing.** The GPL FFmpeg corresponding-source gap does not
   touch the APK, but it binds every release that ships the server.

Not escalated, recorded for completeness: the Android client defaults to
**AGPL-3.0** by inheritance from the root `LICENSE`. Only a proposal to license
it permissively would need escalation, and that belongs in the existing
multi-contributor IP question, not to a single owner.
