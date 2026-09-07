# SVCS documentation map

This folder uses a small set of canonical documents. The phase reports and
dated notes remain as evidence, but new decisions should be added to the
canonical document for their subject instead of creating another parallel
overview.

## Canonical documents

| Document | Covers | Supporting records |
|---|---|---|
| [RESEARCH.md](RESEARCH.md) | Compression, detection, design research, codec decisions, UI research, competitor findings, plate-reader research, VMAF work, benchmarks, and test evidence | `research/` |
| [SYSTEM-ARCHITECTURE.md](SYSTEM-ARCHITECTURE.md) | Desktop pipeline, live streaming, camera and format ingestion, mobile client, notifications, and feature inventory | `architecture/` |
| [BUILD-AND-RELEASE.md](BUILD-AND-RELEASE.md) | Editions, packaging, deployment, FFmpeg and model licensing, build metrics, release, and winget | `build/`, `releases/` |
| [SECURITY.md](SECURITY.md) | Threat model, audit findings, hardening, manual checks, and operating rules | `security/` |
| [TESTING.md](TESTING.md) | Test commands, current baseline, environment constraints, validation evidence, and known limits | `testing/`, `research/stress_test_results.md` |
| [PROJECT-PLAN.md](PROJECT-PLAN.md) | Active roadmap, GUI refactor constraints, desktop zones/events work, mobile follow-up, and owner gates | `plans/`, `releases/` |
| [getting-started.md](getting-started.md) | First install and first successful compression | [releases/INSTALL.md](releases/INSTALL.md), [operations/RUNBOOK-LOCAL.md](operations/RUNBOOK-LOCAL.md) |

## Status and planning records

These files are intentionally kept separate because their dates and decisions
are part of the record: [plans/](plans/),
[CHANGES-SUMMER-2026.md](CHANGES-SUMMER-2026.md),
[release notes](releases/), and the files under `project-records/`. Their canonical summary is
[PROJECT-PLAN.md](PROJECT-PLAN.md).

## Operational records

These are setup-specific or owner-run records rather than research chapters:
[operations/](operations/), [releases/INSTALL.md](releases/INSTALL.md), and
[getting-started.md](getting-started.md). The
Google Drive guide describes an optional team workflow and must not be read as
the default output policy; first-run output selection remains local and
operator-controlled.

## Editing rule

When a supporting record changes a current decision, update the canonical file
and leave the supporting record dated. Do not describe a file as archived unless
it has actually been moved under `archive/`.