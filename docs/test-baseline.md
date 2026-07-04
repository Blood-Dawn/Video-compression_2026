# Test Baseline & Triage (M0 TASK 0.1 + 0.2)

**Author:** Bloodawn (KheivenD), 2026-05-31.
**Purpose:** Establish the reproducible test baseline and triage every failure, so "the suite is green" stops being a sentence in a doc and becomes a CI-verified fact (PLAN-V2 §11).

---

## How to reproduce

```
pwsh scripts/run_tests.ps1        # Windows daily driver (primary)
scripts/run_tests.sh              # Linux / CI
```

Both sync the environment with the documented extras first, then run `pytest tests/` with the project config (`basetemp=.pytest_tmp`, `--tb=short -ra` from `pyproject.toml`), tee to a timestamped log under `logs/`, and print the summary.

**Documented extras for a full run:** `--extra enhance --extra plates --extra crash-reporting`. Core deps (incl. `cryptography`, which encryption needs) come from the base `uv sync`.

---

## GREEN baseline achieved (2026-05-31)

| Field | Value |
|---|---|
| Command | `scripts/run_tests.ps1` |
| Log | `logs/pytest_20260531_204215.log` |
| Result | **513 passed, 3 skipped, 0 failed, 0 errors** (130 s) |
| Env | Windows 11, Python 3.11.9, opencv-contrib-python 4.10.0.84, `.venv` |

Path from the stale "48 failed" claim to green: provision the env (cleared 22 encryption deps) → fix the DB connection leak (6) → mode2 CRF bug + mode2/mode3 settings tests → crash-reporting test isolation (14) → mode2 `finish_segment`/mode3 `source_path` mocks → mode3 single-clip tests (3, D2) → gui_api DB isolation + new output-dir resolution (4). Two real bugs fixed: mode2 was stuck at CRF 18 (now 23), and `get_connection()` leaked sqlite handles (Windows lock risk in the live app).

The 3 skips are the real-webcam hardware tests (`SVCS_TEST_WEBCAM=1` to run) - intentional.

## GREEN baseline after R4 Phase 5 (2026-07-04)

| Field | Value |
|---|---|
| Command | `scripts/run_tests.ps1` |
| Log | `logs/pytest_20260704_182046.log` |
| Result | **1210 passed, 4 skipped, 0 failed** (196 s) |
| Env | Windows 11, Python 3.11.9, `.venv` |

R4 Phase 5 (plate-reader solution, see docs/RESEARCH-PLATES.md +
docs/PLATES-VALIDATION.md) added an in-process ONNX ALPR backend
(`_FastPlateOcrBackend`: fast-plate-ocr + open-image-models, MIT, torch-free)
that installs alongside opencv-contrib in ONE env via a `--no-deps` recipe
(`scripts/install_plates.ps1`) - empirically validated in a throwaway venv. It
is auto-selected first and degrades gracefully when absent, so CI needs no OCR
package. `test_plate_backend_order.py` grew ONNX order + adapter tests (a test
caught a real bbox-parsing bug). Skips unchanged (3 webcam + 1 opt-in Docker).

## GREEN baseline after R4 Phase 4 (2026-07-04)

| Field | Value |
|---|---|
| Command | `scripts/run_tests.ps1` |
| Log | `logs/pytest_20260704_175731.log` |
| Result | **1202 passed, 4 skipped, 0 failed** (197 s) |
| Env | Windows 11, Python 3.11.9, `.venv` |

R4 Phase 4 (server/field build split, see docs/BUILDS.md) added
`src/gui/edition.py` (edition resolution), edition-aware
`register_blueprints` (the field build drops RTSP + HLS), template gating of
the TOOLS tab, run_gui localhost/telemetry enforcement, a parameterized
`installer/svcs.spec` (`SVCS_BUILD_EDITION`), and `test_edition.py` (14). The
phase review then closed a defense-in-depth gap: the `python -m gui.app` entry
now also force-binds loopback in the field build (`_field_safe_host`). The
default module app is unchanged (server, 73 routes), so every other guard
holds. Skips unchanged (3 webcam + 1 opt-in Docker build).

## GREEN baseline after R4 Phase 3 (2026-07-04)

