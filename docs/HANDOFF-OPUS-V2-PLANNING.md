# Handoff: SVCS v2 End-to-End Planning Re-do

**Audience:** Claude Opus 4.8 (or equivalent successor), reasoning at maximum effort.
**Prepared by:** Claude (this session), 2026-05-31.
**Project owner:** Kheiven D'Haiti ("Bloodawn", `kheivendhaiti@gmail.com`).
**Repository:** `C:\Users\kheiven\Documents\GitHub\Video-compression_2026` (Windows host, git remote `origin` on GitHub `Blood-Dawn/Video-compression_2026`).

---

## 0. What you are being asked to do

The owner wants you to **re-do the entire v2 product plan from scratch with maximum effort**, then **produce a sequenced execution plan that can be handed directly to Claude Code** (the CLI tool, agentic, file-aware) to implement.

Two deliverables, in this order:

1. **`PLAN-V2.md`** - a comprehensive, opinionated, end-to-end product + technical plan. It must cover everything: market positioning, license model, feature list, architecture, build + release pipeline, monetization, support, distribution, telemetry, security, accessibility, internationalization, legal. Where current planning docs (`ROADMAP-V2.md`, `ARCHITECTURE.md`, `docs/REFACTOR-PLAN-gui-app.md`) are right, say so explicitly and keep them. Where they are wrong or thin, replace them with reasoning. Push back on weak ideas.

2. **`EXECUTION-CLAUDE-CODE.md`** - a sequenced, machine-actionable task list for Claude Code. Each task must include: a one-line summary, the files Claude Code needs to touch, the acceptance criterion (preferably a failing test that becomes passing), the rough size in lines / hours, dependencies on earlier tasks, and risk notes. Group into milestones. Assume Claude Code has full file I/O, can run shell commands, and follows repo conventions but does not have product context - you are translating product intent into engineering work.

Both deliverables should be written as markdown files inside `docs/` of this repo. Aim for length proportional to thoroughness, not brevity for its own sake. The owner reads everything.

You are not implementing anything in this handoff. You are planning. Implementation happens in subsequent sessions, mostly via Claude Code.

---

## 1. Product context

**SVCS** = **S**elective **V**ideo **C**ompression **S**ystem.

Origin: FAU EGN-4950C senior capstone, Spring 2026 semester, five-person team, sponsored by **Cody Hayashi (NIWC Pacific, DoD)** via the Defense Innovation Unit (DIU). Kickoff was March 23, 2026; sponsor handoff of v1.0.0 (frozen on `main`) was May 6, 2026. The original brief was: "lossless or near-lossless on the targets (people, vehicles), aggressive compression on everything else, for surveillance footage."

What it actually does: a Python pipeline that ingests video (file, RTSP, or live camera), runs background subtraction (MOG2) + optional YOLO object filter on each frame, partitions ROIs from background, and encodes the resulting segments in one of four modes:

- **Mode 0** - every frame kept, single-pass encode (baseline).
- **Mode 1** - dual-CRF: foreground regions at CRF 18 (visually lossless), background at CRF 45 (aggressive). One output file per segment.
- **Mode 2** - record only when targets are detected; idle background dropped entirely.
- **Mode 3** - per-object videos (rewritten 2026-05-02; was previously "blackout-in-full-frame"). Each detected object becomes its own short clip.

Encoded segments are indexed in a SQLite metadata DB (`metadata.db`, WAL mode) with rich fields: camera ID, timestamp, ROI count, file size, duration, object classes, vehicle/person counts, sharpness, dominant color, scene type, time of day, encryption metadata. A Flask-based browser dashboard (`src/gui/app.py`) is the v1 UI: live status, log stream over SSE, file browser, four-quadrant demo, HLS player, encryption (AES-256-GCM, PBKDF2 600k iters), preset import/export, GPU/network/system metrics, plate reader (premium-only).

**The pivot, March → May 2026:** what started as a sponsor deliverable is being productized into a **consumer + commercial open-source competitor to HandBrake**, expanded from surveillance-only to any video type (movies, vlogs, screen recordings, etc.). Dual-license: **AGPL-3.0 open source** + **paid commercial license** with **equal 5-way revenue split** among the team members. Kheiven is the designated licensing administrator (autonomous decisions up to $25k per the CLA).

