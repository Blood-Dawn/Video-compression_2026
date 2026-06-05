# Claude Code Fix/Test Round 2 (feature audit + real-video tests + Library overhaul)

For: Claude Code (auto mode). Same operating rules as `docs/CLAUDE-CODE-MASTER-PLAN.md`: one task at a time, run `pwsh scripts/run_tests.ps1` to green (0 failed; current baseline is ~928 passed), browser-verify UI with the Preview MCP, tick the box, commit (`<type>(<scope>): <subject>` + why-body + final line `Bloodawn(KheivenD)`, NO emojis), `git push origin app`, next. M0 gotchas still apply (.venv not venv, never `[plates]`, opencv-contrib, LF endings, ffprobe not cv2 for AV1). NO em-dashes or en-dashes in anything you write; the guard test enforces `src/`.

Branch `app`. Three tasks plus a version bump. Do TASK R2.3 (Library) and TASK R2.1 (audit) before R2.2 if you like, but all three must land green.

## TASK R2.0 - Bump version to 2.1.0 (this release is the 2.1 beta)

- [x] Set the project version to **`2.1.0.dev0`** in `pyproject.toml` (it is `2.0.0.dev0` now). Update any place that hard-codes the version string (e.g. the installer output name `SVCS-Setup-2.0.0.dev0.exe` becomes `SVCS-Setup-2.1.0.dev0.exe` via `installer/svcs.iss` / `build.ps1`, and any version shown in the dashboard/Help). Grep for `2.0.0` to catch them. Update `docs/RELEASE-CHECKLIST.md` and the draft notes so the beta tag is **`v2.1.0-beta`**. Suite green. (When the owner publishes, the release tag is `v2.1.0-beta` and the asset is `SVCS-Setup-2.1.0.dev0.exe`.)


---

## TASK R2.1 - Full feature audit + end-to-end coverage

Goal: confirm EVERY feature actually works in the running app, write down the result, and fix what is broken.

- [x] **Audit pass (use the Preview MCP, real browser).** Start the server, then exercise every tab and control and record pass/fail in a new `docs/FEATURE-AUDIT.md` (a table: Feature | How tested | Result | Notes). Cover at least:
  - Each topbar tab loads and switches: HOME, UPLOAD, LIBRARY, METRICS, SEARCH, TOOLS, ENCRYPT.
  - Setup overlay: first-run shows it, destinations list, choosing one persists and enables START.
  - HOME: upload a video (UPLOAD tab dropzone), pick each preset, set CRF, START a real compress, watch the live log, confirm an output segment appears in Recent Recordings and on disk.
  - Each of the 4 modes / the preset families actually produce output (tie this to TASK R2.2).
  - METRICS: segments table populates after a run; CPU-during-encoding panel; library summary.
  - SEARCH: archive search returns rows for existing segments; filters apply.
  - TOOLS: HLS live-stream controls; Local RTSP server (download/start/stop) - and confirm FIX 5 made detection correct.
  - ENCRYPT: keygen, encrypt a file, decrypt it back.
  - LIBRARY: folder load, thumbnails, detail player, compress-this (this is TASK R2.3; note current breakage here).
  - Help overlay: all sections render; dependency check; reset button.
  - Verbose log toggle changes console/dashboard detail during a compress.
- [x] **Fix what the audit finds.** Small bugs: fix inline in this task with a regression test each. Anything large or risky: list it at the bottom of `docs/FEATURE-AUDIT.md` as a follow-up rather than rushing it. Do not leave a feature marked "broken" without either a fix or a written follow-up.
- [x] **Automated end-to-end smoke test.** Add `tests/test_end_to_end_smoke.py` that, against the Flask test client, GETs `/` (200) and hits every read-only API route (status, segments, library/videos, setup/state, setup/destinations, metrics, dependencies, etc.) asserting each returns a sane JSON shape (not 500). This is the cheap guard that no route 500s on a clean install. Keep it env-light (no real video required).
- **Acceptance:** `docs/FEATURE-AUDIT.md` exists with every feature marked pass or fixed-or-followup; the smoke test passes; full suite green; browser-verified.

## TASK R2.2 - Real-video integration test (point it at a folder of real clips)

Goal: a test that runs the ACTUAL pipeline on REAL videos from a folder the owner controls, so "does it really compress" is provable, not just unit-mocked.

