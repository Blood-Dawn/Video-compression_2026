# EGN4950C Senior Design

## Weekly Progress Report

**Project Title:** Open Source Selective Video Compression for Static Surveillance Cameras
**Technical Sponsor:** Defense Innovation Unit (DIU) / NIWC Pacific, Cody Hayashi
**Group:** 22
**Report Date:** September 14, 2026
**Report Period:** September 14, 2026 to September 20, 2026
**Team Members:** Kheiven D'Haiti (CS, AI Minor) | Jorge Sanchez (CS) | Ashleyn Montano (CS) | Riley Roberts (CS) | Victor De Souza Teixeira (CS, Cybersecurity)

---

# Part 1: Team Section

**All team members have detailed tasks listed on Teams Planner:** YES. All 19
week 3 tasks (3.2 through 3.16, five of them the shared fresh-install
walkthrough) are now cards in the "Week 3 (2026-09-14)" bucket on the actual
Microsoft Teams Planner board, matching `docs/project-records/PLANNER-FALL-2026.md`,
with the correct assignee and due date on each.

## 1. Team Meeting

**Did the team meet this period?** No. The team did not hold a formal
meeting; coordination happened mostly through the group chat.

## 2. Sponsor / Advisor Meeting

**Did the team meet with the sponsor this period?** No.

## 3. Team Progress This Period

This was a light period against the written plan. None of the sixteen week 3
tasks in `week3.local.json` (3.2 through 3.16) closed, and the proposal
sections carried since week 2 (2.3 through 2.6) are still outstanding. Two
things did get done, and neither was on the plan.

Ashleyn drafted the press release required for the separate class assignment
due this period. Kheiven substantially rewrote it, including a full pass for
tone and a new visual layout, and submitted it. That work is not tied to a
planner task number because the assignment sits outside the numbered
engineering backlog, but it was real, deadline-bound work and it got done on
time.

Separately, Kheiven found that the desktop installer sitting on the
`v2.2.0-beta` GitHub release predated the chunked-upload, zone-event, and
filename-sanitization work from the prior period, and that a fresh build of
it was silently broken: the packaged executable crashed on launch with a
missing `cv2` module. The root cause was two conflicting OpenCV packages
(`opencv-contrib-python` and a plain `opencv-python` pulled in transitively by
`ultralytics`) partially overwriting each other inside the same build
environment, which corrupted PyInstaller's dependency collection without
breaking normal source-mode use. Fixing the environment, rebuilding, and
re-verifying the smoke test took most of a day. While in there, Kheiven also
designed and wired in the project's first real installer branding (a custom
icon and Inno Setup wizard artwork built from the same brand kit as the press
release), replacing the generic default Inno Setup look. The rebuilt installer
and a regenerated checksum file are now attached to the `v2.2.0-beta` release
in place of the stale August 17 build.

That release also surfaced an older problem worth stating plainly: `main`, the
branch this build comes from, does not contain the Android app's source at
all. The Kotlin code lives only on the `app` and `mobile` branches, split
apart from `main` on September 7 so the desktop line could move independently.
Since that split, `main` and `mobile` have drifted in both directions, and at
least one task the planner still lists as 0 percent complete (task 3.1, making
`SvcsApi` fakeable for unit tests) was actually finished on September 14 and
is simply stranded on the unmerged branch. Reconciling this is now the first
item in a new planning document, `docs/project-records/AUTOBUILD-ROADMAP.md`,
which restates the existing roadmap and planner as an ordered, verified
sequence of 49 tasks across 9 milestones, cross-checked line by line against
what the code actually contains rather than what earlier docs claimed. It is
meant to be handed to a coding agent to execute with less back-and-forth than
the team has needed so far, and it flags several other places where a doc's
claim and the code disagree, including a version-number mismatch on the
mobile build and a documented-but-unlogged zip-slip gap in the MediaMTX
downloader.

Jorge, Ashleyn, and Riley did not complete their week 3 tasks or their
carried-over proposal sections (2.4, 2.5, 2.6) this period. The team has not
yet reconvened to say why, which is one of the two open items above.

## 4. Challenges and Blockers

* **Zero of sixteen week 3 tasks closed, and the proposal is now three weeks
  overdue.** Sections 2.4, 2.5, and 2.6 have carried since week 2 with no
  visible progress. This needs to be the team's first conversation next
  period, not a fourth week of carryover.
