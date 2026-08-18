# R7 - finish the desktop upgrades and finish the mobile app

Written 2026-08-17 for Claude Code, running on the owner's Windows machine with
the repo checked out and the phone attached over wireless adb.

Read this file top to bottom before touching anything. Then read
`docs/UPGRADE-PLAN-R6.md`, `docs/DESKTOP-ZONES-EVENTS-PLAN.md`,
`docs/RUNBOOK-LOCAL.md`, and `docs/PUSH-NOTIFICATIONS.md`. Verify every claim
against the repo, not against this document; the git log on branch `mobile` is
the truth.

The whole point of this round is that YOU close the loop. The previous rounds
burned most of their time on a human tapping a phone and reporting back. Task 1
exists so that never happens again. Do it first, use it for everything after.

---

## 0. Ground rules that do not bend

* **Codec law.** mode0 and mode1 are H.264. mode2 and mode3 are AV1. Never
  H.265, anywhere, for any reason.
* **Offline and self-hosted.** No cloud service, no telemetry beyond the
  existing opt-in, no Firebase, no third-party push default.
* **No em dashes and no en dashes.** Not in code, comments, docs, commit
  messages, or UI strings. The box-drawing character used in section headers
  (`──`) is fine and is house style.
* **Commit format.** `<type>(<scope>): subject`, then a body explaining WHY,
  then a final line that is exactly `Bloodawn(KheivenD)`. No emojis. No
  co-author trailers.
* **Never weaken a test to go green.** If a test fails, either the code is
  wrong or the test encodes a real requirement you have not met. Fixing the
  test is only correct when the test itself is provably wrong, and then the
  commit body says so and why.
* **Tests ship in the same commit as the change they cover.**
* **One task at a time.** Suite green before each commit.
* **Delete-original only after a verified output.** `ffprobe` validates
  outputs, never `cv2`.
* **Never log secrets.** No plate text, no tokens, no camera passwords, in any
  log line, exception message, or API response.
* **Route guards travel together.** Adding a Flask route means updating all
  three in the same commit: `tests/test_gui_blueprint_registration.py` (rule
  strings, the `EXPECTED` map, the `EXPECTED_BLUEPRINTS` set, the count),
  `tests/test_gui_routes_resolve.py` (a `SAMPLES` entry with a plain path and
  no query string, and the count), and registration in
  `src/gui/app.py::register_blueprints`. Current counts after R6 Track C: 87
  rule strings, 88 url_map rules.

## 0.1 Environment

* Repo: `C:\Users\kheiven\Documents\GitHub\Video-compression_2026`
* Branch `mobile` is where commits land. `app` fast-forwards from it:
  `git fetch . mobile:app`, then push BOTH.
* Python: `.venv`, never `venv`.
* Tests: `pwsh scripts/run_tests.ps1`, or targeted with a UNIQUE basetemp per
  run. Two runs sharing one basetemp corrupt each other and invent failures:
  `.venv\Scripts\python.exe -m pytest tests/... --basetemp=.pytest_tmp_<unique> -p no:cacheprovider -q`
* Android: `mobile/android`. JDK 17 at
  `C:\Program Files\Microsoft\jdk-17.0.19.10-hotspot`, SDK at
  `%LOCALAPPDATA%\Android\Sdk`, adb at `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe`.
* Release signing: keystore `%USERPROFILE%\.svcs\svcs-release.jks`, password in
  `keystore-credentials.txt` beside it, env vars `SVCS_ANDROID_KEYSTORE` and
  `SVCS_ANDROID_KS_PASS`.
* Current mobile version: versionCode 12, versionName `0.9.0-beta`. Bump both
  per release and keep the comment ledger in `app/build.gradle.kts`.
* Phone: Samsung SM-S948U1 over wireless adb. The app sets `FLAG_SECURE`, so
  **screenshots come back black by design**. Read the UI with
  `adb shell uiautomator dump /sdcard/ui.xml` and parse it.
