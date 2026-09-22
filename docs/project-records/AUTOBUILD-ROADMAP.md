# SVCS Autobuild Roadmap

A task-by-task execution plan for a coding agent (Claude Code or similar)
picking up this repository cold. This is a restructuring of the commitments
already made in `ROADMAP.md`, `docs/project-records/PLANNER-FALL-2026.md`,
`week3.local.json`, and `docs/BLOCKERS.md` / `docs/plans/BLOCKERS.md` into an
ordered, dependency-aware sequence with concrete definitions of done, not a
new product vision. Nothing here should be scope the team has not already
committed to somewhere in those documents, except where explicitly marked
`[verified gap, not yet in a planning doc]`.

**How to use this document.** Work top to bottom within a milestone; a
milestone's tasks are listed in the order their dependencies allow, and later
milestones depend on earlier ones unless stated otherwise. Each task names
its files, its definition of done (a test to run or a manual check to
perform), its dependency, and a rough size (S = a few hours, M = a day or
two, L = several days). When a task's definition of done cannot be met by
CI/pytest alone (a pentest, a signed build, a physical Android device), that
limitation is called out explicitly rather than glossed over.

**Source-of-truth note.** This document does not replace `ROADMAP.md` or the
planner; if a task's scope changes, update the planner first (it is graded
against weekly reports), then this file.

---

## 0. What this roadmap found that the existing docs do not say

These are things a run of `git log`, branch diffs, and targeted greps turned
up that are not reflected — or are reflected incorrectly — in the current
planning docs. Read this section before trusting any "done" claim elsewhere
in the repo.

### 0.1 `main` does not contain the Android app source at all — this is the single most important fact for anyone picking up mobile work

`git branch -a` on `main` shows three long-lived branches: `main`, `app`, and
`mobile` (plus several short-lived `feature/*` branches). **The entire
Android app source tree — every Kotlin file under
`mobile/android/app/src/` — exists only on the `app` and `mobile` branches.**
On `main`, `git ls-tree -r HEAD -- mobile` returns only 65 entries, all
Gradle wrapper/cache junk (`.gradle/**`, `gradle-wrapper.jar`,
`local.properties`); there is no `app/src/main` or `app/src/test` directory
at all. The commit `b36c8a5` on `main`, titled *"fast-forward main from
mobile, minus the unfinished Android app"*, made this split deliberate: `main`
is the desktop-only line, `app`/`mobile` carry the phone client.

Since that fork point (`b36c8a5`, 2026-09-07), the two lines have **diverged
in both directions**: `main` has 18 commits `mobile` does not have (recent
desktop security fixes, the Sep 21 `BLOCKERS.md`/`RELEASE-CHECKLIST.md`
rewrite, `src/gui/routes/ingest_bp.py` changes, `scripts/update_planner.py`,
etc.), and `mobile`/`app` have 7 commits `main` does not have, including
`77288eb` (task 3.1, see 0.2 below) and `e41a447` (planner automation).
`app` and `mobile` are themselves 1 commit apart (`mobile` has `e41a447`,
`app` does not) — treat `mobile` as the current tip of Android work.

**Consequence for this roadmap:** every mobile task below (Milestones 1, 2,
and the mobile parts of 6/7/8) must be done on a branch that contains the
Android source — either `mobile` rebased/merged forward from `main` first,
or `main` after a deliberate merge of `mobile` into it. Milestone 0 below
makes that reconciliation task explicit and first. An agent that checks out
`main` and searches for `SvcsApi.kt` will not find it and may wrongly
conclude the mobile app does not exist yet.

### 0.2 Task 3.1 is marked 0% complete but is already implemented — on the unmerged branch

