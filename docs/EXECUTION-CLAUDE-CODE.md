# SVCS v2 — Execution Plan for Claude Code

**Companion to:** `docs/PLAN-V2.md` (read it first; this is the engineering translation of it).
**Audience:** Claude Code (CLI, agentic, full file I/O, runs shell commands), driven by a human (Kheiven) who reviews and pushes commits.
**Generated:** 2026-05-31. **Revised** the same day to reflect: open-source-only (no commercial/premium track in v2), surveillance focus, and a new consumer/prosumer camera milestone (M-CAM).

---

## 1. How to use this document

A sequenced backlog. Each task is self-contained and sized to fit (mostly) in one Claude Code session (≤ ~500 changed lines, ≤ ~4 hours). Hand Claude Code **one task at a time**, in order, respecting `Depends on`.

For each task: Claude Code implements, runs the named tests, reports the diff; the human reviews, runs the suite, and **pushes the commit themselves** (Claude Code proposes the message and commands, never pushes). Mark done in your own tracker and delete — don't pile.

**Milestones are gates.** Don't start M1 until M0's gating tasks pass (suite reproducibly green). Don't start the Rust spike (M6) until the M0–M5 product has shipped a beta and the spike is explicitly green-lit.

When a task's acceptance criterion is "a failing test becomes passing," write the test first (red), then the implementation (green), in the same commit, unless the test already exists.

---

## 2. Repository conventions Claude Code must follow

**Branch.** `app` is the primary branch for all v2 work. `kdev` holds the Rust spike. `main` (frozen v1.0.0) and `dev` (v1.x bugfix line) are not touched by product work. **`premium` is dormant** — with no paid edition in v2, nothing new lands there (TASK 0.5 folds its one feature, the plate reader, back into `app`).

**No premium mirror.** The old "after every `app` commit, merge to `premium`" routine is **retired** (TASK 0.5). Just push `app`:
```
git push origin app
```

**Commit format** (`<type>` ∈ feat | fix | refactor | test | build | chore | docs):
```
<type>(<scope>): <subject line>

<body — explain WHY, not what>

Bloodawn(KheivenD)
```
Every commit ends with the `Bloodawn(KheivenD)` line. No emojis in commits or code.

**Test discipline.** Every behavior change ships a test in the same commit. Every refactor proves regression-free by a green suite. After M0, "green" means the CI-defined suite, not a hand-picked subset. Never hand-write a test count into prose — reference CI output.

**Authorship comments.** Load-bearing/non-obvious blocks get an inline attribution comment in the repo style, e.g. `# Author: Bloodawn (KheivenD), 2026-06-XX (ONNX swap).`

**Code style.** Black, ruff, type hints on new public functions, Python floor per TASK 0.4. No new deps without justification in the commit body.

**Pytest hygiene.** The project pins `basetemp=.pytest_tmp` and `--tb=short -ra` in `pyproject.toml` to dodge the Windows `%TEMP%` permission problem. Don't undo it.

**Windows is the daily driver.** Filesystem code respects Windows paths/ACLs/`%TEMP%`. macOS/Linux specifics get verified in CI.

---

## 3. Milestones overview

| Milestone | Theme | Branch | Gate |
|---|---|---|---|
| **M0** | Foundation: green baseline, CI, hygiene, fold plate reader into `app` | `app` | **Gating — blocks everything** |
| **M1** | Refactor: split `gui/app.py` + `index.html` | `app` | After M0 |
| **M2** | Slim installer: ONNX swap, bundle FFmpeg, Inno Setup | `app` | After M0 |
| **M3** | Surveillance presets v1 + content auto-detection | `app` | After M2 |
| **M-CAM** | Consumer/prosumer camera ingestion (ONVIF/RTSP, export watch-folder, bridges) | `app` | After M3 |
| **M4** | Self-host: watch-folder hardening, Docker, dashboard auth | `app` | After M1 |
| **M5** | Public beta: download page, unsigned beta, opt-in stats, camera-setup docs | `app` | After M2, M3, M-CAM |
| **M5b** | Signing + macOS/Linux packaging | `app` | After M5 |
| **M6** | Rust encoder spike (gated, measured go/no-go) | `kdev` | After beta + explicit green-light |

There is **no commercial/premium milestone** in v2. A future commercial fork, if the team is ever legally cleared and chooses to pursue one, is out of scope here (PLAN-V2 §13); the dormant `premium` branch is its natural seam.

---

## M0 — Foundation (gating)

> Nothing downstream is trustworthy until the suite is reproducibly green and CI enforces it. PLAN-V2 §11: the most recent full run was **48 failed / 465 passed / 5 errors**, contradicting the "all green" claims. Fix that first.

### TASK 0.1: Capture a reproducible test baseline
**Milestone:** M0 · **Depends on:** none · **Size:** ~40 lines, 1–2 h
**Files:** `scripts/run_tests.(ps1|sh)`, `docs/test-baseline.md`
**Acceptance:**
- One committed command runs the full suite on a clean checkout with documented extras (`uv sync --extra enhance --extra plates --extra crash-reporting`), pinned to the project pytest config.
- Its exact output (pass/fail/skip/error counts) captured in `docs/test-baseline.md` with date, commit SHA, OS, Python version.
- No fixes yet — establish ground truth only.
**Risks:** Some failures are environment-only (missing optional dep). Distinguishing them is 0.2.
**Notes:** `pytest_final.log` (2026-05-14) had 48 failed/465 passed/5 errors; whole-file failures (`test_encryption`, `test_crash_reporting`, `test_gui_api`) suggest extras/import issues. Confirm which extras each red file needs.

