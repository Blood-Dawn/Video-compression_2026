# EGN4950C Senior Design

## Weekly Progress Report

**Project Title:** Open Source Selective Video Compression for Static Surveillance Cameras
**Technical Sponsor:** Defense Innovation Unit (DIU) / NIWC Pacific, Cody Hayashi
**Group:** 22
**Report Date:** September 7, 2026
**Report Period:** September 7, 2026 to September 13, 2026
**Team Members:** Kheiven D'Haiti (CS, AI Minor) | Jorge Sanchez (CS) | Ashleyn Montano (CS) | Riley Roberts (CS) | Victor De Souza Teixeira (CS, Cybersecurity)

> **NOTE FOR THE TEAM, DELETE THIS BOX BEFORE SUBMITTING.** This report is
> being filed on September 14, one day after the Sunday deadline. Read your
> own section, correct anything that is wrong, and fill in the two [FILL IN]
> items in Part 1 before this goes out. Export to PDF named
> `2026-09-07-Progress-Report-Grp-22.pdf`.

---

# Part 1: Team Section

**All team members have detailed tasks listed on Teams Planner:** YES. Source
document: `docs/project-records/PLANNER-FALL-2026.md` and its companion CSV.

## 1. Team Meeting

**Did the team meet this period?** [FILL IN: date, time, and who attended. If
the team did not meet, say so and describe how coordination happened instead.]

## 2. Sponsor / Advisor Meeting

**Did the team meet with the sponsor this period?** [FILL IN. State when the
next sponsor check-in is planned.]

## 3. Team Progress This Period

This period was dominated by the Module 1 Revised Proposal, due September 13,
and by getting the public repository into a state that matches what the team
actually intends to ship.

Kheiven completed the two tasks that unblock everyone else's ramp-up
(`docs/CHANGES-SUMMER-2026.md`, and committing the research, security, and
project-history documents that had been sitting locally), then spent the rest
of the period on a larger repository cleanup that was not on the original
plan: rewriting the README on both the desktop and mobile branches for a
non-technical reader with an honest beta section for the Android app, removing
AI-development-process documents from the public branch, dropping the dormant
commercial-license plan so the project reads as open source only, and
archiving the Spring roadmap in favor of a new person-by-person Fall roadmap
with a regenerated Teams Planner import. This work was real and needed, but it
came at the cost of task 2.3, the system design section of the proposal, which
did not get done this period and carries into week 3.

Victor completed his assigned proposal task, 2.7 (organizational chart and
completed-tasks list), and opened pull request #15 with the drop-in content.
It went through one round of review comments (correcting which milestone the
AV1 codec work actually belonged to, and clarifying the two different
"Coordinator" titles on the sponsor and student sides) and was merged into
`main` on September 14.

Jorge, Ashleyn, and Riley did not complete their assigned proposal sections
(2.4, 2.5, 2.6) this period. Each spent the time reviewing the current state of
their subsystem instead, and the team is using that review to scope new
features to add to the desktop application, rather than only finishing mobile
parity work. Kheiven's own focus for the coming period is getting the mobile
port working end to end.

The consequence is that the Module 1 Revised Proposal was not fully assembled
by the September 13 deadline. Only section 2.7 is ready to fold in; sections
2.3 through 2.6 are outstanding and are the team's first priority this coming
week.

## 4. Challenges and Blockers

* **The Module 1 Revised Proposal deadline was missed.** Only Victor's section
  (2.7) was completed on schedule. The system design section (2.3), the
  requirements list (2.4), the literature survey (2.5), and the Gantt chart
  (2.6) are still outstanding. This report is being filed a day late for the
  same reason: the week's attention went to repository cleanup instead of the
  proposal.
* **Three of five members have not yet returned with concrete plans.** Jorge,
  Ashleyn, and Riley are still reviewing their subsystems and have not yet
  proposed the specific new desktop features they intend to build. That needs
  to land early in week 3 so it can inform both the delayed proposal sections
  and the week 4 task breakdown.
* **The mobile pairing defect and the lack of a mobile test harness remain
  open**, carried from last period. Building the test harness (tasks 3.1, 3.2)
  is scheduled first in week 3, ahead of the pairing fix in week 4, for the
  same reason given last report: diagnosing it without tests is what consumed
  the most time in August.
* **A documentation accuracy gap was found while rebuilding the roadmap.**
  `docs/getting-started.md` says `docker compose up --build` works from a
  fresh clone, but the `Dockerfile` copies in `yolov8n.onnx`, which is
  gitignored and never fetched automatically. Nobody has actually run the
  Docker install from a clean checkout since that gitignore rule was written.
  Verifying and fixing this is scheduled as task 3.16.

## 5. Summary Tables

Previous report period: August 31 to September 6, 2026