* LAN server for phone testing: see `docs/RUNBOOK-LOCAL.md` section 1. Restart
  it after any server-code change; the phone briefly gets 401s across a restart.

## 0.2 Traps that have already cost hours

* **The auth throttle.** Ten failed attempts from one IP locks that IP for 300
  seconds. A phone holding a stale token spends that budget in about 25
  seconds, and then everything looks like a broken token. Restarting the server
  clears it instantly. Build this into your scripts: restart the server, then
  act, rather than waiting out lockouts.
* **Fixed tap coordinates lie.** The MORE screen scrolls. Taps aimed at
  remembered coordinates land in the wrong field and silently concatenate
  values. This is what produced a 73 character "token" and cost an entire
  debugging session. ALWAYS locate a field by finding the EditText whose bounds
  enclose its label, and ALWAYS assert the field length after typing and before
  pressing anything.
* **Gradle dies if you pipe it.** `Select-Object -First N` terminates the
  PowerShell pipeline and kills the build partway, leaving a stale APK that
  looks successful. Run builds detached to a log file, and check the APK's
  `LastWriteTime` before every install.
* **Destructive routes in tests.** Any test that lets a real handler run must
  first redirect `utils.paths.data_dir` (or the specific state file) to tmp.
  Patch the narrow thing, never `utils.paths.state_file` itself, because that
  attribute is shared and patching it drags every other module with it. This is
  why `push_notify.config_path` exists as its own function. See
  `tests/security/test_csrf.py` for the pattern and commit `f44f51e` for what
  happens when you skip it.
* **A factory reset is real.** `/api/setup/reset` deletes `device_tokens.json`
  and unpairs every phone permanently.

---

## 1. TASK 1 - build the harness that lets you verify yourself (do this first)

Nothing else in this document should be attempted until this exists, because
every later task needs it and because doing it first is what turns this from a
supervised round into an autonomous one.

### 1a. Mobile unit tests on the JVM

`mobile/android/app/src/test` has exactly one test file
(`HostClassifierTest.kt`). JUnit and Robolectric are already wired in
`app/build.gradle.kts`. The ViewModels are where the bugs have actually been,
and they are testable without a device.

Add JVM tests covering, at minimum:

* `ServerSettingsViewModel`: `normalizeUrl` across bare host, host with port,
  scheme present, trailing slash, garbage; the public-address consent gate;
  the save path persisting BOTH url and token (see Task 2, which this test
  should fail against until fixed); `loadPushConfig` mapping each `Fetched`
  case onto the right state.
* `LibraryViewModel`, `EventsViewModel`, `HomeViewModel`: their state mapping
  from a faked `SvcsApi`.

Make `SvcsApi` fakeable. Today the ViewModels construct it directly, which is
what makes them untestable. Extract an interface or accept a factory. This
refactor is in scope and is the point.

Run with `.\gradlew.bat testDebugUnitTest`.

### 1b. Instrumented tests on the real device

`androidTestImplementation` already has JUnit and Espresso. Add
`app/src/androidTest` coverage for the flows that keep breaking by hand:
pairing round trip, MORE tab rendering, the push settings section.

Run with `.\gradlew.bat connectedDebugAndroidTest` against the attached phone.

### 1c. A debug build for diagnosis

`HttpLoggingInterceptor` is compiled in for debug only and redacts
`Authorization`. When something 401s and you cannot see why, install the debug
variant and read logcat. The R6 session lost an hour to a mystery 401 on a
minified release build that a debug build would have shown in one line.

### 1d. `scripts/verify_mobile.ps1`

One script that does the whole loop with no human in it:

1. Restart the LAN server (clears the auth throttle).
2. Build the APK detached, assert the APK timestamp is newer than the newest
   `.kt` file, and fail loudly if not.
3. `adb install -r`, assert `dumpsys package org.svcs.mobile` reports the
   expected versionCode and versionName.
4. Launch, navigate, and assert on parsed `uiautomator` dumps. Provide a helper
   that locates an EditText by its enclosing label, types, and re-asserts the
   resulting field length.
