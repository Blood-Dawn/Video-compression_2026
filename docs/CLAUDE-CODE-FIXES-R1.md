# Claude Code Fix/Feature Round 1 (post-beta-test feedback)

For: Claude Code (auto mode). These are fixes and features from the owner after testing the 2.0.0.dev0 installer. Work them in order. Same operating rules as `docs/CLAUDE-CODE-MASTER-PLAN.md` apply: one task at a time, run `pwsh scripts/run_tests.ps1` to green (>=857 passed locally, 0 failed), tick the box, commit (`<type>(<scope>): <subject>` + why-body + final line `Bloodawn(KheivenD)`, NO emojis), `git push origin app`, then next. Honor the M0 gotchas (.venv not venv, never `[plates]`, opencv-contrib, LF endings, ffprobe not cv2 for AV1). Browser-verify UI changes with the Preview MCP like you did for TASK 1.7.

IMPORTANT NEW RULE (applies to all code you write from now on): **no em-dashes (U+2014 "—") or en-dashes (U+2013 "–") anywhere** - use ASCII hyphen `-`, or restructure with commas/periods. This doc is written that way; keep it that way. FIX 9 removes the existing ones.

Branch `app`. Most of these are UI; do not change backend route URLs unless a task says so (the route-count guard test asserts 54).

---

## Context: root causes already scouted (so you don't re-diagnose)

- **OneDrive auto-default for Save-To AND Encrypted output:** the app auto-detects a cloud root and/or reads persisted prefs (`.svcs_gui_state.json`) and silently picks OneDrive. The owner wants to CHOOSE the destination, never an implicit cloud default. See `src/gui/services/cloud_detection.py` (`_default_output_dir`, `_detect_cloud_root`, `_detect_onedrive_root`) and the consumers in `pipeline_bp.py` / `hls_bp.py` / `demo_bp.py` / `files_bp.py`.
- **"Fresh install" shows old CPU averages + pre-chosen folders:** these are persisted state files in `%APPDATA%\SVCS` from prior runs - `.mode_cpu_avgs.json` (the CPU-per-mode samples shown in Metrics) and `.svcs_gui_state.json` (saved prefs incl. output dir). The installer does NOT bundle them (`installer/svcs.spec` datas = onnx model, ffmpeg, license only). A truly fresh machine is clean. We still add explicit setup + reset so it is controllable. `src/gui/services/cpu_sampler.py` owns `_MODE_AVG_FILE`; `src/utils/paths.py` lists the state files.
- **MediaMTX shows "NOT INSTALLED" in the frozen app even after a prior download:** detection resolves `tools/mediamtx/` relative to the dev project root, which does not exist under `C:\Program Files\SVCS`. See `src/gui/services/rtsp.py` and `src/gui/routes/rtsp_bp.py`. Fix the path resolution for the frozen app (check install dir, `%APPDATA%\SVCS\tools`, system PATH, and the bundle).
- **Topbar nav** lives in `src/gui/templates/index.html` (`<nav class="tab-nav">`, the `tab-btn`/`tab-page` pattern, generic `switchTab()`); per-feature JS is in `src/gui/static/js/*.js`. Current tabs: HOME, UPLOAD, METRICS, SEARCH, ENCRYPT.
- **Em/en dashes:** ~1555 em + ~246 en across the repo (verified with a Python count of "—"/"–"; NOTE: `git grep` with `\x{2014}` escapes under-reports and returns a false 0 - use a real scan). App-facing files: `index.html` (68), `static/js/files.js` (28), `static/js/pipeline.js` (23), `src/config.py`, etc.

---

## FIX 1 - First-run setup page + destination chooser (no implicit cloud default)

