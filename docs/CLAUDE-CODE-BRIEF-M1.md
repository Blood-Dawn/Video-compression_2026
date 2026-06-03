# Claude Code Brief — M1: split `gui/app.py` and `index.html`

**For:** Claude Code (CLI, edits files + runs tests in one loop).
**Prepared:** 2026-06-01, after M0 was completed and CI is green.
**How to use:** open this repo in Claude Code and say: *"Read `docs/CLAUDE-CODE-BRIEF-M1.md` and execute it, one task at a time, keeping the test suite green and stopping after each task for me to review and commit."*

---

## 0. What you're doing

Execute milestone **M1** (tasks 1.1–1.5) from `docs/EXECUTION-CLAUDE-CODE.md`, following the design in `docs/REFACTOR-PLAN-gui-app.md`. In short: split the 3,880-line `src/gui/app.py` (48 routes) into a thin `app.py` + `state.py` + `logging_setup.py` + `services/` + `routes/` (12 blueprints), and split the 7,026-line `src/gui/templates/index.html` into per-feature JS modules under `src/gui/static/js/`.

Read these three first, in order:
1. `docs/REFACTOR-PLAN-gui-app.md` — the design (file tree, what goes where, migration order, risk list). This is authoritative for *how* to split.
2. `docs/EXECUTION-CLAUDE-CODE.md` §M1 (tasks 1.1–1.5) — per-task acceptance criteria and the new guard tests to add.
3. `docs/test-baseline.md` — what "green" means and the gotchas that bit us in M0 (below).

This is a pure refactor: **no behavior changes.** Every route must keep its URL, every response shape must stay identical, and the test suite must stay green at every commit.

---

## 1. The green baseline you must not break

The suite is currently **513 passed, 3 skipped, 0 failed** (the 3 skips are the real-webcam hardware tests). Run it with:

```
pwsh scripts/run_tests.ps1
```

That script syncs the env (`enhance` + `crash-reporting` extras — **never `plates`**, see gotchas), sanity-checks OpenCV, and runs `pytest tests/`. After every extraction step, run it. **Do not proceed to the next step on a red suite.** If a step can't be made green, revert it and rethink — don't pile broken changes.

Add the new guard tests the execution plan specifies as you go (`test_gui_state_reexports.py`, `test_gui_blueprint_registration.py`, `test_gui_routes_resolve.py`), and keep them green too.

---

## 2. Repo conventions (non-negotiable)

- **Branch:** work on `app`. Don't touch `main`, `dev`, `kdev`. `premium` is dormant — **there is no `app`→`premium` mirror anymore** (it was retired in M0; just push `app`).
- **Commits:** `<type>(<scope>): <subject>` then a body explaining *why*, ending with a line `Bloodawn(KheivenD)`. Types: feat|fix|refactor|test|build|chore|docs. **No emojis** anywhere in code or commits.
- **The human pushes.** Propose the commit + `git push origin app`; let the user run it. One commit per logical step (per REFACTOR-PLAN migration order) so each is reviewable.
- **Tests ship with changes.** New modules get their guard tests in the same commit. Every refactor proves regression-free by a green run.
- **Authorship comments** on non-obvious/load-bearing blocks, repo style: `# Author: Bloodawn (KheivenD), 2026-06-XX (gui refactor).`
- **Style:** Black, ruff, type hints on new public functions, Python 3.11+.

---

## 3. Hard constraints (from REFACTOR-PLAN §0 — read it, but the load-bearing ones)

- **`from gui.app import app` must keep working** (`run_gui.py` and `tests/test_gui_api.py` rely on it).
- **`gui.app` must keep exposing every private name the tests reach for** via `gui_module.*` — `_state_lock`, `_status`, `_pipeline_thread`, `_stop_event`, `_run_pipeline_thread`, `_demo_lock`, `_demo_state`, `_hls_lock`, `_hls_state`, `_hls_frame_ts_dq`, `_hls_segment_latencies`, `_default_output_dir`, `_CLOUD_SUBFOLDER`, and the others listed in the plan. Re-export them from the new modules.
- **Rebound globals need forwarding.** Some names are reassigned, not just mutated in place: `_log_id += 1`, `_pipeline_thread = ...`, `_stop_event = ...`. Tests also do `gui_module._pipeline_thread = None`. After moving these into a submodule, a plain re-import gives a stale copy. Use the module-level `__getattr__`/`__setattr__` on `gui.app` that forwards reads/writes to the owning submodule (REFACTOR-PLAN §5). Add `tests/test_gui_state_reexports.py` that asserts each name resolves via `gui.app` AND that mutation round-trips between `gui.app` and the submodule — this is your safety net for this whole class of bug.
- **Import direction is one-way:** services may import `state` + `logging_setup`, never the reverse; blueprints import services; `gui.app` imports blueprints; nothing imports `gui.app`. Breaking this causes circular imports.
- **SSE closure:** `api_logs()`'s `generate()` closes over `_log_queue`/`_log_history`/etc. After moving these, import them at the top of `sse_bp.py` so the closure binds to module-level names.
- **atexit ordering:** keep `_file_handler` and `_write_shutdown_log` in the same module (`logging_setup.py`); the shutdown marker must still land in `svcs.log`.
- **`_bg_hw_thread` at import:** convert the import-time hardware-sampler thread start into an explicit `start_hw_sampler()` called from `create_app()`.
- **PyInstaller:** after the split, add every new `gui.state`/`gui.logging_setup`/`gui.services.*`/`gui.routes.*` submodule to `hiddenimports` in `installer/svcs.spec` (TASK 1.4), and confirm `installer/build.ps1`'s smoke test still passes.

