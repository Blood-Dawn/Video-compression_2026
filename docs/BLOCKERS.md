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

### Execution status: M2 TASK 2.1 + 2.2 DONE

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
- **🚦 macOS .dmg notarization (5b.3)** — needs the Apple cert; deferred unless the
  owner provides it. Linux AppImage (5b.2) is done first (no cert needed).
- **🚦 Rust encoder spike (M6)** — explicitly out of scope for this run; needs the
  owner's go-ahead. Skipped entirely.
