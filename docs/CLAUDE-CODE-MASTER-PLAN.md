# Claude Code Master Plan — SVCS v2 (TASK 1.2 → end of roadmap)

**For:** Claude Code (edits + runs tests in one loop).
**Prepared:** 2026-06-01. Picks up where TASK 1.1 left off (state.py / logging_setup.py extracted, suite green).
**How to use:** *"Read `docs/CLAUDE-CODE-MASTER-PLAN.md`. Execute the tasks in order starting at the next unchecked one. Do ONE task at a time: make the change, run `pwsh scripts/run_tests.ps1`, and only when it's green, stop and show me the diff + a proposed commit. Wait for me to commit/push before the next task. Never cross a milestone gate marked 🚦 without asking me."*

This plan is the single source of truth for execution. It inlines what you need; for the deepest design detail it points to `docs/REFACTOR-PLAN-gui-app.md`, `docs/EXECUTION-CLAUDE-CODE.md`, and `docs/PLAN-V2.md`.

---

## A. Operating rules (apply to EVERY task)

**Cadence.** One task → `pwsh scripts/run_tests.ps1` must stay **≥ 513 passed, 0 failed** (3 webcam skips are expected) → stop, show the diff and a proposed commit → human reviews, commits, pushes → next task. **Never proceed on a red suite.** If you can't make a task green, revert it and explain why rather than piling broken changes.

**Conventions.**
- Branch: `app` only. Don't touch `main`/`dev`/`kdev`. `premium` is **dormant** — no `app`→`premium` mirror; just `git push origin app`.
- Commits: `<type>(<scope>): <subject>` + a *why* body, last line `Bloodawn(KheivenD)`. Types: feat|fix|refactor|test|build|chore|docs. **No emojis** in code or commits.
- The **human pushes.** You propose `git add ...` + commit + `git push origin app`; they run it.
- Tests ship with the change in the same commit. One reviewable commit per task (or per sub-step where noted).
- Authorship comment on non-obvious blocks: `# Author: Bloodawn (KheivenD), 2026-06-XX (<what>).`
- Black, ruff, type hints on new public functions, Python 3.11+.

**Gotchas already paid for in M0 — don't relearn them:**
- Use `.venv` (uv-managed), not the stale `venv/`. Run everything via `uv` / `scripts/run_tests.ps1`. Ignore the `VIRTUAL_ENV=venv` warning.
- **Never install the `[plates]` extra in the working/CI env** — easyocr pulls `opencv-python-headless`, which clobbers the core `opencv-contrib-python` and breaks `cv2` (MOG2 disappears). Plate-reader code/tests must not require easyocr at import time.
- OpenCV is **`opencv-contrib-python`** (code uses `cv2.bgsegm`). Don't "fix" it to plain opencv-python.
- **Line endings: LF** (`.gitattributes eol=lf`, except `.ps1`/`.bat`). If files show as whole-file "modified", it's CRLF drift — `git add --renormalize .`; keep commits content-only.
- **Validate produced mp4s with ffprobe, not `cv2.VideoCapture().read()`** — the default codec is AV1 (libsvtav1) and OpenCV can't decode it on some platforms. Pattern: `tests/test_mode_size_hierarchy.py::_ffprobe_ok`.
- CI (`.github/workflows/ci.yml`) runs the suite on Linux+Windows on push to `app`, installs CPU torch (`--no-sources`) + ffmpeg, excludes `[plates]`. Keep it green. CDnet-clip tests skip on CI (LFS not pulled) — don't make CI depend on them.

