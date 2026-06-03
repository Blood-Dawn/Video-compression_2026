# ONNX models (M2 - slim install path)

Author: Bloodawn (KheivenD), 2026-06-02 (TASK 2.1).

The v2 installer drops from multi-GB to a few hundred MB by running inference on
**ONNX Runtime** instead of PyTorch (PLAN-V2 §6). The `.onnx` weights are an
**optional component**, not committed to the repo (`*.onnx` is gitignored). They
are produced once from the PyTorch checkpoints and shipped alongside the
installer (or fetched on first run - TASK 2.4).

## Detection - YOLOv8-nano (DONE, parity-verified)

- **Runtime:** `src/detection/onnx_backend.py` (`YoloOnnxDetector`) - letterbox
  640 preprocess → ONNX Runtime → decode `(1, 84, 8400)` + class-aware NMS →
  `Detection(class_id, class_name, score, xyxy)` in original-image coordinates.
- **Selector:** `ObjectFilter(backend="torch" | "onnx" | "auto")`. Default is
  still `"torch"` during the transition; TASK 2.2 flips the default to ONNX and
  moves torch to an optional `[torch]` extra.
- **Export (one-time, needs the `onnx-export` extra):**

  ```
  uv sync --extra onnx-export        # installs onnx (<1.18) + onnxslim
  uv run python -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx', imgsz=640, simplify=True)"
  # -> yolov8n.onnx (~12.3 MB), placed at repo root; the backend looks there.
  ```

  Note: `onnx` is capped `< 1.18` because `onnx >= 1.18` needs `ml_dtypes >= 0.5`
  (`float4_e2m1fn`), but the `[enhance]` extra pins `ml_dtypes 0.4.1` via
  `tb-nightly`, and `import onnx` then crashes. 1.16/1.17 export fine.

- **Parity:** `tests/test_onnx_detection_parity.py` asserts the ONNX backend
  agrees with ultralytics on detection class-sets and counts (within a 1-frame /
  30% tolerance) on `data/samples/cdnet_mp4/baseline/baseline_highway.mp4`. It
  skips cleanly when `yolov8n.onnx` or the clip is absent (e.g. on CI, where the
  model is a build artifact and the clips are git-LFS).

## Enhancement - Real-ESRGAN x4plus (DEFERRED - follow-up)

Per PLAN-V2 §6 / EXECUTION TASK 2.1 ("if x4plus won't export cleanly, ship
detection-on-ONNX first, enhancement as a follow-up"), the Real-ESRGAN ONNX
path is **intentionally deferred**. Reasons:

- Real-ESRGAN x4plus uses dynamic input shapes and custom upsampling that make a
  clean, parity-stable ONNX export finicky (a known issue called out in the plan).
- The detector is the high-frequency, always-on model on the surveillance path;
  enhancement is opt-in (`--enhance`) and far less common, so detection-on-ONNX
  captures most of the installer-slimming win first.
- The current export toolchain is already constrained by the `onnx < 1.18` /
  `ml_dtypes 0.4.1` pin above; Real-ESRGAN export wants a newer stack.

**Plan:** add `src/enhancement/onnx_backend.py` mirroring the detector backend
(an `RealEsrganOnnx` with the same `Enhancer` interface) in a follow-up, with its
own parity test on the CDnet clips, then make the `[enhance]` extra ONNX-first.
Until then, `--enhance` keeps using the PyTorch Real-ESRGAN path.
