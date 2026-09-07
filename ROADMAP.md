# SVCS Roadmap: Fall 2026

**Course:** EGN4950C Senior Design (ED2), Group 16
**Project:** Open Source Selective Video Compression for Static Surveillance Cameras
**Sponsor:** Defense Innovation Unit (DIU) / NIWC Pacific, Cody Hayashi
**Semester:** August 31, 2026 to December 6, 2026 (14 weeks)
**Built by:** Kheiven D'Haiti, 2026-09-07

This is the active roadmap for the current semester. For what the team already
finished in Spring 2026, see `docs/archive/ROADMAP-SPRING-2026.md`. For the
week-by-week source this roadmap is drawn from, including the full 14-week
outline and the task IDs used in the MS Teams Planner, see
`docs/project-records/PLANNER-FALL-2026.md` and its companion import file
`docs/project-records/PLANNER-FALL-2026.csv`. The planner is filled in about
four to six weeks ahead on a rolling basis, so this roadmap will get more
detailed on weeks 7 through 14 as the semester goes on. This file is the one
to read first; the planner is the one to keep current week to week.

---

## The team

Jump straight to a person's section for exactly what they are working on this
semester.

- [Kheiven D'Haiti](#kheiven-dhaiti): mobile app completion and test infrastructure
- [Jorge Sanchez](#jorge-sanchez): ingest, uploads, and multi-camera streaming
- [Ashleyn Montano](#ashleyn-montano): event surfacing and search
- [Riley Roberts](#riley-roberts): zone editor and compression measurement
- [Victor De Souza Teixeira](#victor-de-souza-teixeira): webhook security and credential review

Sponsor contacts stay the same as Spring: Cody Hayashi (primary sponsor) and
Geena Wann-Kung (project coordinator), NIWC Pacific.

---

## Where this semester picks up

Spring 2026 delivered a working desktop pipeline (background subtraction,
compression modes, encryption, the web dashboard). Over the summer break the
desktop became a distributable product (a Windows installer and a Docker
image) and grew an Android companion app. All of that summer work is written
up in `docs/CHANGES-SUMMER-2026.md`, which every team member should read in
week 1 before picking up their tasks below.

Because of that, the fall semester is not "build the project" again. It is:
finish the mobile app to the point where it is trustworthy, expose the zone
and event system that already exists on the backend through both the desktop
and mobile front ends, and harden the whole thing (security, regression
testing, packaging) into something the sponsor can actually deploy and the
team can demo and hand off in December.

Ownership follows the subsystem each person already held in the spring, so
nobody is starting cold on an unfamiliar part of the codebase:

| Member | Subsystem owned in spring | Fall focus |
|---|---|---|
| Kheiven D'Haiti | Pipeline, background subtraction, YOLO gate, dashboard | Mobile app completion and test infrastructure |
| Jorge Sanchez | ROI encoder, watchfolder, MultiFrameSource | Ingest, uploads, multi-camera streaming |
| Ashleyn Montano | Metadata database, multi-type queries | Event surfacing and search |
| Riley Roberts | Compression modes 2 and 3 | Zone editor and compression measurement |
| Victor De Souza Teixeira | AES-256-GCM encryption, enhancement | Webhook security and credential review |

## Semester phases

| Phase | Weeks | Dates | Goal | Milestone |
|---|---|---|---|---|
| A. Foundations | 1 to 3 | Aug 31 to Sep 20 | Planning, revised proposal, mobile test harness, fix the pairing blocker | M1: mobile changes verifiable without a human holding the phone |
| B. Feature completion | 4 to 7 | Sep 21 to Oct 18 | Desktop zone and event UI, uploads that survive app death, multi-camera streaming | M2: desktop and mobile feature parity on zones and events |
| C. Advanced work | 8 to 11 | Oct 19 to Nov 15 | Native push, semantic search, measured compression results | M3: all outstanding tracks closed |
| D. Hardening and delivery | 12 to 14 | Nov 16 to Dec 6 | Regression, release, final report, sponsor demo | M4: 1.0 release and final demo |

## Fixed course deadlines

| Deliverable | Due | Owner |
|---|---|---|
| Module 1 Revised Project Proposal | September 13, 2026 | All, coordinated by Kheiven |
| Weekly progress report | Every Sunday, 11:59 PM | All, individually |
| Final report | Early December, date TBD | All |
| Final demonstration | Early December, date TBD | All |

## A documentation accuracy check worth knowing about

While building this roadmap, `docs/getting-started.md`'s Docker section was
checked against `docs/BUILD-AND-RELEASE.md`, `docs/build/deployment_packaging.md`,
the actual `Dockerfile`, and `docker-compose.yml`. The command itself is
right: `SVCS_DASHBOARD_PASSWORD='a-long-passphrase' docker compose up --build`
does build and serve the dashboard on `http://localhost:5000` with the
`operator` login, matching what the compose file actually wires up.

What none of the docs say is that the build will fail on a clean checkout
without an extra step first. The `Dockerfile` does `COPY yolov8n.onnx ./`, but
`yolov8n.onnx` is gitignored and is not fetched automatically anywhere in the
build. It only exists after someone runs the one-time export command in
`docs/build/onnx-models.md` (`uv sync --extra onnx-export` then the ultralytics
export command) and drops the resulting file at the repo root. Nobody on the
team has actually run `docker compose up --build` from a fresh clone since
that gitignore rule and the model export step were written, so this has never
been caught. This is exactly the kind of thing task 3.16 below exists to
confirm and, if it reproduces, fix by either documenting the prerequisite
plainly in `docs/getting-started.md` or teaching the Docker build to fetch the
model itself.

---

## Kheiven D'Haiti

Fall focus: get the mobile app to a state where changes can be trusted without
a person manually holding a phone, fix the pairing defect that blocks
everything downstream of it (native push included), and close the Docker
documentation gap above.

### Week 2 (Sep 7 to Sep 13)

| ID | Task | Outcome |
|---|---|---|
| 2.1 | Write the summer changes document for the team | `docs/CHANGES-SUMMER-2026.md` committed and pushed |
| 2.2 | Verify push status on all branches and commit stranded documentation | Zero unpushed commits; `RESEARCH.md`, `SECURITY.md`, `PROJECT-HISTORY.md` committed |
| 2.3 | Revised proposal: update the system design section and functional diagrams | Current architecture diagram including the mobile client, marked in red per the assignment |

### Week 3 (Sep 14 to Sep 20)

Milestone M1 target for the semester: mobile changes verifiable without a
human holding the phone.

| ID | Task | Outcome |
|---|---|---|
| 3.1 | Make `SvcsApi` fakeable and add JVM unit tests for the view models | `gradlew testDebugUnitTest` covers pairing, library, events, and home view models |
| 3.2 | Add a debug build variant with HTTP logging for diagnosis | A failing request shows its reason in logcat instead of being a mystery on a minified build |
| 3.11 | Fresh-install walkthrough (with the rest of the team): install `SVCS-Setup.exe`, complete first-run Setup, run one compression, all without opening the source code | A written note of every point of confusion or friction, with the worst three filed as fixes |
| 3.16 | Verify the Docker install path end to end on a fresh clone, then fix `docs/getting-started.md` | `docker compose up --build` either succeeds from a clean checkout, or the missing `yolov8n.onnx` prerequisite is documented plainly (or the build fetches it automatically); the getting-started guide reflects whichever is true |

### Week 4 (Sep 21 to Sep 27)

| ID | Task | Outcome |
|---|---|---|
| 4.1 | Diagnose the mobile pairing persistence defect | Root cause proven by a failing unit test, not by inspection |
| 4.2 | Fix pairing persistence and prove it with an instrumented test | A phone that pairs once stays paired across restarts and app updates |

### Week 5 (Sep 28 to Oct 4)

| ID | Task | Outcome |
|---|---|---|
| 5.1 | Build `scripts/verify_mobile.ps1` end to end | Build, install, launch, assert, exit non-zero on failure, no human input |
| 5.2 | Design and produce the real Android launcher icon | Adaptive icon at every density, replacing the template robot |

### Week 6 (Oct 5 to Oct 11)

Milestone M2 target: desktop and mobile feature parity on zones and events.

| ID | Task | Outcome |
|---|---|---|
| 6.1 | Add instrumented tests for the pairing and settings flows | `gradlew connectedDebugAndroidTest` green on the physical device |
| 6.2 | Research the UnifiedPush distributor registration flow | Written design for native push replacing the separate ntfy app |

### Weeks 7 to 14 (outline, detail added on the rolling planner)

| Week | Focus |
|---|---|
| 7 | Native UnifiedPush client implementation |
| 8 | Push endpoint fan-out on the server |
| 9 | Mobile polish: METRICS tab decision, preview scope, thumbnail policy verification |
| 10 | Full regression across desktop and mobile |
| 12 | Release 1.0: version bump, signed installer, signed APK, checksums, release notes |

---

## Jorge Sanchez

Fall focus: get uploads to survive the app being killed mid-transfer, and take
the streaming layer from one camera to several running at once.

### Week 2 (Sep 7 to Sep 13)

| ID | Task | Outcome |
|---|---|---|
| 2.4 | Revised proposal: update the requirements list with mobile requirements | Requirements covering the phone client, added in red |

### Week 3 (Sep 14 to Sep 20)

| ID | Task | Outcome |
|---|---|---|
| 3.3 | Investigate the WorkManager API and draft the upload worker design | Written design for moving the chunked upload out of `viewModelScope` |
| 3.4 | Audit the resumable upload protocol for resume correctness | Confirmation that `/api/upload/status` returns an offset a worker can resume from |
| 3.11 | Fresh-install walkthrough (with the rest of the team) | Written note of every point of confusion or friction |

### Week 4 (Sep 21 to Sep 27)

| ID | Task | Outcome |
|---|---|---|
| 4.3 | Implement the upload `CoroutineWorker` with a foreground notification | Upload runs outside the view model scope with visible progress |
| 4.4 | Test upload survival: force-stop mid-transfer and confirm resume | Transfer resumes from the server-reported offset and completes |

### Week 5 (Sep 28 to Oct 4)

| ID | Task | Outcome |
|---|---|---|
| 5.3 | Begin the per-camera HLS registry refactor | Design written; the single global stream slot is identified and scoped |
| 5.4 | Add regression tests for the existing single-camera HLS behavior | Existing behavior pinned before the refactor changes it |

### Week 6 (Oct 5 to Oct 11)

| ID | Task | Outcome |
|---|---|---|
| 6.3 | Implement the per-camera HLS registry | Two cameras stream simultaneously without one blocking the other |
| 6.4 | Update the HLS idle watchdog for multiple streams | Each stream reaped independently on abandonment |

### Weeks 7 to 14 (outline)

| Week | Focus |
|---|---|
| 7 | Multi-camera UI on the desktop dashboard |
| 11 | Deployment packaging review for government COTS hardware, alongside Victor |

---

## Ashleyn Montano

Fall focus: surface the events the pipeline already generates through a real
desktop UI, then extend search past exact tag matching.

### Week 2 (Sep 7 to Sep 13)

| ID | Task | Outcome |
|---|---|---|
| 2.5 | Revised proposal: update the literature survey and reference list | Citations formatted consistently, new sources from the summer research documents |

### Week 3 (Sep 14 to Sep 20)

| ID | Task | Outcome |
|---|---|---|
| 3.5 | Build the desktop EVENTS panel, read-only table | Newest-first table on the TOOLS tab from `/api/events/recent` |
| 3.6 | Add the empty state and ten second auto-refresh to the EVENTS panel | Panel refreshes while visible, stops when hidden, tells the operator to draw zones first |
| 3.13 | Add a folder-browse button to the Setup destination field, reusing the Library folder-browser modal | Setup no longer requires typing a raw folder path from memory |

### Week 4 (Sep 21 to Sep 27)

| ID | Task | Outcome |
|---|---|---|
| 4.5 | Wire desktop event toasts to the existing SSE stream | An `EVENT` line raises exactly one toast; other log lines raise none |
| 4.6 | Write browser tests for the EVENTS panel | Rows render from a seeded events file; empty state verified |

### Week 5 (Sep 28 to Oct 4)

| ID | Task | Outcome |
|---|---|---|
| 5.5 | Extend the query archive sidebar with full-text and multi-tag search | Desktop query UI matches the multi-type CLI capability |
| 5.6 | Write an integration test for event and query interaction | Pipeline run produces events that the query interface can retrieve |

### Week 6 (Oct 5 to Oct 11)

| ID | Task | Outcome |
|---|---|---|
| 6.5 | Write the semantic search research document | `docs/research/RESEARCH-SEMANTIC-SEARCH.md` covering model choice, storage, offline story |
| 6.6 | Build the semantic search skeleton with a stub embedder | Opt-in extra; no model downloaded in CI |

### Weeks 7 to 14 (outline)

| Week | Focus |
|---|---|
| 7 | Semantic search integration |
| 9 | Mobile polish pass alongside the rest of the team |

---

## Riley Roberts

Fall focus: build the zone editor the mobile app already has an equivalent of
on the desktop, and turn the "zones save bandwidth" claim into a measured
number for the final report.

### Week 2 (Sep 7 to Sep 13)

| ID | Task | Outcome |
|---|---|---|
| 2.6 | Revised proposal: build the Gantt chart from this planner | Gantt covering all 14 weeks with owners, dependencies, and milestones |

### Week 3 (Sep 14 to Sep 20)

| ID | Task | Outcome |
|---|---|---|
| 3.7 | Add the `GET /api/zones/frame` route returning a still frame | JPEG still for a camera, black placeholder when no thumbnail exists, all three route guards updated |
| 3.8 | Draft the zone editor canvas layout | Toolbar and canvas markup matching the phone editor |
| 3.12 | Test the Compact install path with no FFmpeg on PATH | Confirmation of whether the app warns before Start is clickable, or fails silently on the first compression, plus a fix if it is silent |

### Week 4 (Sep 21 to Sep 27)

| ID | Task | Outcome |
|---|---|---|
| 4.7 | Implement drag-to-draw for exclude rectangles and crossing lines | Zones round-trip through POST and GET with normalized coordinates intact |
| 4.8 | Implement loiter zones and the SAVE and CLEAR actions | Full toolbar working, banner states that changes apply to the next run |

### Week 5 (Sep 28 to Oct 4)

| ID | Task | Outcome |
|---|---|---|
| 5.7 | Add the camera id datalist from library folder labels | Zone editor offers real camera ids rather than free text |
| 5.8 | Browser-verify the zone editor against a real backdrop frame | Screenshot evidence of a zone drawn over actual footage |

### Week 6 (Oct 5 to Oct 11)

| ID | Task | Outcome |
|---|---|---|
| 6.7 | Run the CDnet corpus with and without exclude zones | Measured file size difference from zone masking |
| 6.8 | Write up the zone compression benefit with numbers | Table for the final report; the claim is either confirmed or corrected |

### Weeks 7 to 14 (outline)

| Week | Focus |
|---|---|
| 12 | Release 1.0 work alongside Kheiven |

---

## Victor De Souza Teixeira

Fall focus: give the pipeline a safe way to notify the outside world when an
event happens, and keep pushing on the security side (credential storage,
penetration testing, fuzzing) that started in the spring with encryption.

### Week 2 (Sep 7 to Sep 13)

| ID | Task | Outcome |
|---|---|---|
| 2.7 | Revised proposal: organizational chart and completed-tasks list | Org chart naming the team leader; list of tasks completed to date |

### Week 3 (Sep 14 to Sep 20)

Note from the planner: this week is Victor's heaviest (four tasks against
everyone else's two to three). If it proves too much, 3.9 and 3.10 move to
week 4 rather than rushing the security testing below.

| ID | Task | Outcome |
|---|---|---|
| 3.9 | Read `push_notify.is_safe_push_url` and specify the webhook emitter | Written specification for `utils/event_webhook.py` reusing the existing guard |
| 3.10 | Write the socket-server test harness for webhook delivery | Test fixture in the style of `tests/test_push_notify.py` |
| 3.14 | External network penetration test against a running SVCS instance | Written findings against the threat model in `docs/SECURITY.md`; anything found gets a severity-rated entry in `docs/plans/BLOCKERS.md` |
| 3.15 | Fuzz the video-ingest and upload path with malformed media | A clean rejection or a filed crash report for each malformed file tried |

### Week 4 (Sep 21 to Sep 27)

| ID | Task | Outcome |
|---|---|---|
| 4.9 | Implement `utils/event_webhook.py` with the SSRF guard | Events post to a configured URL, fire and forget, two second timeout |
| 4.10 | Add the webhook configuration UI next to the push panel | Off by default, write-only secret field, refuses metadata endpoints |

### Week 5 (Sep 28 to Oct 4)

| ID | Task | Outcome |
|---|---|---|
| 5.9 | Review the mobile credential storage path end to end | Written finding on whether a failed decrypt fails closed or returns a stale credential |
| 5.10 | Write tests for webhook URL rejection cases | Metadata endpoints, redirects, and embedded credentials all refused |

### Week 6 (Oct 5 to Oct 11)

| ID | Task | Outcome |
|---|---|---|
| 6.9 | Add the server endpoint for registering a push endpoint per device | Device tokens can carry a push endpoint for the native path |
| 6.10 | Security review of the new endpoint registration | Confirmation that one device cannot register or read another device's endpoint |

### Weeks 7 to 14 (outline)

| Week | Focus |
|---|---|
| 8 | Push endpoint fan-out on the server, alongside Kheiven |
| 11 | Deployment packaging review for government COTS hardware, alongside Jorge |

---

## Dependencies

| Task | Blocked by | Why |
|---|---|---|
| 4.1, 4.2 pairing fix | 3.1, 3.2 test harness and debug build | The defect cannot be diagnosed reliably on a minified build without tests |
| 6.2, week 7 native push | 4.2 pairing fix | Native push needs a credential that survives a restart |
| 4.3, 4.4 upload worker | 3.3, 3.4 design and protocol audit | Resume offset behavior must be confirmed before the worker is written |
| 4.7, 4.8 zone drawing | 3.7 frame route | Nothing to draw on without a backdrop frame |
| 5.8 browser verification | 4.7, 4.8 zone drawing | Cannot verify what does not exist |
| 6.7, 6.8 zone measurement | 4.7, 4.8 zone drawing | Zones must be drawable before their effect can be measured |
| Week 12 release | Week 10 regression | Do not ship what has not been regression tested |
| Week 14 demo | Week 12 release | Demo the release build, not a development build |

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Mobile pairing defect proves deeper than expected | Blocks native push and every credential-dependent feature | Week 3 builds the harness first so week 4 has real diagnostics; fallback is to bypass encrypted storage for a plaintext token on private networks only, with a written security justification |
| Four members ramping up on a codebase that changed substantially | Slow first three weeks | `docs/CHANGES-SUMMER-2026.md` written specifically for this; week 1 is explicitly a ramp-up week |
| Mobile work concentrated on one member | Single point of failure | Weeks 3 to 5 deliberately give Jorge and Victor mobile-adjacent tasks so knowledge spreads |
| No Android CI | Regressions found late | `scripts/verify_mobile.ps1` in week 5 gives a repeatable local check |
| Sponsor availability | Demo requirements drift | Request a check-in during phase B rather than waiting for the final demo |
| Docker install untested from a clean checkout | A sponsor or new contributor following `docs/getting-started.md` hits a build failure with no explanation | Task 3.16 above tests this directly and fixes whichever side (docs or build) is wrong |

## Keeping this roadmap and the planner in sync

This file gives each person their own section for the whole semester as it is
currently known. `docs/project-records/PLANNER-FALL-2026.md` and
`docs/project-records/PLANNER-FALL-2026.csv` are the week-by-week detail that
actually gets imported into MS Teams and updated as weeks are completed or
tasks slip. When a task here changes owner, scope, or week, update the
planner first (it is the one graded against the weekly report) and then
bring this file back in sync, rather than the other way around. Weeks 7
through 14 stay at outline level here until the planner fills them in on its
rolling four-to-six-week window; expand this roadmap's outline sections to
full tables at that point rather than leaving them thin.

---

Author: Bloodawn (KheivenD), 2026-09-07.