* **The Android app is not reachable from `main`.** It only exists on `app`
  and `mobile`, which have diverged from `main` in both directions since
  September 7. Every mobile-related task in the plan, including the ones
  scheduled for weeks 3 and 4, is currently unbuildable from the branch the
  team treats as the source of truth. This is now milestone 0 of
  `AUTOBUILD-ROADMAP.md` and needs to be resolved before mobile work resumes.
* **The planner import is still manual and still not done.** The written task
  list for week 3 existed on time; it was never pushed into Teams Planner.
  This is a process gap, not a content gap, and it is the next thing Kheiven
  is doing.
* **The MediaMTX downloader's zip-slip and missing-checksum gap
  (`src/utils/rtsp_server.py`) is confirmed in code but was never written down
  in `docs/BLOCKERS.md`.** It has been added there and is scheduled in the new
  roadmap ahead of any further reliance on that download path.
* **Victor's heaviest week did not happen as planned.** Task 3.9 and 3.10
  (the webhook emitter and its test harness) were flagged last period as
  likely to slip if the other three tasks ran long; they did slip, and Victor
  still has all five week 3 tasks outstanding.

## 5. Summary Tables

Previous report period: September 7 to September 13, 2026

| Member | Tasks completed | Not completed | Tasks for next period |
|---|---|---|---|
| Kheiven D'Haiti | 2 | 1 | 4 |
| Jorge Sanchez | 0 | 1 | 3 |
| Ashleyn Montano | 0 | 1 | 3 |
| Riley Roberts | 0 | 1 | 3 |
| Victor De Souza Teixeira | 1 | 0 | 4 |

Table 1. Previous report summary.

Current report period: September 14 to September 20, 2026

| Member | Tasks completed | Not completed | Tasks for next period |
|---|---|---|---|
| Kheiven D'Haiti | 1 | 4 | 5 |
| Jorge Sanchez | 0 | 4 | 4 |
| Ashleyn Montano | 0 | 5 | 5 |
| Riley Roberts | 0 | 5 | 5 |
| Victor De Souza Teixeira | 0 | 5 | 5 |

Table 2. Current report summary. "Tasks completed" counts numbered planner
tasks only. It does not count the press release or the installer rebuild,
neither of which carries a planner task number, even though both were real
work finished this period. Kheiven's one completed task (3.1) is done in code
but stranded on the unmerged `mobile` branch, so it does not yet show up on
`main`.

---

# Part 2: Individual Sections

Each member writes their own section. Task numbers match the MS Teams Planner
and `docs/project-records/PLANNER-FALL-2026.md`.

---

## Kheiven D'Haiti, CS Major, AI Minor

**Report Date:** September 14, 2026

### Tasks completed this reporting period

**Task 3.1: Make `SvcsApi` fakeable and add JVM unit tests for the view
models (completed September 14, not yet visible on `main`)**

Description: `gradlew testDebugUnitTest` needed to cover the pairing,
library, events, and home view models without hitting the network.

Outcome: Done, committed September 14. The commit lives on the `mobile`
branch, which does not merge cleanly into `main` as of this report because the
two branches have diverged in both directions since the September 7 split.
This is the first task in the new roadmap.

### Additional work this period (not on the original plan)

* Rewrote and submitted the class press release assignment, building on
  Ashleyn's draft.
* Diagnosed and fixed a corrupted OpenCV install that was silently breaking
  the frozen desktop build (two conflicting `cv2`-providing packages
  partially overwriting each other), rebuilt the installer, and re-verified
  the smoke test.
* Designed and wired in the project's first custom installer branding (icon
  and Inno Setup wizard artwork), replacing the generic default look.
* Published the rebuilt installer and a regenerated SHA-256 checksum file to
  the `v2.2.0-beta` release, replacing the stale August 17 build.
* Wrote `docs/project-records/AUTOBUILD-ROADMAP.md`, a 49-task, 9-milestone
  restatement of the existing roadmap and planner, checked line by line
  against the actual code rather than against what earlier docs claimed.

Outcome: A working, correctly branded installer is now the one attached to
the public beta release, and the team has a single ordered backlog to hand to
a coding agent. The cost was the same as last period: planned tasks did not
move.

