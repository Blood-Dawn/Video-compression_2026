# SVCS fall 2026 semester planner

**Course:** EGN4950C Senior Design (ED2), Group 16
**Project:** Open Source Selective Video Compression for Static Surveillance Cameras
**Sponsor:** Defense Innovation Unit (DIU) / NIWC Pacific, Cody Hayashi
**Planner period:** August 31, 2026 to December 6, 2026 (14 weeks)
**Built:** September 2026 by Kheiven D'Haiti

This is the master plan for the semester. It is the source for the MS Teams
Planner, for the WBS and Gantt in the revised proposal, and for the weekly
progress reports. Every week has two tasks minimum per member, because that is
what the weekly report rubric requires.

## How this plan was built

The spring semester delivered a working desktop pipeline. Over the summer break
the desktop became a distributable product and grew an Android companion app
(documented in `docs/CHANGES-SUMMER-2026.md`). The remaining work is therefore
not "build the project"; it is finish the mobile port, expose the zone and event
system on the desktop, and harden the whole thing into something a sponsor can
deploy.

The technical backlog comes from the open items in `docs/CHANGES-SUMMER-2026.md`
and `docs/BLOCKERS.md`. Ownership follows the
subsystems each member already held in the spring, so nobody starts from zero:

| Member | Subsystem owned in spring | Fall focus |
|---|---|---|
| Kheiven D'Haiti | Pipeline, background subtraction, YOLO gate, dashboard | Mobile app completion and test infrastructure |
| Jorge Sanchez | ROI encoder, watchfolder, MultiFrameSource | Ingest, uploads, multi-camera streaming |
| Ashleyn Montano | Metadata database, multi-type queries | Event surfacing and search |
| Riley Roberts | Compression modes 2 and 3 | Zone editor and compression measurement |
| Victor De Souza Teixeira | AES-256-GCM encryption, enhancement | Webhook security and credential review |

Table 1. Ownership map, spring to fall.

## Semester phases

| Phase | Weeks | Dates | Goal | Milestone |
|---|---|---|---|---|
| A. Foundations | 1 to 3 | Aug 31 to Sep 20 | Planning, revised proposal, mobile test harness, fix the pairing blocker | M1: mobile changes verifiable without a human holding the phone |
| B. Feature completion | 4 to 7 | Sep 21 to Oct 18 | Desktop zone and event UI, uploads that survive app death, multi-camera streaming | M2: desktop and mobile feature parity on zones and events |
| C. Advanced work | 8 to 11 | Oct 19 to Nov 15 | Native push, semantic search, measured compression results | M3: all R5 and R6 tracks closed |
| D. Hardening and delivery | 12 to 14 | Nov 16 to Dec 6 | Regression, release, final report, sponsor demo | M4: 1.0 release and final demo |

Table 2. Phase breakdown with milestones.

## Fixed course deadlines

| Deliverable | Due | Owner |
|---|---|---|
| Module 1 Revised Project Proposal | September 13, 2026 | All, coordinated by Kheiven |
| Weekly progress report | Every Sunday, 11:59 PM | All, individually |
| Final report | Early December, date TBD | All |
| Final demonstration | Early December, date TBD | All |

Table 3. Course deliverables.

---

## Week-by-week plan

Task IDs are `<week>.<sequence>`. Every task has a start, an end, an owner, an
outcome, and a way to tell whether it is done. Tasks are sized to a few hours
each, per the course guidance.

### Week 1: August 31 to September 6 (complete)

| ID | Task | Owner | Outcome | Status |
|---|---|---|---|---|
| 1.1 | Review the summer build and audit repository state | Kheiven | Written account of what changed and confirmation that nothing is stranded locally | Complete Sep 6 |
| 1.2 | Build the fall semester planner | Kheiven | This document; MS Teams Planner populated four weeks ahead | Complete Sep 6 |
| 1.3 | Review my spring contributions and the current state of the ingest subsystem | Jorge | Written account of what I own and how it changed | Complete Sep 5 |
| 1.4 | Team review session on the summer build and fall ownership | Jorge | Agreement on which fall tasks I take | Complete Sep 6 |
| 1.5 | Review my spring contributions and the current state of the metadata subsystem | Ashleyn | Written account of what I own and how it changed | Complete Sep 5 |
| 1.6 | Team review session on the summer build and fall ownership | Ashleyn | Agreement on which fall tasks I take | Complete Sep 6 |
| 1.7 | Review my spring contributions and the current state of the compression modes | Riley | Written account of what I own and how it changed | Complete Sep 5 |
| 1.8 | Team review session on the summer build and fall ownership | Riley | Agreement on which fall tasks I take | Complete Sep 6 |
| 1.9 | Review my spring contributions and the current state of the security subsystem | Victor | Written account of what I own and how it changed | Complete Sep 5 |
| 1.10 | Team review session on the summer build and fall ownership | Victor | Agreement on which fall tasks I take | Complete Sep 6 |

