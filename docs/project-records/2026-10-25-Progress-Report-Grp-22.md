# Weekly Progress Report, Group 22

**Project Title:** Open Source Selective Video Compression for Static Surveillance Cameras
**Technical Sponsor:** Defense Innovation Unit (DIU) / NIWC Pacific, Cody Hayashi
**Group:** 22 (EGN4950C)
**Report Date:** 2026-10-25
**Report Period:** 2026-09-21 to 2026-10-25
**Team Members:** Kheiven D'Haiti (CS, AI Minor) | Jorge Sanchez (CS) | Ashleyn Montano (CS) | Riley Roberts (CS) | Victor De Souza Teixeira (CS, Cybersecurity)

## Part 1: Team Section

**Planner updated:** YES. Kheiven and Victor items are current. Open items for Jorge, Ashleyn and Riley (weeks 3 to 6) are marked Urgent for this week, each with a GitHub issue.

### 1. Team Meeting

Dates and attendance to be filled in by the team before the sponsor meeting.

### 2. Sponsor/Advisor Meeting

Thursday, 2026-10-22, 8:00 PM Eastern (2:00 PM Hawaii) with Cody Hayashi. This is the catch up on everything done since the spring semester talk.

### 3. Team Progress

Merged PRs: #17 (web dashboard), #22 (mobile UploadWorker), #34 (optimization plus fixes for issues #18, #20, #21), #35 (integration of Victor's PRs #23 to #32, hardened). PR #36 (upload size cap PT-04 and library OSError PT-03) is open.

Releases: v2.2.1-beta (2026-09-26), v2.2.2-beta (2026-09-30), v2.2.3-beta (2026-10-01), mobile 1.2.1-beta. Added desktop and mobile auto update, fixed compression that could grow a file, fixed the ONNX detector, Real-ESRGAN small crop crashes and update progress UX.

Security: SSRF hardening (legacy IPv4 spellings, blocked camera source hosts), authenticated webhook config, fail closed token store, upload size cap. Pentest report and credential review are in docs/.

Optimization: brightness math 4.5x faster, pipeline import 1.08 s to 0.24 s, constant memory segment stats, streaming encryption.

Press release: set up and drafted by Ashleyn.

Ashleyn has four commits dated 2026-10-04 on origin/feature/ashleyn-events-panel (events panel, toasts with browser tests, multi type archive search, semantic search skeleton and research doc). They are not in a PR yet and the branch needs a rebase on main.

### 4. Challenges and Blockers

Victor's ten PRs were based on an older main and needed a full integration plus security fixes. Riley has no recorded work in the repository for this period, and Jorge's weeks 5 and 6 items are not started. Open follow ups: cancelled re-pair can leave a new server URL next to an old token, installer smoke test exit code 2, deferred speedups.

### 5. Summary Table (current period)

| Member | Tasks completed | Not completed | Tasks for next period |
| --- | --- | --- | --- |
| Kheiven | Releases, auto update, PR #34, PR #35, 5.1, 5.2, 6.1, 6.2, 6.11, PT fixes | 3.11 walkthrough | PR #36 merge, GitHub Project board, sponsor demo |
| Victor | PRs #23 to #32, 3.9, 3.10, 3.11, 3.14, 3.15, 4.9, 4.10, 5.9, 5.10, 6.9, 6.10 | Re-pair edge case | Pentest follow ups |
| Jorge | 4.3 (PR #22), 4.4, issues #18, #20, #21 | 3.11, 5.3, 5.4, 6.3, 6.4 | Per camera HLS registry (urgent) |
| Ashleyn | Press release, events panel; 4.5, 4.6, 5.5, 5.6, 6.5, 6.6 coded on branch | PR for that branch, 3.11 | Open the PR, rebase on main (urgent) |
| Riley | 3.7, 3.8, 3.12 (earlier weeks) | 3.11, 4.7, 4.8, 5.7, 5.8, 6.7, 6.8 | Zone editor and CDnet run (urgent) |

## Part 2: Individual Sections

### Kheiven D'Haiti

Tasks completed: three beta releases, desktop and mobile auto update, optimization PR #34, integration PR #35, YOLO pose confirmation (6.11), mobile verify script (5.1), launcher icon (5.2), pairing tests (6.1), UnifiedPush design (6.2), PT-03 and PT-04 fixes (PR #36).
Planned: merge PR #36, set up the GitHub Project, prepare the sponsor demo.

### Victor De Souza Teixeira

Tasks completed: webhook emitter, push notifications, device tokens, encryption upgrade (PRs #23 to #32), pentest and credential review documents, fresh install walkthrough.
Planned: review remaining pentest findings and the re-pair edge case.

### Jorge Sanchez

Tasks completed: WorkManager UploadWorker (4.3), upload survival test plan and results (4.4), reported issues #18, #20 and #21 (all fixed in PR #34).
Tasks not completed: 5.3, 5.4, 6.3, 6.4 (per camera HLS registry), 3.11.
Planned: HLS registry work, tracked in GitHub issues.

### Ashleyn Montano

Tasks completed: press release, desktop events panel (3.5, 3.6), folder browse button (3.13). Code for 4.5, 4.6, 5.5, 5.6, 6.5, 6.6 exists on her branch but is not merged.
Planned: open a PR from the branch after rebasing on main.

### Riley Roberts

Tasks completed in earlier weeks: 3.7, 3.8, 3.12. Nothing recorded for 4.7, 4.8, 5.7, 5.8, 6.7, 6.8. Riley, please add anything missing here before Thursday.
Planned: zone editor drawing tools, backdrop verification, CDnet run, tracked in GitHub issues.
