# SVCS v2 - Blockers & Owner Actions

This file tracks items the autonomous build could not complete on its own  - 
hard gates (🚦) that need the owner, and anything that needs a decision,
credential, or environment the agent doesn't have. The agent does everything
possible up to each gate, records exactly what's needed here, and keeps going.

Author: Bloodawn (KheivenD), 2026-06-02 (autonomous v2 build).

---

## Open items

### R3.2 distribution - owner-gated / owner-verified (2026-06-21)

R3.1 (auto-compress) is fully implemented and tested. R3.2 (terminal/winget
distribution) is built, but parts are NOT pytest-coverable and need the owner:

| Item | Why gated | What's ready | Owner action |
|------|-----------|--------------|--------------|
| **winget public submission** | submission is the owner's GitHub action; Microsoft prefers a code-signed installer | `installer/winget/` manifest (3 files), `scripts/winget_validate.ps1`, `docs/winget-submission.md`, structural test green | publish a Release with the asset, run `winget_validate.ps1 -Recompute` to fix the SHA, then `wingetcreate submit` (steps in winget-submission.md) |
| **winget InstallerSha256** | must match the EXACT released asset | SHA computed against the current `dist/` installer | rebuild the installer for the R3 app, then `pwsh scripts/winget_validate.ps1 -Recompute` |
| **Install-SVCS.ps1 GUI** | a WPF window cannot be pytest-tested | script parses, `-DryRun`/`-NoGui` verified, structural test (8) green | run it once on Windows and confirm the window + each component |
| **PSScriptAnalyzer lint** | analyzer not in the CI env | scripts written clean; Write-Host suppressed via attribute | `Install-Module PSScriptAnalyzer; Invoke-ScriptAnalyzer installer/Install-SVCS.ps1, scripts/winget_validate.ps1` |

These are honest gaps, not fake-tested: the manifest is validated structurally
(`tests/test_winget_manifest.py`) and the script is parse-checked + structurally
tested (`tests/test_install_script.py`), but the live `winget validate`, the WPF
window, and the public submission are owner-run.

### ✅ AUTONOMOUS RUN COMPLETE - every non-gated task M1 → M5b is done (2026-06-03)

All non-gated tasks are implemented, tested green, committed, and pushed to
`app`. Final suite: **857 passed, 4 skipped** (3 webcam + 1 opt-in Docker build).
Done: **M1** 1.1-1.6 **+ 1.7** (Upload tab); **M2** 2.1-2.4 (installer 210 MB);
**M3** 3.1, 3.2 (3.3 optional-deferred); **M-CAM** 1-4; **M4** 4.1, 4.4, 4.2
(Docker image built + served + auth-verified); **M5** 5.1, 5.2, 5.3 (+5.4 prep);
**M5b** 5b.2 (AppImage, CI-built) + 5b.1 step (signing wired).

**Everything that remains is GATED on the owner - nothing is blocked on code:**

| Task | Why gated | What's ready | Owner action |
|------|-----------|--------------|--------------|
| **5.4** publish beta | human tags/publishes | RELEASE-CHECKLIST + draft notes | build on a release box, tag `v2.1.0-beta`, publish pre-release |
| **5b.1** Windows signing | needs a cert | `build.ps1 -Sign` wired | get a cert (try SignPath OSS), set env vars, build `-Installer -Sign` |
| **5b.2** AppImage publish | publish is owner's | build.sh + CI build+smoke green | confirm the AppImage CI job, attach artifact to the Release |
| **5b.3** macOS dmg | needs Apple cert + a Mac | - (deferred per plan) | provide Apple Developer cert; build/notarize on macOS |
| **3.3** adaptive bitrate | optional / defer | building blocks exist | say "go" if wanted |
| **6.1 / 6.2** Rust spike | explicit go-ahead, on `kdev` | - | say "go" to start the measured spike |

Details for each gate are in the sections below.

### (historical) Open items at the M2 boundary

**No hard gates hit yet.** The run completed all of M1 (TASK 1.1-1.6) - green
and pushed - and paused at the M2 boundary (not a gate; a deliberate stop before
high-risk ML-parity work in a long session). The first gates appear at M5
(publishing) and M5b (signing).

### Execution status (updated 2026-06-03): M1 + M2 complete; M3 in progress

Done & pushed: **all of M1 (1.1-1.6)**, **all of M2 (2.1 ONNX, 2.2 torch-optional,
2.3 FFmpeg, 2.4 Inno installer)**, and **M3 TASK 3.1 (surveillance presets)**.
Suite green (702 passed). Slim installer **SVCS-Setup-2.0.0.dev0.exe = 210 MB**.

**Next: TASK 3.2 (content auto-detection, rule-based).** Depends on 3.1 (done).
- New `src/pipeline/content_detect.py`: analyze the first ~30 s of a clip,
  extract foreground-area ratio (reuse MOG2 output), scene-change rate, motion
  variance, resolution, fps, luma/colour, audio presence; a small decision tree
  maps to a recommended preset *key* from `pipeline/presets.py`
  (very-low-foreground+static → continuous_cctv; sparse motion → motion_event/
  doorbell; busy multi-object → active_scene). NOT a CNN; keep the interface
  swappable. Add a `/api/detect_content` route (or extend presets_bp) returning
  the recommended preset key + the signals - bumps the route guard tests to 50.
- `tests/test_content_detect.py`: a CDnet surveillance clip → continuous_cctv;
  provide a tiny synthetic fixture so CI exercises the logic without LFS clips.
- The CDnet clips are present locally (data/samples/cdnet_mp4/...).