### TASK 0.2: Triage and classify every failure and error
**Milestone:** M0 · **Depends on:** 0.1 · **Size:** ~30 lines notes + small fixes, 2–4 h
**Files:** `docs/test-baseline.md` (triage table), `tests/conftest.py` or affected modules
**Acceptance:** A table classifying each failure/error as (a) missing-optional-dep, (b) collection/import error, (c) real regression, (d) env flake. Nothing left unexplained.
**Risks:** A "real regression" may hide a genuine bug; treat any in `crypto`/`encryption`/`pipeline` as high priority.
**Notes:** Run each red file in isolation with its extras — quickly separates env from logic failures.

### TASK 0.3: Make the suite reproducibly green
**Milestone:** M0 · **Depends on:** 0.2 · **Size:** ≤ 500 lines, 2–4 h (split if larger)
**Files:** affected `tests/*` and `src/*`
**Acceptance:** `scripts/run_tests.*` exits 0 on a clean checkout with documented extras. Every previously-failing test passes or is `skip`/`xfail` with a reason + tracking note. Optional-dep tests gated via `importorskip`.
**Risks:** Faking green via skips. Skips need reasons; a skipped crypto test is not acceptable, a skipped easyocr test on a casual checkout is.
**Notes:** If large, split into 0.3a/0.3b by subsystem (crypto, gui, crash-reporting); keep each commit green.

### TASK 0.4: Repo hygiene and version reconciliation
**Milestone:** M0 · **Depends on:** 0.3 · **Size:** ~80 lines, 1–2 h
**Files:** new `.gitattributes`, `pyproject.toml`, `CONTRIBUTING.md`, `src/utils/db_query.py` (remove)
**Acceptance:**
- **Line-ending normalization (do this FIRST, as its own commit):** the working tree currently has **109 files showing as modified, pure CRLF↔LF churn**, with **no `.gitattributes`** (verified 2026-05-31 — see `docs/test-baseline.md` "repo-wide line-ending churn"). Add a `.gitattributes` (`* text=auto eol=lf`, `*.ps1`/`*.bat` `eol=crlf`, binaries marked `binary`), run `git add --renormalize .`, and commit as a single isolated `chore: normalize line endings (.gitattributes)` — separate from every functional change. `git status` clean afterward. **This must land before the other 0.4 edits and before any M1+ work, or every later diff is buried in whitespace noise.**
- `requires-python` and the "Python 3.11+" claim in `CONTRIBUTING.md` agree (recommend 3.11).
- `version` bumped off `0.1.0` to a v2 dev scheme (e.g. `2.0.0.dev0`); `v1.0.0` stays tagged on `main`.
- Legacy `src/utils/db_query.py` (superseded by `src/utils/db/`) removed and imports updated; suite green.
**Risks:** The renormalize commit touches ~109 files — that's expected and is exactly why it's isolated. Confirm `git diff --ignore-all-space` is empty before committing so no real change rides along. Also: something may still import `db_query` — grep before deleting.
**Notes:** `src/utils/db/` (`schema.py`, `queries.py`, `__init__.py`) is the live package. The CRLF index/worktree mismatch is shown by `git ls-files --eol`.

### TASK 0.3b: Gate plate-reader tests; keep easyocr out of the core env
**Milestone:** M0 · **Depends on:** 0.2 · **Size:** ~40 lines, 1 h
**Files:** `tests/test_plate_reader.py`, `tests/test_plate_backend_order.py`, `tests/conftest.py`, `scripts/run_tests.*` (already updated)
**Acceptance:**
- Plate-reader tests `importorskip("easyocr")` (or skip when no OCR backend is present) so a core checkout without `[plates]` skips them cleanly instead of failing.
- The default test/CI environment does **not** install `[plates]` (easyocr), because it breaks `cv2` (see `docs/test-baseline.md` "OpenCV / easyocr conflict"). Plate-reader tests are validated in a separate, dedicated environment.
- `scripts/run_tests.ps1`/`.sh` sanity-check `cv2` after sync (done) and exclude `[plates]` by default (done) — verify these are committed.
**Risks:** Skipping must be conditional on the backend being absent, not unconditional — a `[plates]` environment must still run them.
**Notes:** This is the immediate mitigation; TASK 0.4b is the real dependency fix. The 8 collection errors from the 2026-05-31 re-baseline were entirely this conflict.