**Competitors to position against:** HandBrake (mature, free, generic), FFmpeg + ffprobe directly (power users), Compressor / DaVinci (paid pro tools), Adobe Media Encoder (paid, ubiquitous), and the cloud encoders (Mux, AWS Elemental, Bitmovin). SVCS's wedge: **AI-aware compression** ("keep the faces and license plates sharp, throw bits at what matters, save 60%+ on storage with imperceptible loss"), **self-hosted-first** posture for the Plex/Jellyfin crowd, and a **mobile app** that compresses on the device in the background. None of the named competitors do all three.

---

## 2. Team and business

| Member | Role | Email | Cut |
|---|---|---|---|
| Kheiven D'Haiti (Bloodawn) | Lead, licensing administrator | kheivendhaiti@gmail.com | 20% |
| Jorge Sanchez | Benchmarks, CPU/battery | jorgesanchez2022@fau.edu | 20% |
| Ashleyn Montano | Object classification, color | amontano2023@fau.edu | 20% |
| Riley Roberts | Demo/concat, testing | robertsr2022@fau.edu | 20% |
| Victor De Souza Teixeira | Encryption, incident export | vdesouzateix2023@fau.edu | 20% |

CLA: equal 5-way split of net commercial revenue. Kheiven has autonomous authority for licensing decisions up to $25,000; above that requires majority team consent. Contributor License Agreement (`CLA.md`) is in the repo; any future external contributor signs it before merge.

Open-source casual edition: **free, AGPL-3.0**. Commercial edition: **paid**, terms in `LICENSE-COMMERCIAL.md`. Proposed pricing tiers (Indie / Startup / Enterprise / OEM) are placeholders and need real validation.

The team are students; this is summer work alongside whatever else they have going on. Riley's task 5.3 was reassigned to Kheiven on 2026-05-02. The instructor is handling the sponsor invite for task 5.6. Plan for a **realistic part-time pace**, not full-time staffing.

---

## 3. Current state, grounded in actual files

### What's on each branch as of 2026-05-31

| Branch | Purpose | State |
|---|---|---|
| `main` | v1.0.0 sponsor handoff, frozen | Tagged. Don't touch. |
| `dev` | v1.x bugfix line for any sponsor follow-up | Backlog of leftover capstone tasks (~48 hours of work) - see `ROADMAP-V2.md` "Backlog from v1" section. |
| `app` | v2 productization (Python + Flask, before Rust port) | **Active development.** All productization work lands here. |
| `premium` | Tracks `app`, adds premium-only features (plate reader, etc.) at build time | Mirrors `app` after every `app` commit. |
| `kdev` | Rust experiments (`svcs-core` crate scaffolding) | Empty for now; July milestone. |

### Latest commits on `app` (most recent first)

```
10cbda9 refactor: audit fixes - db.py split, Sentry opt-in, gui/app.py plan
a94ab80 build: PyInstaller desktop bundle for SVCS (audit item 6)
d097313 test: comprehensive coverage for v2 productization (102/102 passing)
e0257e8 chore: centralize defaults, structured logging, drop OneDrive default
746cab2 feat(installer): move state files to platform app-data dir
ef66145 chore: licensing pivot - Ultralytics back in core, plate reader premium-only
a300cdb chore: relicense as AGPL-3.0 dual-license, add v2 strategy docs
c2ba6e1 Merge dev to main for sponsor handoff (May 6 capstone)
```

### Test suite: 118 passing

7 test files added in productization, all green:

- `tests/test_paths.py` - platformdirs + legacy state-file migration (19)
- `tests/test_logging_config.py` - console + JSON Lines formatters (16)
- `tests/test_config.py` - compression CRFs, BG subtraction, encryption iters, GUI defaults (21)
- `tests/test_default_output_dir.py` - resolution order (persisted > cloud > Videos > repo fallback) (11)
- `tests/test_plate_backend_order.py` - EasyOCR-first selection (13)
- `tests/test_split_screen.py` - double-label fix regression guard (6)
- `tests/test_pipeline_real_video.py` - end-to-end on real CDnet clips (9)
- `tests/test_crash_reporting.py` - Sentry opt-in invariants (16)

Plus pre-existing tests under `tests/test_database.py`, `tests/test_metrics.py`, `tests/test_gui_api.py`, `tests/test_object_type_queries.py`, `tests/test_roi_encoder.py`, etc.