- [x] **What:** A first-run "Setup" page where the user explicitly chooses where outputs go, plus the same choices reachable later from settings. Remove the silent OneDrive default everywhere. *(DONE: cloud_detection no longer auto-picks a cloud root; _default_output_dir resolves to the user's explicit/persisted choice, else a neutral LOCAL ~/Videos/SVCS, never an implicit cloud. New list_destinations() offers local + drive letters + detected OneDrive/Google Drive/iCloud + custom, none auto-selected; added _detect_icloud_root(). New setup_bp: GET /api/setup/state, GET /api/setup/destinations, POST /api/setup/choose (validates + creates folders + persists). gui_state_persist stores output_dir + encrypted_dir + setup_complete and exposes save_setup_choice/is_setup_complete. encryption_bp + create_app no longer silently target OneDrive for encrypted output. New setup.js shows a first-run overlay that requires a destination pick and disables START until chosen, with a "Change..." affordance to reopen it; output field is filled from the choice, not cloud autodetect. Route guards moved to 57 routes / 15 blueprints. tests/test_setup.py + updated test_default_output_dir + test_gui_api output-dir tests. Browser-verified: overlay shows on first run with 11 detected destinations, START disabled until save, saving closes it and enables START, server persists the choice with Encrypted defaulting to a subfolder. Suite green: 873 passed.)*
- **Destinations to offer (detect which exist; never auto-pick):** Local folder (browse/enter a path), a specific drive (enumerate drive letters on Windows / mount points on Linux/mac), OneDrive (if a OneDrive root is detected), Google Drive (if Drive-for-Desktop root detected), iCloud Drive (if detected on mac/Windows), and a Custom path field. Two separate selections: (a) primary output/save location, (b) encrypted-output location (default to a subfolder of the save location, still user-changeable).
- **Behavior:** on first run (no persisted choice), show the Setup page and require a pick before Start is enabled. If the user skips, default to a neutral LOCAL path (`~/Videos/SVCS` via `paths.default_videos_dir()`), NOT a cloud root. Persist the choice in `.svcs_gui_state.json`. `_default_output_dir()` must return the user's chosen path first, and must NOT fall through to a cloud root unless the user explicitly selected one.
- **Files:** `src/gui/services/cloud_detection.py` (turn cloud roots into OFFERED options, not auto-selected; add detectors for Google Drive / iCloud where feasible), `src/gui/routes/presets_bp.py` or a new `setup_bp.py` (a small API to list detected destinations + save the choice), `index.html` + a new `static/js/setup.js`, `strings.js`.
- **Acceptance:** on a clean profile (no `%APPDATA%\SVCS`), the app opens on Setup; nothing writes to OneDrive unless chosen; the Save-To and Encrypted fields reflect the user's pick; `test_gui_api`'s output-dir tests updated to the new "explicit choice first, local fallback, cloud only if chosen" order; suite green. Browser-verify.
- **Risk:** iCloud/Google Drive root detection varies by OS and may not be reliable - if a provider can't be reliably detected, still offer it as a "Custom path" hint rather than failing.

## FIX 2 - Fresh-install hygiene + reset

- [ ] **What:** Make a fresh install genuinely start blank, and give a way to reset on a machine that already has state.
- **Do:** (a) The Metrics "CPU during encoding" panel must start EMPTY on a fresh install and only show samples gathered in THIS install - if `.mode_cpu_avgs.json` is historical, either label it clearly or do not seed the live panel from it. (b) Add a "Reset app data (factory reset)" action in settings that deletes `%APPDATA%\SVCS` state (`.mode_cpu_avgs.json`, `.svcs_gui_state.json`, `.flask_secret`, etc.) and returns the app to first-run. (c) Inno Setup uninstaller: offer to remove `%APPDATA%\SVCS` on uninstall.
- **Files:** `src/gui/services/cpu_sampler.py`, `src/utils/paths.py` (a `reset_state()` helper), a settings route + UI, `installer/svcs.iss`.
- **Acceptance:** reset clears the CPU samples and prefs and re-triggers Setup; documented "to test fresh, run Reset or clear %APPDATA%\SVCS"; suite green.

## FIX 3 - Sticky top header (fix scroll bleed-through)

- [ ] **What:** When scrolling, the top section's text shows through / overlaps content. Make the top header (SVCS title bar + tab nav) stay pinned on top, opaque, above scrolling content.
- **Do:** give the header `position: sticky` (or fixed) with an opaque background var, a high `z-index`, and ensure scrollable panels start below it (padding/top offset). No text from the header should be visible bleeding into scrolled content.
- **Files:** `index.html` (the header/topbar CSS + the scroll container).
- **Acceptance:** scroll every tab - header stays pinned and opaque, no bleed-through. Browser-verify.

## FIX 4 - Move RTSP + HLS into an "Advanced Tools" topbar tab

- [ ] **What:** The "Local RTSP Server" and "Live Stream (HLS)" blocks currently sit in the left sidebar. Move them into a new topbar tab next to Metrics/Search. Call it **TOOLS** (or "ADVANCED").
- **Do:** add a `tab-btn data-tab="tools"` button in the nav (place it after ENCRYPT, or between SEARCH and ENCRYPT - owner said "by the search and metrics"), a `#tab-tools` page, and relocate the HLS live-stream UI + the MediaMTX/RTSP server UI from the sidebar into it. Keep all wiring and API routes unchanged (no route-count change). Move the relevant logic in `static/js/hls.js` / `rtsp.js` if needed; keep `switchTab` generic.
- **Files:** `index.html`, `static/js/hls.js`, `static/js/rtsp.js`, `strings.js`.
- **Acceptance:** topbar shows the new TOOLS tab; HLS streaming + RTSP server controls work from it; sidebar no longer shows them; route-count guard still 54. Browser-verify both panels function.

## FIX 5 - Dependency detection (MediaMTX/ffmpeg) works in the frozen app

- [ ] **What:** RTSP section shows "NOT INSTALLED" even when MediaMTX was downloaded before, because the path is resolved against the dev project root.
- **Do:** make the MediaMTX detector check, in order: the frozen bundle dir (next to the exe), `%APPDATA%\SVCS\tools\mediamtx`, system PATH (`shutil.which("mediamtx")`), and the legacy `tools/mediamtx/`. Store future downloads under `%APPDATA%\SVCS\tools` (writable in Program Files installs) not the install dir. Reflect "installed" if found anywhere; disable/hide the Download step when present. Apply the same robust resolution pattern already used for bundled ffmpeg (TASK 2.3). Generalize into a small "dependency status" check the Setup/Help can show (ffmpeg, mediamtx, onnx model).
- **Files:** `src/gui/services/rtsp.py`, `src/gui/routes/rtsp_bp.py`, `src/utils/paths.py` (a tools dir helper).
- **Acceptance:** with mediamtx present (PATH or %APPDATA% or bundle), the UI shows installed and skips download; a test covers the resolver finding a binary in each location; suite green.

## FIX 6 - Library / gallery page (new feature)

- [ ] **What:** A **LIBRARY** topbar tab to browse videos in-app as a gallery, then pick one to compress.
- **Do:** new tab `data-tab="library"`; a grid of video thumbnails from the configured output/library folder(s) plus a user-pickable folder; view modes: thumbnail grid, list, and a detail view (single video with metadata + inline player); clicking a video opens detail with a "Compress this video" action that routes it into the existing start/upload flow. Generate a static thumbnail per video with ffmpeg (one frame, e.g. `ffmpeg -ss 1 -i in.mp4 -frames:v 1 thumb.jpg`); cache thumbnails under `%APPDATA%\SVCS\thumbs`. Animated/hover-preview thumbnails are OPTIONAL - skip if it adds risk.
- **Files:** new `src/gui/routes/library_bp.py` (list videos + thumbnail endpoint + "send to compress"), register it (route-count guard moves from 54 to the new total - update the assertion and list), `index.html` + new `static/js/library.js`, `strings.js`.
- **Acceptance:** Library tab lists video thumbnails from the folder; grid/list/detail toggles work; detail has a player + "Compress this"; thumbnails generate and cache; a test covers the listing + thumbnail endpoints (use a synthetic mp4 via the existing helper); suite green. Browser-verify.
- **Risk:** thumbnail generation must not block the request thread - generate lazily/async and cache. Large folders: paginate.

## FIX 7 - Verbose compression logging (console + dashboard)

- [ ] **What:** The console and dashboard log do not show much during a compress run. Add detailed, step-by-step progress.
- **Do:** during a run, log (to the SSE dashboard log AND stdout): source opened (dims/fps), mode + resolved codec + CRF, warmup complete, per-segment open/close with frame counts, detections per segment (people/vehicles), each saved segment path + size + compression ratio, and a running percent-done where the source length is known. Add a verbosity setting (Normal / Verbose) - Verbose adds per-N-frames progress. Make the live-log panel surface these.
- **Files:** `src/pipeline/pipeline.py` (it already logs some of this at INFO - extend, gate extra detail behind a verbose flag), `src/gui/services/pipeline_runner.py`, the log/SSE plumbing, a settings toggle in the UI.
- **Acceptance:** starting a compression shows clear step-by-step detail in the dashboard log and the console; the verbose toggle changes detail level; suite green (add/extend a test that the verbose flag increases emitted log records).

## FIX 8 - Update the Help / Reference section

- [ ] **What:** Reflect everything above in the in-app Help (the "SVCS HELP & REFERENCE" overlay).
- **Do:** document the Setup/destination chooser, the TOOLS tab (RTSP + HLS), the LIBRARY tab, the verbose-log toggle, the reset action, and the dependency-status check. Keep the existing Network Access section. No em/en dashes.
- **Acceptance:** Help covers the new features accurately; a guard test that Help contains the new section keywords; suite green.

## FIX 9 - Remove all em-dashes and en-dashes (codebase + apps + docs)

- [ ] **What:** Replace every U+2014 "—" and U+2013 "–" with ASCII. Verified count: ~1555 em + ~246 en. **Use a reliable scan (Python counting the literal "—"/"–", or `rg -P "\x{2014}|\x{2013}"`) - `git grep` with `\x{}` escapes reports a false 0.**
- **Do:** sweep in this priority order, committing per group: (1) app-facing: `src/gui/templates/index.html`, `src/gui/static/js/*.js`, `src/**/*.py`; (2) the rest of `src/`; (3) `docs/**`, root `*.md`, and other text. Replacement rules: em-dash "—" -> " - " (a spaced hyphen) or restructure to comma/semicolon/period where it reads better; en-dash "–" in numeric/letter ranges -> "-". Be careful inside code strings, regexes, CLI help, and f-strings - keep them syntactically valid. Do NOT touch binary files.
- **Guard:** add `tests/test_no_unicode_dashes.py` that scans tracked text files under `src/` (extend to `docs/` if you sweep them) and FAILS if any "—"/"–" remain, so they cannot creep back. Wire nothing new into CI beyond the test.
- **Acceptance:** the reliable scan reports 0 in `src/`; the new guard test passes; suite green. (Docs sweep is good-to-have; at minimum `src/` and all app-facing files must be clean.)

---

## Order and notes

Recommended order: FIX 9 first is tempting but it touches many files; instead do the functional fixes (1-8) first so their NEW code is already dash-free (the new rule), then FIX 9 sweeps the pre-existing ones last and the guard test locks it. If you prefer, do FIX 9's guard test + `src/` sweep early so everything after is enforced - your call, just keep each commit green.

After all nine: rebuild the installer (`installer/build.ps1` then `iscc installer/svcs.iss`), confirm it launches and the new tabs/Setup work in the frozen app, update `docs/BLOCKERS.md` and the owner-facing notes, and report: which fixes shipped, new route count + updated guard assertion, new test total, and anything that needs the owner (e.g., iCloud/Google Drive detection that could not be done reliably on this OS).