Then M-CAM (ONVIF/watch-folder), M4 (watch-folder hardening, dashboard auth,
Docker), M5 (download page, opt-in stats, docs, 🚦beta), M5b (🚦signing, Linux
AppImage, 🚦macOS).

**Deferred by the plan (not a gate): TASK 3.3 - adaptive per-segment bitrate.**
The master plan marks it *optional / build only if the owner wants it now,
otherwise log as a future enhancement.* No owner signal is available in this
autonomous run, so it is **logged as a future enhancement and skipped**, per the
plan's own instruction. If picked up later: per-segment automatic CRF on
detected content behind an "Advanced" toggle, with a test asserting it never
produces a larger file than the static preset on the CDnet clips. The building
blocks now exist (content_detect signals + the preset registry).

---

### (historical) Execution status: M2 TASK 2.1 + 2.2 DONE

- **TASK 2.1 (ONNX detection backend):** done + parity-tested. Real-ESRGAN ONNX
  deferred (see `docs/onnx-models.md`).
- **TASK 2.2 (default ONNX, torch optional):** done. torch/torchvision/
  ultralytics → `[torch]` extra; `ObjectFilter` default backend is now
  onnx-first; `svcs.spec` excludes torch/CUDA/Real-ESRGAN. **Slim bundle
  measured: 4632 MB → 339 MB**, smoke green, ONNX detection bundled. Suite green
  (662). The test runner + CI add `--extra torch`.

**Next: TASK 2.3 (bundle LGPL FFmpeg) and TASK 2.4 (Inno Setup installer).**
- 2.3 has no deps (parallel-able): vendor a pinned LGPL FFmpeg binary, resolve
  ffmpeg from the bundle first then PATH, add a `docs/ffmpeg-licensing.md`
  (LGPL/GPL/x264/x265 matrix), and a test asserting the app finds the bundled
  ffmpeg when PATH lacks it. The current code shells out to `ffmpeg` on PATH
  (e.g. roi_encoder, hls_runner) - add a single resolver in `src/utils/` and
  route those callsites through it.
- 2.4 (depends 2.2, 2.3, 1.6): write `installer/svcs.iss` (Inno Setup) with an
  optional ONNX-weights component; `iscc` is Windows-only and not in CI.

**Env gotcha hit during 2.2:** killing python/uv mid-operation can leave
`onnxruntime-*.dist-info` without its package dir, so `uv sync` thinks it's
installed and the build omits it. Fix: `uv pip install --reinstall onnxruntime`;
always confirm `import onnxruntime` before a build. (Also: a `uv sync` wipes the
ad-hoc PyInstaller; build.ps1 reinstalls it via `uv pip`.)

---

## Gates known in advance (from the master plan)

These are expected and will be filled in with concrete artifacts/instructions
as the run reaches them:

- **🚦 Code-signing certs (M5b.1 / 5b.3)** - Windows EV cert (~$300-600/yr) and
  Apple Developer cert ($99/yr). The signing *step* will be wired into the build;
  the owner must obtain the certs. Investigate SignPath.io's free OSS program for
  Windows first.
  **STATUS - Windows signing step WIRED (TASK 5b.1), awaiting cert:**
  `installer/build.ps1 -Sign` now Authenticode-signs both the bundle exe and the
  installer via `signtool` (SHA-256 + RFC3161 timestamp). Cert comes from env
  (`SVCS_SIGN_CERT`+`SVCS_SIGN_PASSWORD`, or `SVCS_SIGN_THUMBPRINT`) so no secret
  is in the repo; with `-Sign` but no cert it warns and skips (unsigned beta still
  builds). The autonomous run could NOT execute signing (no cert). **Owner action:**
  obtain a cert (try SignPath.io's free OSS program first), set the env vars, and
  run `pwsh installer/build.ps1 -Installer -Sign` for the GA build.
- **🚦 Publishing a public release / tagging a beta (TASK 5.4, 5b.*)** - the agent
  prepares the installer, checksums, release checklist, and draft notes; the
  **owner** tags and publishes the GitHub Release.
  **STATUS - prep complete, awaiting owner (TASK 5.4):** `docs/RELEASE-CHECKLIST.md`
  (repeatable build → verify → checksums → draft) and `docs/release-notes-v2.0.0-beta.md`
  (draft notes) are written. The remaining steps are the owner's and were NOT done
  by the autonomous run (gated): build the installer (`installer/build.ps1 -Installer`)
  on a release machine, generate `SHA256SUMS.txt`, create the **`v2.1.0-beta`** tag,
  and publish the **pre-release** with the unsigned-beta warning. Nothing here is
  blocked on code - only on the human publish action.
- **Linux AppImage (5b.2) - built + smoke-tested in CI, not on the Windows host.**
  Not a gate: `installer/build.sh` + `installer/appimage/` (AppRun/desktop/icon)
  + `.github/workflows/appimage.yml` build a self-contained AppImage on
  `ubuntu-latest` (relocatable CPython + slim ONNX deps + static FFmpeg + model)
  and smoke-test it (launch → probe the dashboard). The autonomous run is on
  Windows, so it could not execute/verify the AppImage locally - that runs on the
  Linux CI runner. Scripts are `bash -n`-clean and pinned to LF. **Owner/CI
  action:** confirm the `AppImage` workflow goes green, then attach the artifact
  to the published Release (publishing itself is the gated step above).

- **🚦 macOS .dmg notarization (5b.3)** - needs the Apple cert; deferred unless the
  owner provides it. Linux AppImage (5b.2) is done first (no cert needed).
- **🚦 Rust encoder spike (M6)** - explicitly out of scope for this run; needs the
  owner's go-ahead. Skipped entirely.
