# Cleanup sweep, September 2026

A full pass over the repo on 2026-09-24, before continuing the Android
roadmap. Each change is its own commit on `mobile` with the reasoning and the
checks in its message; this page is the summary.

## Baseline before any change

- Python: 1515 passed, 9 failed, 38 skipped (`tests/security` run separately
  and green). All 9 failures were drift, not new bugs in the code under test:
  a version bump that skipped the tests and winget manifests, three route
  tests that never learned about the Week 3 routes, a README section a test
  requires, em dashes in five files, and an NVENC test that ran on machines
  with no NVIDIA GPU.
- Android: 59 JVM tests, 1 to 3 failing per run, all in
  `ServerSettingsViewModelTest` (the docs said "58 of 59"; it was flakier
  than that). Debug build fine.
- CI had not run in weeks: its triggers named the deleted `app` branch.

## After

- Python: about 1,670 passing, 0 failing (skips only for missing hardware
  or data: CDnet clips, webcam, GPU, libvmaf). `uvx ruff check .` clean.
- Android: 67 JVM tests at the end of the cleanup (97 after the roadmap work
  that followed), 0 failing, stable across repeated runs; debug and release
  (R8) builds pass.
- CI runs on `main` and `mobile` again, with a new Android job.

## What changed, by area

**Real bugs found along the way**

- The Windows download button, the README link and INSTALL.md used
  `releases/latest`, which now resolves to the Android `v1-beta` release
  (APKs only). They point at the desktop release tag instead.
- The one-line installer URL pointed at the deleted `app` branch (404), and
  the script defaulted to a release tag and file name that do not exist
  (`v2.1.0.dev0/SVCS-Setup-2.1.0.dev0.exe`). Both fixed and checked with curl.
- Choosing an NVENC codec on a machine without an NVIDIA GPU crashed the
  encode with a broken pipe instead of falling back to libx264. The encoder
  now does a tiny trial encode for hardware codecs.
- The desktop update check would have offered a future mobile release as a
  desktop update (mobile tags have no `mobile-` prefix after all). APK-only
  releases are now skipped.
- `run_gui.py` told users to add the `plates` extra, which breaks background
  subtraction. The text now matches the code and the safe install path.
- Two tests silently checked less than their names promised (a shadowed
  duplicate test, and an MAE comparison that was computed but never
  asserted). Both restored.
- The dashboard's storage and search routes returned 500 on a
  `metadata.db` with no tables, and `/api/encrypt` created exactly that
  file when run before any pipeline job. Both fixed, with tests. A security
  test had been leaving that empty database in the repo's own `outputs/`.
- The no-em-dash guard skipped every folder named `data`, which hid the
  Android `data` package (TokenStore). It surfaced once CI ran again.

**Python hygiene**: 116 unused imports, 27 placeholder-less f-strings, 9
unused variables and one default-argument call removed; intentional
re-exports marked instead of deleted; dead duplicate import blocks left by the
`gui/app.py` blueprint carve removed; a `[tool.ruff]` config keeps it clean.

**Dependencies**: `pyproject.toml` + `uv.lock` are the single source.
`requirements.txt` is generated (`scripts/export_requirements.py`, guarded by
`tests/test_requirements_export.py`); the setup scripts use `uv sync`.

**Repo layout and docs**: helper scripts moved from the root into `scripts/`
(with a README); the abandoned v2 roadmap archived; one release checklist, one
blockers file and one set of v2.2.0 notes instead of two each; a Diataxis-style
docs index; README, DEV.md, CONTRIBUTING.md and the Android README rewritten;
a link checker (`scripts/check_doc_links.py`); em and en dashes gone; file
modes fixed so `./gradlew` runs on Linux.

**Android**: one set of derived color tokens, one share/play helper, one
thumbnail composable, one metadata probe, one formatting file; `ui/` split by
feature (`compress`, `saved`, `server/*`); stale M1.1 comments fixed; the
settings test deflaked through a `TokenCipher` seam in TokenStore (the
Keystore crypto moved verbatim, same key alias, so stored tokens still work).

## Deliberately left alone

- **The `gui.` / `src.gui.` dual import paths** in the Python code. Unifying
  them touches almost every module, the PyInstaller spec and many tests; the
  risk is not worth it for a delivered capstone app. Documented in DEV.md.
- **`src/gui/app.py`'s re-exports** of private names: tests pin them as a
  compatibility contract. Marked, not removed.
- **Flask routes the dashboard never calls** (device tokens, capabilities,
  savings, chunked upload, a couple of debug endpoints): the Android app and
  diagnostics use them.
- **`ROADMAP.md` stays at the root**: it is the team's active semester plan.
- **Physically moving docs into Diataxis folders**: their paths are pinned by
  tests, code comments, release notes and the published download page, so
  the grouping lives in `docs/README.md` instead.
- **Dated records** under `docs/project-records/` and `docs/archive/` keep
  their original wording and paths.
- **Server Mode screens' layouts** (UI-REVIEW item 5) and anything security
  sensitive beyond the test seam: out of scope for a cleanup.
- **The AppImage build** still resolves dependencies with `pip install .`
  rather than the lock; changing it needs a full AppImage build to verify.

## Owner decisions needed

Also tracked in [BLOCKERS.md](BLOCKERS.md):

1. **Teammates' email addresses in public git history** (`week3.local.json`,
   `scripts/team-emails.local.json`, untracked in ce6490f but still in
   history). Removing them needs a history rewrite and force push.
2. **A real Android release keystore.** Until then, only APKs built on the
   owner's Windows machine can update installed copies, and F-Droid or
   IzzyOnDroid submission should wait.
3. **FLAG_SECURE scope**: decided 2026-09-24, removed entirely.
4. **Publishing the next releases** from the owner's machine (a desktop build
   of `2.2.0.dev1` and a mobile build with this work), and whether to keep
   the mobile release marked "latest" on GitHub.
5. **The installer's sample clips** are not in any branch; commit them with
   LFS, host them on a release, or drop the option.
