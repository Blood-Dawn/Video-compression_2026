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

## Recorded baseline

| Field | Value |
|---|---|
| Source | `pytest_final.log` (most recent full run on disk) |
| Timestamp | 2026-05-14 20:23 (after the last commit `10cbda9`, 16:20) |
| Result | **48 failed, 465 passed, 3 skipped, 4 warnings, 5 errors** (516 collected, 142 s) |
| OS / env | Windows (Kheiven's machine) |
| Caveat | **The environment was under-provisioned** — `cryptography` (a core dep) and the `[crash-reporting]` extra were not installed. This alone accounts for **40 of the 48 failures.** |

> The headline: this is *not* 48 broken features. ~40 failures are a missing dependency in that run; the real work is ~8 stale tests plus a handful of Windows file-handle cleanup bugs. Re-running through `scripts/run_tests.ps1` (which syncs the deps) is expected to drop the failure count dramatically before a line of product code is touched.

**Action for the human:** run `scripts/run_tests.ps1` once on Windows and paste the new summary here, replacing this note, so we have a baseline taken with a correctly-provisioned environment. Then TASK 0.3 closes the genuine remainder.

---

## Triage of all 53 issues (48 failed + 5 errors)

Categories: **(A) missing-dep** — environment, not a code bug, fixed by `uv sync`; **(B) Windows file-handle** — real but Windows-specific teardown/cleanup bug; **(C) stale test** — test left behind by an intentional code change, update the test; **(D) needs-investigation** — could be env (ffmpeg) or a real regression, confirm.

### A — Missing dependency (40 tests) — fixed by provisioning the env

| Tests | Count | Root cause | Fix |
|---|---|---|---|
| `test_encryption.py` (all) | 26 | `RuntimeError: cryptography package is required but not installed`. `cryptography>=41.0.0` **is** a declared core dep (`pyproject.toml:62`) — the run just didn't install it. | `uv sync` (core). In CI, assert core deps present. No code change. |
| `test_crash_reporting.py` (all) | 14 | `sentry-sdk` (the `[crash-reporting]` extra) not installed → the stub/patch the tests rely on can't bind → asserts diverge (`init.called == False`, `init_crash_reporting() is False` returns True, `NoneType has no attribute kwargs`). | `uv sync --extra crash-reporting`. Then in TASK 0.3, gate these with `importorskip("sentry_sdk")` so a casual checkout skips them cleanly instead of failing. |

**40/48 failures are Category A.** This is the confirmation of the "whole files fail together = missing deps" hypothesis from PLAN-V2 §11.

### B — Windows file-handle / `%TEMP%` cleanup (5 errors + ~2 failures) — real, Windows-specific

| Tests | Count | Root cause | Fix |
|---|---|---|---|
| `test_object_type_queries.py` (5 tests) | 5 errors | `PermissionError [WinError 32] ... metadata.db ... \AppData\Local\Temp\...`: the SQLite connection isn't closed before the temp dir is torn down, so Windows refuses to delete the locked file. | Close the DB connection (or use a context manager) in the fixture teardown before cleanup; consider routing through the project's `.pytest_tmp` instead of system `%TEMP%`. |
| `test_pipeline_stress.py::test_storage_extrapolation` | 1 | Same `PermissionError [WinError 32]`; this test uses `tempfile` directly, bypassing the `.pytest_tmp` mitigation. | Route through `tmp_path`; ensure handles closed before teardown. |
| Early `PermissionError` block (lines 538–554) | ~ tied to above | System-`%TEMP%` locks on tmp files. | Same pattern: close handles / use `tmp_path`. |

These are the residue of the `%TEMP%` permission war the team mostly solved with `basetemp=.pytest_tmp` — a few tests still call `tempfile` directly or leave a DB handle open. Genuine but small and localized.

### C — Stale tests after intentional code changes (5 tests) — update the tests

| Test | Count | What changed | Fix |
|---|---|---|---|
| `test_gui_api.py::TestDefaultOutputDir::test_default_output_dir_uses_cloud_when_available` / `_falls_back_to_local` | 2 | The audit **removed OneDrive as the implicit default** and changed the output-dir resolution order (persisted → cloud opt-in → Videos → repo fallback). The tests still expect the old `FakeOneDrive\SVCS` / `…/outputs` behavior. | Update the tests to assert the new resolution order (`e0257e8` / `746cab2` changed this intentionally). |
| `test_pipeline.py::TestMode2Behavior::test_mode2_does_not_learn_...` / `test_mode2_refreshes_...` | 2 | `TypeError: RecordingEncoder.begin_segment() got an unexpected keyword argument 'encrypt'` — the encoder API gained an `encrypt` kwarg (per-segment encryption); the test's mock `RecordingEncoder` was never updated. | Add `encrypt=...` to the test double's signature. |
| `test_pipeline.py::TestMode2Behavior::test_mode2_uses_compression_oriented_encoder_settings` | 1 | Asserts `preset == "veryfast"`; encoder now defaults to `ultrafast`. | Confirm which is intended (was the `ultrafast` change deliberate?). If yes, update the test; if no, it's a real regression — revert the default. **Decide before editing.** |

### D — Needs investigation (4 tests) — likely the Mode 3 rewrite or ffmpeg

| Test | Count | Symptom | Likely cause |
|---|---|---|---|
| `test_mode_size_hierarchy.py` (`test_all_four_modes_run_without_raising`, `test_mode3_produces_sparse_directory`, `test_outputs_are_valid_mp4s`) | 3 | `mode3: output bytes was 0`; `mode3 produced no mode3_sparse/ subdirectory`. | Mode 3 was rewritten 2026-05-02 to per-object videos. Either the test expects the old layout, or mode3 produces nothing in this env (missing ffmpeg / no objects detected on the clip). Run mode3 manually on a CDnet clip to see which. |
| `test_pipeline.py::TestMode3Behavior::test_mode3_encodes_object_only_mp4_segments_with_compression_settings` | 1 | `assert seg_dirs == []` — no segment dirs produced. | Same Mode 3 question. |

Also note `test_gui_api.py::TestApiSegments::test_empty_list_when_no_db` / `test_returns_segments_from_db` (2): the tests read the **repo's real `metadata.db`** (25–27 rows) instead of an isolated empty DB → expected `[]`/`2`, got `25`/`27`. This is a **test-isolation bug** (point the test at a temp DB / monkeypatch the DB path), Category C-ish. Counted in the 48.

---

## What this means for TASK 0.3 (make it green)

Order of work, smallest-risk first:

1. **Provision the env** (`scripts/run_tests.ps1` syncs deps). Expected to clear all 26 encryption + 14 crash-reporting failures (Category A) outright. *Re-baseline here and record the new number.*
2. **Gate optional-dep tests** with `importorskip` so a casual checkout (no `[crash-reporting]`) skips rather than fails.
3. **Fix the Windows handle leaks** (Category B): close SQLite connections in fixtures; route stray `tempfile` usage through `tmp_path`. ~6 tests.
4. **Update the stale tests** (Category C): output-dir resolution order, the `encrypt` kwarg on the mock encoder, the test-isolation DB path. ~6 tests. For the `veryfast`→`ultrafast` preset: **ask first** whether the change was intentional before editing the assertion.
5. **Investigate Mode 3** (Category D): run mode3 on a CDnet clip; if it works and only the test is stale, update the test; if mode3 genuinely produces nothing, that's a real bug to file. ~4 tests.

Net: of 48 failures, **40 are a one-command env fix**, ~6 are mechanical test updates, ~6 are small Windows-cleanup fixes, and ~4 need a quick Mode 3 look. None require touching the compression algorithms. This is a half-day to a day of work, not a rewrite — and it unblocks everything else in the roadmap.

---

## Resolved decision — encoder preset

**`ultrafast` is intentional; the test is stale.** The committed `src/pipeline/pipeline.py` sets the preset per mode with a documented rationale:

```python
# Mode 2/3 do extra per-frame compositing work; ultrafast encoding keeps
# overall CPU load manageable. Mode 0/1 can afford slightly better compression.
encode_preset = "ultrafast" if mode in ("mode2", "mode3") else "veryfast"
```

So mode2/mode3 use `ultrafast` by design (CPU budget during compositing), mode0/1 use `veryfast`. The failing `test_mode2_uses_compression_oriented_encoder_settings` (and the line-831 assertion) predate this per-mode choice and still expect `veryfast` for mode2. **Fix in TASK 0.3: update those tests to expect `ultrafast` for mode2/mode3.** No code change. (The git-blame "Not Committed Yet" on these lines was line-ending churn, not a real edit — see below.)

---

## NEW finding — repo-wide line-ending churn (folds into TASK 0.4)

While confirming the preset history, `git status` showed **109 files modified** in the working tree, and the diffs are **purely CRLF↔LF line-ending changes**, not content:

- `git diff --ignore-all-space` on `src/pipeline/pipeline.py` is **empty** — the visible "836 insertions, 836 deletions" is 100% line-ending noise.
- `git ls-files --eol` reports `i/lf  w/crlf` — the index has LF, the working tree has CRLF.
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
   (Keep `.ps1`/`.bat` as CRLF — PowerShell/batch prefer it; everything else LF.)
2. Renormalize once: `git add --renormalize .` then commit as a single isolated `chore: normalize line endings (.gitattributes)` commit, **separate from any functional change**, so the noise lives in one reviewable commit and never again.
3. Verify `git status` is clean afterward.

This is a one-time hygiene commit and it should happen **first in M0**, before the test fixes, so the test-fix diffs are clean.