**Decisions already made (do NOT re-ask; build to these):**
- **Open-source only, AGPL-3.0.** No commercial/premium edition in v2. `premium` dormant. No CLA, no pricing, no SaaS. Ignore `LICENSE-COMMERCIAL.md`/`CLA.md` (marked dormant).
- **Surveillance is the product.** Static-camera footage first. No generic-transcoder / competitor positioning. Consumer security cameras (Ring/Nest/Wyze/Reolink) are in scope via M-CAM.
- **Mode 3 = a single object-only clip** (moving objects kept, background blacked out). NOT the per-object `mode3_sparse/` layout (that never shipped; don't rebuild it unless the owner asks).
- **Foreground CRF is progressive:** mode0=18, mode1=18, mode2=23, mode3=38. Preset `ultrafast` for mode2/mode3 (CPU), `veryfast` for mode0/mode1. Don't change these without owner sign-off.
- **UI hides modes behind named presets** (raw mode picker behind an "Advanced" toggle).
- **Preset auto-detect is rule-based** (reuse the MOG2 foreground-area ratio + simple signals), **not a CNN**.
- **Telemetry: opt-in only**, off by default. A separate, explicitly opt-in anonymous usage-stats channel is allowed (distinct from crash reporting). No PII, no paths, no footage.
- **Inference moves to ONNX Runtime** (M2) to slim the installer; keep the detector backend interface swappable (RT-DETR seam) but don't change detection behavior.
- **Default codec is per-mode (codec gate RESOLVED 2026-06-01):** mode0/mode1 → **H.264** (`libx264`) for universal playback + patent safety; mode2/mode3 → **AV1** (`libsvtav1`) for the most aggressive compression (royalty-free patents). **H.265/HEVC is NOT used** — its patent licensing is fragmented and not royalty-free, unlike H.264. The GUI keeps a codec selector with **"Auto (per-mode)"** as the default plus explicit AV1/H.264 overrides. FFmpeg bundle is an LGPL build. Implement via TASK 1.6.
- **Update channel: manual "check latest GitHub Release"**, no silent auto-update in v2.
- **i18n: extract user-facing strings now** (a `strings.js` catalog), translate nothing yet.

**🚦 GATES — STOP and ask the owner; do not decide these alone:**
1. **Code-signing certs** (Windows EV ~$300–600/yr, Apple Developer $99/yr). Needed for M5b signing. The owner must obtain them; wire the signing step but don't block on buying.
2. **Publishing a public release / tagging a beta** (TASK 5.4, 5b.*). You prepare the artifacts + checklist; the **owner** tags and publishes.
3. **The Rust spike (M6).** Only start on an explicit "go" from the owner — it's a measured spike, not committed work.
4. **macOS .dmg notarization (5b.3).** Requires the Apple cert; defer unless the owner provides it. Linux-first is fine.
5. Anything touching the **commercial/legal** track — out of scope for v2 entirely.

*(The output-codec gate was resolved 2026-06-01 — see the per-mode codec decision above and TASK 1.6.)*

**Progress tracking.** Tick a task here (change `[ ]` to `[x]`) in the same commit that completes it, so this file always shows where execution is.

---

## M1 — Refactor `gui/app.py` + `index.html`  (continue; 1.1 done)

Design authority: `docs/REFACTOR-PLAN-gui-app.md`. Hard constraints recap: keep `from gui.app import app` working; re-export every private name the tests reach via `gui_module.*`; rebound names (`_pipeline_thread`, `_stop_event`, `_log_id`) use the `_ForwardingModule` seam already added in 1.1; import direction one-way (state ← logging_setup ← services ← blueprints ← app; nothing imports `gui.app`); SSE closure binds module-level names; atexit stays with `_file_handler` in `logging_setup.py`; update PyInstaller hiddenimports.

- [x] **TASK 1.1** — extract `state.py` + `logging_setup.py` (DONE, green).

- [x] **TASK 1.2 — extract the services layer.** Depends: 1.1.
  **Files:** new `src/gui/services/{path_safety,cloud_detection,gui_state_persist,db_helpers,cpu_sampler,rtsp,demo_runner,hls_runner,pipeline_runner}.py`; `src/gui/app.py`.
  **Do:** move each service per REFACTOR-PLAN §2/§3, **one module per commit**, in the §4 order; `pipeline_runner` **last** (most threading). Convert the import-time `_bg_hw_thread` start into an explicit `start_hw_sampler()` called from `create_app()`. Route the rebound `_pipeline_thread`/`_stop_event` through the 1.1 forwarder so `gui_module._pipeline_thread = None` (in tests) still works.
  **Acceptance:** suite green after each module; `gui.app.*` contract intact; no circular imports.
  **Risks:** circular imports (keep direction one-way); the SSE generator closure; atexit ordering; the pipeline-thread forwarding. If a module won't extract cleanly, leave a thin shim in `app.py` and note it.

- [x] **TASK 1.3 — carve 48 routes into 12 blueprints.** Depends: 1.2.
  **Files:** new `src/gui/routes/*_bp.py` (12, per REFACTOR-PLAN §1); `src/gui/app.py` (→ thin: `app` + `create_app()` + `register_blueprints()` + re-exports, ~80 lines).
  **Order (smallest first):** ui → sse → metrics → presets → encryption → plates → queries → rtsp → demo → hls → files → pipeline.
  **Acceptance:** add `tests/test_gui_blueprint_registration.py` (asserts the route count and that each expected endpoint exists) and `tests/test_gui_routes_resolve.py` (every URL pattern resolves via `app.url_map`). Suite green.
  **Risks:** a renamed/dropped route silently breaks the frontend. **Before carving, diff blueprint endpoint names against every `fetch(...)` in `index.html`** — that's the only contract. The `plates_bp` routes stay (plate reader is a free optional feature; just don't require easyocr at import).

- [x] **TASK 1.4 — update PyInstaller spec.** Depends: 1.3.
  **Files:** `installer/svcs.spec`.
  **Do:** add every new `gui.state`/`gui.logging_setup`/`gui.services.*`/`gui.routes.*` submodule to `hiddenimports`. Run `installer/build.ps1`; its smoke test (probe `http://127.0.0.1:5000/`) must pass against the refactored app.
  **Risks:** PyInstaller silently drops a dynamically-imported blueprint → runtime ImportError only in the frozen build. The smoke test is the guard.

- [x] **TASK 1.5 — split `index.html` into JS modules + extract strings.** Depends: 1.3. Split into 1.5a/b/c by feature if a commit exceeds ~500 lines.
  **Files:** `src/gui/templates/index.html` (7,026 lines) → new `src/gui/static/js/*.js` grouped by feature (pipeline control, file browser, demo/quadrant, HLS player, metrics, encryption, presets); a single `src/gui/static/js/strings.js` catalog for user-facing strings (i18n groundwork — translate nothing).
  **Acceptance:** dashboard loads; every panel works; `test_gui_api` green. Keep the four-quadrant demo and HLS player intact (demo surface).
  **Risks:** a broken `fetch` URL or lost handler is silent until clicked — verify each panel; split by feature and test incrementally.

**M1 done when:** `app.py` ~80 lines; 12 blueprints + services + state + logging_setup in place; `index.html` logic in `static/js/*`; new guard tests green; `svcs.spec` updated + smoke test passes.