---

## 4. Migration order (each step = one green commit)

Follow REFACTOR-PLAN §4 exactly — it was sequenced to keep tests green at each step:

1. **TASK 1.1** — extract `state.py` (pure data) and `logging_setup.py` (handlers + atexit). Re-export from `app.py`; add the forwarding for rebound names; add `test_gui_state_reexports.py`. Green.
2. **TASK 1.2** — extract the services layer (`services/{path_safety,cloud_detection,gui_state_persist,db_helpers,cpu_sampler,rtsp,demo_runner,hls_runner,pipeline_runner}.py`), `pipeline_runner` last. One commit per module ideally. Green after each.
3. **TASK 1.3** — carve the 48 routes into the 12 blueprints (smallest first: ui → sse → metrics → presets → encryption → plates → queries → rtsp → demo → hls → files → pipeline). `app.py` ends ~80 lines. Add `test_gui_blueprint_registration.py` (route count + each endpoint exists) and `test_gui_routes_resolve.py`. Green.
4. **TASK 1.4** — update `installer/svcs.spec` hiddenimports; run `installer/build.ps1` smoke test. Green.
5. **TASK 1.5** — split `index.html` (7,026 lines) into feature-grouped JS files under `src/gui/static/js/` (pipeline control, file browser, demo/quadrant, HLS player, metrics, encryption, presets). Route user-facing strings through a single `strings.js` catalog (i18n groundwork — **do not translate anything**). Verify every dashboard panel still works; keep `test_gui_api` green. Split into 1.5a/b/c by feature area if a single commit exceeds ~500 lines.

Before TASK 1.3, diff the blueprint endpoint names against the `fetch(...)` calls in `index.html` so no route is silently renamed or dropped — the frontend has no other contract.

---

## 5. Gotchas learned the hard way in M0 (save yourself the loop)

- **Use `.venv`, not `venv`.** `uv` manages `.venv`; an old `venv/` also exists and crossing them caused a confusing OpenCV breakage. Run everything through `uv` / the `scripts/run_tests.ps1` script. Ignore the `VIRTUAL_ENV=venv does not match .venv` warning.
- **Never install the `[plates]` extra in the working env.** easyocr pulls `opencv-python-headless`, which clobbers the core `opencv-contrib-python` and makes `cv2.createBackgroundSubtractorMOG2` disappear (8 import errors). The default test runner already excludes it; keep it that way. (Details in `pyproject.toml` `[plates]` comment.)
- **OpenCV must be `opencv-contrib-python`** (the code uses `cv2.bgsegm`). A clean `uv sync` installs it now; don't "fix" it to plain opencv-python.
- **Line endings: LF.** `.gitattributes` pins `eol=lf` (except `.ps1`/`.bat`). The working tree kept drifting to CRLF in M0, producing noisy whole-file "modified" diffs. If you see that, it's whitespace only — `git add --renormalize .`. If the editor is the culprit, set it to write LF. Keep your commits content-only.
- **The test runner is the source of truth for "green," not a hand-counted number.** Don't write test counts into prose; reference the run.
- **CI** (`.github/workflows/ci.yml`) runs the same suite on Linux+Windows on push to `app`. It installs CPU torch (`--no-sources`), ffmpeg, and excludes `[plates]`. If you add a test that needs a real CDnet clip, it'll skip on CI (clips are git-LFS, not pulled) — that's fine; don't make CI depend on them without adding `git lfs pull`.
- **Output codec is AV1 (libsvtav1).** OpenCV can't decode AV1 on some platforms, so validate produced mp4s with **ffprobe**, not `cv2.VideoCapture(...).read()` (see `tests/test_mode_size_hierarchy.py::_ffprobe_ok` for the pattern). Don't reintroduce cv2-decode checks on pipeline output.

---

## 6. Done criteria

- `src/gui/app.py` is ~80 lines (app + `create_app()` + blueprint registration + re-exports).
- 12 blueprints, the services layer, `state.py`, `logging_setup.py` all in place per REFACTOR-PLAN §3 tree.
- `index.html` logic moved into `static/js/*.js`; strings in `strings.js`.
- New guard tests added and green; full suite still **≥513 passed, 0 failed** locally and on CI.
- `installer/svcs.spec` updated; `build.ps1` smoke test passes.
- One reviewable commit per migration step, each ending `Bloodawn(KheivenD)`, pushed by the human.

Report at the end: final `app.py` line count, the route count the registration test asserts, the new test total, and the before/after `index.html` line count.