5. Print a pass or fail summary and exit non-zero on failure.

### 1e. `scripts/verify_desktop.ps1`

Start `run_gui.py --host 127.0.0.1 --port 5001 --no-browser --no-sync --no-auth`
and drive it headlessly. Playwright is not currently a dependency; add it as a
dev extra and write the browser checks in Python under `tests/browser/`, marked
so `run_tests.ps1` can skip them when no browser is available. Each desktop task
below names the assertion its browser test must make.

Note the first-run Setup overlay will block the page if `setup_complete` is
false. Dismiss it in the test by seeding the state, NOT by clicking Skip, which
persists a destination choice.

**Acceptance for Task 1:** `verify_mobile.ps1` and `verify_desktop.ps1` both
run green with no human input, and `testDebugUnitTest` covers the ViewModels.
Commit before moving on.

---

## 2. TASK 2 - BLOCKER: mobile pairing does not persist

This blocks calling the mobile app finished, and it blocks the R6 Track C phone
UI from working at all.

**Symptom.** After TEST CONNECTION succeeds and SAVE & OPEN is tapped, an app
restart comes back using an OLDER token and an OLDER server address.

**Evidence gathered 2026-08-17** (minified release build, SM-S948U1):

* Pointed the app at a logging HTTP listener on port 8100 and pressed TEST. The
  app sent a bearer token ending `s6WlSc`, while the token just typed and
  validated ended `62jf5Y`.
* Changed SERVER ADDRESS to `:8100`, tapped SAVE & OPEN, force-stopped,
  relaunched. The field was back to `:5000` and the listener saw nothing.
* Server side agrees: `device_tokens.json` `last_used_at` advances at the
  moment of TEST CONNECTION and never again, so no post-restart request
  authenticates.

**Suspects, in order.** `ServerSettingsViewModel.save()` may not be reached at
all by the tap (verify with an instrumented test, not a manual tap).
`TokenStore.setToken` / `setServerUrl` write to DataStore under an Android
Keystore AES-GCM key; a decrypt failure returns null and is swallowed. Check
whether `save()`'s `viewModelScope.launch` is being cancelled by the
`sessionEpoch++` rebuild that `onCredentialsSaved` triggers, which would abort
the DataStore write mid-flight. That last one fits the evidence best: the write
is started, the shell tears down the scope, the write never lands.

**Acceptance:** a JVM test proves `save()` persists both values; an
instrumented test pairs, restarts the app process, and asserts the app
authenticates; `verify_mobile.ps1` goes green end to end; and the MORE tab's
PHONE ALERTS section loads the server's real topic URL after a re-pair.

---

## 3. Desktop upgrades

Full detail lives in `docs/DESKTOP-ZONES-EVENTS-PLAN.md`. Summarised here with
what each one has to prove.

### D1. EVENTS panel on TOOLS (small)

A collapsible `BEHAVIOR EVENTS` card reading `/api/events/recent`, newest
first, columns kind / camera / headline / wall time, 10s auto-refresh while the
tab is visible, and an empty state that tells the operator to draw zones and
run a compress rather than just saying "no data". Reuse the archive-results
table styles. Files: `index.html`, new `static/js/events.js`, `strings.js`.

Browser test asserts: rows render from a seeded `events.jsonl`; the empty state
appears with no file present; the refresh timer stops when the tab is hidden.

### D2. Zone editor over a real backdrop frame (medium)

Better than the phone version, because the desktop can show the scene. New
route `GET /api/zones/frame?camera_id=X` returning a JPEG still: the newest
thumbnail for that camera from the library cache, else a black 16:9
placeholder. Reuse the thumbnail pipeline, add no new ffmpeg surface. Canvas
overlay: drag to draw exclude rects (red), crossing lines (amber), loiter zones
(blue outline). Toolbar chips ZONE, LINE, LOITER, CLEAR, SAVE mirroring the
phone. Camera id input with a datalist built from the folder labels in
`/api/library/videos`. POST `/api/zones` on save, and the banner says "applies
to the next run" because that is the truth: the pipeline reads the config once
at run start.

