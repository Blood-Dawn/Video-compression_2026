# SVCS Handoff - for Fable 5

**Audience:** Claude Fable 5 (or equivalent), reasoning at maximum effort, picking up the SVCS project fresh.
**Owner:** Kheiven D'Haiti ("Bloodawn", kheivendhaiti@gmail.com). FAU EGN-4950C capstone, now an open-source product.
**Repo:** `C:\Users\kheiven\Documents\GitHub\Video-compression_2026` (Windows host, branch `app`, GitHub `Blood-Dawn/Video-compression_2026`).
**Version:** 2.1.0.dev0 (the "2.1 beta"). Previous public asset: `v2.0.0-beta` pre-release.
**Style rule, repo-wide:** NO em-dashes (U+2014) or en-dashes (U+2013) anywhere in code, UI, or docs. ASCII hyphen only. This document obeys that. A guard test (`tests/test_no_unicode_dashes.py`) enforces it for `src/`.

This handoff has two parts. Part A orients you to the whole project so you can continue any thread. Part B is the detailed Claude Design playbook (the owner's current focus: use Claude Design to redesign the desktop app and design the future mobile app).

---

# PART A - Project state and how to work

## A1. What SVCS is

Selective Video Compression System: free, open-source (AGPL-3.0), self-hosted, AI-aware video compression for security-camera footage. It keeps the parts that matter (people, vehicles, motion, faces, plates) sharp and starves the static background a fixed camera stares at all day. Origin: a DoD/DIU-sponsored FAU surveillance capstone, productized into an open-source tool. Biggest measured win: 6x typical, up to 16x on quiet static-camera footage.

Today it is a Python pipeline + Flask browser dashboard, shipped as a Windows installer (~210 MB) that runs a local dashboard at http://127.0.0.1:5000. A mobile app is planned but deliberately deferred.

## A2. The journey so far (what is DONE)

This project went from a 3,880-line monolith with a red test suite and a 4.7 GB installer to a modular, CI-green, 210 MB product. Milestones, all on branch `app`:

- **M0 - Foundation.** Greened the test suite (it was secretly 48-failing), added GitHub Actions CI (Linux + Windows), version/hygiene, fixed two real bugs found along the way (mode2 CRF stuck at 18; a sqlite connection leak via `with conn:` that never closed). Made the project open-source-only (dropped the dual-license/premium track; `CLA.md` + `LICENSE-COMMERCIAL.md` are marked DORMANT).
- **M1 - Refactor.** Split `gui/app.py` (3,880 lines) into a thin `app.py` (~300 lines) + `state.py` + `logging_setup.py` + 9 service modules + 12 route blueprints, with a `_ForwardingModule` seam so rebound globals (`_pipeline_thread`, `_log_id`) still round-trip. Split `index.html` (7,026 lines) into feature JS modules + `strings.js`. Added a dedicated Upload topbar tab.
- **M1.6 - Per-mode codec.** mode0/mode1 = H.264 (libx264, universal playback); mode2/mode3 = AV1 (libsvtav1, max compression, royalty-free). No H.265 (its patent licensing is not free). GUI default is "Auto (per-mode)".
- **M2 - Slim installer.** Replaced PyTorch with ONNX Runtime for detection (YOLOv8n to ONNX), made torch optional, bundled LGPL FFmpeg, wrapped in Inno Setup. Installer: 4.6 GB -> 339 MB slim -> 210 MB `.exe`.
- **M3 - Presets + content auto-detect.** Named surveillance presets (Continuous CCTV, Motion-event, Doorbell, etc.) mapping to (mode, CRF, codec); rule-based first-30-seconds content detection (reuses the MOG2 foreground ratio, not a CNN).
- **M-CAM - Camera ingestion.** ONVIF/RTSP discovery for IP cameras; export-folder watch profiles; a documented bridge path (Home Assistant / Scrypted / Frigate) for cloud-locked cams (Ring/Nest) since they have no local API; a consumer-camera preset family. SVCS never scrapes vendor clouds.
- **M4 - Self-host.** Hardened watch-folder; Docker image; dashboard basic-auth when bound to anything other than localhost.
- **M5 / M5b - Beta prep.** Public download page; opt-in anonymous usage stats (separate from crash reporting); getting-started + camera docs; release checklist + draft notes (publishing is owner-gated); Windows signing step wired (cert is owner-gated); Linux AppImage recipe.
- **Round 1 fixes (post-beta-test).** First-run Setup page + destination chooser (no implicit OneDrive default; user picks Local/drive/OneDrive/GDrive/iCloud/custom for both output and encrypted dirs); fresh-install hygiene + factory reset; sticky header; moved RTSP + HLS into a TOOLS tab; fixed frozen-app MediaMTX detection; a LIBRARY tab (gallery); verbose compression logging; Help updates; and the repo-wide em/en dash removal + guard test.

Current dashboard tabs: **HOME, UPLOAD, LIBRARY, METRICS, SEARCH, TOOLS, ENCRYPT** (plus Setup and Help overlays).

## A3. What is QUEUED (not yet done)

`docs/CLAUDE-CODE-FIXES-R2.md` is written and waiting for Claude Code:
- **R2.0** - bump version to 2.1.0.dev0 (installer name -> `SVCS-Setup-2.1.0.dev0.exe`, release tag -> `v2.1.0-beta`).
- **R2.1** - full feature audit (click through every tab via the Preview MCP, record pass/fail in `docs/FEATURE-AUDIT.md`, fix what is broken, add an end-to-end smoke test).
- **R2.2** - real-video integration test against `data/samples/cdnet_mp4` (52 real CDnet clips across ~12 scene-type folders: baseline, badWeather, cameraJitter, nightVideos, shadow, thermal, etc.). One clip per folder through every mode; assert valid (ffprobe) + smaller + correct per-mode codec; print real ratios. Skips on CI (clips are git-LFS, absent there). Override folder via `SVCS_TEST_VIDEO_DIR`.
- **R2.3** - LIBRARY overhaul: the owner reports it "not working" (most likely it defaults to the empty post-Setup output folder so it shows "No videos"). Add a real folder picker (currently you type a path), a search box, filter/sort controls, and confirm select-for-compression works. Backend already lists/thumbnails/compresses via `library_bp`.

## A4. What is GATED (needs the owner, do not do autonomously)

In `docs/BLOCKERS.md`: tag/publish a release (owner); Windows code-signing cert (owner buys, or SignPath OSS program); macOS .dmg (needs Apple cert + a Mac); the Rust core spike on `kdev` (owner go-ahead only); anything commercial/legal (out of scope for v2).

## A5. Architecture map (where things live)

```
src/
  pipeline/pipeline.py        run_pipeline(): the engine. mode 0-3, per-mode CRF (18/18/23/38) + codec, MOG2 + YOLO(ONNX) + ROI encode.
  pipeline/presets.py         named presets -> (mode, CRF, codec). content_detect.py = rule-based auto-detect.
  detection/object_filter.py  YOLOv8n object filter; backend selector "auto"/"onnx"/"torch" (ONNX default, RT-DETR-ready seam).
  background_subtraction/     MOG2 (default) + GMG (needs cv2.bgsegm -> opencv-CONTRIB).
  compression/roi_encoder.py  the FFmpeg ROI encoder (begin_segment/finish_segment).
  utils/                      db/ (sqlite metadata), paths.py (platformdirs state + reset_state), frame_source.py (file/RTSP/cam),
                              onvif_discovery.py, watchfolder.py, usage_stats.py, crash_reporting.py, encryption.py (AES-256-GCM).
  gui/
    app.py                    thin: app + create_app() + register_blueprints() + re-export forwarder (~300 lines).
    state.py, logging_setup.py
    services/                 path_safety, cloud_detection, gui_state_persist, db_helpers, cpu_sampler, rtsp, demo_runner, hls_runner, pipeline_runner
    routes/                   16 blueprints incl. setup_bp, library_bp, cameras_bp, usage_bp, pipeline_bp, files_bp, hls_bp, rtsp_bp, encryption_bp, ...
    templates/index.html      the single-page dashboard (all CSS tokens + tab markup).
    static/js/                per-feature modules: setup, library, tools, cameras, usage, pipeline, files, metrics, hls, rtsp, status, encryption, presets, strings, ui.
installer/                    build.ps1 (PyInstaller + vendored ffmpeg + Inno; use -Installer), svcs.spec, svcs.iss, appimage/
data/samples/cdnet_mp4/       52 real CDnet test clips (git-LFS).
docs/                         the planning + handoff docs (map in A8).
tests/                        ~49 test files; the route-count + reexport + no-dashes guards live here.
```

## A6. Conventions (non-negotiable)

- Branch `app` only. `main`/`dev`/`kdev` untouched by product work; `premium` is dormant; no `app`->`premium` mirror.
- Commits: `<type>(<scope>): <subject>` + a why-body + final line exactly `Bloodawn(KheivenD)`. No emojis.
- Tests ship with every change. Green = `pwsh scripts/run_tests.ps1` ends 0 failed (current baseline ~928 passed; 3-4 skips expected = webcam + opt-in Docker). Never fake green.
- No em/en dashes (guard-tested in `src/`).
- Gotchas that cost real loops: use `.venv` (not the stale `venv/`); NEVER install the `[plates]` extra in the working env (easyocr pulls opencv-python-headless which clobbers the core opencv-contrib-python and breaks cv2); keep `opencv-contrib-python`; LF line endings (`.gitattributes` enforces; `git add --renormalize .` if CRLF drift); validate produced mp4s with ffprobe, not OpenCV (AV1 is not always decodable by cv2).
- Build the installer with `.venv` active: `pwsh installer\build.ps1 -Installer` (it finds ISCC.exe itself; do not call `iscc` manually). In Git Bash use forward slashes for paths.

## A7. Decisions already made (do not re-open)

Open-source-only / AGPL; surveillance is the product (not a generic transcoder, no competitor positioning); consumer cameras in scope via bridges/export, never cloud-scraping; mode3 = a single object-only clip (NOT a per-object `mode3_sparse/` tree - that never shipped); foreground CRF 18/18/23/38; per-mode codec H.264 (mode0/1) + AV1 (mode2/3), no H.265; ONNX over torch; modes hidden behind presets; rule-based auto-detect (not a CNN); telemetry opt-in only; no SaaS. Rationale for all of this: `docs/PLAN-V2.md`.

## A8. Doc map (read what you need)

- `docs/PLAN-V2.md` - the product + technical plan and every decision's rationale.
- `docs/CLAUDE-CODE-MASTER-PLAN.md` - the full build plan M1.2 -> M5b with operating rules and gates (mostly done now).
- `docs/CLAUDE-CODE-FIXES-R1.md` / `R2.md` - the two post-beta fix rounds (R1 done, R2 queued).
- `docs/BLOCKERS.md` - the owner-gated remainder.
- `docs/test-baseline.md` - the M0 triage history and the two real bugs.
- `docs/REFACTOR-PLAN-gui-app.md` - the gui split design.
- `docs/CLAUDE-DESIGN-SETUP.md` - the short Claude Design setup (Part B here expands it).
- `docs/FEATURE-AUDIT.md` - will exist after R2.1 (feature-by-feature pass/fail).

## A9. The SVCS design tokens (the visual identity, extracted from index.html)

Dark surveillance command-center aesthetic.
- Backgrounds: `#0a0e14` (bg), `#10192a` (surface), `#162238` (raised). Borders `#2a4466` / `#3a5a7a`.
- Primary accent: amber `#ffb900` (soft glow `rgba(255,185,0,0.15)`).
- Section/tab accents (color-coding): teal `#1fd4c8`, green `#2dd6a0`, yellow `#ffc800`, purple `#b888ff`, red `#ff5555` (error/stop).
- Text: `#d8e8f5` body, `#7a8fa8` dim, `#f0f8ff` bright.
- Fonts: Bebas Neue (display headings, letter-spaced), Space Mono (data/labels/terminal), Outfit (body). Google Fonts.
- Patterns: UPPERCASE labels with wide letter-spacing (0.1-0.2em); sharp 2px corners (never pill); subtle CRT scanline overlay; flat cards/buttons with 1px borders and accent glow on active. Status: amber = active, green = online/good, red = offline/error.

---

# PART B - Claude Design playbook (the owner's current focus)

Claude Design (claude.ai/design, Anthropic Labs research preview, in the owner's Max plan, palette icon in the Claude sidebar) lets you collaborate on polished designs, prototypes, slides, and one-pagers. You set up a design SYSTEM once from the codebase/screenshots; after that every project auto-uses SVCS colors, type, and components. The goal here: redesign the desktop app screen-by-screen and design the future mobile app, then hand the designs back to Claude Code to implement.

## B1. One-time design-system setup (the "Set up your design system" form)

Open Claude Design, confirm the org picker (lower-left) shows the owner's account, click "Set up design system", and fill the form:

1. **Company name and blurb:** paste the A1 description of SVCS (surveillance compression, desktop now + mobile planned, dark command-center aesthetic, audience = CCTV operators + home-lab self-hosters + consumer-camera owners).
2. **Link code on GitHub:** SKIP. Documented limitation: large repos lag/break the browser. Our repo is huge (venvs, dist builds, models, 52 sample videos).
3. **Link code from your computer:** attach ONLY the frontend folder: `C:\Users\kheiven\Documents\GitHub\Video-compression_2026\src\gui`. That is the entire frontend (CSS tokens in `templates/index.html` + all `static/js/` modules) and nothing extraneous.
4. **Upload a .fig file:** SKIP. No Figma file; the codebase is the source of truth.
5. **Add fonts, logos and assets:** add 3-5 screenshots of the real running app. Start it with `uv run python run_gui.py`, open localhost:5000, and capture HOME, METRICS, LIBRARY, the Setup overlay, and Help. Real examples beat specs for capturing the feel. Add any SVCS logo asset if one exists.
6. **Any other notes:** paste the A9 design tokens verbatim, and include the no-em/en-dash rule so Design output obeys it.

Click "Continue to generation".

## B2. Validate the extracted system (about 15 minutes)

In a throwaway project, run these and check the output looks like SVCS (dark navy + amber, Bebas/Space Mono/Outfit, 2px corners, uppercase labels), not generic blue/white:
- "Design the SVCS dashboard home: live status cards (frames decoded, segments saved, speed, storage saved), a mode/preset selector, a recent-recordings table."
- "Design the SVCS video library: a thumbnail grid of surveillance clips with search + filters and a detail view with an inline player."
- "Design the SVCS first-run setup: pick where compressed videos are saved (local folder, drive, OneDrive, Google Drive, custom)."

If it drifts, correct via Remix/chat ("backgrounds must be #0a0e14, accent #ffb900, no rounded corners, Bebas Neue headings") or add more screenshots and re-extract. When happy, flip the **Published** toggle so all new projects use the system.

## B3. Redesign the desktop app, screen by screen (the core loop)

For each screen, one Claude Design project (or one project with pages): HOME, UPLOAD, LIBRARY, METRICS, SEARCH, TOOLS, ENCRYPT, the Setup overlay, the Help overlay.

1. **Prompt with the REAL controls** for that screen so nothing is lost in the redesign. Copy the actual control list from the running app or from the relevant `static/js/<feature>.js` + the tab markup in `index.html`. Example for LIBRARY: "folder picker + Browse, search box, filter/sort (type, size, date), thumbnail grid, list view, detail view with player + metadata + Compress-this."
2. **Iterate** with inline comments and the adjustment knobs (spacing/color/layout). If an inline comment vanishes before Claude reads it, paste the comment text into the chat (known quirk). If a save error hits in compact mode, switch to full view and retry.
3. **When a screen is right:** export it (and any generated markup) and save under `docs/design/<screen>/` in the repo. Capture a screenshot too.
4. **Hand it to Claude Code:** write a short fix-round doc (call it `docs/CLAUDE-CODE-FIXES-R3-DESIGN.md`, same format as R1/R2) that says, per screen: "Match `docs/design/<screen>/` for the X tab. Keep every route URL, element ID, and event handler intact (the route-count guard asserts the current count; the frontend contract is the fetch() calls and IDs). No behavior change, only visuals. Run `pwsh scripts/run_tests.ps1` green, browser-verify with the Preview MCP, commit `Bloodawn(KheivenD)`, no emojis, no em/en dashes." Claude Code implements against the existing blueprint/JS structure; the guards keep it honest.

Treat Claude Design output as a SPEC for Claude Code, not a direct code drop, until you have verified its generated markup quality on one screen. The app's real structure (16 blueprints, the `tab-btn`/`tab-page`/`switchTab` pattern, the CSS variables) must be preserved.

## B4. Design the mobile app now (free, before any Flutter code)

The roadmap defers mobile, but Claude Design lets you design it now at no cost and get a clickable prototype to show the team/sponsor. Prompt for an SVCS mobile app using the published system:
- Home: camera status + recent clips.
- Library: thumbnail grid + search/filter.
- Clip detail: player + a Compress action.
- Settings: save destination + preset picker.
Iterate to a prototype. Save the designs under `docs/design/mobile/`. This becomes the concrete input for the eventual mobile decision (Flutter vs other) rather than starting from a blank page.

## B5. Slides and one-pagers (bonus, on-brand for free)

Claude Design also produces slide decks and one-pagers in the published system. Use it for the capstone presentation, the download-page hero, and a README banner; they come out matching SVCS automatically.

## B6. Sequencing recommendation

Let Claude Code finish Round 2 first (the feature audit + the LIBRARY fix + the 2.1 bump). Then take the screenshots in B1 from the FIXED 2.1 app, so the extracted design system reflects the real current product. Then run B3 (desktop redesign) and B4 (mobile) and feed the results back as `docs/CLAUDE-CODE-FIXES-R3-DESIGN.md`.

## B7. Known Claude Design quirks (research preview)

- Inline comments can disappear before Claude reads them -> paste into chat as backup.
- Compact layout mode can trigger save errors -> use full view.
- Large repos lag -> we attach `src/gui` only, never the whole repo.
- It is a preview: keep the repo as the source of truth; designs are specs for Claude Code until verified.

---

*End of handoff. The repo is the source of truth; this document is the orientation. Everything builds on branch `app`, stays test-green, and avoids em/en dashes.*