- [x] **TASK 1.6 — per-mode default codec (gate resolved).** Depends: 1.3 (clean routes/config), do after M1.
  **Decision (final):** mode0/mode1 → `libx264` (H.264); mode2/mode3 → `libsvtav1` (AV1). No H.265. Explicit user selection always wins; "Auto (per-mode)" is the default.
  **Files:** `src/config.py`, `src/pipeline/pipeline.py`, `src/gui/app.py` (the two `config.get("codec", ...)` sites + the codec dropdown), `src/gui/static/js/presets.js` or the codec UI, `tests/test_config.py`, `tests/test_gui_api.py`, `tests/test_pipeline.py`.
  **Do:**
    - `config.py`: add `def default_codec_for_mode(mode: str) -> str: return "libsvtav1" if mode in ("mode2", "mode3") else "libx264"`. Keep `DEFAULT_CODEC`/`FALLBACK_CODEC` (the latter is the ffmpeg-availability fallback when libsvtav1 is missing).
    - `pipeline.py`: change `codec: str = "libsvtav1"` (line ~147) to `codec: Optional[str] = None`; resolve `if codec is None: codec = default_codec_for_mode(mode)` near the CRF block (~286). Explicit codec is honored. Log the resolved codec (already logged).
    - `gui/app.py`: the GUI codec default becomes `"auto"`/None (so the per-mode default applies); add an "Auto (per-mode)" option to the codec dropdown as the default, keeping explicit AV1/H.264 choices. The two `config.get("codec", "libsvtav1")` sites pass the selection through; map `"auto"`/empty → None for the pipeline.
    - Tests: update `test_gui_api`'s `test_start_codec_default_is_libsvtav1` to expect the new "auto" default (rename accordingly) and keep the explicit-passthrough test; add a `test_pipeline` (or `test_config`) case asserting `default_codec_for_mode` returns `libx264` for mode0/mode1 and `libsvtav1` for mode2/mode3; keep `test_config`'s `DEFAULT_CODEC`/`FALLBACK_CODEC` assertions valid.
  **Acceptance:** mode0/1 encode H.264, mode2/3 encode AV1 when codec is "auto"; explicit codec overrides; suite green. (Validate outputs with ffprobe, not cv2 — AV1 decode.)
  **Risks:** the GUI default change touches the codec-default test; update it deliberately. Don't change `FALLBACK_CODEC` behavior (still kicks in when ffmpeg lacks AV1 at encoder construction).