### TASK 0.4b: Fix the OpenCV dependency (declare contrib; resolve the easyocr clash)
**Milestone:** M0 · **Depends on:** 0.4 · **Size:** ~50 lines, 2–3 h
**Files:** `pyproject.toml`, `uv.lock`, `docs/test-baseline.md`
**Acceptance:**
- **DONE (pyproject):** the core dependency is now `opencv-contrib-python>=4.8.0,<4.11.0` (the code calls `cv2.bgsegm.createBackgroundSubtractorGMG`, a contrib-only module — `background_subtraction.py:180`). A fresh `uv sync` now installs a `cv2` with both MOG2 and GMG, with no manual `uv pip install` needed.
- **Regenerate the lock:** run `uv lock` (or `uv sync`) so `uv.lock` records `opencv-contrib-python`; commit `pyproject.toml` + `uv.lock` together.
- **Plates stays in a separate environment — there is NO clean single-env coexistence.** `opencv-contrib-python` (core) and `opencv-python-headless` (easyocr) are distinct PyPI packages that write the same `cv2/` files and clobber each other; a `[tool.uv]` override cannot fix this (it can re-pin a version, not rename/merge two packages). So the policy is: the default/dev/CI env never installs `[plates]`; the plate reader is installed and validated in a dedicated virtualenv (TASK 0.3b). The `[plates]` extra comment in `pyproject.toml` documents this.
**Acceptance check:** a clean `uv sync` (no extras beyond enhance/crash-reporting) + `scripts/run_tests.ps1` is green without any manual opencv reinstall.
**Risks:** none material — this removes a fresh-clone footgun. The longer-term thinning of these heavy vision deps is the ONNX migration (PLAN-V2 §6, M2). Note `cv2.imshow` preview (`pipeline.py:658`) needs a non-headless build, which contrib is — preview still works.

