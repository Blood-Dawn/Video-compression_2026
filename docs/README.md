# SVCS documentation map

Start here to find the right document. It is grouped by what you are trying to
do, following the [Diataxis](https://diataxis.fr/) split: learn by doing
(tutorials), get a specific job done (how-to), look something up (reference),
or understand why (explanation). Dated records sit apart at the end.

New to the code? Read [../DEV.md](../DEV.md) first; it is the developer guide
and links back here for depth.

The files did not move into tutorials/, how-to/ and similar folders: their
paths are linked from code comments, tests, release notes and published pages,
so the grouping lives in this index instead.

## Tutorials: first steps

| Document | For |
|---|---|
| [getting-started.md](getting-started.md) | Install the desktop app and run a first compression. |
| [../mobile/android/EMULATOR-GUIDE.md](../mobile/android/EMULATOR-GUIDE.md) | Run the Android app on an emulator with no phone and no Android background. |

## How-to guides: specific tasks

| Document | Task |
|---|---|
| [releases/INSTALL.md](releases/INSTALL.md) | Install on Windows (one-liner, winget, manual), verify the download. |
| [RELEASE-CHECKLIST.md](RELEASE-CHECKLIST.md) | Cut a desktop or Android release, step by step. |
| [operations/RUNBOOK-LOCAL.md](operations/RUNBOOK-LOCAL.md) | Run, stop and troubleshoot a local server. |
| [operations/google_drive_output.md](operations/google_drive_output.md) | Optional: send output to a synced Google Drive folder (not the default). |
| [build/BUILDS.md](build/BUILDS.md) | Build the Server and Field editions. |
| [releases/winget-submission.md](releases/winget-submission.md) | Submit the winget manifest. |
| [security/KALI-PENTEST-GUIDE.md](security/KALI-PENTEST-GUIDE.md), [security/SECURITY-MANUAL-VERIFY.md](security/SECURITY-MANUAL-VERIFY.md) | Test a running install's security by hand. |

## Reference: how things are

| Document | Covers |
|---|---|
| [SYSTEM-ARCHITECTURE.md](SYSTEM-ARCHITECTURE.md) | Desktop pipeline, live streaming, ingestion, mobile client, notifications. Details in `architecture/`. |
| [architecture/MOBILE-ARCHITECTURE.md](architecture/MOBILE-ARCHITECTURE.md) | Android Server Mode design (pairing, tokens, push). The standalone compressor is in the mobile roadmap below. |
| [BUILD-AND-RELEASE.md](BUILD-AND-RELEASE.md) | Editions, packaging, FFmpeg and model licensing, build metrics. Details in `build/`. |
| [SECURITY.md](SECURITY.md) | Threat model, audit findings, hardening. Details in `security/`. |
| [TESTING.md](TESTING.md) | Test commands, baseline, environment limits. Details in `testing/`. |
| [BLOCKERS.md](BLOCKERS.md) | Open owner gates (signing cert, Android keystore, ...) and the gate register. |
| [releases/](releases/) | Release notes for every desktop and Android release. |

## Explanation: why it is built this way

| Document | Covers |
|---|---|
| [RESEARCH.md](RESEARCH.md) | Compression, detection, codecs, UI research, competitors, VMAF, benchmarks. Chapters in `research/`. |
| [../mobile/android/STANDALONE-COMPRESSOR-ROADMAP.md](../mobile/android/STANDALONE-COMPRESSOR-ROADMAP.md) | Why the Android compressor uses Media3 and LiteRT instead of the desktop's FFmpeg, and its phased plan and progress. |
| [../mobile/android/UI-REVIEW.md](../mobile/android/UI-REVIEW.md) | The Android UI redesign: research, what changed, open items. |
| [../mobile/android/UPLOAD-WORKER-DESIGN.md](../mobile/android/UPLOAD-WORKER-DESIGN.md) | Moving phone uploads to WorkManager. |
| [PROJECT-PLAN.md](PROJECT-PLAN.md) | Desktop work tracks, GUI refactor constraints, owner gates. |
| [../ROADMAP.md](../ROADMAP.md) | The team's Fall 2026 semester plan, by person and week. |

## Records

Dated documents kept as evidence. They describe the project as it was when
written; do not update them to match today, update the canonical document
instead.

- [CHANGES-SUMMER-2026.md](CHANGES-SUMMER-2026.md): what landed over the summer.
- [plans/](plans/): the detailed plans behind PROJECT-PLAN.md (GUI refactor,
  desktop zones and events, R6 upgrade).
- [project-records/](project-records/): progress reports, the planner export,
  handoffs, session logs, the final report.
- [archive/](archive/): retired roadmaps (Spring 2026, the June v2 plan).
- [site/](site/): the static download page.

## Editing rules

- When a record changes a current decision, update the canonical document
  and leave the record dated.
- Only call something archived once it is under `archive/`.
- Run `python scripts/check_doc_links.py` after moving or renaming a file;
  it lists every relative link and repo path that no longer resolves.
- ASCII hyphens only: no em or en dashes (`tests/test_no_unicode_dashes.py`
  enforces it).