- [x] **TASK 1.7 — dedicated "Upload Video" topbar tab (owner request, 2026-06-02).** Depends: 1.5 (JS split, done). **Independent of M2–M5b — slot it in after the current task; do not reorder/restart M2 work for it.** *(Topbar is now HOME · UPLOAD · METRICS · SEARCH · ENCRYPT — added the UPLOAD nav button second with a purple active accent and a #tab-upload tab-page; the primary upload dropzone (#upload-input/#upload-zone/#video-list) was MOVED out of the always-visible sidebar Step-1 into the Upload tab (single instance, no dup IDs), and the sidebar keeps an "⬆ Upload a video →" launcher button + the advanced server-path/ONVIF controls. switchTab() is generic so no JS change was needed; /api/upload unchanged so route guards stay at 54. Browser-verified via Preview MCP: nav order correct, clicking UPLOAD activates the page and shows the dropzone, no console errors. tests/test_upload_tab.py (7): button exists, is second, full nav order, tab-page exists, dropzone relocated-not-duplicated, active CSS rule, sidebar launcher.)*
  **Goal:** the video-upload UI gets its own top-level tab in the dashboard topbar, positioned **immediately after Home**. New nav order: **HOME · UPLOAD · METRICS · SEARCH · ENCRYPT**.
  **Files:** `src/gui/templates/index.html` (the `<nav class="tab-nav">` buttons ~line 2602, a new `tab-page` div, and the `.tab-btn[data-tab="upload"].active` CSS rule), the JS that owns `switchTab()` and the upload zone (`src/gui/static/js/ui.js` / `files.js`, or a new `upload.js`), `src/gui/static/js/strings.js` for the label.
  **Do:** add a `tab-btn data-tab="upload"` button labelled **UPLOAD** right after the `home` button; create `<div id="tab-upload" class="tab-page">` and move the existing upload zone (the "Click to upload a video" dropzone + SAVE-TO + advanced server-file-path + the SOURCE controls) into it. Wire `switchTab('upload')` and give the tab its active-color CSS rule (pick an unused accent, consistent with the others). The Home tab keeps live status/preview; it may keep a small "Upload a video →" shortcut that switches to the Upload tab, but the primary upload UI lives in the Upload tab now.
  **Acceptance:** topbar shows HOME · UPLOAD · METRICS · SEARCH · ENCRYPT with Upload second; clicking Upload reveals the upload panel; uploading still works end-to-end (the `/api/upload` route and file picker are unchanged — this is frontend-only). Browser-verify the tab switches and an upload succeeds. Suite stays green; if any test asserts the tab set/order, update it. Add a lightweight assertion (e.g. in a gui test or a static-HTML check) that the `data-tab="upload"` nav button exists and precedes `metrics`.
  **Risks:** frontend-only, low risk. Don't break the four-quadrant demo or the Home preview player; keep the upload wiring (dropzone → `/api/upload`) intact when relocating it. No backend route changes (so blueprint/route-count tests stay at 48).

---

## M2 — Slim the installer (PyTorch → ONNX, bundle FFmpeg, Inno Setup)

Goal: installer download 2.5–4.7 GB → ~400–600 MB **without a rewrite** (PLAN-V2 §6/§8). The codec decision is settled (TASK 1.6) — presets just reference the per-mode default.

- [x] **TASK 2.1 — ONNX inference backend (YOLOv8n + Real-ESRGAN).** Depends: M1 (clean modules) or may start after 1.3. *(Detection-ONNX DONE + parity-tested; Real-ESRGAN ONNX deferred to a follow-up per the plan's "ship detection-on-ONNX first" allowance — see docs/onnx-models.md.)*
  **Files:** `src/detection/object_filter.py`, `src/enhancement/enhancer.py`, new `src/detection/onnx_backend.py`, new `src/enhancement/onnx_backend.py`, `pyproject.toml`.
  **Do:** export YOLOv8n and Real-ESRGAN to ONNX; add an `onnxruntime` backend selectable alongside the existing torch one (keep torch behind a `[torch]` extra for parity/export during transition). **Keep the detector interface backend-agnostic** (this is the RT-DETR/permissive seam).
  **Acceptance:** a parity test asserts ONNX detection boxes match the torch backend within an agreed tolerance (box IoU / count) on `data/samples/cdnet_mp4/...`. Suite green. Models stored/documented as an optional component, not committed binaries.
  **Risks:** Real-ESRGAN ONNX export is finicky (dynamic shapes/custom ops). If x4plus won't export cleanly, ship **detection-on-ONNX first**, enhancement as a follow-up — document the blocker, don't block the milestone.

- [x] **TASK 2.2 — default to ONNX; make torch optional; shrink exclude list.** Depends: 2.1. *(torch/torchvision/ultralytics → `[torch]` extra; ObjectFilter default → onnx-first; svcs.spec excludes torch/CUDA/Real-ESRGAN; slim bundle **4632 MB → 339 MB**, smoke green — docs/build-metrics.md.)*
  **Files:** `pyproject.toml`, `installer/svcs.spec`, new `docs/build-metrics.md`.
  **Do:** default install path uses ONNX Runtime; move `torch`/`torchvision`/`ultralytics` to an optional `[torch]` extra (parity/export only). Exclude torch/CUDA from the casual bundle in `svcs.spec`. Record measured unpacked bundle size in `docs/build-metrics.md`.
  **Acceptance:** default build ships no torch; smoke test passes; recorded size drops sharply from the 4.7 GB first build.
  **Risks:** a transitive torch dep (skimage/basicsr) sneaks it back in — audit the PyInstaller dependency graph.

- [x] **TASK 2.3 — bundle LGPL FFmpeg.** Depends: none (can parallel 2.1). *(Bundle-first `src/utils/ffmpeg.py` resolver + routed callsites + test; build.ps1 vendors a pinned GPL win64-shared FFmpeg into tools/ffmpeg; svcs.spec bundles it; docs/ffmpeg-licensing.md. NB: we ship **GPL** FFmpeg, not LGPL, because the libx264 (Mode 0/1) codec policy needs it — license-compatible with the AGPL app; LGPL is the documented future-fork seam.)*
  **Files:** `installer/build.ps1`, `installer/svcs.spec`, `src/utils/` (ffmpeg path resolution), new `docs/ffmpeg-licensing.md`.
  **Do:** vendor a pinned LGPL FFmpeg; resolve ffmpeg from the bundle first, PATH second (no longer *require* PATH). Document the LGPL/GPL/x264/x265/HEVC matrix (for an AGPL project GPL-FFmpeg-with-x265 is fine; the doc is readiness for a possible future fork).
  **Acceptance:** a test asserts the app finds the bundled ffmpeg when PATH lacks it. Record the pinned version.

- [x] **TASK 2.4 — Inno Setup installer.** Depends: 2.2, 2.3, 1.6 (codec decided). *(installer/svcs.iss + build.ps1 -Installer; `iscc` produces **SVCS-Setup-2.0.0.dev0.exe = 210.6 MB**; optional bundled-FFmpeg component; installs to Program Files + Start Menu; uninstall preserves %APPDATA%\\SVCS. Built/verified locally — Inno is Windows-only, not in CI.)*
  **Files:** new `installer/svcs.iss`, `installer/build.ps1`.
  **Do:** `iscc installer/svcs.iss` → `SVCS-Setup-x.y.z.exe`, with an optional "AI model weights" component (~70 MB ONNX) so the base download stays small; first run fetches them if skipped. Installs to Program Files + Start Menu shortcut; launches and serves the dashboard via the frozen entry point (`installer/launcher.py` sets `SVCS_FROZEN=1`, splices `--no-sync`). Uninstall leaves `%APPDATA%\SVCS` data unless asked.
  **Acceptance:** installer builds on Windows; recorded download size ~400–600 MB. **Build/test on a Windows runner/machine** (Inno is Windows-only, not in CI yet).

**M2 done when:** a Windows installer < ~600 MB installs and runs, on ONNX, with bundled ffmpeg.

---

## M3 — Surveillance presets + content auto-detection

- [x] **TASK 3.1 — preset system v1 (surveillance-centric, modes hidden).** Depends: 2.2, 1.6 (per-mode codec). *(src/pipeline/presets.py — 8 named presets (Continuous CCTV, Motion-event, Doorbell, Multi-camera/NVR, Active scene, Archive + Screen recording, Generic) → (mode, fg-CRF, bg-CRF, codec); /api/presets endpoint; config import/export carry preset+codec+crf+background_crf; pipeline honors background_crf; presets.js + a named-preset dropdown (modes stay behind Advanced). tests/test_presets.py (29) + browser-verified.)*
  **Files:** new `src/pipeline/presets.py`, `src/config.py`, `src/gui/routes/presets_bp.py`, `src/gui/static/js/presets.js`.
  **Do:** named presets, surveillance-first: **Continuous CCTV (max savings)**, **Motion-event cam**, **Doorbell**, **Multi-camera / NVR**, **Active scene**, **Archive (visually lossless)**, plus a couple general (Screen recording, Generic). Each maps to a `(mode, foreground-CRF, background-CRF, codec)` tuple consistent with the decided CRF progression (mode0/1=18, mode2=23, mode3=38). **UI exposes presets by name**, raw mode picker behind an "Advanced" toggle. Extend the existing preset import/export (config blueprint), don't reinvent.
  **Acceptance:** `tests/test_presets.py` — each preset resolves to a valid encode config and round-trips through import/export. Document each preset's mode mapping + rationale in comments.
  **Risks:** CRF/codec values need a couple of real test encodes to tune, not guesses; reuse the measured behavior in `docs/mode_size_hierarchy.md` (note its banner: mode2 is now CRF 23).

- [x] **TASK 3.2 — content auto-detection (rule-based).** Depends: 3.1. *(src/pipeline/content_detect.py: analyze_video() samples the first ~30s at 5fps, reuses the MOG2 BackgroundSubtractor for a foreground-area ratio + activity fraction + active-subject size + motion variance, plus resolution/fps and ffprobe audio presence -> ContentSignals; recommend_preset() is a 5-branch rule tree (idle->continuous_cctv, busy->active_scene, sparse+close->doorbell, sparse+distant->motion_event, empty->default) each with a human reason; detect_content() is the swappable entry point. New POST /api/detect_content returns the recommended preset+config+signals+reason. tests/test_content_detect.py (13): decision-tree unit cases + synthetic-clip integration (static->continuous_cctv, random-motion->active_scene) + a real CDnet clip when present. Route guards -> 50. Suite green: 717 passed.)*
  **Files:** new `src/pipeline/content_detect.py`, `src/gui/routes/presets_bp.py`.
  **Do:** analyze the first ~30 s; extract foreground-area ratio (reuse MOG2 output), scene-change rate, motion variance, resolution, frame rate, luma/color distribution, audio-track presence. A small decision tree / rule set recommends a **surveillance** preset (very low foreground + static → Continuous CCTV; sparse motion → Motion-event/Doorbell; busy multi-object → Active scene). **Not a CNN.** Keep the interface swappable for a future learned model.
  **Acceptance:** `tests/test_content_detect.py` — known clip types get the expected preset (a CDnet surveillance clip → Continuous CCTV). On CI these may skip if they need LFS clips; provide a tiny synthetic fixture where possible so CI exercises the logic.
  **Risks:** edge-case misclassification is fine for v1 (user overrides; instrument later). Don't over-tune on the tiny CDnet set.

- [ ] **TASK 3.3 (optional) — adaptive per-segment bitrate.** Depends: 3.1. **Optional / defer.**
  Formerly a "premium" feature; with open-source-only it'd be a *free* advanced option on `app`. Build only if the owner wants it now; otherwise log it as a future enhancement. If built: per-segment automatic CRF selection on detected content, gated behind an "Advanced" toggle, with a test asserting it never produces a *larger* file than the static preset on the CDnet clips.

---

## M-CAM — Consumer & prosumer camera ingestion

Honest split (PLAN-V2 §2/§6 Pushback 4): RTSP/ONVIF cameras ingest directly; cloud-locked cams (Ring/Nest/Arlo) go through exported clips or a bridge. **No vendor-cloud scraping.**

- [x] **TASK M-CAM.1 — ONVIF discovery + RTSP auto-config.** Depends: 1.3. *(src/utils/onvif_discovery.py: dependency-free WS-Discovery — a UDP Probe multicast to 239.255.255.250:3702, parse_probe_matches() decodes ProbeMatch SOAP into OnvifDevice (address/name/hardware/scopes) by matching local tag names so it tolerates vendor namespace dialects; build_rtsp_url() URL-encodes credentials; rtsp_url_candidates() offers brand-specific paths (Reolink/Amcrest/Dahua/Hikvision/Axis/Tapo/Wyze, data-driven) then generic fallbacks; discover() never raises (blocked/empty LAN -> [] -> manual entry). New cameras_bp (13th blueprint): GET /api/cameras/discover, POST /api/cameras/rtsp_url (host only logged, never the credentialed URL). cameras.js adds a "Discover ONVIF cameras" affordance to the source panel that fills input-source with a chosen stream. FrameSource already consumes rtsp://. tests/test_onvif_discovery.py: captured Reolink+Hikvision ProbeMatch parsing, credential encoding, candidate ordering, fake-socket discover incl. graceful-degrade + dedupe, and the two routes. Route guards -> 52, blueprints -> 13. Suite green: 738 passed.)*
  **Files:** new `src/utils/onvif_discovery.py`, `src/utils/frame_source.py` (extend; it already handles RTSP), `src/gui/routes/` (a camera-setup endpoint), `src/gui/static/js/cameras.js`, `tests/test_onvif_discovery.py`.
  **Do:** WS-Discovery to find ONVIF cameras on the LAN; list them in the dashboard; add one as an RTSP source with auto-filled stream URL + credentials. First-class for Reolink/Amcrest/Hikvision/Dahua/Wyze-with-RTSP. Keep credentials out of logs.
  **Acceptance:** `tests/test_onvif_discovery.py` covers parsing a mocked ONVIF response + building the RTSP URL. Degrade gracefully to manual RTSP-URL entry when discovery finds nothing.
  **Risks:** ONVIF dialects vary; Windows firewall blocks discovery. Manual entry is the fallback.

- [x] **TASK M-CAM.2 — export-folder watch presets for camera clips.** Depends: 4.1, 3.2. *(watchfolder.py: data-driven WatchProfile registry (WATCHFOLDER_PROFILES) with 6 layouts — continuous (timestamped CCTV/dashcam, fixed Continuous-CCTV preset), motion_events (per-event clips, auto-detect), microsd_dump (DCIM bulk copy), nas_sync (slow/bursty sync → stable_checks=4, settle=2s), nvr_export (per-camera/per-day tree), generic (flat drop) — each a (recursive, auto_preset, preset, stability, prefix) tuple, not hard-coded per vendor. scan_and_ingest gained recursive scanning (rglob) that folds the immediate parent folder into the camera ID so NVR per-camera subfolders stay distinct; run_watchfolder gained profile= (sets layout defaults, explicit args win) + recursive=, CLI --profile/--recursive. New docs/camera-ingestion.md: the three honest ingestion paths (RTSP/ONVIF, export-folder, bridge), per-family setup table, profile table, reliability notes (bridge section stubbed for M-CAM.3). tests/test_watchfolder.py +7 (now 43): profile catalog/validity (every preset real or None), nas>generic stability, recursive finds nested / non-recursive ignores / subfolder folded into camera ID. New media auto-detected (3.2) and compressed. Suite green.)*
  **Files:** `src/utils/watchfolder.py`, new `docs/camera-ingestion.md`.
  **Do:** watch-folder profiles tuned to common camera export/recording layouts (timestamped continuous files, per-event motion clips, microSD dumps, NAS sync, NVR exports); new media auto-detected (3.2), compressed, written to an output tree. Document setup per camera family. This is the **universal** path (works even for cloud-locked cams via their export).
  **Acceptance:** extend `tests/test_watchfolder.py` for the new profiles + partial-write stability (reuse 4.1's stability check). Keep profiles data-driven, not hard-coded per vendor.

- [x] **TASK M-CAM.3 — bridge-ingestion guide (cloud-locked cams).** Depends: M-CAM.1. *(docs/camera-ingestion.md bridge section expanded to a full, honest guide: Ring/Nest/Arlo have no RTSP and no scraping — the supported paths are export-to-watch-folder or a local bridge (Scrypted/Home Assistant/Frigate) that re-exposes the camera as local RTSP which SVCS ingests as Path 1; realistic expectations (extra setup, coverage depends on the bridge+vendor API, latency/reliability vary, prefer export if available); bridge options table + step-by-step connect. cameras.js gained showBridgeHelp() and the camera-add screen links to it ("Ring / Nest / Arlo? Use a bridge or export →"). No code dependency on any bridge — SVCS just consumes their RTSP. Render-verified; guard tests green.)*
  **Files:** `docs/camera-ingestion.md`, `src/gui/static/js/cameras.js` (a "via bridge" help affordance).
  **Do:** documented, honest path for Ring/Nest/Arlo via **Home Assistant / Scrypted / Frigate**, which re-expose the camera as local RTSP that SVCS consumes (M-CAM.1). Be explicit: SVCS does **not** touch vendor clouds; the two supported options are export-folder (M-CAM.2) or a bridge. The camera-add screen links here for unsupported brands.
  **Acceptance:** doc sets honest expectations (PLAN-V2 R-CAM). No code dependency on the bridges — just consume their RTSP.

- [x] **TASK M-CAM.4 — consumer-camera preset family.** Depends: 3.1, M-CAM.2. *(presets.py +3 consumer presets joining the existing Doorbell: Indoor cam (pets/home, mode1 dual-CRF fg23->20 conservative), Outdoor yard cam (mode2 event-recording fg23/bg48), Baby/pet monitor (mode1, object_filter=False so a still baby/curled pet is never gated out as background). CRFs deliberately conservative — consumer sensors are noisy, don't smear detail. All flagged surveillance so they appear in the security-camera family; 11 presets total. tests/test_presets.py: the consumer family exists, is conservative, indoor/baby keep every frame, baby_monitor doesn't object-gate; existing parametrized validity/round-trip/per-mode-codec tests cover the new presets automatically (39 passed).)*
  **Files:** `src/pipeline/presets.py`, `tests/test_presets.py`.
  **Do:** presets tuned for consumer footage — **Doorbell (porch/entry)**, **Indoor cam (pets/home)**, **Outdoor yard cam**, **Baby/pet monitor (long idle)** — mostly-static-with-sparse-events scenes. Tune CRF conservatively (consumer footage is lower-res/noisier; don't smear detail). Tests assert valid configs.

---

## M4 — Self-host hardening

- [x] **TASK 4.1 — harden watch-folder automation.** Depends: 1.3, 3.1. *(watchfolder.py: partial-write detection now requires size stable across N consecutive polls (stable_checks, default 2) instead of one before/after read, so a copy that pauses mid-write can't be ingested early; explicit crash-resume via a .processing marker written before each encode and cleared on success — a file still carrying it (without .ingested) was interrupted and is retried (logged "Resuming after interrupted encode"); a failed encode leaves the marker so the file is never silently dropped; preset auto-detection wired in — auto_preset runs content_detect (3.2) per clip and encodes with the recommended preset's mode/crf/background_crf/codec/object_filter, with explicit --preset override, all degrading to defaults if detection fails. New CLI flags --stable-checks/--settle/--auto-preset/--preset. tests/test_watchfolder.py +25 (now 36): growing-file-not-ready, multi-check stability, crash-resume (success clears marker, failure retains it, interrupted file retried), and auto-preset wiring asserting the detected preset reaches run_pipeline. Underpins M-CAM.2.)*
  **Files:** `src/utils/watchfolder.py`, `tests/test_watchfolder.py`.
  **Do:** point at a directory → new media detected, preset auto-detected (3.2), compressed in background, written out; handle partial writes (size stable for N seconds before processing), dedupe, crash-resume.
  **Acceptance:** extend `tests/test_watchfolder.py` for partial-write + resume. Underpins M-CAM.2.

- [x] **TASK 4.4 — dashboard auth for non-localhost binds.** Depends: 1.3. **Do this before 4.2.** *(src/gui/auth.py: bind-aware policy — decide_auth(host, no_auth, username, password, env) returns an AuthDecision or raises AuthConfigError. Localhost (127.0.0.0/8, ::1) stays auth-free; any other bind REQUIRES Basic Auth and the server refuses to start (exit 2) unless credentials are set (CLI --username/--password or SVCS_DASHBOARD_USER/PASSWORD env) or --no-auth is explicitly passed. install_basic_auth() adds a before_request guard with constant-time hmac comparison + WWW-Authenticate 401; deliberately NOT wired into create_app() so the test client / embedded uses stay open — only run_gui installs it after deciding policy. run_gui gained --username/--password/--no-auth and prints the auth state. password is repr-suppressed (never logged). docs/deployment_packaging.md documents the policy + TLS-at-proxy note. tests/test_dashboard_auth.py (21): the acceptance — non-localhost+no-creds is rejected — plus localhost-open, env creds, partial-creds rejected, --no-auth override, and the live 401/200 Basic-Auth guard.)*
  **Files:** `src/gui/` (new `auth.py` or in the app factory), `docs/deployment_packaging.md`.
  **Do:** when the app binds to anything other than `127.0.0.1`, require basic auth (configurable credential) OR refuse to start without an explicit `--no-auth` override. Localhost stays auth-free.
  **Acceptance:** a test asserts a non-localhost bind without credentials is rejected.
  **Risks:** real security gap today (PLAN-V2 §10 R-AUTH); the server/NAS scenario serves on `0.0.0.0`. Ship this before the Docker image.

- [x] **TASK 4.2 — Docker image (server scenario).** Depends: 2.3, 4.4. *(Dockerfile on the slim ONNX path — python:3.11-slim + apt ffmpeg/libgl1/libglib2.0-0, uv sync --frozen from uv.lock (core deps only, NO torch), bakes in yolov8n.onnx, runs run_gui --host 0.0.0.0; .dockerignore trims context (excludes data/.venv/tools, re-includes the model). docker-compose.yml maps 5000, passes SVCS_DASHBOARD_USER/PASSWORD (TASK 4.4 auth required at the 0.0.0.0 bind), mounts outputs + read-only data, healthcheck. BUILT + RAN locally: image 2.06 GB (vs 4 GB+ with torch), container served 401 without creds / 200 with ci:cipass / 401 wrong creds, logs "Dashboard auth: ENABLED". docs/deployment_packaging.md status → IMPLEMENTED (honest ~2 GB size + trim note). tests/test_docker_artifacts.py (13 static + 1 opt-in real build under SVCS_TEST_DOCKER=1): slim-path/no-torch, ships model, binds server scenario, compose auth+port+healthcheck.)*
  **Files:** new `Dockerfile`, `docker-compose.yml`, `docs/deployment_packaging.md` (status → done).
  **Do:** `docker build` → image running the Flask app on the ONNX/slim path (post-M2 so it isn't 4 GB); `docker run -p 5000:5000 -v ...` serves the dashboard. Start from the Dockerfile sketch already in `docs/deployment_packaging.md`.
  **Acceptance:** image builds and serves; doc status updated. (4.3 was intentionally removed — Plex/Jellyfin folded into M-CAM.3.)

---

## M5 — Public beta

- [x] **TASK 5.2 — opt-in anonymous usage-stats channel.** Depends: none (can parallel). *(src/utils/usage_stats.py — a SEPARATE channel from crash reporting, default OFF: consent unknown until the user answers; env kill-switch SVCS_DISABLE_USAGE_STATS forces off; record_event() is a strict no-op (builds/sends nothing) unless enabled. Hard privacy enforced in code: a per-event field whitelist, categorical coercion to fixed vocab (or other/unknown — never H.265), and a PII/path scrub that drops any value containing a path sep / drive / url-scheme / @ / IPv4; no footage, filenames, paths, machine-id or UUID ever. No SaaS — emits to a local JSONL, POSTs only if SVCS_USAGE_STATS_URL is explicitly set. New usage_bp (14th blueprint): GET /api/usage_stats + POST /api/usage_stats/consent; usage.js shows a first-run consent banner + settings toggle. pipeline_runner records an anonymous encode outcome (preset/mode/codec/success/error-category/ingestion-path) on success+failure. tests/test_usage_stats.py (13): the acceptance — nothing sent when off, payloads carry no PII/path fields — plus consent round-trip, kill-switch, whitelist/scrub, coercion, and the routes. Guards -> 54 routes / 14 blueprints.)*
  **Files:** new `src/utils/usage_stats.py`, `src/gui/` (first-run consent), `tests/test_usage_stats.py`.
  **Do:** a **separate** channel from crash reporting — preset popularity, codec choice, encode success/failure, anonymized error categories, and which **camera-ingestion path** is used (RTSP/ONVIF vs watch-folder vs bridge). No footage, file contents, paths, PII, or reinstall-surviving IDs. Default **off**; first-run consent screen; settings toggle.
  **Acceptance:** `tests/test_usage_stats.py` asserts nothing is sent when off and payloads carry no PII/path fields.

- [x] **TASK 5.1 — public download page.** Depends: 2.4. *(docs/site/index.html + style.css — a static, fully self-hosted download page (no CDN, no external scripts/fonts, no JS) leading with the surveillance / self-hosted / open-source (AGPL) wedge, three value cards, a Download section linking GitHub Releases (SVCS-Setup-*.exe), SHA-256 verification steps (PowerShell Get-FileHash + sha256sum vs the release's SHA256SUMS.txt), system requirements (Windows 64-bit, no GPU required, ~600 MB), and "other ways to run" (Docker/source/cameras). No competitor comparisons. README gained a Download section. tests/test_download_page.py (8): page+css exist, links the installer, documents checksums, lists requirements, leads with the wedge, ships zero external resources, makes no competitor comparison, README has the link.)*
  **Files:** new `docs/site/` (GitHub Pages), `README.md`.
  **Do:** static page linking the latest installer from GitHub Releases, SHA-256 checksums, system requirements. Copy leads with the surveillance/self-hosted/open-source wedge; no competitor comparisons. Plain HTML/CSS, no CDN.

- [x] **TASK 5.3 — getting-started + camera-setup docs.** Depends: M-CAM.3. *(new docs/getting-started.md: install (Windows installer / Docker / source, honest about the unsigned-beta SmartScreen warning) → point at a folder/camera/file → choose a preset (or content auto-detect) and compress → next steps. docs/camera-ingestion.md finalized with a camera compatibility table (Direct RTSP/ONVIF vs Bridge vs Export-folder, recommended path per family incl. Reolink/Amcrest/Dahua/Hikvision/Axis/Wyze/Tapo/UniFi/body-cams/dashcams/Ring/Nest/Arlo), marked "community-maintained — last updated 2026-06-03", and explicit about the cloud-locked limit (no vendor-cloud scraping). tests/test_docs_getting_started.py (6): install/point/compress coverage, unsigned-beta honesty, the compatibility table, the community-maintained+date stamp, and the cloud-locked honesty.)*
  **Files:** `docs/getting-started.md`, `docs/camera-ingestion.md` (finalize).
  **Do:** install → point at a folder or camera → compress; a camera compatibility table (works directly via RTSP/ONVIF / needs a bridge / needs export-folder). Honest about the cloud-locked limit; mark the table "community-maintained, last updated X".

- [~] 🚦 **TASK 5.4 — tag + publish unsigned public beta.** Depends: 5.1, 5.2, 5.3, 3.2, 4.1. **Human tags/publishes.** *(PREP DONE; publish gated to owner. docs/RELEASE-CHECKLIST.md — repeatable build → quality-gate → build installer → smoke-test on clean Windows → SHA256SUMS → draft Release; docs/release-notes-v2.0.0-beta.md — draft notes honest about the unsigned beta + SmartScreen, with verify steps and AGPL. docs/BLOCKERS.md records the remaining owner-only steps (build on a release machine, tag v2.0.0-beta, publish the pre-release). The autonomous run did NOT tag or publish — gated. tests/test_release_artifacts.py (4) guards the checklist/notes/blockers.)*
  **Files:** new `docs/RELEASE-CHECKLIST.md`, release notes.
  **Do:** a repeatable release checklist (build, run suite, smoke-test installer, checksums, draft GitHub Release). You prepare it and the draft notes; the **owner** tags `v2.0.0-beta` and publishes the unsigned Windows installer (note "unsigned beta — SmartScreen will warn").

---

## M5b — Signing + macOS/Linux  (🚦 cert-gated where noted)

- [~] 🚦 **TASK 5b.1 — Windows code signing.** Depends: 5.4 + an EV cert (owner obtains; investigate SignPath.io's free OSS program first). *(STEP WIRED; cert gated. installer/build.ps1 gained -Sign: Resolve-SignTool finds signtool (PATH or Windows SDK), Invoke-CodeSign Authenticode-signs with SHA-256 + an RFC3161 timestamp; it signs BOTH the bundle exe (before Inno packages it, so the installed app is signed) AND the installer exe (after iscc). Cert comes from env (SVCS_SIGN_CERT+SVCS_SIGN_PASSWORD or SVCS_SIGN_THUMBPRINT) so no secret is in the repo; with -Sign but no cert it warns + skips so the unsigned beta still builds. build.ps1 parses clean. RELEASE-CHECKLIST.md got a signing section; BLOCKERS records the cert as the owner's action (SignPath.io OSS lead). tests/test_signing_step.py (5). The run could NOT sign (no cert) — gated.)*
  Wire the signing step into `installer/build.ps1` + `docs/RELEASE-CHECKLIST.md`; publish a signed GA build. Don't block on buying the cert — implement the step, leave the cert as the owner's action.

- [x] **TASK 5b.2 — Linux AppImage.** Depends: 5.4. *(installer/build.sh assembles a self-contained AppDir — relocatable standalone CPython via uv, the project on the slim ONNX path (no heavy ML extras), yolov8n.onnx, and a static FFmpeg — and packages it with appimagetool (--appimage-extract-and-run, no FUSE needed in CI). installer/appimage/ holds AppRun (launches the bundled python on run_gui.py with ffmpeg on PATH), svcs.desktop, a placeholder icon, and a README. .github/workflows/appimage.yml builds it on ubuntu-latest on v* tags / manual dispatch, SMOKE-TESTS it (launch on localhost → probe the dashboard), and uploads the artifact WITHOUT auto-publishing (publish is the owner's gated step). Scripts are bash -n-clean and pinned to LF (.gitattributes). Built/verified on the Linux CI runner — the autonomous run is on Windows, noted in BLOCKERS. tests/test_appimage_build.py (7).)*
  New `installer/appimage/` + `installer/build.sh` + CI job; a working AppImage runs on a clean Ubuntu and is published to Releases. Cheap (no paid cert) — likely do this before macOS.

- [ ] 🚦 **TASK 5b.3 — macOS .dmg (signed + notarized).** Depends: 5.4 + Apple Developer cert (owner provides). **Defer if no cert.**

---

## M6 — Rust encoder spike  (🚦 owner go-ahead required; on `kdev`)

A **measured spike**, not committed work. Only start on an explicit "go". Goal: does porting the encoder to Rust buy enough size/perf to justify a rewrite?

- [ ] 🚦 **TASK 6.1 — `svcs-core` skeleton on `kdev`.** A Cargo crate that compiles for Windows+Linux and exposes one hello-world over a C ABI. Greenfield on `kdev`; don't touch `app`.
- [ ] 🚦 **TASK 6.2 — port the encoder module only; prove parity.** Rust encoder output within an agreed quality/byte tolerance of the Python encoder on CDnet clips; measure binary-size + throughput deltas vs the ONNX Python path; write a go/no-go in `docs/rust-spike-findings.md`. If a crate blocker appears (`ffmpeg-next`/`opencv-rust`), the spike's job is to find it cheaply — document and stop.

---

## Appendix — quick reference

- Run tests: `pwsh scripts/run_tests.ps1` (green = ≥513 passed, 0 failed, 3 webcam skips).
- Glossary, mode definitions, CDnet sample paths: `docs/EXECUTION-CLAUDE-CODE.md` §4 and the same doc's task blocks.
- Product rationale for any decision above: `docs/PLAN-V2.md`.
- gui refactor design: `docs/REFACTOR-PLAN-gui-app.md`.
- Test triage history + the two real bugs fixed in M0: `docs/test-baseline.md`.