### TASK 0.5: Fold the plate reader into `app`; retire the premium mirror
**Milestone:** M0 · **Depends on:** 0.3 · **Size:** ~120 lines, 2–3 h
**Files:** `pyproject.toml` (`[plates]` extra), `src/enhancement/plate_reader.py`, `src/gui/` (plate routes/UI), `CONTRIBUTING.md`, `ARCHITECTURE.md`
**Acceptance:**
- The plate reader (currently premium-only) is available in the open-source `app` build as a **free** optional `[plates]` extra (EasyOCR). The dashboard keeps hiding the plate-reader controls when the backend isn't installed (existing behavior).
- `CONTRIBUTING.md`'s `app`-vs-`premium` section and any "premium-only" language updated to reflect a single open-source edition.
- The "merge `app` → `premium` after every commit" instruction removed from `CONTRIBUTING.md`.
- Suite green.
**Risks:** If the plate reader already lives only on `premium`, cherry-pick or re-implement it onto `app`. Confirm where the code currently is (the handoff says premium-only; `src/enhancement/plate_reader.py` exists on `app` per the tree — verify it's wired, not dead).
**Notes:** PLAN-V2 §4/§13. `premium` goes dormant (don't delete — it's the seam for a possible future commercial fork). EasyOCR is Apache-2.0, fine in AGPL.

### TASK 0.6: Resolve the dormant commercial-license docs
**Milestone:** M0 · **Depends on:** none · **Size:** ~20 lines, 0.5 h
**Files:** `CLA.md`, `LICENSE-COMMERCIAL.md`, `README.md`
**Acceptance:** Per the owner's choice (PLAN-V2 §15 item 6), either (a) mark `CLA.md` and `LICENSE-COMMERCIAL.md` with a clear header — "DORMANT — not in force; the project is open-source AGPL-3.0 only; retained as a draft for a possible future commercial fork" — or (b) remove them and note in `README.md` that the project is AGPL-3.0 only. Default to (a) unless told otherwise. `README.md` states clearly: free, open source, AGPL-3.0, no paid edition.
**Risks:** Leaving them unmarked makes contributors think there's a paid tier. Low effort, prevents confusion.
**Notes:** Don't delete git history; just the working tree per choice.

### TASK 0.7: GitHub Actions CI (build + test, no auto-deploy)
**Milestone:** M0 · **Depends on:** 0.3 · **Size:** ~120 lines YAML, 2–3 h
**Files:** `.github/workflows/ci.yml`
**Acceptance:** On push/PR to `app`, CI installs deps and runs the green suite on windows-latest + ubuntu-latest, prints pass/fail counts, fails on any non-skipped failure, and records a coverage floor (fails if coverage drops below baseline). CI does **not** push/deploy/sign.
**Risks:** Torch/CUDA install is heavy on CI. Until M2's ONNX swap, pin CPU-only torch wheels; document it.
**Notes:** No `.github/` exists today. Use `uv` + lockfile. macOS runner waits for M5b.

---

## M1 — Refactor (after M0)

> Executes `docs/REFACTOR-PLAN-gui-app.md` (sound and detailed). Each step leaves the suite green.

### TASK 1.1: Extract `gui/state.py` and `gui/logging_setup.py`
**Milestone:** M1 · **Depends on:** 0.7 · **Size:** ~250 lines moved, 2–3 h
**Files:** `src/gui/app.py`, new `src/gui/state.py`, new `src/gui/logging_setup.py`
**Acceptance:** Pure-data globals → `state.py`; handlers + atexit → `logging_setup.py`. `gui/app.py` re-exports every private name `tests/test_gui_api.py` touches; `from gui.app import app` still works. New `tests/test_gui_state_reexports.py` asserts each name resolves via `gui.app` and round-trips on mutation. Suite green.
**Risks:** `global _pipeline_thread` mutation hits a stale copy after extraction. Use the `__getattr__`/`__setattr__` forwarding in REFACTOR-PLAN §5.
**Notes:** Hard constraints in REFACTOR-PLAN §0. Imports one-way: services → state/logging, blueprints → services, `gui.app` → blueprints, nothing → `gui.app`.

### TASK 1.2: Extract the services layer
**Milestone:** M1 · **Depends on:** 1.1 · **Size:** ~400 lines moved, 3–4 h (split per migration order)
**Files:** new `src/gui/services/{path_safety,cloud_detection,gui_state_persist,db_helpers,cpu_sampler,rtsp,demo_runner,hls_runner,pipeline_runner}.py`, `src/gui/app.py`
**Acceptance:** Each service per REFACTOR-PLAN §2/§3. Import-time `_bg_hw_thread` → explicit `start_hw_sampler()` from `create_app()`. `pipeline_runner` last. Suite green after each module (commit per module).
**Risks:** Circular imports; SSE generator closure; atexit ordering. Mitigations in REFACTOR-PLAN §5.
**Notes:** Follow REFACTOR-PLAN §4 order exactly — sequenced to stay green.

### TASK 1.3: Carve routes into 12 blueprints
**Milestone:** M1 · **Depends on:** 1.2 · **Size:** ~450 lines moved, 3–4 h (smallest first)
**Files:** new `src/gui/routes/*_bp.py` (12), `src/gui/app.py` (thin: `app` + `create_app()` + registration + re-exports)
**Acceptance:** 48 routes across the 12 blueprints in REFACTOR-PLAN §1. New `tests/test_gui_blueprint_registration.py` (route count + endpoints) and `tests/test_gui_routes_resolve.py` (every URL resolves). `gui/app.py` ~80 lines. Suite green.
**Risks:** A missed/renamed route breaks frontend fetches. Route-count assertion guards; diff endpoint names against `index.html` fetches.
**Notes:** Carve order: ui → sse → metrics → presets → encryption → plates → queries → rtsp → demo → hls → files → pipeline.

### TASK 1.4: Update PyInstaller spec for the new module tree
**Milestone:** M1 · **Depends on:** 1.3 · **Size:** ~40 lines, 1 h
**Files:** `installer/svcs.spec`
**Acceptance:** `hiddenimports` lists every new `gui.state`/`gui.logging_setup`/`gui.services.*`/`gui.routes.*`. `installer/build.ps1` runs clean; smoke test (probe `http://127.0.0.1:5000/`) passes.
**Risks:** PyInstaller drops a dynamically-imported blueprint → runtime ImportError only in the frozen build. The smoke test guards.
**Notes:** `svcs.spec` is folder-mode with explicit hidden imports.

### TASK 1.5: Split `index.html` into JS modules + extract i18n strings
**Milestone:** M1 · **Depends on:** 1.3 · **Size:** ≤ 500 lines moved per commit, 3–4 h (split 1.5a/b/c by feature)
**Files:** `src/gui/templates/index.html` (7,026 lines), new `src/gui/static/js/*.js`
**Acceptance:** Inline scripts → feature-grouped JS files (pipeline control, file browser, demo/quadrant, HLS player, metrics, encryption, presets). User-facing strings routed through a single `strings.js` catalog (i18n groundwork — do **not** translate yet). Dashboard loads, every panel works; `test_gui_api` green.
**Risks:** A broken fetch URL or lost handler is silent until clicked. Split by feature; verify each panel.
**Notes:** Keep the four-quadrant demo and HLS player intact — demo-day surface.

---

## M2 — Slim installer (after M0)

> Highest-value engineering bet (PLAN-V2 §6 Pushback 1, §8): installer 2.5–4.7 GB → ~400–600 MB by replacing PyTorch with ONNX Runtime, no Rust.

### TASK 2.1: Export YOLOv8n and Real-ESRGAN to ONNX; add an ONNX inference path
**Milestone:** M2 · **Depends on:** 0.7 · **Size:** ~300 lines, 4 h
**Files:** `src/detection/object_filter.py`, `src/enhancement/enhancer.py`, new `src/detection/onnx_backend.py`, new `src/enhancement/onnx_backend.py`, `pyproject.toml`
**Acceptance:** An `onnxruntime` backend produces detection boxes within an agreed tolerance of the PyTorch backend on the CDnet clips (a parity test asserts it). Backend selectable; PyTorch stays behind a flag/extra during transition. Models exported to ONNX, stored/documented (weights stay an optional component, not committed binaries).
**Risks:** Real-ESRGAN ONNX export can be finicky (dynamic shapes/custom ops). If x4plus won't export cleanly, ship detection-on-ONNX first, enhancement follow-up.
**Notes:** Validate against `data/samples/cdnet_mp4/...`. Agree the parity metric (box IoU / count match) with the human first. Keep the backend detector-agnostic — it's also the future RT-DETR seam (PLAN-V2 §13), at zero extra cost now.

### TASK 2.2: Make PyTorch optional, default to ONNX, shrink the exclude list
**Milestone:** M2 · **Depends on:** 2.1 · **Size:** ~120 lines, 2–3 h
**Files:** `pyproject.toml`, `installer/svcs.spec`
**Acceptance:** Default install uses ONNX Runtime; `torch`/`ultralytics` move to an optional `[torch]` extra (for parity testing/export only). `svcs.spec` excludes torch/CUDA; smoke test passes. Measured unpacked size recorded in `docs/build-metrics.md`.
**Risks:** A transitive torch dependency (skimage/basicsr) keeps it in. Audit the PyInstaller dependency graph.
**Notes:** Default build must not ship torch.

### TASK 2.3: Bundle LGPL FFmpeg
**Milestone:** M2 · **Depends on:** 0.7 · **Size:** ~150 lines, 2–3 h
**Files:** `installer/build.ps1`, `installer/svcs.spec`, `src/utils/` (FFmpeg path resolution), new `docs/ffmpeg-licensing.md`
**Acceptance:** Build vendors an FFmpeg binary; the app resolves FFmpeg from the bundle first, PATH second (no longer *requires* PATH). `docs/ffmpeg-licensing.md` documents the LGPL/GPL/x264/x265/HEVC matrix (PLAN-V2 §13 — for the AGPL project, GPL-FFmpeg-with-x265 is fine; the doc is readiness for a possible future fork). A test asserts the app finds the bundled FFmpeg when PATH lacks it.
**Risks:** None blocking for the AGPL build. Keep the FFmpeg version pinned and recorded.
**Notes:** The licensing doc matters as much as the code.

### TASK 2.4: Inno Setup installer with optional model-weights component
**Milestone:** M2 · **Depends on:** 2.2, 2.3 · **Size:** ~200 lines, 3–4 h
**Files:** new `installer/svcs.iss`, `installer/build.ps1`
**Acceptance:** `iscc installer/svcs.iss` produces `SVCS-Setup-x.y.z.exe`. Optional "AI model weights" component (~70 MB ONNX) so the base download stays small; first run fetches if skipped. Installs to Program Files, Start Menu shortcut, app launches and serves the dashboard. Installer download hits the ~400–600 MB target.
**Risks:** Inno Setup is Windows-only, not in CI yet; build/test locally on Windows. Uninstall must not touch `%APPDATA%\SVCS` data unless asked.
**Notes:** No `.iss` today. The Inno install must invoke the frozen entry point (`installer/launcher.py` sets `SVCS_FROZEN=1`, splices `--no-sync`).

---

## M3 — Surveillance presets + auto-detection (after M2)

### TASK 3.1: Preset system v1 (surveillance-centric, modes hidden)
**Milestone:** M3 · **Depends on:** 2.2 · **Size:** ~300 lines, 3–4 h
**Files:** new `src/pipeline/presets.py`, `src/config.py`, `src/gui/routes/presets_bp.py`, `src/gui/static/js/presets.js`
**Acceptance:** A named preset family centered on surveillance: e.g. **Continuous CCTV (max savings)**, **Motion-event cam**, **Doorbell**, **Multi-camera / NVR**, **Active scene**, **Archive (visually lossless)**, plus a few general ones (Screen recording, Generic). Each maps to a (mode, foreground-CRF, background-CRF, codec) tuple. UI exposes **presets by name**, not "Mode 0–3" (PLAN-V2 §6 Pushback 3); raw mode control behind an "Advanced" toggle. New `tests/test_presets.py` asserts each preset resolves to a valid encode config and round-trips through import/export.
**Risks:** CRF values need real test encodes to tune, not guesses. Use `docs/mode_size_hierarchy.md` (Mode 2 largest; sparse Mode 3 wins on 1080p+ multi-object).
**Notes:** Preset import/export already exists in the config blueprint — extend it. Document each preset's mode mapping + rationale in comments.

### TASK 3.2: Content auto-detection (rule-based)
**Milestone:** M3 · **Depends on:** 3.1 · **Size:** ~250 lines, 3–4 h
**Files:** new `src/pipeline/content_detect.py`, `src/gui/routes/presets_bp.py`
**Acceptance:** Analyze the first ~30 s; extract foreground-area ratio (reuse MOG2 output), scene-change rate, motion variance, resolution, frame rate, luma/color distribution, audio presence. A rule set / small decision tree maps to a recommended **surveillance** preset (PLAN-V2 §16). New `tests/test_content_detect.py` asserts known clip types get the expected preset (CDnet surveillance clip → "Continuous CCTV"; sparse-motion clip → "Motion-event"). **Not a CNN.**
**Risks:** Misclassification on edge cases (static-camera vlog). Fine for v1 — user overrides; instrument (M5 stats) and learn. Don't over-tune on the tiny CDnet set.
**Notes:** MOG2 foreground ratio is the strongest free signal — start there. Keep the interface swappable for a future learned model.

---

## M-CAM — Consumer & prosumer camera ingestion (after M3) — NEW

> PLAN-V2 §2/§6 Pushback 4. Serve homeowners with Ring/Nest/Wyze/Reolink/Arlo, not just pro CCTV. Honest split: RTSP/ONVIF cams ingest directly; cloud-locked cams go through exported clips or a bridge. **No vendor-cloud scraping.**

### TASK M-CAM.1: ONVIF discovery + RTSP auto-config
**Milestone:** M-CAM · **Depends on:** 1.3 · **Size:** ~300 lines, 3–4 h
**Files:** new `src/utils/onvif_discovery.py`, `src/utils/frame_source.py`, `src/gui/routes/` (a camera-setup endpoint), `src/gui/static/js/cameras.js`, `tests/test_onvif_discovery.py`
**Acceptance:** The app discovers ONVIF cameras on the local network (WS-Discovery), lists them in the dashboard, and lets the user add one as an RTSP source with auto-filled stream URL + credentials. Direct-RTSP cameras (Reolink, Amcrest, Hikvision, Dahua, Wyze-with-RTSP) become first-class sources. `tests/test_onvif_discovery.py` covers parsing a mocked ONVIF response and building the RTSP URL.
**Risks:** ONVIF dialects vary by vendor; discovery may miss some. Degrade gracefully to manual RTSP-URL entry. Network discovery needs care on Windows firewall.
**Notes:** `src/utils/frame_source.py` already handles RTSP — extend it, don't replace. Keep credentials out of logs (PLAN-V2 §10).

### TASK M-CAM.2: Export-folder watch presets for camera clips
**Milestone:** M-CAM · **Depends on:** 4.1, 3.2 · **Size:** ~200 lines, 2–3 h
**Files:** `src/utils/watchfolder.py`, new `docs/camera-ingestion.md`
**Acceptance:** Watch-folder profiles tuned to common camera export/recording layouts: timestamped continuous-recording files, per-event motion clips (microSD dumps, NAS sync folders, NVR exports). New media is auto-detected (TASK 3.2), compressed, and written to an output tree without manual clicks. `docs/camera-ingestion.md` documents the setup per camera family.
**Risks:** Partial writes (a clip still syncing). Reuse the stability check from TASK 4.1. Vendors name files differently; keep the profiles data-driven, not hard-coded.
**Notes:** This is the **universal** path that works even for cloud-locked cams (via their export/download), and the primary one for the consumer audience.

### TASK M-CAM.3: Bridge-ingestion guide + RTSP hand-off for cloud-locked cams
**Milestone:** M-CAM · **Depends on:** M-CAM.1 · **Size:** ~120 lines (mostly docs + config), 2 h
**Files:** `docs/camera-ingestion.md`, `src/gui/static/js/cameras.js` (a "via bridge" help affordance)
**Acceptance:** A documented, tested path for Ring/Nest/Arlo and similar cloud-locked cameras: ingest through **Home Assistant / Scrypted / Frigate**, which re-expose the camera as a local RTSP stream that SVCS consumes via TASK M-CAM.1. The doc is explicit that SVCS does **not** access vendor clouds directly and explains the two supported options (export-folder per M-CAM.2, or a bridge). The dashboard's camera-add screen links to this guide when a user looks for an unsupported brand.
**Risks:** Over-promising. The doc must set honest expectations (PLAN-V2 R-CAM): "Ring/Nest don't offer local streams; here's how to bring them in via a bridge or by compressing your exports." Don't build vendor-cloud integrations.
**Notes:** Frigate/Home Assistant/Scrypted are exactly the prosumer self-hoster ecosystem (PLAN-V2 §3/§12). No code dependency on them — we just consume the RTSP they emit.

### TASK M-CAM.4: Consumer-camera preset family
**Milestone:** M-CAM · **Depends on:** 3.1, M-CAM.2 · **Size:** ~120 lines, 2 h
**Files:** `src/pipeline/presets.py`, `tests/test_presets.py`
**Acceptance:** Presets tuned for consumer footage: **Doorbell (porch/entry)**, **Indoor cam (pets/home)**, **Outdoor yard cam**, **Baby/pet monitor (long idle)**. Each maps to a sensible mode/CRF tuple given the scene (mostly-static with sparse events → aggressive background, gated foreground). Tests assert valid configs.
**Risks:** Consumer footage is lower-res and noisier than pro CCTV; over-aggressive background CRF can smear important detail. Tune conservatively; lean on the "keep what matters sharp" guarantee.
**Notes:** These sit alongside the surveillance presets from TASK 3.1.

---

## M4 — Self-host hardening (after M1)

### TASK 4.1: Harden watch-folder automation
**Milestone:** M4 · **Depends on:** 1.3, 3.1 · **Size:** ~250 lines, 3 h
**Files:** `src/utils/watchfolder.py`, `tests/test_watchfolder.py`
**Acceptance:** Point at a directory; new media is detected, preset auto-detected (3.2), compressed in background, written out — no clicks. Handles partial writes (size stable for N seconds before processing), dedupe, crash-resume. `tests/test_watchfolder.py` extended for partial-write + resume.
**Risks:** Compressing a file mid-copy corrupts output. The stability check is the guard.
**Notes:** `src/utils/watchfolder.py` + `tests/test_watchfolder.py` already exist — extend. This underpins M-CAM.2.

### TASK 4.2: Docker image for the server scenario
**Milestone:** M4 · **Depends on:** 2.3, 4.4 · **Size:** ~120 lines, 2–3 h
**Files:** new `Dockerfile`, new `docker-compose.yml`, `docs/deployment_packaging.md` (status update)
**Acceptance:** `docker build` → image running the Flask app; `docker run -p 5000:5000 -v ...` serves the dashboard. Uses the ONNX/slim path (post-M2) so it isn't 4 GB. `docs/deployment_packaging.md` "Option 1 Docker — Not implemented" updated to done.
**Risks:** Image size (the doc warns 2–4 GB with torch) — why this is post-M2. Don't ship the image before dashboard auth (4.4) exists.
**Notes:** `docs/deployment_packaging.md` sketches the Dockerfile — start there.

### TASK 4.3: ~~(removed)~~
*(Intentionally empty — the old Plex/Jellyfin task is absorbed into M-CAM.3, since for surveillance the relevant ecosystem is Frigate/Home Assistant/Scrypted, not media servers.)*

### TASK 4.4: Dashboard auth for the server profile
**Milestone:** M4 · **Depends on:** 1.3 · **Size:** ~150 lines, 2–3 h
**Files:** `src/gui/app.py` (or new `src/gui/auth.py`), `docs/deployment_packaging.md`
**Acceptance:** When the app binds to anything other than `127.0.0.1`, it requires basic auth (configurable credential) OR refuses to start without an explicit `--no-auth` override. Localhost stays auth-free. A test asserts a non-localhost bind without credentials is rejected.
**Risks:** Real gap today (PLAN-V2 §10, R-AUTH): no auth, and the server scenario (and a NAS deployment) serves on `0.0.0.0`. Ship this before the Docker image (4.2).
**Notes:** HTTP basic auth behind the user's reverse proxy is the documented expectation; the app just must not be wide open by default.

---

## M5 — Public beta (after M2, M3, M-CAM)

### TASK 5.1: Public download page
**Milestone:** M5 · **Depends on:** 2.4 · **Size:** ~200 lines, 2–3 h
**Files:** new `docs/site/` (GitHub Pages), `README.md`
**Acceptance:** A static page links the latest installer from GitHub Releases, shows SHA-256 checksums, states system requirements. Copy leads with the surveillance/self-hosted/open-source wedge (PLAN-V2 §2), no competitor comparisons.
**Risks:** None major; keep it static (no CDN, matching the project's no-React/no-CDN posture).
**Notes:** Plain HTML/CSS; links point at GitHub Releases artifacts.

### TASK 5.2: Opt-in anonymous usage-stats channel
**Milestone:** M5 · **Depends on:** 0.7 · **Size:** ~200 lines, 3 h
**Files:** new `src/utils/usage_stats.py`, `src/gui/` (first-run consent), `tests/test_usage_stats.py`
**Acceptance:** A **separate** channel from crash reporting (PLAN-V2 §9): preset popularity, codec choice, encode success/failure, anonymized error categories, **and which camera-ingestion path is used** (RTSP/ONVIF vs watch-folder vs bridge) — to guide M-CAM investment. No footage, file contents, paths, PII, or reinstall-surviving IDs. Default **off**; first-run consent; settings toggle. `tests/test_usage_stats.py` asserts nothing sent when off and payloads carry no PII/path fields.
**Risks:** Privacy is the wedge; a leak is reputational. The PII-exclusion test guards.
**Notes:** Mirror crash-reporting's opt-in discipline as a distinct subsystem with its own consent.

### TASK 5.3: Camera-setup + getting-started docs
**Milestone:** M5 · **Depends on:** M-CAM.3 · **Size:** ~150 lines docs, 2 h
**Files:** `docs/getting-started.md`, `docs/camera-ingestion.md` (finalize)
**Acceptance:** User-facing getting-started (install → point at a folder or camera → compress) and a camera compatibility table: which cameras work directly (RTSP/ONVIF), which need a bridge (Ring/Nest/Arlo), which need export-folder. Honest about the cloud-locked limitation.
**Risks:** The compatibility table will age as firmware changes; mark it "community-maintained, last updated X."
**Notes:** High-leverage for the consumer audience (PLAN-V2 §12).

### TASK 5.4: Tag and publish unsigned public beta
**Milestone:** M5 · **Depends on:** 5.1, 5.2, 5.3, 3.2, 4.1 · **Size:** ~60 lines, 1–2 h
**Files:** `docs/RELEASE-CHECKLIST.md`, release notes
**Acceptance:** A repeatable release checklist (build, run suite, smoke-test installer, checksums, draft GitHub Release). `v2.0.0-beta` tagged; unsigned Windows installer published with a clear "unsigned beta — SmartScreen will warn" note.
**Risks:** Unsigned installer triggers SmartScreen (R6); set expectations in notes; signing is M5b.
**Notes:** The human tags/pushes; Claude Code produces the checklist + draft notes.

---

## M5b — Signing + macOS/Linux (after M5)

### TASK 5b.1: Windows code signing
**Milestone:** M5b · **Depends on:** 5.4, (external: cert or SignPath OSS approval) · **Size:** ~80 lines, 1–2 h + lead time
**Files:** `installer/build.ps1`, `docs/RELEASE-CHECKLIST.md`
**Acceptance:** The build signs the installer; a signed GA build is published; checklist updated.
**Risks:** Cert acquisition has lead time/cost (PLAN-V2 §0 item 3). Investigate SignPath.io's free OSS signing program before buying an EV cert. SmartScreen reputation still accrues over time.
**Notes:** "Wire the signing step," not "obtain the cert."

### TASK 5b.2: Linux AppImage
**Milestone:** M5b · **Depends on:** 5.4 · **Size:** ~150 lines, 2–3 h
**Files:** new `installer/appimage/`, `installer/build.sh`, CI
**Acceptance:** A working AppImage runs the app on a clean Ubuntu; published to Releases. CI builds it on ubuntu-latest.
**Risks:** Bundling FFmpeg/ONNX/OpenCV into an AppImage has its own quirks; test on a clean distro.
**Notes:** Linux is "best effort" tier (`ARCHITECTURE.md`) but cheap — no paid cert needed, unlike macOS.

### TASK 5b.3: macOS .dmg (signed + notarized) — conditional
**Milestone:** M5b · **Depends on:** 5.4, (external: Apple Developer cert) · **Size:** ~150 lines, 3 h + lead time
**Files:** `installer/macos/`, CI (macos runner)
**Acceptance:** A signed, notarized `.dmg` runs on a clean macOS without Gatekeeper blocking; published to Releases.
**Risks:** Requires a paid Apple Developer account (PLAN-V2 §0 item 3, §15 item 1). **Defer if no budget** — Linux-first may be the right order.
**Notes:** Gate on the cert; don't start without it.

---

## M6 — Rust encoder spike (gated; after beta + explicit go)

> A **spike**, not a commitment (PLAN-V2 §6 Pushback 1, R17). Measure whether porting the encoder to Rust buys enough to justify the rewrite. Produces a go/no-go.

### TASK 6.1: `svcs-core` skeleton on `kdev`
**Milestone:** M6 · **Depends on:** explicit green-light after M5 · **Size:** ~150 lines, 2–3 h
**Files:** new `svcs-core/` Cargo crate on `kdev`
**Acceptance:** A Rust crate compiles for Windows + Linux, exposes one hello-world function over a C ABI, buildable from the repo. (`kdev` has no Rust scaffold today — verified.)
**Risks:** Toolchain setup on Windows. Keep the FFI surface minimal.
**Notes:** Greenfield on `kdev`; don't touch `app`. Module layout per `ARCHITECTURE.md`.

### TASK 6.2: Port the encoder module only; prove parity
**Milestone:** M6 · **Depends on:** 6.1 · **Size:** ~400 lines, 4+ h
**Files:** `svcs-core/src/encoder.rs`, parity harness, `docs/rust-spike-findings.md`
**Acceptance:** The Rust encoder produces output within an agreed quality/byte tolerance of the Python encoder on CDnet clips. Measured: binary-size delta and encode-throughput delta vs the ONNX Python path. A written go/no-go in `docs/rust-spike-findings.md`.
**Risks:** `ffmpeg-next`/`opencv-rust` maturity (R17). If a blocker appears, the spike's job is to find it cheaply — document and stop.
**Notes:** Encoder first (lowest-risk/highest-impact per ARCHITECTURE migration). The deliverable is the *finding*; the human decides Rust's future from it.

---

## 4. Glossary

- **SVCS** — Selective Video Compression System.
- **CDnet** — CDnet 2014 change-detection benchmark; the integration-test corpus (`data/samples/cdnet_mp4/`). Sample clips: `baseline/baseline_pedestrians.mp4`, `intermittentObjectMotion/intermittentObjectMotion_parking.mp4`.
- **MOG2** — Mixture of Gaussians background subtraction (OpenCV); primary motion/foreground detector, recommended over KNN per `docs/algorithm_comparison.md`.
- **ROI** — Region of Interest; foreground/object regions kept at high quality.
- **Foreground-area ratio** — fraction of pixels MOG2 marks as moving; the cheapest free signal for content auto-detection (TASK 3.2).
- **Mode 0** — every frame kept, single-pass (baseline).
- **Mode 1** — dual-CRF: foreground at CRF 18, background at CRF 45, one output per segment.
- **Mode 2** — record only when targets detected; idle background dropped. **Consistently the largest output** (`docs/mode_size_hierarchy.md`) — why modes hide behind presets (PLAN-V2 §6 Pushback 3).
- **Mode 3** — per-object videos (rewritten 2026-05-02 from blackout-in-full-frame); each object its own clip. Wins on 1080p+ multi-object scenes.
- **dual-CRF** — encoding foreground and background at different CRF values in one pipeline (core of Mode 1).
- **Segment** — an encoded output unit indexed in `metadata.db` (camera ID, timestamp, ROI count, size, duration, object classes, etc.).
- **ONVIF** — open standard for IP camera discovery/control; WS-Discovery finds cameras on a LAN (TASK M-CAM.1).
- **RTSP** — Real-Time Streaming Protocol; how IP/CCTV cameras emit live streams (already supported in `frame_source`).
- **Bridge (Frigate / Home Assistant / Scrypted)** — self-hosted NVR/automation tools that can re-expose cloud-locked cameras as local RTSP; SVCS consumes that RTSP (TASK M-CAM.3). SVCS never touches vendor clouds.
- **Cloud-locked camera** — Ring, Nest, Arlo, etc.; footage lives in the vendor cloud with no official local stream. Ingested via export-folder (M-CAM.2) or a bridge (M-CAM.3).
- **`[plates]` / `[enhance]` / `[crash-reporting]`** — optional `pyproject.toml` extras (EasyOCR plate reader; basicsr+realesrgan enhancement; sentry-sdk). All free; split out only for install size.
- **platformdirs** — library putting state files in OS-standard app-data dirs instead of repo root.
- **PyInstaller / Inno Setup** — the bundler (folder-mode `.exe`) and the Windows installer wrapper.
- **ONNX / ONNX Runtime** — model-export format and cross-platform inference engine replacing PyTorch (TASK 2.1) to slim the installer.
- **`svcs-core`** — the (not-yet-existing) Rust crate the long-term architecture targets; spiked, not committed, in M6.

---

*End of `docs/EXECUTION-CLAUDE-CODE.md`. Product intent: `docs/PLAN-V2.md`.*