- [ ] **New `tests/test_real_videos.py`.** It resolves a folder in this order: env var `SVCS_TEST_VIDEO_DIR`, else the existing CDnet sample corpus at `data/samples/cdnet_mp4` (the repo's real-clip test set; it has subfolders like `baseline/`, `intermittentObjectMotion/`, etc., so scan it **recursively** with `rglob("*.mp4")` and pick the clips to run). If the folder is empty or missing (it is git-LFS, so absent on CI), **skip with a clear message** (so CI stays green - CI has no real clips). When clips are present:
  - **Pick ONE clip from each immediate subfolder** of the corpus (one per CDnet scene-type category - baseline, badWeather, cameraJitter, dynamicBackground, intermittentObjectMotion, nightVideos, shadow, thermal, etc., about a dozen), so every scene type is exercised. Run each selected clip through every mode (mode0..mode3), writing to a temp output dir. (If `SVCS_TEST_VIDEO_DIR` points at a flat folder with no subfolders, just take the clips directly, capped at a reasonable number.)
  - Assert every produced segment is a valid container via **ffprobe** (reuse the `_ffprobe_ok` pattern from `test_mode_size_hierarchy.py`), has a video stream, and is non-empty.
  - Assert the output is smaller than the raw uncompressed size, and record the actual compression ratio per clip/mode in the captured output (so the owner can see real numbers).
  - Verify the per-mode codec is what TASK 1.6 decided (mode0/1 = H.264, mode2/3 = AV1) by probing the output stream codec with ffprobe.
- [ ] **Owner doc.** A short note in the test's module docstring (and a line in `docs/FEATURE-AUDIT.md`): "Runs the real pipeline on the CDnet clips in `data/samples/cdnet_mp4` (or set `SVCS_TEST_VIDEO_DIR` to point at any folder of clips). Run `uv run --no-sync pytest tests/test_real_videos.py -s` to see real compression ratios per clip and mode, and confirm each mode + codec works on real footage." No new media committed; it reuses the clips already in the repo.
- **Acceptance:** with an empty folder the test skips cleanly and the suite stays green; with clips present it runs them through the pipeline and asserts valid + smaller + correct codec; runtime is bounded; `-s` prints a readable per-clip/mode ratio table.

## TASK R2.3 - Library: real folder selection, populate reliably, filters, search, compress

Goal: the Library tab must let the user PICK a folder, see videos populate, filter and search them, and send one to compression. The owner reports it "not working" today.

Current state (so you do not re-discover): backend `src/gui/routes/library_bp.py` already has `GET /api/library/videos?folder=&page=&page_size=`, `/meta`, `/thumb`, `/file`, and `POST /api/library/compress`. Frontend `src/gui/static/js/library.js` has a `library-folder` text input + Load, grid/list toggle, thumbnails, detail player, and `compressLibrarySelection()`. So folder-by-typed-path, populate, and compress EXIST; what is missing is a real folder PICKER, FILTERS, and SEARCH, and something is making it not populate in practice.

- [x] **Diagnose the "not working" first.** Likely causes to check and fix: (a) the default folder is the post-Setup output dir which is empty on a fresh install, so it shows "No videos" and looks broken - make the empty state clear and offer Browse; (b) thumbnail generation fails in the frozen app if ffmpeg is not resolved the FIX 5 way - reuse the robust ffmpeg resolver, and make a thumbnail failure fall back to a placeholder rather than a broken image; (c) any JS error in `library.js` (check the console). Write down the actual root cause in the commit body.
- [x] **Folder picker.** Add a "Browse..." button next to the folder field that opens a folder chooser. Reuse the existing `GET /api/browse` (files_bp) to navigate directories server-side, or a native dialog if simpler; the user must be able to SELECT a folder without typing a path. Remember the last-used library folder (persist it like the other prefs).
- [x] **Search.** A search box on the Library tab that filters the listed videos by filename substring (live). Server-side `q=` param on `/api/library/videos` for large folders, with a client-side filter for the loaded page.
- [x] **Filters.** Filter controls on the page: by file type/extension, by size range, by date modified (newest/oldest), and if cheap from `/meta`, by resolution or duration. Sort options (name, size, date). Filters and search compose.
- [x] **Select for compression.** Confirm selecting a video (grid or detail) and pressing "Compress this" loads it into the source and switches to the compress flow, and that a subsequent Start actually compresses THAT file. Fix if broken.
- [x] **Tests.** Extend `tests/test_library.py` (or add one): listing a temp folder of synthetic mp4s, the `q=` search filter, type/size/date filtering and sorting, the browse-folder flow, thumbnail fallback when ffmpeg is missing, and the compress route wiring. Browser-verify the whole flow with the Preview MCP (pick a folder, see clips, search, filter, open one, compress).
- **Acceptance:** in the browser, pick a folder with videos, they populate as a thumbnail grid; search narrows by name; filters/sort work; opening a clip shows the player + metadata; "Compress this" routes it into Start and a real compress runs; empty/missing folders show a clear message with Browse; suite green.

---

When all three are done: rebuild the installer (`pwsh installer\build.ps1 -Installer`), smoke-test the frozen app, and report: the FEATURE-AUDIT results (what was broken and fixed), the real-video test behavior, the Library overhaul, new route count + updated guard assertions, new test total, and anything deferred to `docs/BLOCKERS.md`.