### Week 2: September 7 to September 13

**Milestone: revised proposal submitted (Sep 13).**

| ID | Task | Owner | Outcome |
|---|---|---|---|
| 2.1 | Write the summer changes document for the team | Kheiven | `docs/CHANGES-SUMMER-2026.md` committed and pushed |
| 2.2 | Verify push status on all branches and commit stranded documentation | Kheiven | Zero unpushed commits; `RESEARCH.md`, `SECURITY.md`, `PROJECT-HISTORY.md` committed |
| 2.3 | Revised proposal: update system design section and functional diagrams | Kheiven | Current architecture diagram including the mobile client, in red per the assignment |
| 2.4 | Revised proposal: update the requirements list with mobile requirements | Jorge | Requirements covering the phone client, added in red |
| 2.5 | Revised proposal: update the literature survey and reference list | Ashleyn | Citations formatted consistently, new sources from the summer research documents |
| 2.6 | Revised proposal: build the Gantt chart from this planner | Riley | Gantt covering all 14 weeks with owners, dependencies, and milestones |
| 2.7 | Revised proposal: organizational chart and completed-tasks list | Victor | Org chart naming the team leader; list of tasks completed to date |

### Week 3: September 14 to September 20

**Milestone M1 target: mobile changes verifiable without a human holding the phone.**

| ID | Task | Owner | Outcome |
|---|---|---|---|
| 3.1 | Make `SvcsApi` fakeable and add JVM unit tests for the view models | Kheiven | `gradlew testDebugUnitTest` covers pairing, library, events, and home view models |
| 3.2 | Add a debug build variant with HTTP logging for diagnosis | Kheiven | A failing request shows its reason in logcat instead of being a mystery on a minified build |
| 3.3 | Investigate the WorkManager API and draft the upload worker design | Jorge | Written design for moving the chunked upload out of `viewModelScope` |
| 3.4 | Audit the resumable upload protocol for resume correctness | Jorge | Confirmation that `/api/upload/status` returns an offset a worker can resume from |
| 3.5 | Build the desktop EVENTS panel, read-only table | Ashleyn | Newest-first table on the TOOLS tab from `/api/events/recent` |
| 3.6 | Add the empty state and ten second auto-refresh to the EVENTS panel | Ashleyn | Panel refreshes while visible, stops when hidden, tells the operator to draw zones first |
| 3.7 | Add the `GET /api/zones/frame` route returning a still frame | Riley | JPEG still for a camera, black placeholder when no thumbnail exists, all three route guards updated |
| 3.8 | Draft the zone editor canvas layout | Riley | Toolbar and canvas markup matching the phone editor |
| 3.9 | Read `push_notify.is_safe_push_url` and specify the webhook emitter | Victor | Written specification for `utils/event_webhook.py` reusing the existing guard |
| 3.10 | Write the socket-server test harness for webhook delivery | Victor | Test fixture in the style of `tests/test_push_notify.py` |

### Week 3 addendum: application testing pass

Added September 7: before the mobile-focused tasks above, the whole team
spends part of week 3 testing the desktop application itself, since nobody
has done a cold, fresh-install pass since the summer build changed so much.
This came out of a review of the installer and first-run Setup flow. The
review's findings are folded into the tasks below rather than kept as a
separate document, so they show up as things to actually check off.

**What the review found.** The onboarding is honest and privacy-respecting
where it matters: Setup states plainly that nothing goes to a cloud folder
unless the user picks one, a Skip option exists for anyone who does not care,
and a factory reset is built in specifically so a clean install can be
retested without reinstalling. Three real gaps stood out. The destination
field in Setup is a raw text box with no folder-browse button, even though
the Library tab already has a folder-browser modal that could be reused, so a
non-technical operator has to know or type a Windows path from memory. The
installer's "Compact - use a system FFmpeg on PATH" component gives no
indication, during Setup or on first Start, of whether FFmpeg was actually
found; the dependency checker that would catch this lives inside the Help
overlay, a place a first-time user has no reason yet to open. And nothing in
the first-run flow explains what a compression mode is before asking the
operator to use the app, so understanding the actual core feature depends on
independently discovering and reading Help.

