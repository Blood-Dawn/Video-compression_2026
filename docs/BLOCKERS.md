# SVCS v2 — Blockers & Owner Actions

This file tracks items the autonomous build could not complete on its own —
hard gates (🚦) that need the owner, and anything that needs a decision,
credential, or environment the agent doesn't have. The agent does everything
possible up to each gate, records exactly what's needed here, and keeps going.

Author: Bloodawn (KheivenD), 2026-06-02 (autonomous v2 build).

---

## Open items

**No hard gates hit yet.** The run completed all of M1 (TASK 1.1–1.6) — green
and pushed — and paused at the M2 boundary (not a gate; a deliberate stop before
high-risk ML-parity work in a long session). The first gates appear at M5
(publishing) and M5b (signing).

### Execution status (updated 2026-06-03): M1 + M2 complete; M3 in progress

Done & pushed: **all of M1 (1.1–1.6)**, **all of M2 (2.1 ONNX, 2.2 torch-optional,
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
  the recommended preset key + the signals — bumps the route guard tests to 50.
- `tests/test_content_detect.py`: a CDnet surveillance clip → continuous_cctv;
  provide a tiny synthetic fixture so CI exercises the logic without LFS clips.
- The CDnet clips are present locally (data/samples/cdnet_mp4/...).

Then M-CAM (ONVIF/watch-folder), M4 (watch-folder hardening, dashboard auth,
Docker), M5 (download page, opt-in stats, docs, 🚦beta), M5b (🚦signing, Linux
AppImage, 🚦macOS).

**Deferred by the plan (not a gate): TASK 3.3 — adaptive per-segment bitrate.**
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
  (e.g. roi_encoder, hls_runner) — add a single resolver in `src/utils/` and
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

- **🚦 Code-signing certs (M5b.1 / 5b.3)** — Windows EV cert (~$300–600/yr) and
  Apple Developer cert ($99/yr). The signing *step* will be wired into the build;
  the owner must obtain the certs. Investigate SignPath.io's free OSS program for
  Windows first.
- **🚦 Publishing a public release / tagging a beta (TASK 5.4, 5b.*)** — the agent
  prepares the installer, checksums, release checklist, and draft notes; the
  **owner** tags and publishes the GitHub Release.
  **STATUS — prep complete, awaiting owner (TASK 5.4):** `docs/RELEASE-CHECKLIST.md`
  (repeatable build → verify → checksums → draft) and `docs/release-notes-v2.0.0-beta.md`
  (draft notes) are written. The remaining steps are the owner's and were NOT done
  by the autonomous run (gated): build the installer (`installer/build.ps1 -Installer`)
  on a release machine, generate `SHA256SUMS.txt`, create the **`v2.0.0-beta`** tag,
  and publish the **pre-release** with the unsigned-beta warning. Nothing here is
  blocked on code — only on the human publish action.
- **🚦 macOS .dmg notarization (5b.3)** — needs the Apple cert; deferred unless the
  owner provides it. Linux AppImage (5b.2) is done first (no cert needed).
- **🚦 Rust encoder spike (M6)** — explicitly out of scope for this run; needs the
  owner's go-ahead. Skipped entirely.