### Tasks not completed this reporting period

**Task 2.3 (carried a second time): Revised proposal, system design section
and functional diagrams.** Still not started. Now the most overdue item on
the board.

**Task 3.2: Add a debug build variant with HTTP logging.** Not started.

**Task 3.11: Fresh-install walkthrough**, with the rest of the team. Not
done; the team has not scheduled it.

**Task 3.16: Verify the Docker install path end to end.** Not started.

### Planned tasks for the coming period (September 21 to September 27)

**Task 2.3 (carried over):** Revised proposal, system design section,
including the mobile client, device token boundary, and push path.

**New task: Reconcile `main` and `mobile`.** Decide whether to merge, rebase,
or cherry-pick the Android source back onto `main` so mobile work is buildable
from the branch the team treats as canonical. This blocks every other mobile
task in the new roadmap.

**Task 3.2, 3.11, 3.16 (carried over).**

### Additional resources or support required

None beyond the team actually reconvening to redistribute the proposal
sections that are now three weeks overdue.

---

## Jorge Sanchez, CS Major

**Report Date:** September 14, 2026

### Tasks completed this reporting period

None. Task 2.4, the requirements section of the revised proposal, was not
completed this period, and none of the week 3 tasks closed.

### Planned tasks for the coming period (September 21 to September 27)

* **Task 2.4 (carried over, now overdue two periods):** Revised proposal,
  requirements list including mobile requirements.
* **Task 3.3 (carried over):** Investigate the WorkManager API and draft the
  upload worker design.
* **Task 3.4 (carried over):** Audit the resumable upload protocol for resume
  correctness.
* **Task 3.11 (carried over):** Fresh-install walkthrough, with the rest of
  the team.

---

## Ashleyn Montano, CS Major

**Report Date:** September 14, 2026

### Tasks completed this reporting period

Drafted the press release for the class assignment; Kheiven finalized and
submitted it. This is not a numbered planner task, but it was the one concrete
deliverable the team turned in this period.

Task 2.5, the literature survey section of the revised proposal, was not
completed. None of the week 3 desktop tasks closed.

### Planned tasks for the coming period (September 21 to September 27)

* **Task 2.5 (carried over, now overdue two periods):** Revised proposal,
  literature survey and reference list.
* **Task 3.5 (carried over):** Build the desktop EVENTS panel, read-only
  table.
* **Task 3.6 (carried over):** Add the empty state and ten second
  auto-refresh to the EVENTS panel.
* **Task 3.13 (carried over):** Add a folder-browse button to the Setup
  destination field.
* **Task 3.11 (carried over):** Fresh-install walkthrough, with the rest of
  the team.

---

## Riley Roberts, CS Major

**Report Date:** September 14, 2026

### Tasks completed this reporting period

None. Task 2.6, the Gantt chart section of the revised proposal, was not
completed, and none of the week 3 tasks closed.

### Planned tasks for the coming period (September 21 to September 27)

* **Task 2.6 (carried over, now overdue two periods):** Revised proposal,
  Gantt chart built from the planner.
* **Task 3.7 (carried over):** Add the `GET /api/zones/frame` route returning
  a still frame.
* **Task 3.8 (carried over):** Draft the zone editor canvas layout.
* **Task 3.12 (carried over):** Test the Compact install path with no FFmpeg
  on PATH.
* **Task 3.11 (carried over):** Fresh-install walkthrough, with the rest of
  the team.

---

## Victor De Souza Teixeira, CS Major, Cybersecurity Minor

**Report Date:** September 14, 2026

### Tasks completed this reporting period

None. All five assigned week 3 tasks are outstanding. Last report flagged that
tasks 3.9 and 3.10 might need to slip to week 4 if the other three ran long;
that is what happened.

### Planned tasks for the coming period (September 21 to September 27)

* **Task 3.9 (carried over):** Specify the webhook emitter, reusing the
  existing `is_safe_push_url` guard.
* **Task 3.10 (carried over):** Write the socket-server test harness for
  webhook delivery.
* **Task 3.14 (carried over):** External network penetration test against a
  running SVCS instance.
* **Task 3.15 (carried over):** Fuzz the video-ingest and upload path with
  malformed media.
* **Task 3.11 (carried over):** Fresh-install walkthrough, with the rest of
  the team.
