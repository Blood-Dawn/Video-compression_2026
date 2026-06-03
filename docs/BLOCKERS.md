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

### Execution paused: start of M2 (TASK 2.1, ONNX backend)

Where the next session resumes, with the scouting already done:

- **Deps:** `onnxruntime` and `onnx` are NOT installed and NOT in `pyproject.toml`.
  Add `onnxruntime` to core deps (inference runtime) and `onnx` (+`onnxslim`) for
  the one-time export. `uv sync` will then provision them. Note: ad-hoc
  `uv pip install` packages get wiped by the next `uv sync` (this bit the
  PyInstaller build — see TASK 1.4 commit), so put real deps in `pyproject.toml`.
- **Model:** `yolov8n.pt` (6.5 MB) is present at the repo root; `ultralytics`
  8.4.45 and `torch` 2.11.0+cu128 are installed, so `yolo export
  model=yolov8n.pt format=onnx imgsz=640` will produce `yolov8n.onnx` (a build
  artifact — do NOT commit it; ship it as the optional weights component).
- **Parity clips:** the CDnet sample mp4s ARE present locally under
  `data/samples/cdnet_mp4/` (e.g. `baseline/baseline_highway.mp4` has vehicles),
  so the TASK 2.1 parity test can run locally. They are git-LFS and absent on CI,
  so gate that test with a skip when the clip is missing.
- **Interface to match:** `src/detection/object_filter.py` —
  `ObjectFilter._classify_box_labels()` runs the model on a crop and collects
  COCO class names. Add `src/detection/onnx_backend.py` (a `YoloOnnxDetector`
  doing letterbox-640 preprocess → onnxruntime → decode (1,84,8400) + NMS → class
  names), then make `ObjectFilter` backend-selectable (`backend="torch"|"onnx"|
  "auto"`), keeping torch the default during transition (TASK 2.2 flips it).

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