Route guards go to 88 rule strings and 89 url_map rules in the same commit.

Browser test asserts: a drawn rect round-trips through POST and GET with
normalized coordinates intact; the frame route returns `image/jpeg` for a
camera with no thumbnail (the placeholder) and does not 500.

### D3. Desktop event toasts (small)

The SSE log already streams `EVENT line_crossing at gate...` lines from the
pipeline. `events.js` listens on the existing feed, filters lines starting with
`EVENT`, and raises the dashboard's existing toast with the headline. Zero new
routes, zero polling.

Browser test asserts: a synthetic `EVENT` line pushed onto the SSE stream
produces exactly one toast, and a non-EVENT log line produces none.

### D4. Webhook emitter (small server)

`utils/event_webhook.py`. On `append_events`, if the operator configured a
webhook URL, POST the event JSON with a 2s timeout, fire and forget, never
blocking the pipeline.

**Reuse `utils.push_notify.is_safe_push_url` rather than writing a second
guard.** It already implements exactly the right policy for this: allow
loopback and RFC1918 because that is where a self-hosted receiver lives, refuse
the cloud-metadata surface, refuse redirects, refuse URL credentials, check
after DNS resolution, unwrap IPv4-mapped IPv6. If the webhook needs anything
`push_notify` does not offer, extend that module rather than forking it.

Config and UI belong next to the push panel on TOOLS, off by default, following
the same write-only-secret pattern.

Tests against a local socket server, in the style of
`tests/test_push_notify.py`.

### D5. Acceptance for the desktop half

Draw a zone and a line for a camera over a real backdrop, run the highway clip,
watch the toast fire, see the rows in the EVENTS panel, and confirm the phone's
EVENTS tab shows the same events from the shared server state. Suite green.

### D6. Remaining desktop polish

* **E2 is D3**, already covered above.
* **E3 winget manifest refresh** for the 2.2 installer sha. Blocked on the
  owner publishing a non-beta tag. Do not do it unprompted.

---

## 4. Finish the mobile app

Order matters here. Task 2 first, then the harness proves each of these.

### M-1. Uploads must survive app death

`LibraryViewModel` runs the chunked upload in `viewModelScope`, so Android
killing the app kills the transfer. The resumable protocol from R6 Track B
already supports continuation (`/api/upload/begin`, `/api/upload/status`,
`/api/upload/chunk`, `/api/upload/finish`), so this is a wrapper, not a
redesign.

Add `androidx.work`, move the transfer into a `CoroutineWorker` with a
foreground notification showing progress, and resume from the offset the server
reports rather than restarting at byte 0. Constraint: unmetered network by
default, with an override.

Acceptance: start an upload of a large clip, `adb shell am force-stop
org.svcs.mobile` mid-transfer, and watch it resume and finish. The verify
script should do exactly that automatically.

### M-2. App icon

The launcher icon is still the Android Studio template robot. Produce a real
adaptive icon (foreground, background, monochrome for themed icons) at every
density plus the anydpi-v26 XML. Match the dashboard's palette: amber `#ffb900`
and teal `#1fd4c8` on the dark surface.

### M-3. The METRICS tab

The owner called the general METRICS tab useless now that per-clip INFO exists.
**Do not delete it without asking.** Put the question to the owner once, in one
message, with a recommendation: either remove the tab and keep INFO, or keep
METRICS but reduce it to the two numbers that are not per-clip (disk headroom
and whether the pipeline is running). Then do what they say.

### M-4. Native UnifiedPush

R6 Track C shipped the server half and documented the ntfy-app subscription
path, which is the zero-code version and already works. The native version
means the SVCS app registers with a UnifiedPush distributor itself and drops
the separate ntfy app: hold a distributor-issued endpoint per install, hand it
to the server, handle re-registration when the distributor changes or the
endpoint rotates, and degrade cleanly when no distributor is installed.