Pytest config: project-local `basetemp=.pytest_tmp`, `--tb=short -ra` in `pyproject.toml [tool.pytest.ini_options]`. Avoids the Windows `%TEMP%\pytest-of-kheiven` permission war that plagued the team for weeks.

### Installer

- `installer/launcher.py` - frozen entry point. Sets `SVCS_FROZEN=1`, splices `--no-sync` into argv (so the bundled exe doesn't try to call `uv sync`), primes `sys.path`, then imports `run_gui.main()`.
- `installer/svcs.spec` - PyInstaller spec, folder mode, hidden imports for Ultralytics/PyTorch/skimage/platformdirs, excludes Numba/sympy/torch.testing/paddleocr/Jupyter for size.
- `installer/build.ps1` - clean → install pyinstaller → build → smoke-test loop. Probes `http://127.0.0.1:5000/` for 60s after launch.

**First build outcome:** 4.7 GB unpacked, 219 sec build, smoke test passed. After exclude-list trimming, should land near 2.5 GB. FFmpeg expected on PATH; bundling it is a not-yet-done item.

### Audit fixes done

From the May 4 audit:

- ✅ Centralized `src/config.py` (compression CRFs, codec defaults, warmup, encryption iters, HLS targets, GUI defaults).
- ✅ Structured logging via `src/utils/logging_config.py` (console + JSON Lines).
- ✅ Platform-aware app-data dirs via `src/utils/paths.py` (platformdirs, OS-standard locations, one-shot migration of legacy repo-root state files).
- ✅ OneDrive removed as implicit default; new resolution order: persisted → cloud (opt-in only) → Videos/Movies/Documents → repo fallback.
- ✅ `print()` calls audited and replaced with logging in production paths.
- ✅ `src/utils/db.py` split into `src/utils/db/` package (`schema.py`, `queries.py`, `__init__.py` re-exports).
- ✅ Sentry SDK wired with **opt-in** crash reporting (`SVCS_ENABLE_SENTRY=1` AND `SENTRY_DSN` both required, PII off, traces=0, idempotent). Optional `[crash-reporting]` extra.
- ✅ PyInstaller bundle (audit item 6) - working .exe.

### Audit fixes still open

- ❌ `src/gui/app.py` (3835 lines, 48 routes) **not yet split**. Plan is saved in `docs/REFACTOR-PLAN-gui-app.md` - 12 blueprints + ~10 service modules. Multi-hour refactor.
- ❌ `src/gui/templates/index.html` (6000+ lines) **not split**. Frontend extraction into separate JS files under `src/gui/static/js/`. Lower risk than `gui/app.py` but still big.
- ❌ Bundled FFmpeg (currently expected on PATH).
- ❌ Inno Setup wrapper to produce `SVCS-Setup-x.y.z.exe`.
- ❌ macOS `.dmg` (signed + notarized) and Linux AppImage.
- ❌ Preset system v1 - 10 presets (Movie, Show, Vlog, Action, Animation, Screen Recording, Surveillance, Music Video, Archive, Mobile).
- ❌ Auto-detect content type (analyze first 30 seconds, recommend preset).
- ❌ Public download page (GitHub Pages or similar).
- ❌ RealESRGAN model weights bundling/CDN strategy.

### v2 future-state items (not started)

- Rust `svcs-core` crate (July target).
- Flutter UI + Android app (August target).
- Public beta tag `v2.0.0-beta` (September).

---

## 4. Architectural decisions, with rationale

These are decisions the team has made. If you disagree with any of them in your re-plan, **say so explicitly** with reasoning - but understand what's already committed.

### Dual license: AGPL-3.0 + commercial

Same playbook Ultralytics uses. AGPL means anyone who runs SVCS as a service must release their modifications, which is fine for hobbyists and self-hosters but unacceptable for companies who want to embed SVCS in a closed product. Those companies buy the commercial license. The team gets paid; the open-source casual edition stays free and full-featured.

**Why not MIT or Apache:** would let competitors take everything and not pay us back. AGPL forces the choice: contribute or buy.

**Why not pure proprietary:** kills the open-source community, kills the Plex/Jellyfin distribution channel, kills the "free download to try" funnel.

### Edition split via branches, not feature flags

`premium` tracks `app` and adds the `[plates]` extra (and future paid features) at build time, not via a runtime license-key check. Two physically separate installer binaries. The casual installer literally does not contain the paid code, so there's nothing to crack and no PII / license-check phone-home in the free edition. Build tooling difference is "include `[plates]` extra in PyInstaller spec" - that's it.

### Ultralytics (YOLO) stays in core deps

YOLOv8-nano under AGPL-3.0. Compatible with the AGPL casual edition. Commercial customers who can't take AGPL get an Ultralytics enterprise sublicense as part of their deal, or we swap to MediaPipe / RT-DETR via ONNX at sale time. **Future:** MediaPipe + RT-DETR via ONNX Runtime is the planned permissive replacement for v3.

### Rust core + Flutter UI for v2

Single Rust core (`svcs-core` crate) compiles to every platform. Flutter calls into it via `flutter_rust_bridge` (auto-generated FFI). One UI codebase for desktop + Android + (future) iOS. Avoids the React Native bridge tax, avoids Tauri's no-mobile-story, avoids Kotlin Multiplatform's no-UI-story.

### Migration strategy: Python first, Rust later

The June installer ships the **Python** Flask app inside PyInstaller. Real users get a working product in June. The Rust port proceeds in parallel on `kdev`. As Rust modules reach parity with their Python counterparts (validated against the 19 CDnet test clips), the Python orchestrator in `app` calls into Rust via FFI for hot-path work. The Flask UI eventually retires when the Flutter UI is ready (August).

### Storage / state files: platformdirs, not repo root

Was the single biggest installer-readiness blocker. Files like `.flask_secret`, `mode_cpu_avgs.json`, `gui_state.json` used to live next to the binary. Now they live under the platform's app-data dir (`%APPDATA%\SVCS` on Windows, `~/Library/Application Support/SVCS` on macOS, `~/.local/share/SVCS` on Linux) via `platformdirs`. Legacy files at the repo root are auto-migrated on first run.

### Crash reporting: opt-in only, double-guarded

Both `SVCS_ENABLE_SENTRY=1` AND `SENTRY_DSN` must be set, AND the optional `[crash-reporting]` extra must be installed. Casual installer doesn't ship `sentry-sdk` at all. The casual user never phones home unless they explicitly turn it on. Premium / enterprise builds may default it on (to be decided at premium-tier scoping time).

### Test discipline

Every change since the audit has shipped tests. 118 passing. Pre-existing pre-audit tests cover the pipeline core. Refactors must keep the suite green; new modules need their own tests in the same commit. **Real video integration tests** run against CDnet sample clips in `data/samples/cdnet_mp4/` - these caught issues no unit test could.

---

## 5. Known constraints and risks

- **Windows is the daily-driver dev environment.** macOS / Linux work happens in CI eventually. Anything that hits the filesystem must respect Windows-specific quirks (paths, ACLs, the `%TEMP%` permission war that fixed-by-`.pytest_tmp`).
- **Team is part-time, students, summer.** Schedules will slip. Plan should not assume a 40hr/wk full-time staff.
- **PyInstaller bundle size is 2.5-4.7 GB.** Acceptable for v1.x desktop, brutal for download. Real solution comes with the Rust port (single ~50 MB binary). For Inno Setup, expect a 1-2 GB installer download with optional model weight component.
- **FFmpeg licensing.** FFmpeg LGPL/GPL build choice matters when we bundle it. Default to LGPL build (less restrictive) and avoid GPL-only codecs unless we accept GPL on the bundled FFmpeg binary specifically. Document this carefully.
- **Ultralytics AGPL is a sale-time conversation.** It's compatible with our AGPL casual edition but is the single biggest licensing snag in commercial deals. Plan a clear story for it.
- **No CI yet.** All builds and tests run on Kheiven's machine. GitHub Actions setup is a needed but not-yet-done item.
- **No code signing yet.** Both Windows (Authenticode) and macOS (Developer ID + notarization) certs cost money and time. Plan for the first signed beta to be later than the first unsigned one.
- **No telemetry beyond opt-in crash reports.** No usage analytics, no preset-popularity tracking, no feature-adoption metrics. Future product decisions will be made on instinct unless we add some.
- **Mobile GPU paths are unproven.** ONNX Runtime supports CPU and most accelerators in theory; specific Android Adreno / Mali driver quirks may bite.
- **Real-ESRGAN model weights are 63 MB (x4plus).** Currently downloaded on first use; bundling means a fatter installer or a separate optional component.

---

## 6. Open questions you should resolve in PLAN-V2.md

- What are the **real** commercial pricing tiers? Current `LICENSE-COMMERCIAL.md` placeholder of Indie/Startup/Enterprise/OEM needs validation - talk through what each customer profile looks like, what they actually pay competitors today, and what value they get from SVCS that they don't get from HandBrake + FFmpeg.
- Should we offer a **hosted SaaS** tier (you upload, we compress)? The current `ARCHITECTURE.md` says no. Push back if you disagree.
- How does the **preset auto-detection** actually work? "Analyze first 30 seconds, recommend preset" - what's the actual classifier? Hand-engineered features (motion variance, scene change rate, color palette diversity)? A small CNN? A wrapper around an existing video-content classifier? Specify it.
- **Plex / Jellyfin integration** is listed as "out of scope for v2". Re-evaluate - these are the audiences who care most about self-hosted AI-aware compression, and a watch-folder plugin could be a wedge into the community.
- **Update channel mechanism.** Self-hosted apps need an updater. Build our own, use Squirrel/Sparkle, or skip auto-updates for v2?
- **Analytics / telemetry posture.** Current default is none. Do we want anonymous usage stats (preset popularity, codec choice, failure modes) opt-in or opt-out by default?
- **Internationalization.** v1 is English-only. When do we add i18n? Which languages first?
- **Accessibility.** Flask dashboard has zero accessibility audit. Flutter UI must be WCAG 2.1 AA at minimum. Plan when.
- **Mobile-specific features.** Battery-aware throttling? Storage-aware (don't compress if disk < N GB free)? Network-aware (don't upload results on cellular)? Spec these.
- **The Rust port has unmeasured risk.** What if the FFmpeg-next crate has a critical bug? What if `flutter_rust_bridge` breaks on iOS in 2027? Plan contingencies.

---

## 7. Working-style preferences (the user's, not yours)

These are well-established. Honor them in `EXECUTION-CLAUDE-CODE.md`.

- **The user pushes commits themselves.** Claude proposes commands, the user runs them. Do not assume CI or auto-push.
- **Delete completed tasks; don't pile.** Task trackers stay clean. Add → in_progress → completed → delete.
- **Commit signature:** `Bloodawn(KheivenD)`. End every commit message with that line.
- **Branches:** `app` is primary. After every commit on `app`, mirror to `premium` (`git checkout premium && git merge app && git push origin premium`).
- **Pacing:** the user values steady progress over heroic single-session marathons. Section large work into checkpointed chunks the user can review.
- **Tone:** direct, technical, no fluff. Avoid emojis, avoid breathy phrases ("genuinely", "honestly", "straightforward"). Get to the point.
- **Documentation:** docs go under `docs/`. Plans, runbooks, ADRs. The user reads them.
- **Tests are non-negotiable.** Every behavior change ships with a test. Every refactor proves regression-free by running the full suite.
- **Authorship comments:** load-bearing code blocks should include an inline author attribution comment when the user (or team) is adding non-obvious context. Example pattern already in the repo: `# Author: Bloodawn (KheivenD), 2026-05-14 (installer prep).`
- **No emojis in code or commits.**

---

## 8. Files to read first (in this order)

Read these in your sandbox before producing anything:

1. `ROADMAP-V2.md` - current rough roadmap (full text included in section 11 of this doc as appendix A).
2. `ARCHITECTURE.md` - current architecture decisions (full text in appendix B).
3. `LICENSE-COMMERCIAL.md` - commercial license terms.
4. `CLA.md` - contributor agreement (note the revenue split clause).
5. `CONTRIBUTING.md` - branch layout + contribution rules.
6. `docs/REFACTOR-PLAN-gui-app.md` - the saved plan for the `gui/app.py` refactor (you will fold this into `EXECUTION-CLAUDE-CODE.md` as one of the milestones).
7. `pyproject.toml` - current dependency picture, including `[plates]` and `[crash-reporting]` extras.
8. `src/gui/app.py` - the 3800-line monolith (skim, don't ingest fully).
9. `src/gui/templates/index.html` - the 6000-line frontend (skim).
10. `installer/svcs.spec`, `installer/launcher.py`, `installer/build.ps1` - current build system.
11. `tests/` - the test suite. Skim test names to understand what behaviors are pinned.
12. `DEV.md` (49 KB) and `ROADMAP.md` (68 KB) - historical context from the capstone phase. Skim, don't read end-to-end.

---

## 9. Output requirements

### `docs/PLAN-V2.md`

Sections (suggested; reorder if you have a better structure):

1. Executive summary (1 page max).
2. Market positioning and competitive landscape.
3. Customer profiles (open-source casual user, prosumer self-hoster, paying small business, paying enterprise, paying OEM).
4. Feature inventory by edition (casual vs premium).
5. Pricing strategy with reasoning (replace the placeholder tiers).
6. Architecture (extend / correct `ARCHITECTURE.md` - don't just restate it).
7. Detailed roadmap with monthly granularity through Q1 2027.
8. Build, release, and distribution pipeline.
9. Telemetry / privacy posture.
10. Security model (encryption-at-rest, key management, plate-reader PII handling, etc.).
11. Quality bar (tests, coverage targets, accessibility, internationalization).
12. Support and community model (Discord? GitHub Discussions? Paid support tier?).
13. Legal and licensing (FFmpeg LGPL/GPL choice, Ultralytics AGPL story, dependency audit).
14. Risk register with severity, likelihood, and mitigation for each.
15. Open questions remaining after your re-plan.

### `docs/EXECUTION-CLAUDE-CODE.md`

Sections:

1. How to use this document (instructions for the human handing tasks to Claude Code).
2. Repository conventions Claude Code must follow (branch, commit format, test discipline, authorship comments).
3. Milestones (probably matching the roadmap; one heading per milestone).
4. Under each milestone, an ordered list of tasks. Each task is a block of the form:

   ```
   ### TASK <id>: <verb-phrase title>
   **Milestone:** <name>
   **Depends on:** <task ids> (or `none`)
   **Estimated size:** <N> lines / <H> hours
   **Files:** path/a, path/b, path/c
   **Acceptance:**
     - <bullet criterion>
     - <bullet criterion, ideally a failing test that becomes passing>
   **Risks:** <one or two sentences>
   **Notes for Claude Code:** <pointers, gotchas, where to find similar prior work>
   ```

5. Glossary of project terms Claude Code will need (CDnet, MOG2, Mode 0-3, ROI, dual-CRF, segment, etc.).

Tasks should be sized so most fit in a single Claude Code session (≤ 500 lines of changes, ≤ 4 hours). Bigger tasks get broken down.

---

## 10. Process you should follow before writing

1. Read everything in section 8.
2. Make a list of decisions you want to either ratify or overturn from the current planning docs.
3. For each overturn, write the reasoning in the form: "Current doc says X. I believe Y because Z. Cost of being wrong: W."
4. Decide pricing by sketching what each customer profile pays for HandBrake / FFmpeg / Compressor / cloud encoders today, what time / money they save with SVCS, and how price-sensitive each is.
5. Sketch the build/release pipeline end-to-end - from `git push` on `app` to a downloaded `.exe` on a user's machine - and identify every step that doesn't exist yet.
6. Only then start writing.

---

## 11. Appendices

### Appendix A - `ROADMAP-V2.md` (verbatim, current state)

```
# SVCS v2 Roadmap

The v2 product is a consumer / commercial video compression toolkit. It
keeps the AI-aware compression engine from v1 but expands beyond
surveillance to any video and adds a real installer, a mobile app, and
auto-detected presets.

See ARCHITECTURE.md for the technical plan and LICENSE-COMMERCIAL.md
for the dual-license strategy.

## June 2026 - Desktop installer (Python, on `app` branch)
- Audit fixes landed (mostly done; gui/app.py + index.html splits remain)
- Premium branch live (done)
- PaddleOCR removed (done)
- Preset system v1 (10 presets) - NOT STARTED
- Auto-detect content type - NOT STARTED
- Windows installer via Inno Setup, bundling FFmpeg + Python + weights - NOT STARTED
- macOS .dmg signed + notarized - NOT STARTED
- Linux AppImage - NOT STARTED
- Public download page - NOT STARTED
- Crash reporting (Sentry opt-in) - DONE

## July 2026 - Rust core MVP (`kdev` branch) - NOT STARTED
## August 2026 - Flutter UI + Android app (`app` branch) - NOT STARTED
## September 2026 - Public beta - NOT STARTED

## Backlog from v1 (Python pipeline on `dev` branch)
~48 hours of leftover capstone tasks - color detection (Ashleyn),
contour-based object classifier (Ashleyn), adaptive mode controller
(Kheiven), Mode 2 background staleness (Kheiven), demo concat (Riley),
test_pipeline extensions (Riley), per-segment encryption (Victor),
password-protected export (Victor), per-mode CPU/battery benchmarks
(Jorge), AV1 benchmark doc (Jorge).
```

### Appendix B - `ARCHITECTURE.md` (key excerpts)

Stack:
```
Flutter UI (Dart, one codebase for desktop + Android + iOS-future)
        ↓ flutter_rust_bridge (FFI)
svcs-core (Rust crate)
  modules: frame_source, bg_subtract, detect, mode, encoder, enhance, db, crypto, preset
        ↓ C ABI
FFmpeg static + ONNX Runtime + OpenCV (via opencv-rust) + SQLite (rusqlite)
```

Phasing (current plan, possibly wrong, push back if so):

- Phase 1 (June): Python desktop installer ships.
- Phase 2 (June-July): Rust core skeleton compiles cross-platform.
- Phase 3 (July): Encoder ported, validated against Python on 19 CDnet clips.
- Phase 4 (August): BG subtraction + mode dispatch ported.
- Phase 5 (August): Flutter desktop UI prototype, mixed Rust+Python backend.
- Phase 6 (August/September): Flutter Android, pure Rust core.
- Phase 7 (Fall): Pure Rust desktop, Python retired from user-facing path.

Editions:
- Casual (built from `app`, AGPL-3.0, free, full feature set minus plate reader).
- Premium (built from `premium`, commercial license, casual + plate reader + future paid features).

### Appendix C - Memory facts the user wants preserved across sessions

These live in the agent memory system at
`C:\Users\kheiven\AppData\Roaming\Claude\local-agent-mode-sessions\bc113a3e-d95e-4975-903b-9fcf6f899152\7afec904-5ae9-4b89-80d6-f2a15ca19d25\spaces\099558e1-996f-4412-8bc5-d6bc0bb4ae94\memory\`:

- `project_kickoff_meeting.md` - DIU kickoff meeting takeaways with sponsor Cody Hayashi, NIWC Pacific, March 23, 2026.
- `feedback_pr_signature.md` - PR/commit signature `Bloodawn(KheivenD)` convention.
- `project_task_reassignments.md` - Riley's 5.3 reassigned to Kheiven on 2026-05-02; instructor handles 5.6 Cody invite.
- `project_plate_reader.md` - AI license-plate reader (post-process) shipped 2026-05-02; Real-ESRGAN + EasyOCR (was PaddleOCR) + multi-frame consensus.
- `project_mode3_sparse.md` - Mode 3 rewritten 2026-05-02 to per-object videos; was blackout-in-full-frame.

### Appendix D - Key file paths

- Repo root: `C:\Users\kheiven\Documents\GitHub\Video-compression_2026`
- GitHub remote: `Blood-Dawn/Video-compression_2026`
- Test sample clips: `data/samples/cdnet_mp4/baseline/baseline_pedestrians.mp4`, `data/samples/cdnet_mp4/intermittentObjectMotion/intermittentObjectMotion_parking.mp4`
- Pipeline entry point: `src/pipeline/pipeline.py::run_pipeline`
- GUI app: `src/gui/app.py`
- GUI template: `src/gui/templates/index.html`
- Launcher (frozen entry): `installer/launcher.py`
- PyInstaller spec: `installer/svcs.spec`
- Build wrapper: `installer/build.ps1`
- License files: `LICENSE`, `LICENSE-COMMERCIAL.md`, `CLA.md`
- Saved plans: `docs/REFACTOR-PLAN-gui-app.md`

### Appendix E - Branch / commit cheat sheet for `EXECUTION-CLAUDE-CODE.md`

Commit template:

```
<type>(<scope>): <subject line>

<body - explain *why*, not what>

Bloodawn(KheivenD)
```

`<type>`: `feat`, `fix`, `refactor`, `test`, `build`, `chore`, `docs`.

Push routine after every commit on `app`:

```
git push origin app
git checkout premium && git merge app && git push origin premium
git checkout app
```

---

## 12. Final notes for Opus 4.8

Push back where the current planning is weak. The owner respects strong arguments. Do not flatter or pad. If a section of this handoff is wrong, say so before you write your plan. If you need information that isn't here and can't be derived from reading the listed files, list your questions at the top of `PLAN-V2.md` as "questions outstanding" - do not invent answers.

Treat this as a real product launch, not a school project. The team is launching a real commercial offering. The plans you produce will be used.

 -  end of handoff  - 
