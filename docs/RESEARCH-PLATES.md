# RESEARCH: plate-reader solution (R4 Phase 5)

Date: 2026-07-04. Method: deep-research workflow (5 angles, 102 agents, verified
claims 3-0). This is the decision record + the empirical validation of the one
claim the research could not confirm from metadata alone.

## The problem (verified from SVCS's own code)
The optional plate reader uses EasyOCR, which (a) depends unconditionally on
`opencv-python-headless` and (b) is a PyTorch CRNN (drags torch+torchvision).
All four opencv-python variants share ONE `cv2/` namespace with no plugin
architecture, so installing headless CLOBBERS the core `opencv-contrib-python`
(`cv2.bgsegm` / MOG2 disappear). That is why `[plates]` needs a separate venv -
it cannot ship in one env/exe.

## Verified findings
1. **Best stack (3-0):** ankandrew's MIT toolkit - `fast-plate-ocr` (ONNX OCR,
   recognizes CROPPED plates) + `open-image-models` (YOLOv9 ONNX plate
   detection), optionally wired by `fast-alpr`. All MIT, torch-free, run on
   ONNX Runtime (already a core SVCS dep). Sources: github.com/ankandrew/*.
2. **Hard blocker (3-0):** all three ALSO declare `opencv-python-headless` as a
   REQUIRED core dependency (fast-alpr pins `opencv-python-headless>=4.9.0.80`
   directly). A normal `pip install` re-creates the clobber. Source:
   fast-alpr pyproject + issue #38.
3. **Root cause (3-0):** the four opencv-python wheels are mutually exclusive,
   same `cv2/` namespace, "SELECT ONLY ONE". Only the contrib variants ship
   bgsegm/MOG2. Source: opencv/opencv-python README.
4. **The fix (3-0 on facts):** dependency surgery - `pip install --no-deps` the
   ankandrew packages so `opencv-python-headless` is NOT pulled; the existing
   `opencv-contrib-python` satisfies their runtime `import cv2` (contrib is a
   superset). Only `onnxruntime` + `numpy` (both core) + the ONNX model files
   are added. Source: fast-alpr issue #38 names dependency surgery as the fix.
5. **Fallback (3-0):** if `--no-deps` proves fragile, isolate the reader as a
   separate frozen helper exe (`PYINSTALLER_RESET_ENVIRONMENT=1`) fed cropped
   images over a temp file.
6. **EasyOCR is wrong for a single CPU exe (3-0):** unconditional headless dep +
   torch/torchvision.
7. **Temporal voting is essential (medium):** single-frame OCR on night/angled
   surveillance plates is unreliable (one 2026 arXiv preprint measured EasyOCR
   mean confidence 0.414). SVCS ALREADY does multi-frame consensus voting.

## Empirical validation (done here, resolving the research's open caveat)
The research could NOT confirm from metadata that a `--no-deps` install actually
runs against opencv-contrib's cv2. So it was tested locally in a THROWAWAY venv
(never the core env): see docs/PLATES-VALIDATION.md for the exact commands and
result. Outcome recorded there drives whether in-process ships enabled by
default or stays behind the documented recipe.

## Decision
- **Add an in-process ONNX ALPR backend** (`_FastPlateOcrBackend`) to
  `src/enhancement/plate_reader.py`, conforming to the existing `_OcrBackend`
  interface, lazy-imported and fully optional. Auto-selected FIRST in "auto"
  (it is torch-free and coexists), falling back to easyocr/paddle/tesseract/none
  exactly as today. Optionally uses `open-image-models` to detect+crop plates in
  a frame before OCR; without it, OCRs the ROI/frame it is given (works when the
  caller passes plate/vehicle ROI boxes, which the pipeline already supports).
- **Ship the install recipe, not a resolver extra:** a normal `uv sync --extra
  plates` cannot avoid the headless clobber (the extra's deps pull it), so the
  ONNX reader is installed via a documented `--no-deps` recipe / helper script
  into the SAME env. The GUI auto-detects the backend when present and hides the
  plate UI when absent (unchanged behaviour).
- **Keep EasyOCR as a legacy, separate-env option**, demoted below the ONNX
  path in docs.

## Honest caveats carried forward (also in docs/BLOCKERS.md)
- `--no-deps` is a maintenance liability: re-audit the cv2/numpy pins on every
  fast-plate-ocr / open-image-models upgrade.
- The default bundled model weights may carry their own (non-MIT) license -
  verify before bundling any weights in the installer.
- Actually running the real ONNX model end-to-end (and bundling it in the exe)
  is owner-run, like the other optional AI extras; the code path degrades
  gracefully when the package/model is absent, and the tests use a stub.