The server side needs a small addition: an endpoint the app can POST its
UnifiedPush endpoint URL to, stored per device token, so the publisher fans out
to every registered endpoint instead of one operator-typed topic. Keep the
manual topic URL working; it is the fallback when no distributor exists.

This is the largest remaining mobile item. Do it after M-1 and the harness, and
only once Task 2 is fixed, because it depends on a pairing that persists.

### M-5. Mobile completeness sweep

With the harness in place, walk every screen and close whatever is unfinished
against `docs/MOBILE-ARCHITECTURE.md` sections 4 and 5. Known live constraints
worth honoring rather than rediscovering:

* Thumbnails are memory-cached only, never written to disk. They are
  surveillance frames.
* Preview is scoped to compressed mp4, mkv, mov, webm. Vendor originals
  (`.dav`, `.g64`, `.mxf`, raw `.264`) are thumbnail-only; Android cannot demux
  them.
* No on-device encoding. No FFmpeg in the APK.
* No Crashlytics, no analytics, no Sentry with PII.
* HLS: poll the playlist URL for an `#EXTINF` before creating a player.
  `running: true` from `/api/hls/status` is useless as a readiness gate, and
  Media3's default retry budget is shorter than the real 3.2s gap.
* The library folder is pinned per request via the `folder` context param, so
  the desktop moving the server-global library folder cannot break the phone
  mid-session. Keep that param on any new media route.
* R8 minification is ON. New `@Serializable` classes under `org.svcs.mobile`
  are covered by the existing keep rules, but verify on a real device after any
  dependency bump. A stripped `$$serializer` is what caused the 0.3.0 black
  screen.

---

## 5. Track D - R5 5.5 semantic search (the last R5 box)

Research document first: `docs/RESEARCH-SEMANTIC-SEARCH.md` covering model
choice, storage, and the offline story, per the R5 spec. Then the opt-in
skeleton with a stub embedder so CI never downloads a model. The real model
install stays a helper-script extra, exactly like the plate reader
(`scripts/install_plates.ps1` is the pattern). No `[plates]`-style extra in the
working environment.

---

## 6. Release

Only when the tasks above are green.

* Bump versionCode and versionName, and extend the ledger comment in
  `app/build.gradle.kts`.
* Copy the APK to `dist\SVCS-Mobile-X.Y.Z-beta.apk`.
* Regenerate `dist\SHA256SUMS.txt` covering BOTH assets.
* `gh release delete-asset` the old APK, then upload the new APK and the sums
  with `--clobber`. `gh` is authed as Blood-Dawn.
* Update the Mobile heading in `docs/release-notes-v2.2.0-beta.md` in the same
  commit; it has lagged the shipped APK before.
* The v2.1.0-beta artifacts and `RELEASE-CHECKLIST.md` are pinned by tests.
  Leave them alone.

---

## 7. Do not do these without an explicit go from the owner

* macOS signed dmg (needs a paid Apple certificate).
* The Rust core spike, M6.
* Publishing a non-beta tag, and therefore the winget refresh that depends on it.
* Deleting the METRICS tab (see M-3).
* TASK 3.3 adaptive per-segment bitrate, deferred by decision.

---

## 8. What "done" looks like

* `pwsh scripts/run_tests.ps1` green, with no test weakened to get there.
* `.\gradlew.bat testDebugUnitTest` and `connectedDebugAndroidTest` green.
* `scripts/verify_mobile.ps1` and `scripts/verify_desktop.ps1` green with no
  human input.
* A phone that pairs once and stays paired across app restarts and app updates.
* An upload that survives the app being killed.
* Zones drawn on the desktop over a real frame, events visible on both desktop
  and phone, a toast on the desktop, and a push to the phone with SVCS closed.
* Commit bodies that say honestly what remains.

Author: Bloodawn (KheivenD), 2026-08-17 (R7 handoff).