| ID | Task | Owner | Outcome |
|---|---|---|---|
| 3.11 | Fresh-install walkthrough on a clean machine: install `SVCS-Setup.exe`, complete first-run Setup, run one compression, all without opening the source code | All, each on their own machine | A written note per person of every point of confusion or friction, with the worst three filed as fixes |
| 3.12 | Test the Compact install path with no FFmpeg on PATH | Riley | Confirmation of whether the app warns before Start is clickable, or fails silently on the first compression, plus a fix if it is silent |
| 3.13 | Add a folder-browse button to the Setup destination field, reusing the Library folder-browser modal | Ashleyn | Setup no longer requires typing a raw folder path from memory |
| 3.14 | External network penetration test against a running SVCS instance | Victor | Written findings against the threat model in `docs/SECURITY.md`; anything found gets a severity-rated entry in `docs/BLOCKERS.md`, matching the pentest item already deferred there |
| 3.15 | Fuzz the video-ingest and upload path with malformed media | Victor | A clean rejection or a filed crash report for each malformed file tried, closing the fuzzing item already deferred in `docs/BLOCKERS.md` |

Table 3a. Application testing pass, added to week 3.

Victor's week 3 load is now four tasks (3.9, 3.10, 3.14, 3.15) against everyone
else's two. If that proves too much, move 3.9 and 3.10 (the webhook design
work) to week 4 rather than rushing the security testing.

### Week 4: September 21 to September 27

| ID | Task | Owner | Outcome |
|---|---|---|---|
| 4.1 | Diagnose the mobile pairing persistence defect | Kheiven | Root cause proven by a failing unit test, not by inspection |
| 4.2 | Fix pairing persistence and prove it with an instrumented test | Kheiven | A phone that pairs once stays paired across restarts and app updates |
| 4.3 | Implement the upload `CoroutineWorker` with a foreground notification | Jorge | Upload runs outside the view model scope with visible progress |
| 4.4 | Test upload survival: force-stop mid-transfer and confirm resume | Jorge | Transfer resumes from the server-reported offset and completes |
| 4.5 | Wire desktop event toasts to the existing SSE stream | Ashleyn | An `EVENT` line raises exactly one toast; other log lines raise none |
| 4.6 | Write browser tests for the EVENTS panel | Ashleyn | Rows render from a seeded events file; empty state verified |
| 4.7 | Implement drag-to-draw for exclude rectangles and crossing lines | Riley | Zones round-trip through POST and GET with normalized coordinates intact |
| 4.8 | Implement loiter zones and the SAVE and CLEAR actions | Riley | Full toolbar working, banner states that changes apply to the next run |
| 4.9 | Implement `utils/event_webhook.py` with the SSRF guard | Victor | Events post to a configured URL, fire and forget, two second timeout |
| 4.10 | Add the webhook configuration UI next to the push panel | Victor | Off by default, write-only secret field, refuses metadata endpoints |

### Week 5: September 28 to October 4

| ID | Task | Owner | Outcome |
|---|---|---|---|
| 5.1 | Build `scripts/verify_mobile.ps1` end to end | Kheiven | Build, install, launch, assert, exit non-zero on failure, no human input |
| 5.2 | Design and produce the real Android launcher icon | Kheiven | Adaptive icon at every density replacing the template robot |
| 5.3 | Begin the per-camera HLS registry refactor | Jorge | Design written; the single global stream slot is identified and scoped |
| 5.4 | Add regression tests for the existing single-camera HLS behavior | Jorge | Existing behavior pinned before the refactor changes it |
| 5.5 | Extend the query archive sidebar with full-text and multi-tag search | Ashleyn | Desktop query UI matches the multi-type CLI capability |
| 5.6 | Write an integration test for event and query interaction | Ashleyn | Pipeline run produces events that the query interface can retrieve |
| 5.7 | Add the camera id datalist from library folder labels | Riley | Zone editor offers real camera ids rather than free text |
| 5.8 | Browser-verify the zone editor against a real backdrop frame | Riley | Screenshot evidence of a zone drawn over actual footage |
| 5.9 | Review the mobile credential storage path end to end | Victor | Written finding on whether a failed decrypt fails closed or returns a stale credential |
| 5.10 | Write tests for webhook URL rejection cases | Victor | Metadata endpoints, redirects, and embedded credentials all refused |