| Member | Tasks completed | Not completed | Tasks for next period |
|---|---|---|---|
| Kheiven D'Haiti | 2 | 0 | 3 |
| Jorge Sanchez | 2 | 0 | 2 |
| Ashleyn Montano | 2 | 0 | 2 |
| Riley Roberts | 2 | 0 | 2 |
| Victor De Souza Teixeira | 2 | 0 | 2 |

Table 1. Previous report summary.

Current report period: September 7 to September 13, 2026

| Member | Tasks completed | Not completed | Tasks for next period |
|---|---|---|---|
| Kheiven D'Haiti | 2 | 1 | 4 |
| Jorge Sanchez | 0 | 1 | 3 |
| Ashleyn Montano | 0 | 1 | 3 |
| Riley Roberts | 0 | 1 | 3 |
| Victor De Souza Teixeira | 1 | 0 | 4 |

Table 2. Current report summary. "Not completed" for Jorge, Ashleyn, and Riley
is their proposal section (2.4, 2.5, 2.6 respectively), carried into week 3
alongside their originally scheduled tasks.

---

# Part 2: Individual Sections

Each member writes their own section. Task numbers match the MS Teams Planner
and `docs/project-records/PLANNER-FALL-2026.md`.

---

## Kheiven D'Haiti, CS Major, AI Minor

**Report Date:** September 7, 2026

### Tasks completed this reporting period

**Task 2.1: Write the summer changes document for the team (completed)**

Description: The team needed one document that explains what changed over the
summer and why, rather than a 158-commit log nobody has time to read.

Outcome: `docs/CHANGES-SUMMER-2026.md` written and committed, covering the
distribution work, the compression quality changes, the security audit, and
the mobile app build-out, with a reading guide pointing each member at the
files relevant to their subsystem.

**Task 2.2: Commit the stranded documentation and re-verify push status (completed)**

Description: `docs/RESEARCH.md`, `docs/SECURITY.md`, and
`docs/archive/PROJECT-HISTORY.md` existed only on my machine as of last
report.

Outcome: All three committed and pushed. Re-checked every branch against its
remote; zero unpushed commits remained after this task.

### Additional work this period (not on the original plan)

The rest of the period went into a repository cleanup pass that the proposal
work made necessary once I looked closely at what a sponsor or outside
contributor would actually see on the public branch:

* Rewrote the README on both `main` (desktop first, then mobile) and
  `mobile`/`app` (mobile first) for a non-technical reader, with an honest
  beta section for the Android app covering what it does, what it does not do
  yet, and the real risks (pairing not surviving a restart, uploads not
  surviving the app being killed, thin test coverage, no signed build yet).
* Removed AI-development-process documents (planning and handoff notes,
  `AGENTS.md`) from the public `main` branch, since a sponsor or outside
  contributor has no use for the internal record of how the code was
  developed. These stay on `mobile`/`app`, the internal working branches.
* Dropped `CLA.md` and `LICENSE-COMMERCIAL.md`, the dormant dual-license plan,
  and rewrote every "premium tier" reference in code comments and docs to
  plain "optional extras" language, so the project reads as open source only.
  A commercial variant, if it happens, will be a separate forked repository.
* Archived the Spring 2026 roadmap to `docs/archive/ROADMAP-SPRING-2026.md`
  and wrote a new `ROADMAP.md` for this semester, organized by person with a
  linked section each, detailed for weeks 2 through 6 and outlined for weeks 7
  through 14 to match the planner's own rolling window.
* Regenerated the Teams Planner CSV to include the week 3 application-testing
  tasks that had been added to the written plan but never made it into the
  importable file, plus a new task (3.16) to verify the Docker install path,
  which I found undocumented while doing this work.

Outcome: The public branch now matches what the team is actually building and
intends to ship, and the semester plan is current. The cost was task 2.3,
below.

### Tasks not completed this reporting period

**Task 2.3: Revised proposal, system design section and functional diagrams**
Not started. The architecture changed enough over the summer (mobile client,
device token boundary, push path) that this is closer to a rewrite than an
edit, and the cleanup work above took priority. Carried into week 3.

### Planned tasks for the coming period (September 14 to September 20)

**Task 2.3 (carried over): Revised proposal, system design section and
functional diagrams.** Redraw the architecture diagram to include the mobile
client, the device token boundary, and the push path, marked in red.

**Task 3.1: Make `SvcsApi` fakeable and add JVM unit tests for the view
models.** `gradlew testDebugUnitTest` should cover the pairing, library,
events, and home view models.

**Task 3.2: Add a debug build variant with HTTP logging for diagnosis**, so a
failing mobile request shows its reason in logcat instead of being a mystery
on a minified build.

**Task 3.11: Fresh-install walkthrough**, with the rest of the team: install
`SVCS-Setup.exe`, complete first-run Setup, run one compression, all without
opening the source code.

**Task 3.16: Verify the Docker install path end to end on a fresh clone**, and
fix `docs/getting-started.md` to either state the `yolov8n.onnx` prerequisite
plainly or make the build fetch it automatically.

