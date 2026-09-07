# Plate reader: in-process ONNX coexistence - empirical validation (R4 Phase 5)

Date: 2026-07-04. The deep research (docs/research/RESEARCH-PLATES.md) could not confirm
from package metadata alone that a `--no-deps` install of the ankandrew ONNX
ALPR stack actually RUNS against SVCS's `opencv-contrib-python` without pulling
`opencv-python-headless`. This was tested locally in a THROWAWAY venv (never the
core/dev env). Result: **YES, it works in one environment.**

## Exact commands (throwaway venv, mirroring SVCS core deps)
```
python -m venv plates_val
plates_val/Scripts/python -m pip install "opencv-contrib-python>=4.8.0,<4.11.0" "numpy<2.0.0" \
    "onnxruntime>=1.16.0" tqdm "pyyaml>=6.0"       # <- all already in SVCS core
plates_val/Scripts/python -m pip install --no-deps fast-plate-ocr open-image-models
plates_val/Scripts/python -m pip install rich      # <- the ONLY missing runtime dep
```

## Verified results
- `pip list` shows `opencv-contrib-python 4.10.0.84` as the ONLY opencv variant;
  `opencv-python-headless` was NOT pulled. No torch anywhere.
- `import cv2` -> 4.10.0 with `cv2.bgsegm` PRESENT (MOG2 intact, NOT clobbered).
- `import fast_plate_ocr` and `import open_image_models` both succeed against
  contrib cv2 + onnxruntime + numpy.
- `LicensePlateRecognizer('cct-xs-v1-global-model')` instantiates (downloads a
  small ONNX model from the HF hub on first use).
- Real inference: `rec.run(bgr_crop)` -> `[PlatePrediction(plate='33366', ...)]`.
- The `open-image-models 0.5.1 requires opencv-python-headless, which is not
  installed` line is a pip RESOLVER warning only - import and inference both
  succeed, because the runtime does a plain `import cv2` that contrib satisfies.

## Package APIs captured (for the backend adapter)
- OCR: `from fast_plate_ocr import LicensePlateRecognizer`;
  `LicensePlateRecognizer(model).run(bgr_img) -> list[PlatePrediction]`;
  `PlatePrediction` has `.plate` (str) and `.char_probs` (per-char list or None;
  None for the xs model).
- Detection (optional): `from open_image_models import LicensePlateDetector`;
  `LicensePlateDetector(model).predict(frame) -> list` of detections
  (bounding box + confidence); empty on a blank frame.

## Minimal dependency delta for SVCS
Beyond the existing core (numpy, pyyaml, tqdm, onnxruntime, opencv-contrib):
- add `rich` (the only missing runtime dep), and install `fast-plate-ocr` +
  `open-image-models` with `--no-deps` so `opencv-python-headless` is never
  pulled.
- ALSO ensure `onnxruntime>=1.19.2`: the plate DETECTOR (open-image-models)
  pins that floor, which is HIGHER than core's `>=1.16.0`. Because the install
  is `--no-deps`, this floor is not resolver-enforced. On an env resolved to
  onnxruntime in [1.16, 1.19.2) the OCR loads but the detector silently fails
  to load (OCR-only mode, no plate detection). `scripts/install_plates.ps1`
  installs `onnxruntime>=1.19.2` and its `-Verify` reports the detector state;
  `PlateReader.status()` exposes `plate_detector` so the GUI can show it. This
  skew was NOT exercised in the run below (the venv installed a fresh
  onnxruntime, which pulled a current >=1.19.2 wheel).

## Conclusion
The in-process ONNX plate reader is viable in ONE environment/exe. SVCS ships it
via a documented `--no-deps` recipe (a resolver `extra` cannot express
`--no-deps`, and would pull headless). The new `_FastPlateOcrBackend` is
auto-selected when present and degrades gracefully when absent.

## Maintenance liability (carried to BLOCKERS)
`--no-deps` means the cv2/numpy expectations of these packages are not enforced
by the resolver - re-audit on every fast-plate-ocr / open-image-models upgrade.
Model weights download from the HF hub on first use (or bundle them in the
installer - verify the individual model's license before bundling).