| Field | Value |
|---|---|
| Command | `scripts/run_tests.ps1` |
| Log | `logs/pytest_20260704_173148.log` |
| Result | **1188 passed, 4 skipped, 0 failed** (195 s) |
| Env | Windows 11, Python 3.11.9, `.venv` |

R4 Phase 3 (competitor gap analysis, see docs/RESEARCH-COMPETITORS.md) added
retention / disk-budget / auto-purge (the #1 table-stakes NVR gap):
`gui/services/retention.py`, two new routes on `autocompress_bp`
(`/api/retention` GET+POST, `/api/retention/purge_now`; route guard 71 -> 73,
blueprints stay 17), a daemon hook, and `test_retention.py` (mostly
deletion-safety guards). The phase review added 5 more: an in-flight
active-output registry (`utils/active_outputs.py`) so a clip being encoded is
never purged mid-write, inf/nan guards on the policy, and a locked
`compressed_index.prune_missing`. Skips unchanged (3 webcam + 1 opt-in Docker).

## GREEN baseline after R4 Phase 2 (2026-07-04)

| Field | Value |
|---|---|
| Command | `scripts/run_tests.ps1` |
| Log | `logs/pytest_20260704_164336.log` |
| Result | **1163 passed, 4 skipped, 0 failed** (222 s) |
| Env | Windows 11, Python 3.11.9, `.venv` |

R4 Phase 2 (compression research adoptions, see docs/RESEARCH-COMPRESSION.md)
added `test_encoder_r4.py` (22: long-GOP/capped-CRF/NVENC arg builders,
denoise + addroi filter chains, VMAF; guarded real NVENC + libvmaf smokes)
and 2 GUI-API knob tests. New encoder knobs (long GOP default, capped CRF,
NVENC/x265 codecs, denoise, encoder-level ROI, VMAF metric) are plumbed
through pipeline -> GUI/CLI. The failing-then-fixed regression was a
diagnostic log line that read encoder attrs the test doubles lack (now
getattr-guarded). The phase review then fixed two more: _clamp_int OverflowError
on inf/1e999 (would 500), and inert ROI grid aging (`<= 0` never fired; now a
`< 0.5` threshold). Skips unchanged (3 webcam + 1 opt-in Docker build).

## GREEN baseline after R4 Phase 1 (2026-07-04)

| Field | Value |
|---|---|
| Command | `scripts/run_tests.ps1` |
| Log | `logs/pytest_20260704_013219.log` |
| Result | **1139 passed, 4 skipped, 0 failed** (216 s) |
| Env | Windows 11, Python 3.11.9, `.venv` |

Between R3 and R4 the security audit added `tests/security/` (94 tests, see
docs/SECURITY-AUDIT.md). R4 Phase 1 (UI/UX research adoptions, see
docs/RESEARCH-UIUX.md) added `test_job_history.py` (19, incl. 5 regression
tests from the phase review) and the new `/api/jobs/recent` endpoint; the
route guard moved to 71 routes (blueprints stay at 17). Skips unchanged
(3 webcam + 1 opt-in Docker build).

## GREEN baseline after R3 (2026-06-21)

| Field | Value |
|---|---|
| Command | `scripts/run_tests.ps1` |
| Result | **1025 passed, 4 skipped, 0 failed** (~200 s) |
| Env | Windows 11, Python 3.11.9, `.venv` |

R3 added the auto-compress feature (R3.1) and terminal/winget distribution
(R3.2). New tests: `test_compressed_index.py` (7), `test_autocompress.py` (14,
the live-save test skips without the CDnet corpus), `test_winget_manifest.py`
(7), `test_install_script.py` (8), plus 5 new `test_library.py` kind-filter
tests; the route/blueprint guards moved to 70 routes / 17 blueprints and the
nav-order guard gained the AUTO-COMPRESS tab. The 4 skips are 3 webcam + 1
opt-in Docker build (the live-save test runs when the corpus is present).

---

## (historical) First provisioned run, 2026-05-31 20:02

| Field | Value |
|---|---|
| Command | `scripts/run_tests.ps1` (syncs `enhance + crash-reporting`, no `plates`; cv2 sanity-checked) |
| Timestamp | 2026-05-31 20:02, log `logs/pytest_20260531_200154.log` |
| Result | **26 failed, 487 passed, 3 skipped, 5 errors** (516 collected, 130 s) |
| OS / env | Windows 11, Python 3.11.9, opencv-contrib-python 4.10.0.84, `.venv` |

What the proper provisioning changed vs the stale 2026-05-14 log (48 failed):
- **The 26 `test_encryption` failures are GONE** - `cryptography` is now installed (it's a core dep; the old run just hadn't synced it). +22 tests.
- **The 14 `test_crash_reporting` failures REMAIN even with sentry-sdk installed** - so my earlier "missing-dep" guess was WRONG. These are a **real test-isolation bug** (see the corrected triage below). Running it mattered.

### Corrected triage of the 31 remaining issues (26 failed + 5 errors)

| Group | Count | Real cause | Status |
|---|---|---|---|
| `test_object_type_queries` (5 err) + `test_pipeline_stress` (1) | 6 | **Source bug:** `get_connection()` used `with conn:` which commits but never *closes* - leaked sqlite connections + WAL sidecars locked the file (WinError 32 on Windows). Affects the live app too. | **FIXED** this session (see below) |
| `test_pipeline` mode2 `encrypt` kwarg | 2 | Stale mock - `begin_segment` gained `encrypt*` params. | **FIXED** this session |
| `test_crash_reporting` | 14 | **Real** - `_SENTRY_ENABLED` module global leaks `True` into tests; the reimport helper + `patch.dict(sys.modules)` don't reset it, so `init_crash_reporting()` early-returns `True` without calling the stub. Source logic is correct; the TEST is fragile. | Open - needs test fix |
| `test_gui_api` default_output_dir | 2 | Stale - the OneDrive-default removal changed the resolution order; tests still expect `FakeOneDrive\SVCS` / `…/outputs`. | Open - update assertions |
| `test_gui_api` segments | 2 | Test isolation - reads the repo's real `metadata.db` (25-27 rows) instead of an empty/temp DB. | Open - point at temp DB |
| `test_mode_size_hierarchy` mode3 (3) | 3 | **Divergence:** tests expect a `mode3_sparse/` per-object output, but **no `mode3_sparse.py` exists in `app`** (only a stale `.pyc`). The 2026-05-02 per-object rewrite never landed on `app`; current mode3 = single object-only mp4. | Open - **decision** |
| `test_pipeline` mode2 (1) + mode3 (1) encoder settings | 2 | Tests pin OLD preset+CRF (`veryfast`, CRF 23). Code now gives mode2 `ultrafast`/CRF 18 and mode3 `ultrafast`/CRF 38 - which `mode_size_hierarchy.md` documents as the *intended* design (mode2 = forensic/largest). | Open - **decision** |

### Fixes applied this session (TASK 0.3, partial)

1. **`src/utils/db/schema.py` - `get_connection()` now closes connections.** Converted to a `@contextmanager` that commits on success, rolls back on error, and closes in `finally`. Root-cause fix for all 6 `WinError 32` failures *and* a real production connection leak. All 22 call sites already use `with get_connection(...)`, so no caller changes needed. **Verify by re-running the suite.**
2. **`tests/test_object_type_queries.py`** - `temp_db` fixture now uses `tmp_path` (no system `%TEMP%`, no manual `os.remove`); dropped unused `os`/`tempfile` imports.
3. **`tests/test_pipeline.py`** - the two mode2 mock encoders' `begin_segment` now absorb `**kwargs` (the `encrypt*` params).

Expected effect: the 6 WinError-32 issues and the 2 mode2 `encrypt` tests go green → ~8 of 31 resolved. **Re-run `scripts/run_tests.ps1` to confirm**, then paste the new summary.

### Decisions

- **D1 - mode2/mode3 encoder settings. RESOLVED (owner, 2026-05-31).** Design intent is **progressive compression mode0 → mode3**: foreground CRF mode0=18, mode1=18, **mode2=23**, **mode3=38**; preset `ultrafast` for mode2/mode3 (CPU). **This exposed a real code bug:** mode2 was wrongly left at CRF 18 (same as mode0/1), so it wasn't compressing as designed. **FIXED** in `src/pipeline/pipeline.py` (added `elif mode == "mode2": resolved_crf = 23`). The mode2 test (CRF 23) now passes against the corrected code; the mode3 test was updated to expect CRF 38 + `ultrafast`. *Follow-up:* `docs/mode_size_hierarchy.md` is now outdated (it documents mode2 as always-largest-at-CRF-18); update it to the progressive-CRF design (the doc itself anticipated this at its line 98).
- **D2 - mode3 per-object sparse output. OPEN.** The per-object `mode3_sparse/` rewrite isn't in `app` (only a stale `.pyc`; nothing imports it). Current `app` mode3 = single object-only mp4. Either recover the sparse rewrite from whatever branch has it (and keep the 3 `test_mode_size_hierarchy` tests), or ratify single-object-only mode3 as the truth (update the 3 tests). **Needs owner input.**

### Fixes applied this session - updated tally

- DB connection-close (`schema.py`): 6 WinError-32 tests.
- mode2 `encrypt` kwarg mocks: 2 tests.
- mode2 CRF code bug + mode2/mode3 test assertions (D1): 2 tests.
- → ~10 of 31 addressed. **Re-run `scripts/run_tests.ps1` to confirm.**

Still open after a confirming run: `crash_reporting` (14, real test-isolation), `gui_api` default_output_dir (2, stale) + segments isolation (2), `mode_size_hierarchy` mode3 (3, D2). All mechanical except D2.

---

## Triage of all 53 issues (48 failed + 5 errors)

Categories: **(A) missing-dep** - environment, not a code bug, fixed by `uv sync`; **(B) Windows file-handle** - real but Windows-specific teardown/cleanup bug; **(C) stale test** - test left behind by an intentional code change, update the test; **(D) needs-investigation** - could be env (ffmpeg) or a real regression, confirm.

### A - Missing dependency (40 tests) - fixed by provisioning the env

| Tests | Count | Root cause | Fix |
|---|---|---|---|
| `test_encryption.py` (all) | 26 | `RuntimeError: cryptography package is required but not installed`. `cryptography>=41.0.0` **is** a declared core dep (`pyproject.toml:62`) - the run just didn't install it. | `uv sync` (core). In CI, assert core deps present. No code change. |
| `test_crash_reporting.py` (all) | 14 | `sentry-sdk` (the `[crash-reporting]` extra) not installed → the stub/patch the tests rely on can't bind → asserts diverge (`init.called == False`, `init_crash_reporting() is False` returns True, `NoneType has no attribute kwargs`). | `uv sync --extra crash-reporting`. Then in TASK 0.3, gate these with `importorskip("sentry_sdk")` so a casual checkout skips them cleanly instead of failing. |

**40/48 failures are Category A.** This is the confirmation of the "whole files fail together = missing deps" hypothesis from PLAN-V2 §11.

### B - Windows file-handle / `%TEMP%` cleanup (5 errors + ~2 failures) - real, Windows-specific

| Tests | Count | Root cause | Fix |
|---|---|---|---|
| `test_object_type_queries.py` (5 tests) | 5 errors | `PermissionError [WinError 32] ... metadata.db ... \AppData\Local\Temp\...`: the SQLite connection isn't closed before the temp dir is torn down, so Windows refuses to delete the locked file. | Close the DB connection (or use a context manager) in the fixture teardown before cleanup; consider routing through the project's `.pytest_tmp` instead of system `%TEMP%`. |
| `test_pipeline_stress.py::test_storage_extrapolation` | 1 | Same `PermissionError [WinError 32]`; this test uses `tempfile` directly, bypassing the `.pytest_tmp` mitigation. | Route through `tmp_path`; ensure handles closed before teardown. |
| Early `PermissionError` block (lines 538-554) | ~ tied to above | System-`%TEMP%` locks on tmp files. | Same pattern: close handles / use `tmp_path`. |

These are the residue of the `%TEMP%` permission war the team mostly solved with `basetemp=.pytest_tmp` - a few tests still call `tempfile` directly or leave a DB handle open. Genuine but small and localized.

### C - Stale tests after intentional code changes (5 tests) - update the tests

| Test | Count | What changed | Fix |
|---|---|---|---|
| `test_gui_api.py::TestDefaultOutputDir::test_default_output_dir_uses_cloud_when_available` / `_falls_back_to_local` | 2 | The audit **removed OneDrive as the implicit default** and changed the output-dir resolution order (persisted → cloud opt-in → Videos → repo fallback). The tests still expect the old `FakeOneDrive\SVCS` / `…/outputs` behavior. | Update the tests to assert the new resolution order (`e0257e8` / `746cab2` changed this intentionally). |
| `test_pipeline.py::TestMode2Behavior::test_mode2_does_not_learn_...` / `test_mode2_refreshes_...` | 2 | `TypeError: RecordingEncoder.begin_segment() got an unexpected keyword argument 'encrypt'` - the encoder API gained an `encrypt` kwarg (per-segment encryption); the test's mock `RecordingEncoder` was never updated. | Add `encrypt=...` to the test double's signature. |
| `test_pipeline.py::TestMode2Behavior::test_mode2_uses_compression_oriented_encoder_settings` | 1 | Asserts `preset == "veryfast"`; encoder now defaults to `ultrafast`. | Confirm which is intended (was the `ultrafast` change deliberate?). If yes, update the test; if no, it's a real regression - revert the default. **Decide before editing.** |

### D - Needs investigation (4 tests) - likely the Mode 3 rewrite or ffmpeg

| Test | Count | Symptom | Likely cause |
|---|---|---|---|
| `test_mode_size_hierarchy.py` (`test_all_four_modes_run_without_raising`, `test_mode3_produces_sparse_directory`, `test_outputs_are_valid_mp4s`) | 3 | `mode3: output bytes was 0`; `mode3 produced no mode3_sparse/ subdirectory`. | Mode 3 was rewritten 2026-05-02 to per-object videos. Either the test expects the old layout, or mode3 produces nothing in this env (missing ffmpeg / no objects detected on the clip). Run mode3 manually on a CDnet clip to see which. |
| `test_pipeline.py::TestMode3Behavior::test_mode3_encodes_object_only_mp4_segments_with_compression_settings` | 1 | `assert seg_dirs == []` - no segment dirs produced. | Same Mode 3 question. |

Also note `test_gui_api.py::TestApiSegments::test_empty_list_when_no_db` / `test_returns_segments_from_db` (2): the tests read the **repo's real `metadata.db`** (25-27 rows) instead of an isolated empty DB → expected `[]`/`2`, got `25`/`27`. This is a **test-isolation bug** (point the test at a temp DB / monkeypatch the DB path), Category C-ish. Counted in the 48.

---

## NEW finding (2026-05-31 re-baseline) - OpenCV / easyocr conflict breaks cv2

Running `scripts/run_tests.ps1` with `--extra plates` (the first version of the script) **made things worse, not better**: 8 test files failed at *collection* with `AttributeError: module 'cv2' has no attribute 'createBackgroundSubtractorMOG2'`. Root cause, confirmed:

- The `[plates]` extra installs **easyocr**, which depends on **`opencv-python-headless`**.
- The project already resolves **`opencv-python`** (uv.lock pins 4.10.0.84).
- Both packages install into the same `cv2/` namespace. When uv reconciled them, the shared binaries got clobbered, leaving a `cv2` so broken that even base `createBackgroundSubtractorMOG2` is gone. Every module that imports the pipeline dies at import.

Second, latent issue found while diagnosing:

- `src/background_subtraction/background_subtraction.py:180` calls **`cv2.bgsegm.createBackgroundSubtractorGMG`** - a **contrib-only** module - but `pyproject.toml:17` declares plain `opencv-python` (no contrib). It only ever worked because `opencv-contrib-python` was manually installed into the old `venv`. A clean install per `pyproject` would not have `bgsegm` at all (the GMG background-subtraction method would crash at runtime).
- Also: `src/pipeline/pipeline.py:658` uses `cv2.imshow` (HighGUI) in a preview path - fine for a desktop build, but it means a pure-headless OpenCV would break that preview. The preview is optional; core processing doesn't need HighGUI.

**Fixes:**
- **Immediate (done in the script):** `run_tests.ps1`/`.sh` no longer install `[plates]` by default; they sync `enhance + crash-reporting` only, then sanity-check that `cv2` is whole before running. Plate-reader tests get `importorskip` and are validated in a dedicated environment. → **TASK 0.3b** below.
- **Proper (pyproject):** declare the OpenCV dependency correctly and stop the dual-install. Recommended: switch the project to **`opencv-contrib-python`** (the code needs `cv2.bgsegm`), and add a `[tool.uv]` override so easyocr's `opencv-python-headless` resolves to the same single OpenCV build instead of a second one. → **TASK 0.4b** below. This also reinforces the PLAN-V2 §6 ONNX direction: these heavy, fragile vision deps are exactly what the ONNX migration thins out.

> Net: the `--extra plates` failure is a packaging bug, not a code regression. The real baseline must be taken **without** `[plates]` (the updated script does this). Re-run and record the number below.

---

## What this means for TASK 0.3 (make it green)

Order of work, smallest-risk first:

1. **Provision the env** (`scripts/run_tests.ps1` syncs deps). Expected to clear all 26 encryption + 14 crash-reporting failures (Category A) outright. *Re-baseline here and record the new number.*
2. **Gate optional-dep tests** with `importorskip` so a casual checkout (no `[crash-reporting]`) skips rather than fails.
3. **Fix the Windows handle leaks** (Category B): close SQLite connections in fixtures; route stray `tempfile` usage through `tmp_path`. ~6 tests.
4. **Update the stale tests** (Category C): output-dir resolution order, the `encrypt` kwarg on the mock encoder, the test-isolation DB path. ~6 tests. For the `veryfast`→`ultrafast` preset: **ask first** whether the change was intentional before editing the assertion.
5. **Investigate Mode 3** (Category D): run mode3 on a CDnet clip; if it works and only the test is stale, update the test; if mode3 genuinely produces nothing, that's a real bug to file. ~4 tests.

Net: of 48 failures, **40 are a one-command env fix**, ~6 are mechanical test updates, ~6 are small Windows-cleanup fixes, and ~4 need a quick Mode 3 look. None require touching the compression algorithms. This is a half-day to a day of work, not a rewrite - and it unblocks everything else in the roadmap.

---

## Resolved decision - encoder preset

**`ultrafast` is intentional; the test is stale.** The committed `src/pipeline/pipeline.py` sets the preset per mode with a documented rationale:

```python
# Mode 2/3 do extra per-frame compositing work; ultrafast encoding keeps
# overall CPU load manageable. Mode 0/1 can afford slightly better compression.
encode_preset = "ultrafast" if mode in ("mode2", "mode3") else "veryfast"
```

So mode2/mode3 use `ultrafast` by design (CPU budget during compositing), mode0/1 use `veryfast`. The failing `test_mode2_uses_compression_oriented_encoder_settings` (and the line-831 assertion) predate this per-mode choice and still expect `veryfast` for mode2. **Fix in TASK 0.3: update those tests to expect `ultrafast` for mode2/mode3.** No code change. (The git-blame "Not Committed Yet" on these lines was line-ending churn, not a real edit - see below.)

---

## NEW finding - repo-wide line-ending churn (folds into TASK 0.4)

While confirming the preset history, `git status` showed **109 files modified** in the working tree, and the diffs are **purely CRLF↔LF line-ending changes**, not content:

- `git diff --ignore-all-space` on `src/pipeline/pipeline.py` is **empty** - the visible "836 insertions, 836 deletions" is 100% line-ending noise.
- `git ls-files --eol` reports `i/lf  w/crlf` - the index has LF, the working tree has CRLF.
- There is **no `.gitattributes`** in the repo, so nothing pins line endings; Git + the editor are silently rewriting them on Windows.

**Why this is urgent:** committing now would produce a massive, unreviewable, noise-only diff across the whole repo and bury every real change. This must be fixed before any M0 commit lands.

**Fix (add to TASK 0.4):**
1. Add a `.gitattributes` that normalizes line endings, e.g.:
   ```
   * text=auto eol=lf
   *.ps1 text eol=crlf
   *.bat text eol=crlf
   *.png binary
   *.jpg binary
   *.mp4 binary
   *.pt binary
   *.db binary
   ```
   (Keep `.ps1`/`.bat` as CRLF - PowerShell/batch prefer it; everything else LF.)
2. Renormalize once: `git add --renormalize .` then commit as a single isolated `chore: normalize line endings (.gitattributes)` commit, **separate from any functional change**, so the noise lives in one reviewable commit and never again.
3. Verify `git status` is clean afterward.

This is a one-time hygiene commit and it should happen **first in M0**, before the test fixes, so the test-fix diffs are clean.