### Week 6: October 5 to October 11

**Milestone M2 target: desktop and mobile feature parity on zones and events.**

| ID | Task | Owner | Outcome |
|---|---|---|---|
| 6.1 | Add instrumented tests for the pairing and settings flows | Kheiven | `gradlew connectedDebugAndroidTest` green on the physical device |
| 6.2 | Research the UnifiedPush distributor registration flow | Kheiven | Written design for native push replacing the separate ntfy app |
| 6.3 | Implement the per-camera HLS registry | Jorge | Two cameras stream simultaneously without one blocking the other |
| 6.4 | Update the HLS idle watchdog for multiple streams | Jorge | Each stream reaped independently on abandonment |
| 6.5 | Write the semantic search research document | Ashleyn | `docs/RESEARCH-SEMANTIC-SEARCH.md` covering model choice, storage, offline story |
| 6.6 | Build the semantic search skeleton with a stub embedder | Ashleyn | Opt-in extra; no model downloaded in CI |
| 6.7 | Run the CDnet corpus with and without exclude zones | Riley | Measured file size difference from zone masking |
| 6.8 | Write up the zone compression benefit with numbers | Riley | Table for the final report; the claim is either confirmed or corrected |
| 6.9 | Add the server endpoint for registering a push endpoint per device | Victor | Device tokens can carry a push endpoint for the native path |
| 6.10 | Security review of the new endpoint registration | Victor | Confirmation that one device cannot register or read another device's endpoint |

### Weeks 7 to 14: outline

Detailed tasks are added four weeks ahead on a rolling basis, per the planner
requirement. The shape of the remaining semester:

| Week | Dates | Focus | Owners |
|---|---|---|---|
| 7 | Oct 12 to Oct 18 | Native UnifiedPush client implementation; semantic search integration; multi-camera UI | Kheiven, Ashleyn, Jorge |
| 8 | Oct 19 to Oct 25 | Push endpoint fan-out on the server; mobile screen completeness sweep | Kheiven, Victor |
| 9 | Oct 26 to Nov 1 | Mobile polish: METRICS tab decision, preview scope, thumbnail policy verification | All |
| 10 | Nov 2 to Nov 8 | Full regression across desktop and mobile; performance measurement on target hardware | All |
| 11 | Nov 9 to Nov 15 | Sponsor-facing demo build; deployment packaging review for government COTS hardware | Jorge, Victor |
| 12 | Nov 16 to Nov 22 | Release 1.0: version bump, signed installer, signed APK, checksums, release notes | Kheiven, Riley |
| 13 | Nov 23 to Nov 29 | Final report writing; all measured results consolidated | All |
| 14 | Nov 30 to Dec 6 | Demo rehearsal, final report submission, sponsor demonstration | All |

Table 4. Weeks 7 through 14 outline.

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

Table 5. Task dependencies.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Mobile pairing defect proves deeper than expected | Blocks native push and every credential-dependent feature | Week 3 builds the harness first so week 4 has real diagnostics; fallback is to bypass encrypted storage for a plaintext token on private networks only, with a written security justification |
| Four members ramping up on a codebase that changed substantially | Slow first three weeks | `docs/CHANGES-SUMMER-2026.md` written specifically for this; week 1 is explicitly a ramp-up week |
| Mobile work concentrated on one member | Single point of failure | Weeks 3 to 5 deliberately give Jorge and Victor mobile-adjacent tasks so knowledge spreads |
| No Android CI | Regressions found late | `scripts/verify_mobile.ps1` in week 5 gives a repeatable local check |
| Sponsor availability | Demo requirements drift | Request a check-in during phase B rather than waiting for the final demo |

Table 6. Risk register.

## Notes for maintaining the Teams Planner

* Fill at least four weeks ahead at all times. Weeks 1 through 6 are detailed
  here; add week 7 detail during week 3, and keep rolling.
* Mark previous weeks complete, or move the task and say why in the report.
* Every task needs a start date, a due date, an owner, and a checkable outcome.
* If a task slips, move it in the planner and note it in red in the report.
  Slipping a documented task costs nothing. A planner that does not match the
  report costs points from everyone.

Author: Bloodawn (KheivenD), 2026-09-06.