---

## Jorge Sanchez, CS Major

**Report Date:** September 7, 2026

### Tasks completed this reporting period

None formally closed. I spent the period reviewing the ingest and streaming
code I own (the watchfolder daemon and `MultiFrameSource`) against what
changed over the summer, and I am scoping new capture and multi-camera
streaming features to bring to the team for the desktop app, rather than
building yet. Task 2.4, the requirements section of the revised proposal, was
not completed this period.

### Planned tasks for the coming period (September 14 to September 20)

* Finish scoping new desktop ingest and streaming features and bring specific
  proposals to the team.
* **Task 2.4 (carried over):** Revised proposal, requirements list including
  mobile requirements, marked in red.
* **Task 3.3:** Investigate the WorkManager API and draft the upload worker
  design.
* **Task 3.4:** Audit the resumable upload protocol for resume correctness.
* **Task 3.11:** Fresh-install walkthrough, with the rest of the team.

---

## Ashleyn Montano, CS Major

**Report Date:** September 7, 2026

### Tasks completed this reporting period

None formally closed. I spent the period reviewing the metadata and query code
I own against what changed over the summer, and I am scoping new event
surfacing and search features to bring to the team for the desktop app. Task
2.5, the literature survey section of the revised proposal, was not completed
this period.

### Planned tasks for the coming period (September 14 to September 20)

* Finish scoping new desktop event and search features and bring specific
  proposals to the team.
* **Task 2.5 (carried over):** Revised proposal, literature survey and
  reference list.
* **Task 3.5:** Build the desktop EVENTS panel, read-only table.
* **Task 3.6:** Add the empty state and ten second auto-refresh to the EVENTS
  panel.
* **Task 3.13:** Add a folder-browse button to the Setup destination field.

---

## Riley Roberts, CS Major

**Report Date:** September 7, 2026

### Tasks completed this reporting period

None formally closed. I spent the period reviewing the compression mode code I
own against what changed over the summer, and I am scoping new compression and
zone-related features to bring to the team for the desktop app. Task 2.6, the
Gantt chart section of the revised proposal, was not completed this period.

### Planned tasks for the coming period (September 14 to September 20)

* Finish scoping new compression and zone features and bring specific
  proposals to the team.
* **Task 2.6 (carried over):** Revised proposal, Gantt chart built from the
  planner.
* **Task 3.7:** Add the `GET /api/zones/frame` route returning a still frame.
* **Task 3.8:** Draft the zone editor canvas layout.
* **Task 3.12:** Test the Compact install path with no FFmpeg on PATH.

---

## Victor De Souza Teixeira, CS Major, Cybersecurity Minor

**Report Date:** September 7, 2026

### Tasks completed this reporting period

**Task 2.7: Revised proposal, organizational chart and completed-tasks list
(completed September 12, merged September 14)**

Description: The assignment requires an organizational chart that explicitly
names a team leader, and a table of tasks completed to date. I drafted both as
drop-in content for Kheiven to fold into the master proposal document, opened
as pull request #15 (`feature/victor-week2-task-2.7`).

Implementation: The organizational chart names Kheiven D'Haiti as Student Team
Leader / Project Coordinator, distinct from Geena Wann-Kung's "Project
Coordinator" title on the sponsor side, with the sponsor and faculty advisor
above him and the four subsystem owners reporting to him, matching the
ownership table in `ROADMAP.md`. The completed-tasks table (proposal Table
4.4) is split into three periods: Spring 2026 milestones 1 through 3
(complete) with the open items honestly marked as not done by the May 6
deadline, Summer 2026's headline build-out, and Fall Week 1's ten completed
ramp-up tasks.

After opening the pull request I addressed two review comments: the AV1 codec
work had been miscredited to the Spring capstone when it was actually finished
afterward in a summer fix, and I moved it to the correct period; and the two
different "Coordinator" titles needed an explicit note that there is no
reporting relationship between them.

Outcome: `docs/project-records/PROPOSAL-SECTION-2.7-ORG-CHART-AND-COMPLETED-TASKS.md`,
merged into `main` in pull request #15.

Evidence: Pull request #15, commits `b92fd02` and `4c7b18c`.

### Planned tasks for the coming period (September 14 to September 20)

This is my heaviest week this semester, four tasks against everyone else's
two or three:

**Task 3.9:** Read `push_notify.is_safe_push_url` and specify the webhook
emitter, reusing the existing guard.

**Task 3.10:** Write the socket-server test harness for webhook delivery, in
the style of `tests/test_push_notify.py`.

**Task 3.14:** External network penetration test against a running SVCS
instance, findings recorded against `docs/SECURITY.md`.

**Task 3.15:** Fuzz the video-ingest and upload path with malformed media.

If this proves too much alongside the others, tasks 3.9 and 3.10 move to week
4 rather than rushing the security testing.