`week3.local.json` and `docs/project-records/PLANNER-FALL-2026.md` both list
task **3.1 "Make `SvcsApi` fakeable and add JVM unit tests for the view
models"** (owner Kheiven) at `percentComplete: 0`. In fact this task is
already done: commit `77288eb` ("feat(mobile): make SvcsApi fakeable, add
JVM unit tests for view models (3.1)", 2026-09-14) is on `origin/mobile` and
`origin/app`, and adds `FakeSvcsApi.kt`, `HomeViewModelTest.kt`,
`LibraryViewModelTest.kt`, `EventsViewModelTest.kt`, and
`ServerSettingsViewModelTest.kt` under `mobile/android/app/src/test/`. It is
real, tested code, just stranded on a branch that has since drifted from
`main`. Do not redo this task; verify it still builds after the Milestone 0
merge and update the planner's percentComplete instead.

### 0.3 Mobile version number is stale in the latest release notes

`docs/release-notes-v2.2.0-beta.md` lists the mobile artifact as
`SVCS-Mobile-0.8.0-beta.apk`. The actual mobile app's
`mobile/android/app/build.gradle.kts` (on `origin/mobile`) sets
`versionName = "0.9.0-beta"` / `versionCode = 12`, which matches
`docs/SYSTEM-ARCHITECTURE.md`'s own statement that "the Android app is at
version 0.9.0-beta". The release notes' APK filename/version is one release
behind reality. Fix as part of Milestone 0 (cheap, no code risk) rather than
carrying a wrong filename into the next real release.

### 0.4 The desktop EVENTS panel and zone editor genuinely do not exist yet — the roadmap's claim here is accurate

Checked so this isn't assumed: `src/gui/routes/events_bp.py` has
`GET /api/events/recent` and `GET`/`POST /api/zones`, but there is **no**
`GET /api/zones/frame` route anywhere in `src/gui/routes/`, and
`src/gui/templates/index.html` (4,176 lines) has no EVENTS table, zone
canvas, or toolbar markup. Tasks 3.5–3.8 / 4.5–4.8 / 5.5–5.8 / 6.7–6.8 in
Milestone 3 below are real, not-yet-started work, exactly as the planner
says.

### 0.5 The webhook emitter also genuinely does not exist yet

`src/utils/event_webhook.py` does not exist; only `src/utils/push_notify.py`
(the ntfy push guard) exists. Task 3.9/3.10/4.9/4.10 in Milestone 5 below are
real, not-yet-started work. `docs/plans/BLOCKERS.md`'s June 2026 entry
("Outbound webhook / MQTT / email on events... deferred") is the origin of
this backlog item and is consistent with what's in the code today.

### 0.6 `[verified gap, not yet in a planning doc]` — MediaMTX download has a zip-slip / no-checksum gap, and it is not actually written down anywhere in `docs/`

`src/utils/rtsp_server.py`'s `_do_download()` (lines ~183–211) downloads a
MediaMTX release archive over plain `urllib.request.urlretrieve()` with no
hash check against a pinned value, then calls `z.extractall(dest_dir)` /
`t.extractall(dest_dir)` directly with no check that archive members stay
under `dest_dir` (the standard zip-slip path-traversal pattern: a malicious
or corrupted archive entry named `../../something` would write outside
`tools/mediamtx/`). A repo-wide grep for `extractall`, `zip-slip`, and
`zip slip` across `docs/` and `src/` turns up **only these two call sites in
the code** — the issue is not mentioned in `docs/BLOCKERS.md`,
`docs/plans/BLOCKERS.md`, `docs/SECURITY.md`, or
`docs/security/SECURITY-AUDIT.md`, and no test in `tests/security/` or
elsewhere exercises this path. Fix it in Milestone 5 below and add an entry
to `docs/BLOCKERS.md` (or close it there directly) so it stops being
undocumented tribal knowledge.

### 0.7 Everything else checked out as advertised

Spot-checks that came back **consistent** with the docs (listed so the human
owner knows these were actually verified, not assumed): AES-256-GCM
encryption, YOLOv8 ONNX detection, and the enhancement module are all present
and match the Spring-2026-complete claim in
`docs/project-records/PROPOSAL-SECTION-2.7-ORG-CHART-AND-COMPLETED-TASKS.md`.
`src/utils/push_notify.py`'s SSRF guard exists and is what tasks 3.9/4.9
below are meant to reuse. The 97-file `tests/` suite (14 files under
`tests/security/`) is real and broad, not a stub. `tests/test_autocompress.py`
does contain `test_live_save_daemon_compresses_and_dedups` (line 316) —
a real end-to-end daemon test with a 120-second polling wait loop around a
background thread, which is a plausible shape for the unconfirmed race
mentioned in `docs/BLOCKERS.md`; this roadmap does not attempt to diagnose it
(that needs an actual full test run, out of scope here) but schedules an
investigation task in Milestone 8.

---

## Milestone 0 — Branch reconciliation and doc hygiene (do this first, blocks everything mobile)

Nothing in Milestones 1–2 (or the mobile halves of 6–8) can be verified on
`main` until this lands, because the Android source is not there.

### 0.a — Reconcile `main` and `mobile`/`app`
- **Files:** whole-repo merge; expect conflicts in `docs/BLOCKERS.md`,
  `docs/release-notes-v2.2.0-beta.md`, `installer/svcs.spec`,
  `src/gui/routes/ingest_bp.py`, `tests/test_release_artifacts.py`,
  `tests/test_version_consistency.py`, `week3.local.json` (deleted on
  `mobile`, present on `main` — keep `main`'s copy, it's newer).
- **Approach:** merge `origin/mobile` into `main` (not the reverse — `main`
  has the more recent security/docs work and should stay the integration
  branch). Resolve conflicts by keeping `main`'s desktop-side changes and
  `mobile`'s Android-side additions; both sides touched `docs/BLOCKERS.md`-
  adjacent files so read each conflict rather than blindly picking a side.
- **Definition of done:** `mobile/android/app/src/main` and
  `mobile/android/app/src/test` exist and are non-empty on `main`; `pytest -q`
  still passes (desktop side untouched by the merge should not regress);
  `git log --oneline main..origin/mobile` and
  `git log --oneline origin/mobile..main` are both empty afterward, i.e. the
  branches are actually reconciled, not just cherry-picked past each other.
- **Dependency:** none. **Size:** M (mechanical merge, but wide).

### 0.b — Update the stale completion tracking for task 3.1
- **Files:** `week3.local.json`, `docs/project-records/PLANNER-FALL-2026.md`.
- **Definition of done:** task 3.1's entry reflects that it is complete
  (with the actual commit hash `77288eb` noted), not `percentComplete: 0`.
- **Dependency:** 0.a (so the code is actually visible on `main` when this is
  written). **Size:** S.

### 0.c — Fix the mobile version number in the current release notes
- **Files:** `docs/release-notes-v2.2.0-beta.md`.
- **Definition of done:** the mobile artifact line reads
  `SVCS-Mobile-0.9.0-beta.apk`, matching `mobile/android/app/build.gradle.kts`
  `versionName` and `docs/SYSTEM-ARCHITECTURE.md`.
- **Dependency:** 0.a. **Size:** S.

### 0.d — Log the MediaMTX zip-slip/checksum gap in `docs/BLOCKERS.md`
- **Files:** `docs/BLOCKERS.md`.
- **Definition of done:** a new entry describing the gap in
  `src/utils/rtsp_server.py::_do_download()` exists in `docs/BLOCKERS.md`,
  pointing at Milestone 5 task 5.f below for the fix. This just makes the
  known-but-undocumented gap visible before it's fixed, in case the fix
  itself slips.
- **Dependency:** none. **Size:** S.

---

## Milestone 1 — Mobile test infrastructure and the pairing fix (Phase A / M1 target)

This is the semester's stated milestone 1: "mobile changes verifiable
without a human holding the phone." Everything else mobile depends on this
existing, per the planner's own dependency table (`4.1, 4.2 pairing fix` is
blocked by `3.1, 3.2`).

### 1.a — Debug build variant with HTTP logging (planner 3.2)
- **Files:** `mobile/android/app/build.gradle.kts` (add/confirm a `debug`
  build type with an OkHttp logging interceptor wired only into that
  variant), a new or extended `net/SvcsApiClient.kt` logging hook.
- **Definition of done:** a deliberately-failing request (e.g. point the app
  at a closed port) shows a readable reason in `adb logcat` on a debug build;
  confirm the interceptor is compiled out of the `release` variant (grep the
  release-variant merged manifest / minified output for the interceptor
  class, or check `buildTypes { release { ... } }` excludes the debug
  dependency).
- **Dependency:** Milestone 0. **Size:** S.

### 1.b — Diagnose and fix mobile pairing persistence (planner 4.1 + 4.2)
- **Files:** `mobile/android/app/src/main/java/org/svcs/mobile/ui/ServerSettingsViewModel.kt`
  (the `save()` / `onCredentialsSaved` / `sessionEpoch` interaction),
  `data/TokenStore.kt`.
- **Root cause already identified in `docs/CHANGES-SUMMER-2026.md`** ("What is
  broken right now"): `save()` runs in `viewModelScope` while
  `onCredentialsSaved` bumps `sessionEpoch` and tears that scope down
  mid-write, so the write to `TokenStore` (Keystore-backed DataStore) can be
  cancelled before it lands — proven in that doc by watching two different
  token suffixes (`s6WlSc` vs `62jf5Y`) after a restart.
- **Definition of done:** a failing JVM test in
  `mobile/android/app/src/test/java/org/svcs/mobile/ui/ServerSettingsViewModelTest.kt`
  reproduces the lost write (assert the token/URL written before a
  simulated `sessionEpoch` bump/scope teardown is the one read back), then a
  fix (e.g. moving the `TokenStore` write off `viewModelScope`, onto
  `viewModelScope` scoped to the write completing, or a
  non-cancellable write) makes that test pass. `gradlew testDebugUnitTest`
  green. A phone that pairs once and is restarted must come back with the
  same server URL/token it saved (this half needs a physical device or
  emulator and cannot be fully confirmed by the JVM test alone — call this
  out rather than claiming it closed on unit tests only).
- **Dependency:** 1.a (needs the debug logging to diagnose reliably, per the
  planner's own stated dependency), Milestone 0. **Size:** M.

### 1.c — Instrumented tests for pairing and settings flows (planner 6.1)
- **Files:** new `mobile/android/app/src/androidTest/java/org/svcs/mobile/...`
  instrumented test(s) covering the pair → restart → still-paired flow.
- **Definition of done:** `gradlew connectedDebugAndroidTest` green on a
  physical device or emulator. This is explicitly device-dependent; note in
  the PR/commit which device/emulator API level it was run against.
- **Dependency:** 1.b. **Size:** M.

### 1.d — `scripts/verify_mobile.ps1` end to end (planner 5.1)
- **Files:** new `scripts/verify_mobile.ps1`.
- **Definition of done:** the script builds the debug APK, installs it on a
  connected device/emulator via `adb`, launches it, asserts on a
  machine-readable signal (e.g. a specific logcat line or an
  `adb shell dumpsys activity` check) that the app reached a known screen,
  and exits non-zero on any failure — no human interaction required to
  reach a pass/fail exit code.
- **Dependency:** 1.a. **Size:** M.

### 1.e — Real Android launcher icon (planner 5.2)
- **Files:** `mobile/android/app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml`
  and companion `drawable`/`mipmap` density buckets; currently
  `ic_launcher_background.xml` / `ic_launcher_foreground.xml` are the
  Android Studio template.
- **Definition of done:** an adaptive icon (foreground + background layers)
  reflecting the SVCS brand (see `installer/` for the existing brand kit
  used on the Windows installer/exe icon, added in commit `7f65daf`) is
  present at every standard density; the template robot no longer appears in
  `gradlew assembleDebug` output APK.
- **Dependency:** Milestone 0 only (independent of the rest of M1).
  **Size:** S.

---

## Milestone 2 — Mobile upload reliability (Phase B, part of M2 target)

### 2.a — WorkManager design + resumable-upload protocol audit (planner 3.3 + 3.4, merged since neither happened yet)
- **Files:** read `mobile/android/app/src/main/java/org/svcs/mobile/...`
  wherever the current chunked upload lives (search for `viewModelScope` +
  upload logic), and `src/gui/routes/` server-side `/api/upload/status`.
- **Definition of done:** a short written design (can live as a doc comment
  or a `docs/architecture/` note) confirming (a) `/api/upload/status` returns
  a byte offset a `CoroutineWorker` can resume from, verified by a manual or
  scripted call against a real server, and (b) the shape of the
  `CoroutineWorker` replacing the current `viewModelScope`-based transfer.
  This is a design task; its "done" is a document plus a passing check
  against the real endpoint, not new production code yet.
- **Dependency:** Milestone 0. **Size:** S.

### 2.b — Implement the upload `CoroutineWorker` with a foreground notification, and prove it survives a kill (planner 4.3 + 4.4)
- **Files:** new/modified Kotlin under `mobile/android/app/src/main/java/org/svcs/mobile/` for the worker, plus wiring into whatever screen currently starts uploads (`LibraryScreen.kt` / `LibraryViewModel.kt` or similar — confirm at implementation time).
- **Definition of done:** the upload runs as a `WorkManager` `CoroutineWorker`
  with a foreground notification showing progress, not inside
  `viewModelScope`; force-stopping the app mid-transfer (`adb shell am
  force-stop org.svcs.mobile`) and relaunching resumes the transfer from the
  server-reported offset (from 2.a) and completes, verified either by an
  instrumented test or a documented manual repro with before/after byte
  counts.
- **Dependency:** 2.a, Milestone 1 (pairing must persist for a resumed
  session to authenticate). **Size:** L.

---

## Milestone 3 — Desktop EVENTS panel and zone editor (Phase B, M2 target: desktop/mobile parity)

Verified in section 0.4 as not yet started. Order follows the planner's own
dependency table (`4.7, 4.8 zone drawing` blocked by `3.7 frame route`;
`5.8` blocked by `4.7/4.8`; `6.7/6.8` blocked by `4.7/4.8`).

### 3.a — `GET /api/zones/frame` still-frame route (planner 3.7)
- **Files:** new route in `src/gui/routes/events_bp.py` (or a new
  `zones_bp.py` if that's cleaner — the existing zones routes are currently
  inside `events_bp.py`), reusing whatever thumbnail/frame-grab utility the
  library routes already use.
- **Definition of done:** `GET /api/zones/frame?camera_id=X` returns a JPEG
  still for a camera with an existing thumbnail, and a black placeholder
  image (not an error) when no thumbnail exists yet. All three existing
  route-guard tests that enumerate blueprint routes (see
  `tests/test_gui_routes_resolve.py` / the route-guard sweep referenced in
  `docs/plans/BLOCKERS.md`'s "82 rules" note) are updated to include the new
  route. A new `tests/test_zones_events.py` (already exists — extend it)
  case covers both the real-thumbnail and placeholder paths.
- **Dependency:** Milestone 0. **Size:** S.

### 3.b — Desktop EVENTS panel: read-only table, empty state, auto-refresh (planner 3.5 + 3.6)
- **Files:** `src/gui/templates/index.html` (new EVENTS table markup on the
  TOOLS tab), a new or extended static JS module under `src/gui/static/`.
- **Definition of done:** a newest-first table populated from
  `GET /api/events/recent`; an empty state that tells the operator to draw
  zones first when there are no events; a 10-second auto-refresh that stops
  when the tab/panel is hidden (e.g. via the Page Visibility API) and
  resumes when visible. A browser/DOM test (see task 3.d) seeds
  `/api/events/recent` and asserts rows render; a second case asserts the
  empty state.
- **Dependency:** 3.a is not required for this (events don't need the frame
  route), but do 3.a first anyway since 3.c needs it and they touch adjacent
  UI. **Size:** M.

### 3.c — Zone editor canvas: layout, drag-to-draw, SAVE/CLEAR (planner 3.8 + 4.7 + 4.8)
- **Files:** `src/gui/templates/index.html` (toolbar + canvas markup
  matching the phone editor's tool set — see `mobile`'s
  `ui/` zone-editor screen, added in mobile commit `55b41cd`, for the
  reference interaction model), new static JS for canvas drawing, existing
  `GET`/`POST /api/zones` in `src/gui/routes/events_bp.py`.
- **Definition of done:** drag-to-draw for exclude rectangles and crossing
  lines, plus loiter zones, all round-trip through `POST`/`GET /api/zones`
  with normalized coordinates intact (add a `tests/test_zones_events.py`
  case posting a drawn shape and reading it back byte-for-byte on
  coordinates); a SAVE and CLEAR action in the toolbar; a banner stating
  changes apply to the next pipeline run (matching the async nature of the
  backend, which doesn't hot-reload zones mid-run).
- **Dependency:** 3.a (needs the backdrop frame to draw over). **Size:** L.

### 3.d — Desktop event toasts wired to SSE, and browser tests for the EVENTS panel (planner 4.5 + 4.6)
- **Files:** the existing SSE client in `src/gui/static/` (search for the
  SSE `EventSource` consumer), `src/gui/routes/sse_bp.py`.
- **Definition of done:** exactly one toast raised per `EVENT` line on the
  existing SSE stream; other log line types raise none (test by feeding a
  mixed log stream and counting toasts, not just checking one fires). A
  browser test (Playwright, matching whatever the existing browser test
  suite uses — check `tests/` for the current browser-test harness pattern)
  seeds a fixture events file and asserts panel rows render, and separately
  asserts the empty state from 3.b.
- **Dependency:** 3.b. **Size:** M.

### 3.e — Camera id datalist + browser-verified zone editor over a real frame (planner 5.7 + 5.8)
- **Files:** the zone editor markup from 3.c, sourcing camera ids from
  existing library folder labels (check `src/gui/routes/library_bp.py` or
  `cameras_bp.py` for how camera ids are already enumerated elsewhere).
- **Definition of done:** the zone editor's camera field is a datalist of
  real camera ids, not free text; a screenshot (saved under
  `docs/testing/` or attached to the PR) shows a zone actually drawn over
  real footage from `data/samples/` or a live source, confirming the canvas
  aligns with the frame route from 3.a pixel-for-pixel.
- **Dependency:** 3.c. **Size:** S.

### 3.f — Query archive full-text/multi-tag search + integration test (planner 5.5 + 5.6)
- **Files:** `src/gui/routes/queries_bp.py`, the query sidebar markup in
  `src/gui/templates/index.html`, and whatever CLI multi-type query already
  exists (per `docs/project-records/PROPOSAL-SECTION-2.7-...md`, Ashleyn's
  spring work: `query_by_type()`).
- **Definition of done:** the desktop query UI supports full-text and
  multi-tag search matching the existing CLI capability (same query
  semantics, not a subset); a new integration test runs the pipeline against
  a sample producing events, then confirms the query interface retrieves
  them.
- **Dependency:** Milestone 0. Can run in parallel with 3.a–3.e (different
  subsystem). **Size:** M.

### 3.g — CDnet zone-compression measurement + writeup (planner 6.7 + 6.8)
- **Files:** a new script under `scripts/` or `tools/` running the CDnet
  corpus (`data/samples/cdnet_mp4/...`) with and without exclude zones,
  reusing the existing benchmark/metrics utilities (`metrics.py` per the
  spring history).
- **Definition of done:** a measured file-size difference from zone masking,
  written up as a table (destined for the final report), with the existing
  "zones save bandwidth" claim either confirmed or corrected with numbers —
  this is explicitly a measure-and-report task, not a code-correctness one.
- **Dependency:** 3.c (zones must be drawable/definable before their effect
  is measurable, per the planner's own dependency table). **Size:** M.

---

## Milestone 4 — Desktop onboarding hardening (Phase A/B addendum, week 3 findings)

These came out of the team's own fresh-install review (documented in
`docs/project-records/PLANNER-FALL-2026.md`'s "Week 3 addendum" section) and
are independent of the mobile/events work above, so they can run in
parallel with Milestones 1–3.

### 4.a — Folder-browse button on the Setup destination field (planner 3.13)
- **Files:** `src/gui/routes/setup_bp.py`, `src/gui/templates/index.html`
  (Setup screen), reusing the existing Library folder-browser modal (find it
  via `library_bp.py` / the corresponding JS).
- **Definition of done:** Setup's destination field offers the same
  folder-browse modal the Library tab uses; a non-technical operator is
  never required to type a raw Windows path from memory. A UI/route test
  confirms the browse endpoint is reachable from Setup.
- **Dependency:** none. **Size:** S.

### 4.b — Compact install path: warn (don't silently fail) when FFmpeg is missing from PATH (planner 3.12)
- **Files:** `src/utils/ffmpeg.py` (the resolver from summer TASK 2.3), the
  Setup/Start flow in `src/gui/routes/setup_bp.py` or `pipeline_bp.py`.
- **Definition of done:** first, confirm current behavior with a test that
  installs Compact-style (no bundled ffmpeg, PATH cleared) and either finds
  an existing warning before Start is clickable, or reproduces silent
  failure on first compression. If silent, add a check at Setup/Start time
  that surfaces a clear "FFmpeg not found" message before the operator hits
  a confusing failure mid-compression. A new `tests/` case pins whichever
  behavior is correct.
- **Dependency:** none. **Size:** S–M depending on what 3.12's investigation
  finds.

### 4.c — Fresh-install walkthrough findings, filed as fixes (planner 3.11)
- **Files:** whatever the top 3 friction points turn out to be — cannot be
  named in advance since 3.11 is itself the discovery step. File each as its
  own small task once found; do not treat this entry as "one task," treat it
  as "run the walkthrough, then create 1–3 follow-up tasks."
- **Definition of done:** a written note of every point of confusion from a
  clean-machine install → first-run Setup → one compression, with the worst
  three turned into filed, scoped fixes (which may land in this milestone or
  a later one depending on size).
- **Dependency:** none, can run anytime. **Size:** S (the walkthrough itself);
  its filed fixes are sized individually.

### 4.d — Docker install path: fix or document the `yolov8n.onnx` gitignore gap (planner 3.16)
- **STATUS (2026-09-22): fix (a) implemented, pending clean-clone verification.**
  `Dockerfile` now has a throwaway builder stage that installs CPU-only torch +
  ultralytics + onnx/onnxslim, lets ultralytics auto-download `yolov8n.pt`
  (it isn't committed either — also gitignored), exports to ONNX, and copies
  only the resulting `yolov8n.onnx` into the final slim image. `docs/getting-
  started.md` and `docs/build/onnx-models.md` were updated to describe it.
  Not yet marked done in the planner: per this task's own definition of done
  below, it needs to be verified by actually running `git clone` into a
  scratch directory and building from there, not by inspection. That
  verification is scheduled as the next step.
- **Files:** `Dockerfile` (does `COPY yolov8n.onnx ./`), `.gitignore`,
  `docs/getting-started.md`, `docs/build/onnx-models.md`.
- **Root cause already identified in `ROADMAP.md`**: `yolov8n.onnx` is
  gitignored and never fetched automatically; it only exists after running
  the one-time export in `docs/build/onnx-models.md`. Nobody has run
  `docker compose up --build` from a truly clean clone since this gitignore
  rule was added, so it has never been caught in practice.
- **Definition of done:** either (a) `docker compose up --build` succeeds
  from a genuinely clean checkout because the build now fetches/exports the
  model itself (preferred, closes the gap at the root), or (b) it still
  requires the manual export step but `docs/getting-started.md` says so
  plainly, with the exact command, before the Docker section's `docker
  compose up --build` line rather than after a user hits a failure. Verified
  by actually running `git clone` into a scratch directory and building from
  there — not by inspection.
- **Dependency:** none. **Size:** S–M.

---

## Milestone 5 — Webhooks and security hardening (Phase B/C)

### 5.a — Specify the webhook emitter (planner 3.9)
- **Files:** read `src/utils/push_notify.py::is_safe_push_url` in full; write
  the spec for a new `src/utils/event_webhook.py` that reuses that guard
  (same SSRF posture: block cloud metadata hosts, resolve-then-check DNS,
  refuse redirects and embedded credentials — see
  `docs/SYSTEM-ARCHITECTURE.md` section 5 for the exact guard shape already
  proven out for ntfy).
- **Definition of done:** a written spec (doc or detailed PR description)
  naming the function signatures, the timeout, and exactly which checks are
  reused vs. webhook-specific.
- **Dependency:** Milestone 0. **Size:** S.

### 5.b — Socket-server test harness for webhook delivery (planner 3.10)
- **Files:** new `tests/test_event_webhook.py`, styled on the existing
  `tests/test_push_notify.py` (a local socket server the test controls,
  asserting on what actually arrives).
- **Definition of done:** the harness exists and can assert on a delivered
  POST body/headers before any production webhook code is written (TDD
  order, matching the planner's own sequencing of 3.10 before 4.9).
- **Dependency:** 5.a. **Size:** S.

### 5.c — Implement `utils/event_webhook.py` with the SSRF guard (planner 4.9)
- **Files:** new `src/utils/event_webhook.py`.
- **Definition of done:** events POST to a configured URL, fire-and-forget,
  with a 2-second timeout; reuses `is_safe_push_url` (or an equivalent
  webhook-specific wrapper per the 5.a spec); the 5.b harness test passes
  against real code.
- **Dependency:** 5.a, 5.b. **Size:** M.

### 5.d — Webhook configuration UI + URL-rejection tests (planner 4.10 + 5.10)
- **Files:** `src/gui/templates/index.html` (new panel next to the existing
  push panel), `src/gui/routes/` (new config endpoint, likely alongside
  `push_bp.py`), `tests/test_event_webhook.py` (extend).
- **Definition of done:** off by default; a write-only secret field (never
  echoed back, matching the push token's existing write-only pattern in
  `ServerSettingsViewModel.kt`'s `pushToken` field for the mobile
  equivalent); metadata endpoints, redirects, and embedded credentials in
  the URL are all refused with a clear error, each covered by its own test
  case.
- **Dependency:** 5.c. **Size:** M.

### 5.e — Mobile credential storage review (planner 5.9)
- **Files:** `mobile/android/app/src/main/java/org/svcs/mobile/data/TokenStore.kt`.
- **Definition of done:** a written finding on whether a failed decrypt
  (Keystore key invalidated, corrupted blob, etc.) fails closed (forces
  re-pairing) or silently returns a stale/wrong credential. If it fails
  open, file that as its own fix task with a test forcing a decrypt failure
  and asserting the app does not proceed with a stale token.
- **Dependency:** Milestone 0, Milestone 1 (pairing fix should land first so
  this review isn't reviewing code that's about to change underneath it).
  **Size:** S.

### 5.f — Fix the MediaMTX zip-slip / no-checksum gap `[verified gap, not in a planning doc — see 0.6]`
- **Files:** `src/utils/rtsp_server.py::_do_download()`.
- **Definition of done:** two independent fixes, both required: (1) before
  calling `extractall`, validate every archive member's resolved path stays
  under `dest_dir` (reject any entry containing `..` path segments or
  resolving outside the destination — the standard zip-slip mitigation;
  Python's `zipfile`/`tarfile` do not do this for you), and (2) verify a
  SHA-256 checksum of the downloaded archive against a pinned per-version
  value (pin one hash per `MEDIAMTX_VERSION`/platform combination as a
  constant near `MEDIAMTX_VERSION`) before extracting, refusing to proceed
  on a mismatch. Add `tests/test_rtsp_server.py` (new file) with a
  deliberately malicious fixture archive (a zip with a `../evil` entry) that
  currently would escape `dest_dir` and, after the fix, is rejected; and a
  case asserting a checksum mismatch is rejected before extraction is
  attempted. Update the `docs/BLOCKERS.md` entry from Milestone 0 task 0.d
  to closed.
- **Dependency:** Milestone 0 (0.d should exist first so this task shows as
  closing a documented item). **Size:** M.

### 5.g — Push endpoint registration + security review (planner 6.9 + 6.10)
- **Files:** `src/gui/routes/tokens_bp.py` and/or `push_bp.py` (new
  endpoint for a device to register a push endpoint), `src/gui/device_tokens.py`.
- **Definition of done:** device tokens can carry a registered push
  endpoint for the future native-push path (Milestone 7); a security review
  (and accompanying test) confirms one device cannot register or read
  another device's endpoint — same per-device isolation model as the
  existing bearer-token scheme described in
  `docs/SYSTEM-ARCHITECTURE.md` section 4.
- **Dependency:** none beyond Milestone 0. **Size:** M.

### 5.h — External pentest and ingest/upload fuzzing (planner 3.14 + 3.15)
- **Files:** none pre-specified; findings go into `docs/BLOCKERS.md` with a
  severity rating, per the planner's own instruction.
- **Definition of done — explicitly not CI-automatable**, matching
  `docs/plans/BLOCKERS.md`'s own June 2026 assessment of these same two
  items ("not a pytest-coverable, CI-safe activity... owner runs..."): an
  agent can prepare the fuzzing corpus/harness (malformed containers,
  truncated files, oversized headers) and run it locally, filing a clean
  rejection or a crash report per file tried, but the external network
  pentest needs a live bound instance and a real external vantage point,
  which this roadmap cannot assert an agent has. Do the fuzzing half in
  full; flag the pentest half back to the human owner rather than marking it
  done on a partial substitute.
- **Dependency:** none. **Size:** M (fuzzing harness), owner-gated
  (pentest).

---

## Milestone 6 — Multi-camera streaming (Phase B/C)

### 6.a — Regression tests pinning current single-camera HLS behavior (planner 5.4)
- **Files:** new/extended `tests/test_hls_streaming.py`.
- **Definition of done:** the existing single-global-stream-slot behavior in
  `src/gui/services/hls_runner.py` (and `hls_bp.py`) is pinned by tests
  before it changes, so the 6.c refactor has a regression net.
- **Dependency:** Milestone 0. **Size:** S.

### 6.b — Per-camera HLS registry design (planner 5.3)
- **Files:** design note covering `src/gui/services/hls_runner.py`,
  `src/gui/routes/hls_bp.py`.
- **Definition of done:** a written design identifying and scoping the
  single global stream slot that needs to become per-camera.
- **Dependency:** 6.a. **Size:** S.

### 6.c — Implement the per-camera HLS registry (planner 6.3)
- **Files:** `src/gui/services/hls_runner.py`, `src/gui/routes/hls_bp.py`.
- **Definition of done:** two cameras stream simultaneously without one
  blocking the other, verified by a test starting two HLS sessions
  concurrently and asserting both produce independent, non-interfering
  playlists/segments.
- **Dependency:** 6.b. **Size:** L.

### 6.d — Per-stream idle watchdog (planner 6.4)
- **Files:** the watchdog logic in `hls_runner.py`.
- **Definition of done:** each stream is reaped independently on
  abandonment; a test with two streams, one abandoned and one active,
  confirms only the abandoned one is reaped.
- **Dependency:** 6.c. **Size:** S.

### 6.e — Multi-camera UI on the desktop dashboard (planner outline, week 7)
- **Files:** `src/gui/templates/index.html`.
- **Definition of done:** the dashboard can display and control more than
  one camera's live/HLS view at once, backed by 6.c/6.d.
- **Dependency:** 6.d. **Size:** L.

---

## Milestone 7 — Native push and semantic search (Phase C, M3 target)

### 7.a — UnifiedPush distributor registration research (planner 6.2)
- **Files:** design doc.
- **Definition of done:** a written design for native push replacing the
  separate ntfy app, covering distributor registration flow.
- **Dependency:** Milestone 1 (native push needs a credential that survives
  a restart, per the planner's own dependency table: "6.2, week 7 native
  push | blocked by 4.2 pairing fix"). **Size:** S.

### 7.b — Native UnifiedPush client implementation (planner outline, week 7)
- **Files:** new Kotlin under `mobile/android/app/src/main/java/org/svcs/mobile/`.
- **Definition of done:** the app can receive a push via UnifiedPush without
  the separate ntfy app installed, alongside (not necessarily replacing
  immediately) the existing ntfy path.
- **Dependency:** 7.a. **Size:** L.

### 7.c — Push endpoint fan-out on the server (planner outline, week 8)
- **Files:** `src/gui/routes/push_bp.py` or a new module, building on 5.g's
  per-device endpoint registration.
- **Definition of done:** the server fans an event out to every registered
  device push endpoint, not just a single configured ntfy topic.
- **Dependency:** 7.b, 5.g. **Size:** M.

### 7.d — Semantic search research document (planner 6.5)
- **Files:** new `docs/research/RESEARCH-SEMANTIC-SEARCH.md`.
- **Definition of done:** covers model choice, storage, and the offline
  story (this is a local-first tool per `docs/plans/BLOCKERS.md`'s stated
  posture — no RBAC, no built-in cloud dependency — so the model choice
  should respect that).
- **Dependency:** none. **Size:** S.

### 7.e — Semantic search skeleton with a stub embedder (planner 6.6)
- **Files:** new module under `src/pipeline/` or `src/utils/`, an opt-in
  extra in `pyproject.toml`.
- **Definition of done:** the skeleton is opt-in and no model is downloaded
  in CI; a stub embedder lets the interface be tested without network
  access.
- **Dependency:** 7.d. **Size:** M.

### 7.f — Semantic search integration (planner outline, week 7)
- **Files:** builds on 7.e, wired into `queries_bp.py` / the desktop query
  UI from Milestone 3 task 3.f.
- **Definition of done:** semantic search is a selectable mode alongside the
  existing full-text/multi-tag search, with a real (non-stub) embedder
  behind the opt-in extra.
- **Dependency:** 7.e, 3.f. **Size:** L.

---

## Milestone 8 — Regression, polish, and release 1.0 (Phase D)

### 8.a — Investigate the possible race in `test_live_save_daemon_compresses_and_dedups`
- **Files:** `tests/test_autocompress.py` (line ~316), `src/gui/services/`
  autocompress daemon it exercises.
- **Definition of done:** run the test repeatedly (e.g. `pytest -q
  tests/test_autocompress.py::test_live_save_daemon_compresses_and_dedups
  --count=20` with `pytest-repeat`, or a shell loop) to try to reproduce a
  flake; if reproduced, root-cause and fix the race (likely a polling/timing
  assumption in the 120-second wait loop or the daemon's own file-stability
  check); if not reproduced after a real effort, document that in
  `docs/BLOCKERS.md` with the repro attempt count so "unconfirmed" becomes
  "investigated, not reproduced" rather than sitting open indefinitely.
- **Dependency:** none, but sensible to do once the desktop-side milestones
  above have landed so this isn't investigating a moving target.
  **Size:** M.

### 8.b — Mobile screen completeness sweep (planner outline, week 8)
- **Files:** all `mobile/android/app/src/main/java/org/svcs/mobile/ui/*Screen.kt`.
- **Definition of done:** every screen reachable from the app's navigation
  is functional end to end against a real server; gaps filed as their own
  tasks.
- **Dependency:** Milestones 1, 2, 7. **Size:** M.

### 8.c — Mobile polish: METRICS tab decision, preview scope, thumbnail policy verification (planner outline, week 9)
- **Files:** `MetricsScreen.kt`/`MetricsViewModel.kt`, preview/thumbnail
  handling per `docs/SYSTEM-ARCHITECTURE.md` section 4's stated policy
  (thumbnails in-memory only, preview scoped to already-compressed
  mp4/mkv/mov/webm).
- **Definition of done:** a decision (keep/cut/redesign) on the METRICS tab
  is made and implemented; a verification pass confirms the thumbnail policy
  actually matches what's documented (memory-only, never written to disk).
- **Dependency:** 8.b. **Size:** M.

### 8.d — Full regression across desktop and mobile (planner outline, week 10)
- **Files:** whole repo.
- **Definition of done:** `pytest -q` full suite green (or documented,
  reviewed skips only) on the desktop side; `gradlew testDebugUnitTest` and
  `connectedDebugAndroidTest` green on mobile. This is the gate before any
  release work per the planner's own dependency table ("Week 12 release |
  blocked by | Week 10 regression").
- **Dependency:** every prior milestone. **Size:** L.

### 8.e — Rebuild the stale v2.2.0-beta desktop artifact from current `main`
- **Files:** none (build-only task), per `docs/BLOCKERS.md`'s open item
  "v2.2.0-beta desktop exe is stale relative to `main`."
- **Definition of done:** `installer\build.ps1 -Installer` run against
  current `main` (post-Milestone-0-merge) produces a fresh
  `SVCS-Setup-*.exe` reflecting the chunked resumable upload, zone/behavior
  events, job registry, mobile push, and the filename-sanitization fix — all
  landed on `main` after the 2026-08-17 build currently attached to the
  GitHub release. Signing (`-Sign`) remains owner-gated on the SignPath.io
  cert per `docs/BLOCKERS.md`; build unsigned if the cert still isn't ready
  by this point.
- **Dependency:** 8.d (don't publish an artifact from an unregressed tree).
  **Size:** S (mechanical, but requires a Windows machine with the project
  venv — call this out if the executing agent's environment can't do it).

### 8.f — Sponsor demo build + deployment packaging review for COTS hardware (planner outline, week 11)
- **Files:** build/installer docs, `docs/build/deployment_packaging.md`.
- **Definition of done:** a build suitable for a sponsor demo exists; a
  written review of packaging fit for government COTS hardware is produced
  (owners Jorge/Victor per the planner).
- **Dependency:** 8.e. **Size:** M.

### 8.g — Release 1.0: version bump, signed installer, signed APK, checksums, release notes (planner outline, week 12)
- **Files:** `pyproject.toml`, `mobile/android/app/build.gradle.kts`,
  `docs/RELEASE-CHECKLIST.md` (follow it exactly), a new
  `docs/release-notes-v<version>-beta.md` or the 1.0 equivalent,
  `dist/SHA256SUMS.txt`.
- **Definition of done:** follow `docs/RELEASE-CHECKLIST.md` step by step;
  signing both the desktop exe and the APK remains gated on certificates
  the owner must obtain (Windows: SignPath.io per `docs/BLOCKERS.md`;
  Android APK signing has its own separate keystore requirement not yet
  discussed in the docs this roadmap reviewed — flag that gap to the owner
  explicitly if it's still unresolved at this point). Tagging and
  publishing the GitHub Release remains the owner's action alone, per the
  checklist's own step 6.
- **Dependency:** 8.d, 8.f. **Size:** M (agent-doable steps) + owner-gated
  (signing, publish).

### 8.h — Final report writing + demo rehearsal (planner outline, weeks 13–14)
- **Files:** `docs/project-records/final_report.md` or a new final report
  for this semester, consolidating measured results (including 3.g's zone
  compression numbers).
- **Definition of done:** a submitted final report and a rehearsed demo
  using the 1.0 release build, not a development build.
- **Dependency:** 8.g. **Size:** L, and largely a writing/coordination task
  rather than a code task.

---

## Summary table

| Milestone | Theme | Task count | Blocking? |
|---|---|---|---|
| 0 | Branch reconciliation + doc hygiene | 4 | Blocks all mobile work |
| 1 | Mobile test infra + pairing fix | 5 | Blocks 2, 7, 8b/c |
| 2 | Mobile upload reliability | 2 | Blocks 8b |
| 3 | Desktop EVENTS/zones parity | 7 | Feeds 3.g, 7.f |
| 4 | Desktop onboarding hardening | 4 | Independent, parallelizable |
| 5 | Webhooks + security hardening | 8 | Feeds 7c |
| 6 | Multi-camera streaming | 5 | Independent, parallelizable |
| 7 | Native push + semantic search | 6 | Depends on 1, 3, 5g |
| 8 | Regression, polish, release 1.0 | 8 | Terminal; depends on nearly everything |

49 tasks total across 9 milestones. Milestones 4 and 6 have no hard
dependency on Milestones 1–3 and can be worked in parallel by a second agent
or contributor if the team wants to parallelize; everything else follows the
ordering above.

---

Author: written by an AI planning agent at the request of Kheiven D'Haiti
(repo owner), 2026-09-21, from `ROADMAP.md`,
`docs/project-records/PLANNER-FALL-2026.md`, `week3.local.json`,
`docs/BLOCKERS.md`, `docs/plans/BLOCKERS.md`,
`docs/RELEASE-CHECKLIST.md`, `docs/release-notes-v2.2.0-beta.md`,
`docs/SYSTEM-ARCHITECTURE.md`, and direct inspection of the code and git
history on `main`, `mobile`, and `app` as of that date. No application code
was written or modified to produce this document.
